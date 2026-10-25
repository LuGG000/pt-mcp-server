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
Dependency helpers: the shared Packet Tracer client and destructive-action confirmation.
"""

import logging
from typing import Any, Optional

from fastmcp import Context

from pt_mcp.pt_client import PTClient
from pt_mcp.settings import settings

logger = logging.getLogger("pt-mcp.dependencies")

# One IPC session per server process: Packet Tracer authenticates the ExApp per TCP connection.
pt_client = PTClient(
    settings.pt_host,
    settings.pt_port,
    settings.pt_app_id,
    settings.pt_app_key,
    timeout=settings.pt_timeout,
    api_spec=settings.pt_api_spec,
    port_scan=settings.pt_port_scan,
    allow_unverified=settings.pt_allow_unverified_ipc,
)


def get_pt_client_dep() -> PTClient:
    """Return the shared Packet Tracer client."""
    return pt_client


def cleanup_pt_client() -> None:
    """Close the IPC session. Called on shutdown."""
    try:
        pt_client.close()
    except Exception:
        logger.exception("Error closing Packet Tracer IPC session")


async def elicit_confirmation(ctx: Context, message: str, response_type: Optional[Any] = ["yes", "no"]) -> bool:
    """
    Request confirmation via elicitation if the client supports it.

    Disabled for the same reason as in cml-mcp: several MCP clients handle ctx.elicit() poorly or duplicate
    the prompt. Destructive tools rely on the CRITICAL line in their docstrings instead; keep calling this
    helper so re-enabling is a one-line change.
    """
    return True
