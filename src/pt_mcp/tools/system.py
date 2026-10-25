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
System information tools for the Packet Tracer MCP server.
"""

import logging

from fastmcp.exceptions import ToolError

from pt_mcp.pt_client import PTClient
from pt_mcp.tools.dependencies import get_pt_client_dep
from pt_mcp.types import SystemInformation

logger = logging.getLogger("pt-mcp.tools.system")

SETUP_HINT = (
    "Is Packet Tracer running with IPC listening (Extensions > IPC > Options, default port 39000), and is the "
    "pt-mcp ExApp (exapp/PTMCP.pta) added under Extensions > IPC > Configure Apps with an ID/key matching "
    "PT_APP_ID/PT_APP_KEY?"
)


def _system_info(c: PTClient) -> SystemInformation:
    ipc = c.root()
    app = ipc.appWindow()
    net = ipc.network()
    info = SystemInformation(
        pt_version=c.pt_version or app.getVersion(),
        ipc_api_spec=c.api.version,
        server_uid=c.ptmp.server_info.get("server_uid"),
        device_count=net.getDeviceCount(),
        link_count=net.getLinkCount(),
    )
    try:
        info.logical_mode = app.isLogicalMode()
        info.simulation_mode = app.isSimulationMode()
        info.file = app.getActiveFile().getSavedFilename() or None
    except Exception:
        logger.debug("Optional system fields unavailable", exc_info=True)
    return info


def register_tools(mcp):
    """Register all system-related tools with the FastMCP server."""

    @mcp.tool(
        annotations={
            "title": "Get Packet Tracer Information",
            "readOnlyHint": True,
        },
    )
    async def get_pt_information() -> SystemInformation:
        """
        Connect to Cisco Packet Tracer over IPC and report its version, the IPC API spec in use,
        device/link counts, workspace mode (logical/physical, realtime/simulation) and the open file.
        Call this first to confirm the connection works.

        Examples:
        - "Is Packet Tracer connected?"
        - "What version of Packet Tracer is running?"
        - "How many devices are in my network?"
        """
        client = get_pt_client_dep()
        try:
            return (await client.run(_system_info)).model_dump(exclude_none=True)
        except OSError as e:
            raise ToolError(f"Cannot reach Packet Tracer at {client.ptmp.host}:{client.ptmp.port} ({e}). {SETUP_HINT}")
        except Exception as e:
            logger.exception("Error getting Packet Tracer information")
            raise ToolError(f"{e}. {SETUP_HINT}")
