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
Interface (port) tools for the Packet Tracer MCP server.
"""

import logging

from fastmcp.exceptions import ToolError

from pt_mcp.ipc import Ref
from pt_mcp.pt_client import PTClient
from pt_mcp.ptmp import IpcCallError
from pt_mcp.tools.dependencies import get_pt_client_dep
from pt_mcp.types import DeviceName, HostInterfaceConfig, InterfaceInfo, IPv4String, PortName

logger = logging.getLogger("pt-mcp.tools.interfaces")


def describe_port(c: PTClient, p: Ref, device: str) -> InterfaceInfo:
    info = InterfaceInfo(name=p.getName(), class_name=p.class_name)
    for attr, method in (("up", "isPortUp"), ("protocol_up", "isProtocolUp"), ("mac_address", "getMacAddress")):
        try:
            setattr(info, attr, p.call(method))
        except (IpcCallError, TypeError):
            pass
    if c.is_a(p, "HostPort"):
        ip = p.getIpAddress()
        if ip and ip != "0.0.0.0":
            info.ip_address, info.subnet_mask = ip, p.getSubnetMask()
    # Port.getRemotePortName() is empty in 9.0.1 even for cabled ports; walk the Cable object instead.
    # An unlinked port's getLink() is a null object, so the first call through it raises.
    try:
        link = p.getLink()
        info.link_uuid = link.getObjectUuid()
        other = link.getOtherPort(device, info.name)
        info.remote_port = other.getName()
        info.remote_device = other.getOwnerDevice().getName()
    except IpcCallError:
        pass
    return info


def list_ports(c: PTClient, device: str) -> list[InterfaceInfo]:
    d = c.device(device)
    return [describe_port(c, d.getPortAt(i), device) for i in range(d.getPortCount())]


def configure_host(
    c: PTClient, device: str, port: str, ip: str | None, mask: str | None, gateway: str | None, dns: str | None, dhcp: bool | None
) -> HostInterfaceConfig:
    d = c.device(device)
    p = d.getPort(port)
    if not c.is_a(p, "HostPort"):
        raise ValueError(f"{device} {port} is a {p.class_name}, not an IP host port; configure routers/switches with send_cli_command")
    if dhcp is not None:
        p.setDhcpClientFlag(dhcp)
    if ip:
        p.setIpSubnetMask(ip, mask or "255.255.255.0")
    if gateway:
        p.setDefaultGateway(gateway)
    if dns:
        p.setDnsServerIp(dns)
    return HostInterfaceConfig(ip_address=p.getIpAddress(), subnet_mask=p.getSubnetMask(), dhcp=p.isDhcpClientOn())


def register_tools(mcp):
    """Register all interface-related tools with the FastMCP server."""

    @mcp.tool(
        annotations={
            "title": "Get Interfaces for a Device",
            "readOnlyHint": True,
        },
    )
    async def get_interfaces_for_device(name: DeviceName) -> list[InterfaceInfo]:
        """
        List a device's ports: name, IPC class, link/protocol state, MAC, IPv4 address/mask (host
        ports), and the remote port name if a cable is attached.

        Examples:
        - "What interfaces does R1 have?"
        - "Which ports on the switch are connected?"
        - "Show PC0's IP address"
        """
        client = get_pt_client_dep()
        try:
            return [i.model_dump(exclude_none=True) for i in await client.run(lambda c: list_ports(c, name))]
        except Exception as e:
            logger.exception("Error listing interfaces for %s", name)
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Configure an End-Device Interface", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    )
    async def configure_host_interface(
        name: DeviceName,
        port: PortName,
        ip_address: IPv4String | None = None,
        subnet_mask: IPv4String | None = None,
        default_gateway: IPv4String | None = None,
        dns_server: IPv4String | None = None,
        dhcp: bool | None = None,
    ) -> HostInterfaceConfig:
        """
        Set IPv4 settings on an end device's port (PC, laptop, server, printer...). Typical port names:
        'FastEthernet0' (PC-PT), 'GigabitEthernet0'. For routers and switches use send_cli_command.
        subnet_mask defaults to 255.255.255.0 when ip_address is given. dhcp=true switches the port to DHCP.

        Examples:
        - "Give PC0 192.168.1.10/24 with gateway 192.168.1.1"
        - "Set the server's DNS to 8.8.8.8"
        - "Put PC1 on DHCP"
        """
        client = get_pt_client_dep()
        try:
            cfg = await client.run(lambda c: configure_host(c, name, port, ip_address, subnet_mask, default_gateway, dns_server, dhcp))
            return cfg.model_dump(exclude_none=True)
        except Exception as e:
            logger.exception("Error configuring %s %s", name, port)
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Set Interface Power", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    )
    async def set_interface_power(name: DeviceName, port: PortName, power_on: bool) -> bool:
        """
        Administratively enable or disable a port at the physical level (like plugging/unplugging the port's
        power in Packet Tracer). For IOS 'shutdown'/'no shutdown' use send_cli_command.

        Examples:
        - "Disable PC0's FastEthernet0"
        """
        client = get_pt_client_dep()
        try:
            await client.run(lambda c: c.device(name).getPort(port).setPower(power_on))
            return power_on
        except Exception as e:
            logger.exception("Error setting power on %s %s", name, port)
            raise ToolError(e)
