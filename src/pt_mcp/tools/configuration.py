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
Device configuration tools (running/startup config) for the Packet Tracer MCP server.
"""

import logging
import re
from typing import Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError

from pt_mcp.pt_client import PTClient
from pt_mcp.tools.cli import run_ios
from pt_mcp.tools.dependencies import elicit_confirmation, get_pt_client_dep
from pt_mcp.types import CliCommandResult, ConfigureResult, DeviceConfiguration, DeviceName

logger = logging.getLogger("pt-mcp.tools.configuration")

# Lines in a pasted/exported config that are not configuration commands.
_SKIP = re.compile(
    r"^(!.*|end|enable|conf(igure)?( t(erminal)?)?|version \S+|building configuration.*|current configuration.*"
    r"|boot-start-marker|boot-end-marker|\S+#|\S+>"
    # show running-config defaults/identity lines Packet Tracer prints but rejects when typed back in
    r"|license udi .*|ip classless|spanning-tree extend system-id)$",
    re.I,
)


def config_lines(config: str, startup_semantics: bool = False) -> list[str]:
    """
    Commands from a config (pasted, or `show running-config` output), keeping indentation (it marks sub-mode lines).

    startup_semantics=True applies the config the way IOS loads a startup-config: show running-config omits
    "no shutdown" (up is the default when loading startup-config), so an interface block without "shutdown" gets
    an explicit "no shutdown". Pasted into a fresh device without this, every interface would stay shut down.
    """
    out: list[str] = []
    block: list[str] = []

    def close_block():
        if not block:
            return
        head = block[0].strip().lower()
        body = [b.strip().lower() for b in block[1:]]
        lines = list(block)
        if head.startswith("line ") and "login" in body and not any(b.startswith("password") for b in body):
            lines = [b for b in lines if b.strip().lower() != "login"]  # rejected without a password; IOS default anyway
        if startup_semantics and head.startswith("interface ") and "shutdown" not in body:
            indent = next((b[: len(b) - len(b.lstrip())] for b in block[1:]), " ") or " "
            lines.append(f"{indent}no shutdown")
        out.extend(lines)
        block.clear()

    for raw in re.split(r"\r?\n", config):
        line = raw.rstrip()
        if not line.strip() or _SKIP.match(line.strip()):
            continue
        if line[:1] not in (" ", "\t"):
            close_block()
        block.append(line)
    close_block()
    return out


def read_config(c: PTClient, device: str, source: str) -> str:
    if not c.is_a(c.device(device), "CiscoDevice"):
        raise ValueError(f"{device} is not an IOS device; use get_interfaces_for_device for its IP settings")
    cmd = "show running-config" if source == "running" else "show startup-config"
    _, output = c.device(device).enterCommand(cmd, "enable")
    return output.strip("\n")


def apply_config(c: PTClient, device: str, config: str, save: bool, startup_semantics: bool = False) -> ConfigureResult:
    lines = config_lines(config, startup_semantics)
    results = run_ios(c, device, lines, config_command=True) if lines else []
    result = ConfigureResult(device=device, commands_sent=len(lines), errors=[r for r in results if r.status != "ok"])
    if save:
        result.saved = save_config(c, device)
    return result


def save_config(c: PTClient, device: str) -> bool:
    if not c.is_a(c.device(device), "CiscoDevice"):
        raise ValueError(f"{device} is not an IOS device")
    status, output = c.device(device).enterCommand("write memory", "enable")
    return status == 0 and "[OK]" in output


def erase_config(c: PTClient, device: str, reload: bool) -> list[CliCommandResult]:
    d = c.device(device)
    if not c.is_a(d, "CiscoDevice"):
        raise ValueError(f"{device} is a {d.class_name}, not an IOS device; there is no configuration to erase")
    steps = []

    def enter(cmd: str, mode: str = "") -> str:
        status, output = d.enterCommand(cmd, mode)
        steps.append(CliCommandResult(command=cmd or "<enter>", status="ok" if status == 0 else str(status), output=output))
        return output

    out = enter("write erase", "enable")
    if "[confirm]" in out:
        out = enter("")
    if reload:
        out = enter("reload", "enable")
        if "[yes/no]" in out:  # "System configuration has been modified. Save?"
            out = enter("no")
        if "[confirm]" in out:
            enter("")
    return steps


def register_tools(mcp):
    """Register configuration tools with the FastMCP server."""

    @mcp.tool(
        annotations={"title": "Get a Device's Configuration", "readOnlyHint": True},
    )
    async def get_device_configuration(name: DeviceName, source: Literal["running", "startup"] = "running") -> DeviceConfiguration:
        """
        Return a Cisco device's running-config (default) or startup-config as text. Useful for reviewing
        a lab, comparing running vs startup ("did I save?"), or exporting a config to reuse.

        Examples:
        - "Show me R1's running config"
        - "Is SW1's startup config the same as its running config?"
        """
        client = get_pt_client_dep()
        try:
            text = await client.run(lambda c: read_config(c, name, source))
            return DeviceConfiguration(device=name, source=source, config=text).model_dump()
        except Exception as e:
            logger.exception("Error reading %s config of %s", source, name)
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Configure a Cisco Device", "readOnlyHint": False, "destructiveHint": True},
    )
    async def configure_device(name: DeviceName, config: str, save: bool = False) -> ConfigureResult:
        """
        Apply a block of IOS configuration to a Cisco device, like pasting it into the CLI in global
        config mode. Accepts output of `show running-config` as-is: "!" lines, "end", "enable",
        "configure terminal", "version", and prompt lines are skipped. Indentation does not matter.
        Returns how many commands were sent and only the ones IOS rejected. save=true runs
        "write memory" afterwards.

        Prefer this over send_cli_command for multi-line configs (VLANs, OSPF, ACLs, interface blocks).

        CRITICAL: Changes device configuration. Show the user the config and confirm before applying.

        Examples:
        - "Configure OSPF area 0 on R1 for 10.0.0.0/8"
        - "Apply this config to SW1 and save it"
        - "Create VLANs 10 and 20 on the switch and assign Fa0/1-12 to VLAN 10"
        """
        client = get_pt_client_dep()
        try:
            return (await client.run(lambda c: apply_config(c, name, config, save))).model_dump()
        except Exception as e:
            logger.exception("Error configuring %s", name)
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Save a Device's Configuration", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    )
    async def save_device_configuration(name: DeviceName) -> bool:
        """
        Save a Cisco device's running-config to startup-config ("write memory" / "copy run start") so it
        survives a reload or power cycle. Returns true when IOS reports [OK].

        Examples:
        - "Save R1's config"
        - "Make sure all my changes on SW1 survive a reload"
        """
        client = get_pt_client_dep()
        try:
            return await client.run(lambda c: save_config(c, name))
        except Exception as e:
            logger.exception("Error saving config on %s", name)
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Erase a Device's Configuration", "readOnlyHint": False, "destructiveHint": True},
    )
    async def erase_device_configuration(name: DeviceName, ctx: Context, reload: bool = True) -> list[CliCommandResult]:
        """
        Erase a Cisco device's startup-config ("write erase") and, by default, reload it so it boots with a
        blank configuration -- the classic way to reset lab gear. Prompts are answered automatically
        (the running config is NOT saved before reload).

        CRITICAL: Destructive and irreversible. Always ask "Erase the configuration of [device]?" and wait
        for the user's "yes" before invoking this tool.

        Examples:
        - "Wipe R1's configuration"
        - "Reset the switch to factory defaults"
        """
        client = get_pt_client_dep()
        try:
            if not await elicit_confirmation(ctx, f"Erase the configuration of {name}?"):
                raise Exception("Operation cancelled by user.")
            return [s.model_dump() for s in await client.run(lambda c: erase_config(c, name, reload))]
        except Exception as e:
            logger.exception("Error erasing config on %s", name)
            raise ToolError(e)
