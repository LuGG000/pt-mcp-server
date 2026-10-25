# Copyright (c) 2026  Cisco Systems, Inc.
# All rights reserved.

# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.

# THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
# OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.

"""
Whole-network tools for the Packet Tracer MCP server: build a full topology in one call, export the current
network (with configs) in the same format, and the network description.
"""

import logging

from fastmcp.exceptions import ToolError
from pydantic import Field
from typing_extensions import Annotated

from pt_mcp.pt_client import PTClient
from pt_mcp.ptmp import IpcCallError
from pt_mcp.tools.activity import html_to_text
from pt_mcp.tools.configuration import apply_config, read_config
from pt_mcp.tools.dependencies import get_pt_client_dep
from pt_mcp.tools.devices import INFRASTRUCTURE_TYPES, add_device, list_devices
from pt_mcp.tools.interfaces import configure_host
from pt_mcp.tools.links import connect, list_links
from pt_mcp.tools.model_helpers import lenient_construct
from pt_mcp.tools.modules import add_module, model_details
from pt_mcp.types import (
    DEVICE_TYPES,
    Topology,
    TopologyBuildResult,
    TopologyDevice,
    TopologyHost,
    TopologyLink,
)

logger = logging.getLogger("pt-mcp.tools.topology")


def build_topology(c: PTClient, topo: Topology) -> TopologyBuildResult:
    """Devices -> modules -> links -> host IPs -> IOS configs. Continues past errors and reports them."""
    result = TopologyBuildResult()
    if topo.description is not None:
        c.root().appWindow().getActiveFile().setNetworkDescription(topo.description)
    for dev in topo.devices:
        if dev.device_type not in DEVICE_TYPES:
            result.errors.append(f"{dev.name}: unknown device_type {dev.device_type!r}")
            continue
        try:
            result.devices.append(add_device(c, dev.device_type, dev.model, dev.x, dev.y, dev.name))
        except Exception as e:
            result.errors.append(f"{dev.name}: {e}")
            continue
        for mod in dev.modules:
            try:
                add_module(c, dev.name, str(mod["slot"]), mod["module"])
            except Exception as e:
                result.errors.append(f"{dev.name} module {mod}: {e}")
    for link in topo.links:
        label = f"{link.device_a}:{link.port_a} <-> {link.device_b}:{link.port_b}"
        try:
            cable = connect(c, link.device_a, link.port_a, link.device_b, link.port_b, link.cable)
            result.links.append(f"{label} ({cable})")
        except Exception as e:
            result.errors.append(f"link {label}: {e}")
    for host in topo.hosts:
        try:
            configure_host(c, host.name, host.port, host.ip_address, host.subnet_mask, host.default_gateway, host.dns_server, host.dhcp)
        except Exception as e:
            result.errors.append(f"host {host.name} {host.port}: {e}")
    for dev in topo.devices:
        if dev.config and dev.name in result.devices:
            try:
                # Device configs here are whole configs (often exported show running-config): load them like a
                # startup-config so interfaces without "shutdown" come up.
                applied = apply_config(c, dev.name, dev.config, save=False, startup_semantics=True)
                result.errors += [f"{dev.name}: '{r.command}' -> {r.status}" for r in applied.errors]
            except Exception as e:
                result.errors.append(f"{dev.name} config: {e}")
    return result


def _process_ip(c: PTClient, name: str, process: str, method: str) -> str | None:
    """Host IP settings live on processes: "HostIpProcess" (gateway), "DnsClient" (DNS server)."""
    try:
        ip = c.device(name).getProcess(process).call(method)
        return ip if ip and ip != "0.0.0.0" else None
    except (IpcCallError, TypeError):
        return None


def export_topology(c: PTClient, include_configs: bool) -> Topology:
    topo = Topology()
    try:
        # After a save/reopen PT returns the description as Qt rich-text HTML; export plain text.
        topo.description = html_to_text(c.root().appWindow().getActiveFile().getNetworkDescription() or "") or None
    except IpcCallError:
        pass
    for d in list_devices(c):
        if d.type in INFRASTRUCTURE_TYPES:
            continue
        entry = TopologyDevice(name=d.name, device_type=d.type, model=d.model, x=d.x or 0, y=d.y or 0)
        try:
            entry.modules = [{"slot": s.slot, "module": s.module} for s in model_details(c, d.name).slots if s.module]
        except IpcCallError:
            pass
        ref = c.device(d.name)
        if include_configs and c.is_a(ref, "CiscoDevice"):
            try:
                entry.config = read_config(c, d.name, "running")
            except IpcCallError:
                logger.debug("No running-config for %s", d.name, exc_info=True)
        if c.is_a(ref, "Pc"):
            for i in range(ref.getPortCount()):
                p = ref.getPortAt(i)
                if not c.is_a(p, "HostPort"):
                    continue
                ip, dhcp = p.getIpAddress(), p.isDhcpClientOn()
                if dhcp or (ip and ip != "0.0.0.0"):
                    topo.hosts.append(
                        TopologyHost(
                            name=d.name,
                            port=p.getName(),
                            ip_address=None if dhcp else ip,
                            subnet_mask=None if dhcp else p.getSubnetMask(),
                            default_gateway=_process_ip(c, d.name, "HostIpProcess", "getDefaultGateway"),
                            dns_server=_process_ip(c, d.name, "DnsClient", "getServerIp"),
                            dhcp=dhcp or None,
                        )
                    )
        topo.devices.append(entry)
    for link in list_links(c):
        if link.device_b:
            topo.links.append(
                TopologyLink(
                    device_a=link.device_a, port_a=link.port_a, device_b=link.device_b, port_b=link.port_b, cable=link.cable or "auto"
                )
            )
    return topo


def register_tools(mcp):
    """Register topology tools with the FastMCP server."""

    @mcp.tool(
        annotations={"title": "Create a Full Network Topology", "readOnlyHint": False, "destructiveHint": False},
    )
    async def create_full_network_topology(
        topology: Annotated[
            Topology | dict | str,
            Field(description="Topology object (or its JSON string): description, devices, links, hosts -- see the docstring"),
        ],
    ) -> TopologyBuildResult:
        """
        Build a whole network in one call into the open Packet Tracer file (existing devices are kept).
        Same format export_network_topology returns, so exports can be rebuilt. Steps run in order:
        devices (+modules), links, host IP settings, then IOS configs; errors are collected, not fatal.

        Format:
        {
          "description": "OSPF lab",
          "devices": [
            {"name": "R1", "device_type": "router", "model": "2911", "x": 100, "y": 100,
             "modules": [{"slot": "0/0", "module": "HWIC-2T"}],
             "config": "hostname R1\\ninterface Gi0/0\\n ip address 192.168.1.1 255.255.255.0\\n no shutdown"},
            {"name": "SW1", "device_type": "switch", "model": "2960-24TT", "x": 300, "y": 100},
            {"name": "PC1", "device_type": "pc", "model": "PC-PT", "x": 500, "y": 100}
          ],
          "links": [{"device_a": "R1", "port_a": "GigabitEthernet0/0", "device_b": "SW1", "port_b": "GigabitEthernet0/1"},
                    {"device_a": "PC1", "port_a": "FastEthernet0", "device_b": "SW1", "port_b": "FastEthernet0/1"}],
          "hosts": [{"name": "PC1", "port": "FastEthernet0", "ip_address": "192.168.1.10",
                     "subnet_mask": "255.255.255.0", "default_gateway": "192.168.1.1"}]
        }
        Use full port names. cable defaults to "auto". Discover models with get_device_models and modules with
        get_device_model_details.

        Examples:
        - "Build a 3-router OSPF lab with a LAN behind each router"
        - "Recreate the topology I exported earlier"
        - "Set up a router-on-a-stick lab with two VLANs"
        """
        client = get_pt_client_dep()
        try:
            topo = lenient_construct(Topology, topology)
            return (await client.run(lambda c: build_topology(c, topo))).model_dump()
        except Exception as e:
            logger.exception("Error building topology")
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Export the Network Topology", "readOnlyHint": True},
    )
    async def export_network_topology(include_configs: bool = True) -> Topology:
        """
        Export the open network as a topology object: devices (type, model, position, installed modules,
        running-config), links, and host IPv4 settings. The result can be fed back to
        create_full_network_topology, saved as a study reference, or reviewed for mistakes.

        Examples:
        - "Export my lab"
        - "Give me a summary of everything in this network including configs"
        - "Back up this topology as JSON"
        """
        client = get_pt_client_dep()
        try:
            return (await client.run(lambda c: export_topology(c, include_configs))).model_dump(exclude_none=True)
        except Exception as e:
            logger.exception("Error exporting topology")
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Set the Network Description", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    )
    async def set_network_description(description: str) -> str:
        """
        Set the network file's description (shown in Packet Tracer under File > Network description / Info).
        Handy for lab notes, objectives, or an IP addressing table.

        Examples:
        - "Describe this lab as 'CCNA 2 - OSPF single area practice'"
        - "Put the addressing table in the network description"
        """
        client = get_pt_client_dep()
        try:
            await client.run(lambda c: c.root().appWindow().getActiveFile().setNetworkDescription(description))
            return description
        except Exception as e:
            logger.exception("Error setting network description")
            raise ToolError(e)
