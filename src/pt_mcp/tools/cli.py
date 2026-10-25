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
CLI and terminal tools for the Packet Tracer MCP server.
"""

import logging
import re
import time

from fastmcp.exceptions import ToolError
from pydantic import Field
from typing_extensions import Annotated

from pt_mcp.pt_client import PTClient
from pt_mcp.tools.dependencies import get_pt_client_dep
from pt_mcp.types import COMMAND_STATUS, CliCommandResult, CommandLogEntry, DeviceName, PingResult, TerminalOutput

logger = logging.getLogger("pt-mcp.tools.cli")

TERMINAL_EVENTS = ("outputWritten", "commandEnded")


def _split(commands: str) -> list[str]:
    """Non-empty lines, right-stripped only: leading indentation marks sub-mode lines in config blocks."""
    return [c.rstrip() for c in re.split(r"\r?\n", commands) if c.strip()]


# IOS error lines start with "% " (syslog messages are "%FACILITY-n-..." with no space). Packet Tracer reports
# some rejections (e.g. "% 10.0.12.0 overlaps with GigabitEthernet0/0") with an OK status.
_IOS_ERROR = re.compile(r"^% (?!\w+-\d-)", re.M)
# Commands that enter a configuration sub-mode; if one fails we must not keep typing into the previous sub-mode.
_SUBMODE = re.compile(
    r"^(interface|router|line|vlan|ip dhcp pool|ip access-list|ipv6 access-list|class-map|policy-map|controller|"
    r"crypto (isakmp policy|map)|key chain|track|zone(-pair)?|parameter-map|archive|redundancy|ipv6 dhcp pool)\b",
    re.I,
)


def wait_until_ready(d, timeout: float = 15.0) -> None:
    """Skip the boot sequence and wait until IOS accepts commands (it rejects them while booting)."""
    if not d.isBooting():
        return
    d.skipBoot()
    deadline = time.monotonic() + timeout
    while d.isBooting() and time.monotonic() < deadline:
        time.sleep(0.25)
    time.sleep(0.5)  # interfaces of freshly installed modules register just after boot finishes


def _status(code: int, output: str) -> str:
    status = COMMAND_STATUS.get(code, str(code))
    return "rejected" if status == "ok" and _IOS_ERROR.search(output) else status


def run_ios(c: PTClient, device: str, commands: list[str], config_command: bool) -> list[CliCommandResult]:
    d = c.device(device)
    if not c.is_a(d, "CiscoDevice"):
        raise ValueError(f"{device} is a {d.class_name}, not an IOS device; use send_terminal_command for PCs and servers")
    wait_until_ready(d)
    if not config_command:
        results = []
        for cmd in commands:
            code, output = d.enterCommand(cmd.strip(), "enable")
            results.append(CliCommandResult(command=cmd.strip(), status=_status(code, output), output=output))
        return results
    return _run_config(d, commands)


def _run_config(d, commands: list[str]) -> list[CliCommandResult]:
    """
    Enter config lines the way pasting into IOS would. CiscoDevice.enterCommand(cmd, mode) takes mode
    user|enable|global (switch mode first) or "" (current mode):
    - indented configs (show running-config style): unindented lines run from global config, indented lines in
      the current sub-mode;
    - flat configs: lines run in the current mode; a rejected line is retried from global config (IOS falls back
      to the parent mode, PT does not), and after a failed sub-mode command we return to global so later lines
      cannot land in the previous interface/router.
    """
    indented = any(cmd[:1] in (" ", "\t") for cmd in commands)
    results, reset, submode = [], True, None
    for cmd in commands:
        text = cmd.strip()
        top_level = cmd[:1] not in (" ", "\t")
        mode = "global" if reset or (indented and top_level) else ""
        code, output = d.enterCommand(text, mode)
        status = _status(code, output)
        if status == "invalid" and mode == "" and not indented:
            code, output = d.enterCommand(text, "global")
            status = _status(code, output)
            if status != "ok" and submode:
                d.enterCommand(submode, "global")  # a genuine error: go back to the sub-mode we were in
        results.append(CliCommandResult(command=text, status=status, output=output))
        is_submode = bool(_SUBMODE.match(text))
        if status == "ok" and is_submode:
            submode = text
        elif status == "ok" and mode == "global":
            submode = None
        reset = status != "ok" and is_submode
    d.enterCommand("end", "")
    return results


# IOS terminal lines never emit commandEnded; a command is done when the prompt reappears at the end of the output.
_IOS_PROMPT_AT_END = re.compile(r"[\r\n][\w.\-]+(\([\w\-/.]+\))?[>#]\s*$")


def _leave_setup_dialog(c: PTClient, line) -> None:
    """After a (re)boot without startup-config, IOS sits at the setup dialog; anything typed would answer it."""
    for _ in range(3):
        prompt = line.getPrompt()
        if "initial configuration dialog" in prompt or "[yes/no]" in prompt:
            line.enterCommand("no")
        elif "RETURN" in prompt or not prompt.strip():
            line.enterCommand("")
        else:
            return
        c.ptmp.pump(1.5)


def run_terminal(c: PTClient, device: str, command: str, timeout: float) -> TerminalOutput:
    d = c.device(device)
    ios = c.is_a(d, "CiscoDevice")
    line = d.getCommandPrompt() if c.is_a(d, "Pc") else d.getCommandLine()
    uid, line_cls = line.getObjectUuid(), line.class_name
    for ev in TERMINAL_EVENTS:
        c.ptmp.subscribe(line_cls, uid, ev)
    start = c.ptmp.event_seq
    seen: list[str] = []

    def done(e) -> bool:
        if e.uuid.lower() != uid.lower():
            return False
        if e.name == "commandEnded":
            return True
        if e.name == "outputWritten" and e.params:
            seen.append(str(e.params[0]))
            text = "".join(seen)
            return ios and len(text.strip()) > len(command) and bool(_IOS_PROMPT_AT_END.search(text))
        return False

    try:
        if ios:
            wait_until_ready(d)
            _leave_setup_dialog(c, line)
        line.enterCommand(command)
        c.ptmp.pump(timeout, until=done, since=start)
    finally:
        for ev in TERMINAL_EVENTS:
            c.ptmp.subscribe(line_cls, uid, ev, on=False)
    events = [e for e in c.ptmp.events_since(start) if e.uuid.lower() == uid.lower()]
    output = "".join(str(e.params[0]) for e in events if e.name == "outputWritten" and e.params)
    ended = [e for e in events if e.name == "commandEnded"]
    status = None
    if ended and len(ended[-1].params) > 1:
        status = COMMAND_STATUS.get(ended[-1].params[1], str(ended[-1].params[1]))
    completed = bool(ended) or (ios and bool(_IOS_PROMPT_AT_END.search(output)))
    return TerminalOutput(output=output, completed=completed, status=status)


_WIN_PING = re.compile(r"Sent = (\d+), Received = (\d+), Lost = \d+ \((\d+)% loss\)")
_IOS_PING = re.compile(r"Success rate is (\d+) percent \((\d+)/(\d+)\)")


def parse_ping(source: str, destination: str, output: str) -> PingResult:
    m = _WIN_PING.search(output)
    if m:
        sent, received, loss = int(m.group(1)), int(m.group(2)), int(m.group(3))
    elif (m := _IOS_PING.search(output)) is not None:
        received, sent = int(m.group(2)), int(m.group(3))
        loss = 100 - int(m.group(1))
    else:
        return PingResult(source=source, destination=destination, success=False, output=output.strip() or "no ping output")
    ok = received > 0
    return PingResult(
        source=source,
        destination=destination,
        sent=sent,
        received=received,
        loss_percent=loss,
        success=ok,
        output=None if ok else output.strip(),
    )


def ping(c: PTClient, source: str, destination: str, attempts: int, timeout: float) -> PingResult:
    result = None
    for _ in range(attempts):
        out = run_terminal(c, source, f"ping {destination}", timeout)
        result = parse_ping(source, destination, out.output)
        # The first ping often loses packets while ARP resolves / switch ports finish STP; retry only on total loss.
        if result.success:
            break
    return result


def console_log(c: PTClient, device: str, max_chars: int) -> str:
    d = c.device(device)
    line = d.getCommandPrompt() if c.is_a(d, "Pc") else d.getConsoleLine() if c.is_a(d, "CiscoDevice") else d.getCommandLine()
    return line.getOutput()[-max_chars:]


def command_history(c: PTClient, device: str | None, limit: int) -> list[CommandLogEntry]:
    log = c.root().commandLog()
    entries = []
    for i in range(log.getEntryCount()):
        e = log.getEntryAt(i)
        name = e.getDeviceName()
        if device and name != device:
            continue
        entries.append(CommandLogEntry(time=e.getTimeToString(), device=name, prompt=e.getPrompt(), command=e.getCommand()))
    return entries[-limit:]


def register_tools(mcp):  # noqa: C901
    """Register all CLI and terminal tools with the FastMCP server."""

    @mcp.tool(
        annotations={"title": "Send CLI Command to a Cisco Device", "readOnlyHint": False, "destructiveHint": True},
    )
    async def send_cli_command(
        name: DeviceName,
        commands: str,
        config_command: bool = False,
    ) -> list[CliCommandResult]:
        """
        Send IOS commands to a Cisco device (router, switch, multilayer switch, ASA, WLC...) and return each
        command's status and output. Works even before the device finishes booting (boot is skipped).

        - Separate multiple commands with newlines.
        - config_command=false (default): privileged exec mode (e.g. "show ip interface brief").
        - config_command=true: configuration mode -- DO NOT include "enable", "configure terminal" or "end".
          Sub-modes carry over, so "interface Gi0/0\\nip address 10.0.0.1 255.255.255.0\\nno shutdown" works.
        - status is "invalid"/"incomplete"/"ambiguous" when IOS rejected a command.

        CRITICAL: Can modify device state. Review commands carefully before executing, especially when
        config_command=true.

        Examples:
        - "Run 'show ip route' on R1"
        - "Configure Gi0/0 on R1 with 10.0.0.1/24 and bring it up"
        - "Show the running config of SW1"
        """
        client = get_pt_client_dep()
        cmds = _split(commands)
        if not cmds:
            raise ToolError("No commands given")
        try:
            results = await client.run(lambda c: run_ios(c, name, cmds, config_command))
            return [r.model_dump() for r in results]
        except Exception as e:
            logger.exception("Error sending CLI commands to %s", name)
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Send Command to an End-Device Terminal", "readOnlyHint": False, "destructiveHint": False},
    )
    async def send_terminal_command(
        name: DeviceName,
        command: str,
        timeout: Annotated[float, Field(ge=1, le=300, description="Seconds to wait for the command to finish")] = 20,
    ) -> TerminalOutput:
        """
        Type one command into a device's terminal and collect its output -- for PCs, laptops and servers this
        is the Desktop > Command Prompt ('ping 10.0.0.1', 'ipconfig /all', 'tracert 8.8.8.8', 'arp -a').
        Output is collected until Packet Tracer reports the command ended or the timeout passes; pings
        in Realtime mode take a few seconds.

        Examples:
        - "Ping 192.168.1.1 from PC0"
        - "Run ipconfig on the laptop"
        - "Traceroute from PC1 to the server"
        """
        client = get_pt_client_dep()
        try:
            return (await client.run(lambda c: run_terminal(c, name, command, timeout))).model_dump(exclude_none=True)
        except Exception as e:
            logger.exception("Error running terminal command on %s", name)
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Verify Connectivity (Ping Test)", "readOnlyHint": True},
    )
    async def verify_connectivity(
        source: DeviceName,
        destinations: Annotated[list[str], Field(min_length=1, max_length=20, description="IP addresses or hostnames to ping")],
        attempts: Annotated[int, Field(ge=1, le=5, description="Pings per destination if all packets are lost")] = 2,
    ) -> list[PingResult]:
        """
        Ping each destination from a device (PC/server Command Prompt or a Cisco device) and report sent/received/
        loss per destination. A destination that loses everything is retried (ARP resolution and STP on fresh
        switch links make the first ping fail). Raw output is included only for failures. The standard way to
        verify a CCNA lab end to end.

        Examples:
        - "Can PC1 reach its gateway, the server and the other LAN?"
        - "Verify connectivity from PC1 to 192.168.1.1, 192.168.2.10 and 8.8.8.8"
        - "Is my static routing working?"
        """
        client = get_pt_client_dep()
        try:
            results = await client.run(lambda c: [ping(c, source, d, attempts, 25) for d in destinations])
            return [r.model_dump(exclude_none=True) for r in results]
        except Exception as e:
            logger.exception("Error verifying connectivity from %s", source)
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Get Console Log for a Device", "readOnlyHint": True},
    )
    async def get_console_log(
        name: DeviceName,
        max_chars: Annotated[int, Field(ge=100, le=200000, description="Return at most this many trailing characters")] = 20000,
    ) -> str:
        """
        Return the device's console/terminal buffer as shown in its CLI tab (or the PC's Command Prompt):
        boot messages, %LINK/%LINEPROTO and other syslog messages, and recent command output.

        Examples:
        - "Show R1's console messages"
        - "Did any interface go down on the switch?"
        - "What happened on PC1's command prompt?"
        """
        client = get_pt_client_dep()
        try:
            return await client.run(lambda c: console_log(c, name, max_chars))
        except Exception as e:
            logger.exception("Error reading console log of %s", name)
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Get Command History", "readOnlyHint": True},
    )
    async def get_command_history(
        name: Annotated[str | None, Field(description="Only this device (display name); omit for all devices")] = None,
        limit: Annotated[int, Field(ge=1, le=2000)] = 200,
    ) -> list[CommandLogEntry]:
        """
        Return Packet Tracer's command log: commands typed into device terminals (by a person in the CLI tab, or by
        send_terminal_command/verify_connectivity; send_cli_command and configure_device are not logged), with time,
        device and prompt
        (so the mode is visible, e.g. "R1(config-if)#"). Great for reviewing how a lab was solved, spotting a
        typo, or building a study sheet of the commands used. Most recent last.

        Examples:
        - "What commands did I type on R1?"
        - "Make me a cheat sheet from the commands I used in this lab"
        - "Which command did I mistype?"
        """
        client = get_pt_client_dep()
        try:
            return [e.model_dump() for e in await client.run(lambda c: command_history(c, name, limit))]
        except Exception as e:
            logger.exception("Error reading command log")
            raise ToolError(e)
