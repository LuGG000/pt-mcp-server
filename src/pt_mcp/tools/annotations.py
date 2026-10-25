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
Logical-workspace annotation tools (notes and drawn shapes) for the Packet Tracer MCP server.
"""

import logging

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field
from typing_extensions import Annotated

from pt_mcp.pt_client import PTClient
from pt_mcp.ptmp import IpcCallError
from pt_mcp.tools.dependencies import elicit_confirmation, get_pt_client_dep
from pt_mcp.types import Annotation

logger = logging.getLogger("pt-mcp.tools.annotations")

AnnotationId = Annotated[str, Field(pattern=r"^\{?[0-9a-fA-F-]{36}\}?$", description="Annotation UUID from get_annotations")]
Coord = Annotated[int, Field(ge=-100000, le=100000, description="Logical-workspace coordinate in pixels")]
_KINDS = (("note", "getCanvasNoteIds"), ("line", "getCanvasLineIds"), ("ellipse", "getCanvasEllipseIds"), ("rectangle", "getCanvasRectIds"),
          ("polygon", "getCanvasPolygonIds"))  # fmt: skip
# Only notes and lines are read per item. LogicalWorkspace.getEllipseItemData() crashes Packet Tracer 9.0.1
# (verified live), and the other shape getters are unverified, so ellipses/rectangles/polygons are listed by id only.
_PER_ITEM_SAFE = {"note", "line"}


def list_annotations(c: PTClient) -> list[Annotation]:
    lw = c.logical_workspace()
    out = []
    for kind, method in _KINDS:
        for uid in lw.call(method) or []:
            a = Annotation(id=uid, kind=kind)
            if kind not in _PER_ITEM_SAFE:
                out.append(a)
                continue
            try:
                if kind == "note":
                    # Real* is the workspace position addNote uses; getCanvasItemX is scene-relative.
                    a.x, a.y = lw.getCanvasItemRealX(uid), lw.getCanvasItemRealY(uid)
                    a.text = lw.getCanvasNoteText(uid)
                else:
                    sx, sy, ex, ey, rgb = (lw.getLineItemData(uid) + [None] * 5)[:5]
                    a.x, a.y, a.end_x, a.end_y, a.color = int(sx), int(sy), int(ex), int(ey), rgb
            except IpcCallError:
                pass
            if kind == "note" and not a.text:
                continue  # PT 9 keeps hidden, empty placeholder notes in every network
            out.append(a)
    return out


def add_line(c: PTClient, start_x: int, start_y: int, end_x: int, end_y: int, width: int, r: int, g: int, b: int) -> str:
    lw = c.logical_workspace()
    # LogicalWorkspace.drawLine(sx, sy, ex, ey, layer, w, r, g, b) per the bundled IPC reference
    return lw.drawLine(start_x, start_y, end_x, end_y, lw.getIncNoteZOrder(), width, r, g, b)


def add_circle(c: PTClient, cx: int, cy: int, radius: int, r: int, g: int, b: int) -> str:
    lw = c.logical_workspace()
    # LogicalWorkspace.drawCircle(cx, cy, layer, radius, r, g, b). Never read it back with getEllipseItemData (crashes PT).
    return lw.drawCircle(cx, cy, lw.getIncNoteZOrder(), radius, r, g, b)


def add_note(c: PTClient, text: str, x: int, y: int) -> str:
    lw = c.logical_workspace()
    return lw.addNote(x, y, lw.getIncNoteZOrder(), text)


def register_tools(mcp):
    """Register annotation tools with the FastMCP server."""

    @mcp.tool(
        annotations={"title": "Get Workspace Annotations", "readOnlyHint": True},
    )
    async def get_annotations() -> list[Annotation]:
        """
        List the notes and drawn shapes on the logical workspace with their ids, positions and note text.

        Examples:
        - "What notes are on my topology?"
        - "Find the label that says 'LAN A'"
        """
        client = get_pt_client_dep()
        try:
            return [a.model_dump(exclude_none=True) for a in await client.run(list_annotations)]
        except Exception as e:
            logger.exception("Error listing annotations")
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Add a Text Note", "readOnlyHint": False, "destructiveHint": False},
    )
    async def add_text_note(text: Annotated[str, Field(min_length=1, max_length=4000)], x: Coord = 50, y: Coord = 50) -> str:
        """
        Place a text note on the logical workspace (the "Place Note" tool) -- e.g. subnet labels,
        "VLAN 10 - Sales", an addressing table, or lab instructions. Returns the note's id.

        Examples:
        - "Label the LAN behind R1 as 192.168.1.0/24"
        - "Add a note with the lab objectives at the top"
        """
        client = get_pt_client_dep()
        try:
            return await client.run(lambda c: add_note(c, text, x, y))
        except Exception as e:
            logger.exception("Error adding note")
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Add a Line Annotation", "readOnlyHint": False, "destructiveHint": False},
    )
    async def add_line_annotation(
        start_x: Coord,
        start_y: Coord,
        end_x: Coord,
        end_y: Coord,
        width: Annotated[int, Field(ge=1, le=20, description="Line width in pixels")] = 2,
        color: Annotated[str, Field(pattern=r"^\d{1,3},\d{1,3},\d{1,3}$", description="RGB as 'r,g,b'")] = "0,0,0",
    ) -> str:
        """
        Draw a line on the logical workspace, e.g. to separate sites, mark a WAN boundary, or underline a label.
        Returns the line's id.

        Examples:
        - "Draw a red line between the HQ and branch halves of the topology"
        - "Underline the title note"
        """
        r, g, b = (min(255, int(v)) for v in color.split(","))
        client = get_pt_client_dep()
        try:
            return await client.run(lambda c: add_line(c, start_x, start_y, end_x, end_y, width, r, g, b))
        except Exception as e:
            logger.exception("Error adding line")
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Add a Circle Annotation", "readOnlyHint": False, "destructiveHint": False},
    )
    async def add_circle_annotation(
        center_x: Coord,
        center_y: Coord,
        radius: Annotated[int, Field(ge=5, le=5000, description="Radius in pixels")] = 100,
        color: Annotated[str, Field(pattern=r"^\d{1,3},\d{1,3},\d{1,3}$", description="RGB as 'r,g,b'")] = "0,128,255",
    ) -> str:
        """
        Draw a circle on the logical workspace, e.g. to group a LAN, mark a broadcast or collision domain, or
        highlight an OSPF area. Returns the circle's id (get_annotations lists circles as kind "ellipse").

        Examples:
        - "Circle the devices in VLAN 10"
        - "Mark each broadcast domain with a circle"
        """
        r, g, b = (min(255, int(v)) for v in color.split(","))
        client = get_pt_client_dep()
        try:
            return await client.run(lambda c: add_circle(c, center_x, center_y, radius, r, g, b))
        except Exception as e:
            logger.exception("Error adding circle")
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Edit a Text Note", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    )
    async def edit_text_note(annotation_id: AnnotationId, text: Annotated[str, Field(min_length=1, max_length=4000)]) -> bool:
        """
        Replace the text of an existing note.

        Examples:
        - "Change the R1 LAN label to 10.1.1.0/24"
        """
        client = get_pt_client_dep()
        try:
            return await client.run(lambda c: c.logical_workspace().changeNoteText(annotation_id, text))
        except Exception as e:
            logger.exception("Error editing note %s", annotation_id)
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Delete an Annotation", "readOnlyHint": False, "destructiveHint": True},
    )
    async def delete_annotation(annotation_id: AnnotationId, ctx: Context) -> bool:
        """
        Delete a note or drawn shape from the workspace.

        CRITICAL: Destructive. Confirm with the user before deleting.

        Examples:
        - "Remove the old 'TODO' note"
        """
        client = get_pt_client_dep()
        try:
            if not await elicit_confirmation(ctx, f"Delete annotation {annotation_id}?"):
                raise Exception("Operation cancelled by user.")
            ok = await client.run(lambda c: c.logical_workspace().removeCanvasItem(annotation_id))
            if not ok:
                raise LookupError(f"No annotation {annotation_id}")
            return True
        except Exception as e:
            logger.exception("Error deleting annotation %s", annotation_id)
            raise ToolError(e)
