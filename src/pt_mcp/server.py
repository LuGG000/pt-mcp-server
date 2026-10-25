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
Main server module for the Packet Tracer MCP server.
This module initializes the FastMCP server and registers all tools from modular components.
"""

import logging
import os

# Import dependencies first so the shared Packet Tracer client exists before tool modules load
from pt_mcp.settings import settings
from pt_mcp.tools import dependencies  # noqa: F401 - imported for side effects (global client init)
from pt_mcp.tools import (
    activity,
    annotations,
    cli,
    configuration,
    devices,
    files,
    interfaces,
    ipc_api,
    links,
    modules,
    simulation,
    system,
    topology,
)

# Set up root logging for pt-mcp and all submodules (stderr: stdout carries the stdio transport)
logger = logging.getLogger("pt-mcp")
loglevel = logging.DEBUG if os.getenv("DEBUG", "false").lower() == "true" else logging.INFO
logger.setLevel(loglevel)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False

from fastmcp import FastMCP  # noqa: E402

server_mcp = FastMCP(
    name="Cisco Packet Tracer",
    website_url="https://www.netacad.com/cisco-packet-tracer",
    instructions=(
        "Tools for building and configuring networks in a running Cisco Packet Tracer over its native IPC interface. "
        "Start with get_pt_information. Devices are addressed by display name (e.g. 'Router0'). Use send_cli_command "
        "for IOS devices and send_terminal_command for PC/server command prompts. Users are often CCNA students: "
        "explain what each step does and why, verify with show commands and verify_connectivity, and use simulation "
        "mode (send_simple_pdu, step_simulation, get_simulation_event_details) to show how packets move. On graded "
        "activities (.pka), teach and give hints rather than completing the tasks for the student."
    ),
)

logger.info("Registering tools...")
system.register_tools(server_mcp)
devices.register_tools(server_mcp)
interfaces.register_tools(server_mcp)
links.register_tools(server_mcp)
cli.register_tools(server_mcp)
configuration.register_tools(server_mcp)
modules.register_tools(server_mcp)
topology.register_tools(server_mcp)
annotations.register_tools(server_mcp)
simulation.register_tools(server_mcp)
activity.register_tools(server_mcp)
files.register_tools(server_mcp)
ipc_api.register_tools(server_mcp, enable_raw_ipc=settings.pt_mcp_enable_raw_ipc)
logger.info("All tools registered successfully")
