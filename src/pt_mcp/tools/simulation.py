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
Simulation-mode tools for the Packet Tracer MCP server -- Packet Tracer's counterpart to packet capture:
send PDUs, step time, and inspect every hop with Packet Tracer's own OSI-layer explanation.
"""

import logging
from typing import Literal

from fastmcp.exceptions import ToolError
from pydantic import Field
from typing_extensions import Annotated

from pt_mcp.ipc import Ref
from pt_mcp.pdu import decode
from pt_mcp.pt_client import PTClient
from pt_mcp.ptmp import IpcCallError
from pt_mcp.tools.dependencies import get_pt_client_dep
from pt_mcp.types import TRAFFIC_TYPES, DeviceName, PduHeader, SimulationEvent, SimulationEventDetails

logger = logging.getLogger("pt-mcp.tools.simulation")

EventIndex = Annotated[int, Field(ge=0, description="Event index from get_simulation_events")]

_STATUS_CHECKS = (
    ("isFrameDropped", "dropped"),
    ("isFrameAccepted", "accepted"),
    ("isFrameCollidedOnLink", "collided"),
    ("isFrameCollidedAtDevice", "collided"),
    ("isFrameBuffered", "buffered"),
    ("isFrameNotForwarded", "not_forwarded"),
    ("isFrameUnexpected", "unexpected"),
    ("isFrameOnTransit", "in_transit"),
    ("isFrameSent", "sent"),
)


def _name(ref_factory) -> str | None:
    try:
        return ref_factory().getName()
    except IpcCallError:
        return None


def describe_event(fi: Ref, index: int) -> SimulationEvent:
    status = "unknown"
    for method, label in _STATUS_CHECKS:
        try:
            if fi.call(method):
                status = label
                break
        except IpcCallError:
            continue
    t = fi.getUserTrafficType()
    return SimulationEvent(
        index=index,
        time=fi.getTime(),
        at_device=_name(fi.getDevice),
        from_device=_name(fi.getPreviousDevice),
        protocol=TRAFFIC_TYPES.get(t, str(t)),
        status=status,
        source=fi.getSourceString() or None,
        destination=fi.getDestinationString() or None,
    )


def list_events(c: PTClient, start: int, limit: int, protocol: str | None) -> list[SimulationEvent]:
    sim = c.root().simulation()
    out = []
    for i in range(start, sim.getFrameInstanceCount()):
        ev = describe_event(sim.getFrameInstanceAt(i), i)
        if protocol and ev.protocol.lower() != protocol.lower():
            continue
        out.append(ev)
        if len(out) >= limit:
            break
    return out


def event_details(c: PTClient, index: int) -> SimulationEventDetails:
    sim = c.root().simulation()
    if index >= sim.getFrameInstanceCount():
        raise IndexError(f"No simulation event {index}; there are {sim.getFrameInstanceCount()}")
    fi = sim.getFrameInstanceAt(index)
    details = SimulationEventDetails(**describe_event(fi, index).model_dump())
    for i in range(64):  # FrameInstance has no decision count; PT errors past the last one
        try:
            text = fi.getDecisionAt(i)
        except IpcCallError:
            break
        if not text:
            break
        details.decisions.append(text)
    for attr, method in (("inbound_pdu", "getInFrame"), ("outbound_pdu", "getOutFrame")):
        try:
            frame = fi.call(method, fetch=True)
            setattr(details, attr, [PduHeader(**h) for h in decode(frame)])
        except IpcCallError:
            pass
    return details


def step(c: PTClient, steps: int, direction: str) -> dict:
    sim = c.root().simulation()
    if not sim.isSimulationMode():
        raise ValueError("Packet Tracer is in Realtime mode; call set_simulation_mode(enabled=true) first")
    before = sim.getFrameInstanceCount()
    for _ in range(steps):
        sim.forward() if direction == "forward" else sim.backward()
    return {
        "time": sim.getCurrentSimTime(),
        "event_count": sim.getFrameInstanceCount(),
        "new_events": max(0, sim.getFrameInstanceCount() - before),
        "current_index": sim.getCurrentFrameInstanceIndex(),
    }


def register_tools(mcp):  # noqa: C901
    """Register simulation-mode tools with the FastMCP server."""

    @mcp.tool(
        annotations={"title": "Switch Realtime/Simulation Mode", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    )
    async def set_simulation_mode(enabled: bool) -> bool:
        """
        Switch Packet Tracer between Simulation mode (enabled=true: time advances only when stepped, every packet
        is recorded) and Realtime mode (enabled=false). Returns the resulting mode. Switching back to Realtime
        clears the event list, so read events/details first.

        Examples:
        - "Switch to simulation mode so I can watch the ping"
        - "Go back to realtime"
        """
        client = get_pt_client_dep()
        try:

            def run(c: PTClient) -> bool:
                sim = c.root().simulation()
                sim.setSimulationMode(enabled)
                return sim.isSimulationMode()

            return await client.run(run)
        except Exception as e:
            logger.exception("Error setting simulation mode")
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Send a Simple PDU (ICMP)", "readOnlyHint": False, "destructiveHint": False},
    )
    async def send_simple_pdu(source: DeviceName, destination: DeviceName) -> int:
        """
        Create a Simple PDU (the envelope tool: an ICMP echo) from one device to another. In Simulation mode,
        step_simulation then moves it hop by hop and get_simulation_events shows where it went -- including any
        ARP it triggers. Returns the PDU's index in the user-created PDU list.

        Examples:
        - "Send a ping PDU from PC1 to the server and watch it"
        - "Show me how ARP works between PC1 and R1"
        """
        client = get_pt_client_dep()
        try:
            return await client.run(lambda c: c.root().appWindow().getUserCreatedPDU().addSimplePdu(source, destination))
        except Exception as e:
            logger.exception("Error adding simple PDU %s -> %s", source, destination)
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Step the Simulation", "readOnlyHint": False, "destructiveHint": False},
    )
    async def step_simulation(
        steps: Annotated[int, Field(ge=1, le=100, description="How many steps (Capture/Forward clicks)")] = 1,
        direction: Literal["forward", "backward"] = "forward",
    ) -> dict:
        """
        Advance (or rewind) Simulation mode by N steps, like clicking Capture/Forward. Returns the simulation
        time, total event count and how many new events were recorded.

        Examples:
        - "Step the simulation forward 5 times"
        - "Go back one step"
        """
        client = get_pt_client_dep()
        try:
            return await client.run(lambda c: step(c, steps, direction))
        except Exception as e:
            logger.exception("Error stepping simulation")
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Get Simulation Events", "readOnlyHint": True},
    )
    async def get_simulation_events(
        start: Annotated[int, Field(ge=0, description="First event index")] = 0,
        limit: Annotated[int, Field(ge=1, le=500, description="Max events to return")] = 50,
        protocol: Annotated[str | None, Field(description="Only this protocol, e.g. ICMP, ARP, OSPF, STP, DHCP")] = None,
    ) -> list[SimulationEvent]:
        """
        List Simulation-mode events (the Event List): time, the device the PDU is at, where it came from,
        protocol, and what happened (sent, accepted, dropped, buffered...).

        Examples:
        - "Where did the ping go?"
        - "Show only the ARP events"
        - "Did any packet get dropped?"
        """
        client = get_pt_client_dep()
        try:
            return [e.model_dump(exclude_none=True) for e in await client.run(lambda c: list_events(c, start, limit, protocol))]
        except Exception as e:
            logger.exception("Error listing simulation events")
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Get Simulation Event Details", "readOnlyHint": True},
    )
    async def get_simulation_event_details(index: EventIndex) -> SimulationEventDetails:
        """
        Explain one Simulation-mode event the way Packet Tracer's PDU Information window does: the device's
        OSI-layer decisions in plain English ("The frame destination MAC address is not in the MAC table. The
        Switch floods the frame...") plus the inbound and outbound headers decoded field by field (Ethernet,
        802.1Q, IP, ICMP, ARP, TCP/UDP, STP, OSPF, DHCP, ...). Great for learning why a packet was forwarded or dropped.

        Examples:
        - "Why was event 2 dropped?"
        - "What does the switch do with the frame at event 1?"
        - "Show me the IP and Ethernet headers of the ping"
        """
        client = get_pt_client_dep()
        try:
            return (await client.run(lambda c: event_details(c, index))).model_dump(exclude_none=True)
        except Exception as e:
            logger.exception("Error reading simulation event %s", index)
            raise ToolError(e)

    @mcp.tool(
        annotations={"title": "Reset the Simulation", "readOnlyHint": False, "destructiveHint": False},
    )
    async def reset_simulation() -> bool:
        """
        Clear the Simulation-mode event list and restart simulation time (Reset Simulation). Device
        configurations are not changed.

        Examples:
        - "Clear the event list"
        - "Start the simulation over"
        """
        client = get_pt_client_dep()
        try:
            await client.run(lambda c: c.root().simulation().resetSimulation())
            return True
        except Exception as e:
            logger.exception("Error resetting simulation")
            raise ToolError(e)
