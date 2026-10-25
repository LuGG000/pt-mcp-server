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
Link (cable) tools for the Packet Tracer MCP server.
"""

import logging

from fastmcp import Context
from fastmcp.exceptions import ToolError

from pt_mcp.pt_client import PTClient
from pt_mcp.ptmp import IpcCallError
from pt_mcp.tools.dependencies import elicit_confirmation, get_pt_client_dep
from pt_mcp.types import CABLE_TYPE_NAMES, CABLE_TYPES, SWITCHING_DEVICE_TYPES, CableTypeName, DeviceName, LinkInfo, PortName

logger = logging.getLogger("pt-mcp.tools.links")


def list_links(c: PTClient) -> list[LinkInfo]:
    """Walk Network.getLinkAt(i) -> Cable.getPort1/getPort2 -> Port.getOwnerDevice()."""
    net = c.root().network()
    links = []
    for i in range(net.getLinkCount()):
        cable = net.getLinkAt(i)
        a = cable.getPort1()
        link = LinkInfo(device_a=a.getOwnerDevice().getName(), port_a=a.getName(), link_uuid=cable.getObjectUuid())
        try:
            b = cable.getPort2()
            link.device_b, link.port_b = b.getOwnerDevice().getName(), b.getName()
        except IpcCallError:
            pass  # wireless/one-ended links
        try:
            ct = cable.getConnectionType()
            link.cable = CABLE_TYPE_NAMES.get(ct, str(ct))
        except IpcCallError:
            pass
        links.append(link)
    return links


def auto_cable(c: PTClient, device_a: str, port_a: str, device_b: str, port_b: str) -> list[int]:
    """Cable types to try, best first. PT's createLink rejects ConnectType AUTO (8107); the GUI picks it client-side."""
    names = (port_a.lower(), port_b.lower())
    if all(n.startswith("serial") for n in names):
        return [CABLE_TYPES["serial"]]
    if any(n.startswith(("console", "rs 232", "rs232")) for n in names):
        return [CABLE_TYPES["console"]]
    if any("fiber" in n for n in names):
        return [CABLE_TYPES["fiber_singlemode"], CABLE_TYPES["fiber_multimode"]]
    a_sw = c.device(device_a).getType() in SWITCHING_DEVICE_TYPES
    b_sw = c.device(device_b).getType() in SWITCHING_DEVICE_TYPES
    first, second = ("straight", "cross") if a_sw != b_sw else ("cross", "straight")
    return [CABLE_TYPES[first], CABLE_TYPES[second], CABLE_TYPES["fiber_singlemode"], CABLE_TYPES["fiber_multimode"]]


def connect(c: PTClient, device_a: str, port_a: str, device_b: str, port_b: str, cable: str) -> str:
    lw = c.logical_workspace()
    candidates = auto_cable(c, device_a, port_a, device_b, port_b) if cable == "auto" else [CABLE_TYPES[cable]]
    for ct in candidates:
        if lw.createLink(device_a, port_a, device_b, port_b, ct):
            return CABLE_TYPE_NAMES[ct]
    raise ValueError(
        f"Packet Tracer refused the link {device_a}:{port_a} <-> {device_b}:{port_b} ({cable}). "
        "Check the port names (get_interfaces_for_device), that both ports are free, and that the cable suits the ports."
    )


def register_tools(mcp):
    """Register all link-related tools with the FastMCP server."""

    @mcp.tool(
        annotations={
            "title": "Connect Two Devices",
            "readOnlyHint": False,
            "destructiveHint": False,
        },
    )
    async def connect_two_devices(
        device_a: DeviceName,
        port_a: PortName,
        device_b: DeviceName,
        port_b: PortName,
        cable: CableTypeName = "auto",
    ) -> str:
        """
        Cable a port on one device to a port on another and return the cable type used. Both ports must
        exist and be free; use get_interfaces_for_device to find port names. cable="auto" (default) picks
        like Packet Tracer's GUI: serial for Serial ports, console for console ports, straight-through between
        a switch and a host/router, crossover between like devices.

        Examples:
        - "Connect R1 Gi0/0 to SW1 Gi0/1"
        - "Cable PC0 FastEthernet0 to the switch's Fa0/1"
        - "Add a serial link between R1 Serial0/1/0 and R2 Serial0/1/0"
        """
        client = get_pt_client_dep()
        try:
            return await client.run(lambda c: connect(c, device_a, port_a, device_b, port_b, cable))
        except Exception as e:
            logger.exception("Error connecting %s:%s to %s:%s", device_a, port_a, device_b, port_b)
            raise ToolError(e)

    @mcp.tool(
        annotations={
            "title": "Get All Links in the Network",
            "readOnlyHint": True,
        },
    )
    async def get_all_links() -> list[LinkInfo]:
        """
        List every cable in the network as device/port pairs with the cable type.

        Examples:
        - "Show all the links"
        - "What is R1 connected to?"
        - "Map the topology connections"
        """
        client = get_pt_client_dep()
        try:
            return [link.model_dump(exclude_none=True) for link in await client.run(list_links)]
        except Exception as e:
            logger.exception("Error listing links")
            raise ToolError(e)

    @mcp.tool(
        annotations={
            "title": "Delete a Link",
            "readOnlyHint": False,
            "destructiveHint": True,
        },
    )
    async def delete_link(device: DeviceName, port: PortName, ctx: Context) -> bool:
        """
        Remove the cable attached to a device port.

        CRITICAL: Destructive. Always ask "Confirm removal of the link on [device] [port]?" and wait for
        the user's "yes" before invoking this tool.

        Examples:
        - "Disconnect R1 Gi0/0"
        - "Remove the cable between PC0 and the switch"
        """
        client = get_pt_client_dep()
        try:
            if not await elicit_confirmation(ctx, f"Are you sure you want to remove the link on {device} {port}?"):
                raise Exception("Delete operation cancelled by user.")
            ok = await client.run(lambda c: c.logical_workspace().deleteLink(device, port))
            if not ok:
                raise LookupError(f"No link on {device} {port}")
            return True
        except Exception as e:
            logger.exception("Error deleting link on %s %s", device, port)
            raise ToolError(e)
