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
Network file (.pkt) tools for the Packet Tracer MCP server.
"""

import asyncio
import logging
import os

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field
from typing_extensions import Annotated

from pt_mcp.tools.dependencies import elicit_confirmation, get_pt_client_dep

logger = logging.getLogger("pt-mcp.tools.files")

PktPath = Annotated[str, Field(min_length=1, description="Absolute path to a .pkt/.pka file on the Packet Tracer host")]


def register_tools(mcp):
    """Register all file-related tools with the FastMCP server."""

    @mcp.tool(
        annotations={"title": "Create a New Empty Network", "readOnlyHint": False, "destructiveHint": True},
    )
    async def create_new_network(ctx: Context) -> bool:
        """
        Close the current network and start a new, empty one without a save prompt.

        CRITICAL: Unsaved changes to the current network are lost. Always ask "Discard the current network?"
        (or offer save_network_file first) and wait for the user's "yes" before invoking this tool.

        Examples:
        - "Start a fresh topology"
        - "Clear the workspace"
        """
        client = get_pt_client_dep()
        try:
            if not await elicit_confirmation(ctx, "Discard the current network?"):
                raise Exception("Operation cancelled by user.")
            return await client.run(lambda c: c.root().appWindow().fileNew(False))
        except Exception as e:
            logger.exception("Error creating new network")
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Open a Network File", "readOnlyHint": False, "destructiveHint": True},
    )
    async def open_network_file(path: PktPath, ctx: Context) -> int:
        """
        Open a .pkt (network) or .pka (activity) file. Returns Packet Tracer's result code.

        CRITICAL: Replaces the open network; unsaved changes may be lost. Confirm with the user first.

        Examples:
        - "Open ~/labs/ospf.pkt"
        - "Load the activity file I downloaded"
        """
        client = get_pt_client_dep()
        path = os.path.abspath(os.path.expanduser(path))
        try:
            if not await elicit_confirmation(ctx, f"Open {path} and replace the current network?"):
                raise Exception("Operation cancelled by user.")
            return await client.run(lambda c: c.root().appWindow().fileOpen(path))
        except Exception as e:
            logger.exception("Error opening %s", path)
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Save the Network to a File", "readOnlyHint": False, "destructiveHint": False},
    )
    async def save_network_file(path: PktPath) -> str:
        """
        Save the current network as a .pkt file at an absolute path, without a dialog. Overwrites an
        existing file at that path. Returns the saved path.

        Examples:
        - "Save this topology to ~/labs/campus.pkt"
        - "Back up the network"
        """
        client = get_pt_client_dep()
        path = os.path.abspath(os.path.expanduser(path))
        if not path.lower().endswith((".pkt", ".pka")):
            path += ".pkt"
        try:
            await client.run(lambda c: c.root().appWindow().fileSaveAsNoPrompt(path, True))
            for _ in range(20):
                if os.path.exists(path):
                    break
                await asyncio.sleep(0.25)
            return path
        except Exception as e:
            logger.exception("Error saving %s", path)
            raise ToolError(e)
