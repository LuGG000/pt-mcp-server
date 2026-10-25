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
Device management tools for the Packet Tracer MCP server.
"""

import logging

from fastmcp import Context
from fastmcp.exceptions import ToolError

from pt_mcp.ipc import Ref
from pt_mcp.pt_client import PTClient
from pt_mcp.tools.dependencies import elicit_confirmation, get_pt_client_dep
from pt_mcp.types import DEVICE_TYPE_NAMES, DEVICE_TYPES, Coordinate, DeviceName, DeviceSummary, DeviceTypeName

logger = logging.getLogger("pt-mcp.tools.devices")


def summarize_device(d: Ref) -> DeviceSummary:
    t = d.getType()
    return DeviceSummary(
        name=d.getName(),
        class_name=d.class_name,
        model=d.getModel(),
        type=DEVICE_TYPE_NAMES.get(t, str(t)),
        power=d.getPower(),
        x=d.getXCoordinate(),
        y=d.getYCoordinate(),
    )


# PT 9 auto-creates a hidden "Power Distribution Device0" in every network for the physical power model.
INFRASTRUCTURE_TYPES = {"power_distribution_device"}


def list_devices(c: PTClient, include_infrastructure: bool = False) -> list[DeviceSummary]:
    net = c.root().network()
    devices = [summarize_device(net.getDeviceAt(i)) for i in range(net.getDeviceCount())]
    return [d for d in devices if include_infrastructure or d.type not in INFRASTRUCTURE_TYPES]


def device_models(c: PTClient, device_type: str) -> list[str]:
    t = DEVICE_TYPES[device_type]
    factory = c.root().hardwareFactory().devices()
    models = [factory.getAvailableDeviceForTypeAt(t, i).getModel() for i in range(factory.getAvailableDeviceForTypeCount(t))]
    return list(dict.fromkeys(models))  # PT lists one descriptor per hardware variant; model names repeat


def add_device(c: PTClient, device_type: str, model: str, x: float, y: float, name: str | None) -> str:
    assigned = c.logical_workspace().addDevice(DEVICE_TYPES[device_type], model, float(x), float(y))
    if not assigned:
        raise ValueError(f"Packet Tracer refused to add a {device_type} of model {model!r}. Check get_device_models for valid models.")
    if name and name != assigned:
        c.device(assigned).setName(name)
        assigned = name
    return assigned


def register_tools(mcp):  # noqa: C901
    """Register all device-related tools with the FastMCP server."""

    @mcp.tool(
        annotations={
            "title": "Get All Devices in the Network",
            "readOnlyHint": True,
        },
    )
    async def get_devices_in_network(include_infrastructure: bool = False) -> list[DeviceSummary]:
        """
        List every device in the active Packet Tracer network: name, IPC class, model, device type,
        power state and logical-workspace x/y position. Packet Tracer's auto-created power distribution
        device is hidden unless include_infrastructure=true.

        Examples:
        - "What devices are in my Packet Tracer network?"
        - "List all routers and switches"
        - "Show me the topology"
        """
        client = get_pt_client_dep()
        try:
            return [d.model_dump(exclude_none=True) for d in await client.run(lambda c: list_devices(c, include_infrastructure))]
        except Exception as e:
            logger.exception("Error listing devices")
            raise ToolError(e)

    @mcp.tool(
        annotations={
            "title": "Get Available Device Models",
            "readOnlyHint": True,
        },
    )
    async def get_device_models(device_type: DeviceTypeName) -> list[str]:
        """
        List the device models Packet Tracer offers for a device type. Use one of these model
        strings with add_device_to_network.

        Examples:
        - "Which router models can I add?"
        - "List the available switch models"
        - "What PC models does Packet Tracer have?"
        """
        client = get_pt_client_dep()
        try:
            return await client.run(lambda c: device_models(c, device_type))
        except Exception as e:
            logger.exception("Error listing models for %s", device_type)
            raise ToolError(e)

    @mcp.tool(
        annotations={
            "title": "Add a Device to the Network",
            "readOnlyHint": False,
            "destructiveHint": False,
        },
    )
    async def add_device_to_network(
        device_type: DeviceTypeName,
        model: str,
        x: Coordinate = 100,
        y: Coordinate = 100,
        name: DeviceName | None = None,
    ) -> str:
        """
        Add a device to the logical workspace. Returns the device's name (Packet Tracer assigns one such
        as 'Router0'; it is renamed to `name` if given).

        Required: device_type (e.g. "router", "switch", "pc", "server"), model (e.g. "2911", "ISR4331",
        "2960-24TT", "PC-PT", "Server-PT" -- discover via get_device_models).
        Optional: x/y position, name.

        Examples:
        - "Add a 2911 router called R1"
        - "Put a 2960 switch at 300,200"
        - "Add two PCs to the network"
        """
        client = get_pt_client_dep()
        try:
            return await client.run(lambda c: add_device(c, device_type, model, x, y, name))
        except Exception as e:
            logger.exception("Error adding %s %s", device_type, model)
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Rename a Device", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    )
    async def rename_device(name: DeviceName, new_name: DeviceName) -> str:
        """
        Change a device's display name (the name used by all other tools). This does not change the IOS
        hostname; use send_cli_command with "hostname X" for that.

        Examples:
        - "Rename Router0 to R1"
        - "Call PC0 'Accounting-PC'"
        """
        client = get_pt_client_dep()
        try:
            await client.run(lambda c: c.device(name).setName(new_name))
            return new_name
        except Exception as e:
            logger.exception("Error renaming %s", name)
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Set Device Power", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    )
    async def set_device_power(name: DeviceName, power_on: bool) -> bool:
        """
        Power a device on or off. Powering off a Cisco device discards its unsaved running-config.

        Examples:
        - "Turn off R1"
        - "Power on all the switches"
        """
        client = get_pt_client_dep()
        try:
            await client.run(lambda c: c.device(name).setPower(power_on))
            return power_on
        except Exception as e:
            logger.exception("Error setting power on %s", name)
            raise ToolError(e)

    @mcp.tool(
        annotations={
            "title": "Delete a Device from the Network",
            "readOnlyHint": False,
            "destructiveHint": True,
        },
    )
    async def delete_device_from_network(name: DeviceName, ctx: Context) -> bool:
        """
        Delete a device and all of its links from the network.

        CRITICAL: Destructive and irreversible (the device's configuration is lost). Always ask
        "Confirm deletion of [device]?" and wait for the user's "yes" before invoking this tool.

        Examples:
        - "Delete R2"
        - "Remove the extra switch"
        """
        client = get_pt_client_dep()
        try:
            if not await elicit_confirmation(ctx, f"Are you sure you want to delete {name}?"):
                raise Exception("Delete operation cancelled by user.")
            ok = await client.run(lambda c: c.logical_workspace().removeDevice(name))
            if not ok:
                raise LookupError(f"Packet Tracer could not remove {name!r} (does it exist?)")
            return True
        except Exception as e:
            logger.exception("Error deleting %s", name)
            raise ToolError(e)
