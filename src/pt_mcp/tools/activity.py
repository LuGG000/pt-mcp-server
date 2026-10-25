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
Packet Tracer activity (.pka) tools for the Packet Tracer MCP server.

Academic integrity: the pt-mcp ExApp deliberately does NOT request Packet Tracer's ACTIVITY_WIZARD privilege.
That privilege is what exposes an activity's answer network, assessment tree, score and password hash, so
these tools can only read what a student already sees: the instructions.
"""

import html
import logging
import re

from fastmcp.exceptions import ToolError

from pt_mcp.pt_client import PTClient
from pt_mcp.tools.dependencies import get_pt_client_dep
from pt_mcp.types import ActivityInstructions

logger = logging.getLogger("pt-mcp.tools.activity")


def html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<!DOCTYPE[^>]*>|<head>.*?</head>", "", s)
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</tr>|</h\d>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "- ", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", s)).strip()


def instructions(c: PTClient) -> ActivityInstructions:
    f = c.root().appWindow().getActiveFile()
    if f.class_name != "ActivityFile" or not f.isActivityFile():
        return ActivityInstructions(is_activity=False)
    n = f.getInstructionCount()
    return ActivityInstructions(is_activity=True, page_count=n, pages=[html_to_text(f.getInstruction(i)) for i in range(n)])


def register_tools(mcp):
    """Register activity tools with the FastMCP server."""

    @mcp.tool(
        annotations={"title": "Get Activity Instructions", "readOnlyHint": True},
    )
    async def get_activity_instructions() -> ActivityInstructions:
        """
        If the open file is a Packet Tracer activity (.pka, e.g. a NetAcad CCNA lab), return its instruction pages
        as plain text: objectives, addressing table, and the tasks to complete.

        This server cannot read an activity's answers, score or completion percentage (it does not hold Packet
        Tracer's ACTIVITY_WIZARD privilege). Use Check Results in Packet Tracer for grading. When helping a
        student, prefer explaining concepts and hinting over doing the graded tasks for them.

        Examples:
        - "What does this activity ask me to do?"
        - "Read me the addressing table from the instructions"
        - "Explain task 3 of this lab"
        """
        client = get_pt_client_dep()
        try:
            return (await client.run(instructions)).model_dump()
        except Exception as e:
            logger.exception("Error reading activity instructions")
            raise ToolError(e)
