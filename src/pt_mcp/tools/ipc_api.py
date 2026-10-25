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
Raw IPC API tools: reach any of the Packet Tracer IPC methods not covered by a dedicated tool.
"""

import json
import logging
from typing import Any

from fastmcp.exceptions import ToolError
from pydantic import Field
from typing_extensions import Annotated

from pt_mcp.ipc import Ref
from pt_mcp.pt_client import PTClient
from pt_mcp.tools.dependencies import get_pt_client_dep

logger = logging.getLogger("pt-mcp.tools.ipc_api")


def _parse_chain(chain: list[list[Any]] | str) -> list[list[Any]]:
    if isinstance(chain, str):
        chain = json.loads(chain)
    if not isinstance(chain, list) or not all(isinstance(s, list) and s and isinstance(s[0], str) for s in chain):
        raise ValueError('chain must be a list of [method, arg...] lists, e.g. [["network"], ["getDeviceCount"]]')
    return chain


def call_chain(c: PTClient, chain: list[list[Any]]) -> Any:
    ref: Any = c.root()  # every method is vetted by pt_mcp.safety.CallGuard before it is sent
    for step in chain:
        if not isinstance(ref, Ref):
            raise ValueError(f"Cannot call {step[0]} on a non-object result {ref!r}")
        ref = ref.call(step[0], *step[1:])
    if isinstance(ref, Ref):
        ref.class_name  # resolve so the caller learns what it got
    return c.plain(ref)


def describe(c: PTClient, class_name: str, name_filter: str) -> dict:
    api = c.offline_api()
    if class_name not in api.classes:
        similar = [k for k in api.classes if class_name.lower() in k.lower()]
        raise ValueError(f"Unknown IPC class {class_name!r}. Similar: {similar[:25]}")
    methods = {
        m: [f"({', '.join(s['params'])}) -> {s['returns']}" + (f"  [{s['privilege']}]" if s["privilege"] else "") for s in sigs]
        for m, sigs in sorted(api.methods(class_name).items())
        if name_filter.lower() in m.lower()
    }
    return {"class": class_name, "lineage": api.lineage(class_name), "api_spec": api.version, "methods": methods}


def register_tools(mcp, enable_raw_ipc: bool = False):
    """Register IPC API tools. call_ipc_api is only registered when PT_MCP_ENABLE_RAW_IPC=true."""

    if enable_raw_ipc:
        _register_call_ipc_api(mcp)

    _register_describe(mcp)


def _register_call_ipc_api(mcp):
    @mcp.tool(
        annotations={"title": "Call the Packet Tracer IPC API", "readOnlyHint": False, "destructiveHint": True},
    )
    async def call_ipc_api(
        chain: Annotated[
            list[list[Any]] | str,
            Field(
                description='Call chain from the IPC root, e.g. [["network"], ["getDevice", "R1"], ["getPort", "Gi0/0"], ["getIpAddress"]]'
            ),
        ],
    ) -> Any:
        """
        Advanced escape hatch: evaluate a raw IPC call chain starting at the root `ipc` object (methods:
        appWindow, network, simulation, hardwareFactory, options, ipcManager, commandLog, multiUserManager,
        systemFileManager, userAppManager). Argument wire types come from the IPC API spec decoded from
        the running Packet Tracer version; use describe_ipc_class to look up signatures. Object results come
        back as {object, path}; data structures as {data, fields}.

        CRITICAL: Setter methods modify the network. Prefer the dedicated tools; confirm destructive calls
        (remove*, delete*, fileNew, exit) with the user first. Only methods verified against a live Packet Tracer
        are sent (others are refused to avoid crashing it) unless PT_ALLOW_UNVERIFIED_IPC=true.

        Examples:
        - "What's the MAC of R1 Gi0/0?" -> [["network"],["getDevice","R1"],["getPort","GigabitEthernet0/0"],["getMacAddress"]]
        - "Switch to simulation mode" -> [["simulation"],["setSimulationMode",true]]
        """
        client = get_pt_client_dep()
        try:
            steps = _parse_chain(chain)
            return await client.run(lambda c: call_chain(c, steps))
        except Exception as e:
            logger.exception("Error calling IPC chain %s", chain)
            raise ToolError(e)


def _register_describe(mcp):
    @mcp.tool(
        annotations={"title": "Describe a Packet Tracer IPC Class", "readOnlyHint": True},
    )
    async def describe_ipc_class(
        class_name: Annotated[str, Field(description="IPC class, e.g. Router, CiscoDevice, HostPort, LogicalWorkspace, AppWindow")],
        name_filter: Annotated[str, Field(description="Only methods whose name contains this text")] = "",
    ) -> dict:
        """
        Show an IPC class's inheritance and method signatures, (param types) -> return type plus the
        ExApp privilege each needs. Use with call_ipc_api.

        Examples:
        - "What methods does a Router have for OSPF?" -> class_name="OspfProcess"
        - "How do I read a port's MAC address?" -> class_name="Port", name_filter="mac"
        """
        client = get_pt_client_dep()
        try:
            return describe(client, class_name, name_filter)
        except Exception as e:
            raise ToolError(e)
