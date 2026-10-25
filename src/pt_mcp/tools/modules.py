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
Hardware module tools (WIC/HWIC/NIM cards, SFPs...) for the Packet Tracer MCP server.
"""

import logging
import re

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field
from typing_extensions import Annotated

from pt_mcp.ipc import Ref
from pt_mcp.pt_client import PTClient
from pt_mcp.ptmp import IpcCallError
from pt_mcp.tools.cli import wait_until_ready
from pt_mcp.tools.dependencies import elicit_confirmation, get_pt_client_dep
from pt_mcp.types import DeviceModelDetails, DeviceName, ModuleSlot, SupportedModule

logger = logging.getLogger("pt-mcp.tools.modules")

SlotPath = Annotated[str, Field(pattern=r"^\d+(/\d+)*$", description="Slot path, e.g. '0/0' (see get_device_model_details)")]
ModuleModel = Annotated[str, Field(min_length=1, description="Module model, e.g. 'HWIC-2T', 'NIM-2T', 'WIC-2T', 'HWIC-4ESW'")]

NON_REMOVABLE = 18  # ModuleType.NON_REMOVABLE_MODULE: chassis/motherboard, not a slot the user fills
_SUPPORTED = re.compile(r"^([^:]+):(.*?\.(?:png|jpg|jpeg|svg|gif))?(.*)$", re.I | re.S)
_catalog: dict[int, dict[str, int]] = {}  # id(client) -> {model: module type}


def module_catalog(c: PTClient) -> dict[str, int]:
    """Model -> ModuleType for every module Packet Tracer offers (fetched once per client)."""
    if id(c) not in _catalog:
        mf = c.root().hardwareFactory().modules()
        cat = {}
        for i in range(mf.getAvailableModuleCount()):
            md = mf.getAvailableModuleAt(i)
            cat.setdefault(md.getModel(), md.getType())
        _catalog[id(c)] = cat
    return _catalog[id(c)]


def _module_model(m: Ref) -> str | None:
    try:
        model = m.getDescriptor().getModel()
    except IpcCallError:
        return None
    return None if model in ("", "None") else model


def _walk(m: Ref, prefix: str, out: list[ModuleSlot]) -> None:
    for i in range(m.getSlotCount()):
        default_path = f"{prefix}/{i}" if prefix else str(i)
        try:
            child = m.getModuleAt(i)
            path = child.getSlotPath() or default_path
            model = _module_model(child)
        except IpcCallError:
            out.append(ModuleSlot(slot=default_path, module=None))  # empty slot: PT has no object there
            continue
        ports = []
        try:
            ports = [child.getPortAt(j).getName() for j in range(child.getPortCount())]
        except IpcCallError:
            pass
        try:
            built_in = child.getModuleType() == NON_REMOVABLE
        except IpcCallError:
            built_in = False
        if model and not built_in:
            out.append(ModuleSlot(slot=path, module=model, ports=ports))
        _walk(child, path, out)


def model_details(c: PTClient, device: str) -> DeviceModelDetails:
    d = c.device(device)
    slots: list[ModuleSlot] = []
    _walk(d.getRootModule(), "", slots)
    supported = []
    for entry in d.getSupportedModule() or []:
        m = _SUPPORTED.match(entry)
        if m:
            supported.append(SupportedModule(model=m.group(1).strip(), description=m.group(3).strip()))
    return DeviceModelDetails(device=device, model=d.getModel(), slots=slots, supported_modules=supported)


def _with_power_off(d: Ref, action):
    """Packet Tracer (like real hardware) only accepts module changes while the device is powered off."""
    was_on = d.getPower()
    if was_on:
        d.setPower(False)
    try:
        return action()
    finally:
        if was_on:
            d.setPower(True)


def add_module(c: PTClient, device: str, slot: str, module: str) -> list[str]:
    catalog = module_catalog(c)
    if module not in catalog:
        close = [m for m in catalog if module.lower().replace("-", "") in m.lower().replace("-", "")]
        raise ValueError(f"Unknown module {module!r}. Similar: {close[:15]}")
    d = c.device(device)
    if any(s.slot == slot and s.module == module for s in model_details(c, device).slots):
        return []  # already installed (e.g. a PC's default NIC in an exported topology): nothing to do
    before = {d.getPortAt(i).getName() for i in range(d.getPortCount())}
    if not _with_power_off(d, lambda: d.addModule(slot, catalog[module], module)):
        raise ValueError(
            f"Packet Tracer refused {module} in slot {slot} of {device}. The slot may be occupied or not accept this card; "
            "check get_device_model_details for free slots and supported modules."
        )
    if c.is_a(d, "CiscoDevice") and d.getPower():
        wait_until_ready(d)  # the power cycle reboots IOS; return a usable device
    return [d.getPortAt(i).getName() for i in range(d.getPortCount()) if d.getPortAt(i).getName() not in before]


def remove_module(c: PTClient, device: str, slot: str) -> bool:
    d = c.device(device)
    return _with_power_off(d, lambda: d.removeModule(slot))


def register_tools(mcp):
    """Register module tools with the FastMCP server."""

    @mcp.tool(
        annotations={"title": "Get Device Model Details (Slots and Modules)", "readOnlyHint": True},
    )
    async def get_device_model_details(name: DeviceName) -> DeviceModelDetails:
        """
        Show a device's expansion slots (installed module and its ports, or empty) and every module model it
        supports with Packet Tracer's description. Use before add_module_to_device.

        Examples:
        - "What modules can I add to R1?"
        - "Which slots on the 2911 are free?"
        - "Does this router have serial interfaces?"
        """
        client = get_pt_client_dep()
        try:
            return (await client.run(lambda c: model_details(c, name))).model_dump(exclude_none=True)
        except Exception as e:
            logger.exception("Error reading model details for %s", name)
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Add a Module to a Device", "readOnlyHint": False, "destructiveHint": False},
    )
    async def add_module_to_device(name: DeviceName, slot: SlotPath, module: ModuleModel) -> list[str]:
        """
        Install a hardware module (e.g. HWIC-2T for two serial ports, NIM-2T on ISR4000s, HWIC-4ESW, SFPs)
        into a free slot. The device is powered off for the change and powered back on, so an unsaved
        running-config on it is lost -- save first if needed. Returns the new port names
        (e.g. ["Serial0/0/0", "Serial0/0/1"]).

        Examples:
        - "Add a serial card to R1 so I can do a WAN link"
        - "Put an HWIC-2T in slot 0/0 of R2"
        - "Add a NIM-2T to the ISR4331"
        """
        client = get_pt_client_dep()
        try:
            return await client.run(lambda c: add_module(c, name, slot, module))
        except Exception as e:
            logger.exception("Error adding %s to %s slot %s", module, name, slot)
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Remove a Module from a Device", "readOnlyHint": False, "destructiveHint": True},
    )
    async def remove_module_from_device(name: DeviceName, slot: SlotPath, ctx: Context) -> bool:
        """
        Remove the module in a slot. The device is power-cycled; cables on the module's ports are removed.

        CRITICAL: Destructive. Confirm with the user ("Remove the module in [slot] of [device]?") first.

        Examples:
        - "Take the serial card out of R1 slot 0/0"
        """
        client = get_pt_client_dep()
        try:
            if not await elicit_confirmation(ctx, f"Remove the module in slot {slot} of {name}?"):
                raise Exception("Operation cancelled by user.")
            ok = await client.run(lambda c: remove_module(c, name, slot))
            if not ok:
                raise LookupError(f"No removable module in slot {slot} of {name}")
            return True
        except Exception as e:
            logger.exception("Error removing module from %s slot %s", name, slot)
            raise ToolError(e)
