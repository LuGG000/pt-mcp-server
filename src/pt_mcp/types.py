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
Shared types: Packet Tracer enums (from the IPC framework's DeviceType / ConnectType / CommandStatus)
and the response models returned by tools.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

# DeviceType (pt-cep-java-framework 9.0.0, ipc/enums/DeviceType.java)
DEVICE_TYPES: dict[str, int] = {
    "router": 0,
    "switch": 1,
    "cloud": 2,
    "bridge": 3,
    "hub": 4,
    "repeater": 5,
    "coaxial_splitter": 6,
    "access_point": 7,
    "pc": 8,
    "server": 9,
    "printer": 10,
    "wireless_router": 11,
    "ip_phone": 12,
    "dsl_modem": 13,
    "cable_modem": 14,
    "remote_network": 15,
    "multilayer_switch": 16,
    "switch3650": 17,
    "laptop": 18,
    "tablet": 19,
    "pda": 20,
    "wireless_end_device": 21,
    "wired_end_device": 22,
    "tv": 23,
    "home_voip": 24,
    "analog_phone": 25,
    "asa": 27,
    "ioe": 28,
    "home_gateway": 29,
    "wireless_router_new_generation": 30,
    "cell_tower": 31,
    "central_office_server": 32,
    "cisco_access_point": 33,
    "embedded_cisco_access_point": 34,
    "sniffer": 35,
    "mcu": 36,
    "sbc": 37,
    "thing": 38,
    "embedded_server": 40,
    "wireless_lan_controller": 41,
    "lightweight_access_point": 44,
    "power_distribution_device": 45,
    "patch_panel": 46,
    "wall_mount": 47,
    "security_appliance": 48,
    "meraki_server": 49,
    "network_controller": 50,
    "plc": 51,
    "cyber_observer": 54,
    "data_historian": 55,
}
DEVICE_TYPE_NAMES: dict[int, str] = {v: k for k, v in DEVICE_TYPES.items()}

DeviceTypeName = Literal[
    "router",
    "switch",
    "cloud",
    "bridge",
    "hub",
    "repeater",
    "coaxial_splitter",
    "access_point",
    "pc",
    "server",
    "printer",
    "wireless_router",
    "ip_phone",
    "dsl_modem",
    "cable_modem",
    "remote_network",
    "multilayer_switch",
    "switch3650",
    "laptop",
    "tablet",
    "pda",
    "wireless_end_device",
    "wired_end_device",
    "tv",
    "home_voip",
    "analog_phone",
    "asa",
    "ioe",
    "home_gateway",
    "wireless_router_new_generation",
    "cell_tower",
    "central_office_server",
    "cisco_access_point",
    "embedded_cisco_access_point",
    "sniffer",
    "mcu",
    "sbc",
    "thing",
    "embedded_server",
    "wireless_lan_controller",
    "lightweight_access_point",
    "power_distribution_device",
    "patch_panel",
    "wall_mount",
    "security_appliance",
    "meraki_server",
    "network_controller",
    "plc",
    "cyber_observer",
    "data_historian",
]

# ConnectType (ipc/enums/ConnectType.java, 9.0.0: FIBER split into single-mode 8103 / multimode 8117)
CABLE_TYPES: dict[str, int] = {
    "straight": 8100,
    "cross": 8101,
    "rollover": 8102,
    "fiber_singlemode": 8103,
    "phone": 8104,
    "cable": 8105,
    "serial": 8106,
    "auto": 8107,
    "console": 8108,
    "wireless": 8109,
    "coaxial": 8110,
    "octal": 8111,
    "cellular": 8112,
    "usb": 8113,
    "custom_io": 8114,
    "bluetooth_paired": 8115,
    "bluetooth_broadcast": 8116,
    "fiber_multimode": 8117,
}
CABLE_TYPE_NAMES: dict[int, str] = {v: k for k, v in CABLE_TYPES.items()}

# Device types whose Ethernet ports are MDI-X (switch side): straight-through to hosts/routers, crossover to each other.
SWITCHING_DEVICE_TYPES = {1, 3, 4, 5, 7, 16, 17, 33, 44}

CableTypeName = Literal[
    "auto",
    "straight",
    "cross",
    "rollover",
    "fiber_singlemode",
    "fiber_multimode",
    "phone",
    "cable",
    "serial",
    "console",
    "wireless",
    "coaxial",
    "octal",
    "cellular",
    "usb",
    "custom_io",
]

COMMAND_STATUS: dict[int, str] = {0: "ok", 1: "ambiguous", 2: "invalid", 3: "incomplete", 4: "not_implemented"}

DeviceName = Annotated[
    str,
    Field(min_length=1, max_length=128, description="Device display name as shown in Packet Tracer (e.g. 'Router0', 'PC1')"),
]
PortName = Annotated[
    str,
    Field(min_length=1, max_length=64, description="Full port name (e.g. 'GigabitEthernet0/0', 'FastEthernet0', 'Serial0/1/0')"),
]
IPv4String = Annotated[str, Field(pattern=r"^\d{1,3}(\.\d{1,3}){3}$", description="Dotted-quad IPv4 address")]
Coordinate = Annotated[float, Field(ge=-100000, le=100000, description="Logical-workspace coordinate in pixels")]


class SystemInformation(BaseModel):
    pt_version: str | None = Field(None, description="Packet Tracer version reported over IPC (e.g. '9.0.1.0858')")
    ipc_api_spec: str = Field(..., description="Bundled IPC API spec in use")
    server_uid: str | None = Field(None, description="IPC server instance UUID")
    device_count: int = Field(..., description="Devices in the active network")
    link_count: int = Field(..., description="Links in the active network")
    logical_mode: bool | None = Field(None, description="True when the Logical workspace is showing")
    simulation_mode: bool | None = Field(None, description="True when in Simulation mode (False = Realtime)")
    file: str | None = Field(None, description="Saved filename of the active network, if any")


class DeviceSummary(BaseModel):
    name: str
    class_name: str = Field(..., description="IPC class (e.g. Router, CiscoDevice, Pc, Server)")
    model: str
    type: str = Field(..., description="Device type name (see add_device_to_network)")
    power: bool
    x: float | None = None
    y: float | None = None


class InterfaceInfo(BaseModel):
    name: str
    class_name: str
    up: bool | None = Field(None, description="Physical/link state")
    protocol_up: bool | None = None
    mac_address: str | None = None
    ip_address: str | None = None
    subnet_mask: str | None = None
    remote_device: str | None = Field(None, description="Device at the other end of the attached cable")
    remote_port: str | None = Field(None, description="Port name at the other end of the attached cable")
    link_uuid: str | None = None


class LinkInfo(BaseModel):
    device_a: str
    port_a: str
    device_b: str | None = None
    port_b: str | None = None
    cable: str | None = Field(None, description="Cable type (straight, cross, serial, ...)")
    link_uuid: str


class CliCommandResult(BaseModel):
    command: str
    status: str = Field(..., description="ok | rejected (IOS printed a '% ...' error) | ambiguous | invalid | incomplete | not_implemented")
    output: str


class TerminalOutput(BaseModel):
    output: str
    completed: bool = Field(..., description="True if Packet Tracer reported the command finished before the timeout")
    status: str | None = None


class HostInterfaceConfig(BaseModel):
    ip_address: str | None = None
    subnet_mask: str | None = None
    dhcp: bool | None = None


# TrafficType (ipc/enums/TrafficType.java): FrameInstance.getUserTrafficType() -> protocol label
TRAFFIC_TYPES: dict[int, str] = {
    0: "ICMP",
    1: "TCP",
    2: "UDP",
    3: "RIPv1",
    4: "RIPv2",
    5: "ARP",
    6: "CDP",
    7: "DHCP",
    8: "NAT",
    9: "EIGRP",
    10: "VTP",
    11: "STP",
    12: "OSPF",
    13: "DTP",
    14: "TELNET",
    15: "SSH",
    16: "TFTP",
    17: "HTTP",
    18: "HTTPS",
    19: "DNS",
    20: "ICMPv6",
    21: "LACP",
    22: "PAGP",
    23: "IPSEC",
    24: "IKE",
    25: "SYSLOG",
    26: "TACACS",
    27: "RADIUS",
    28: "SNMP",
    29: "NTP",
    30: "FTP",
    31: "SMTP",
    32: "POP3",
    33: "SCCP",
    34: "RTP",
    35: "H323",
    36: "BGP",
    37: "HSRP",
    38: "HSRPv6",
    39: "NETFLOW",
    40: "NDv6",
    41: "RIPng",
    42: "DHCPv6",
    43: "EIGRPv6",
    44: "OSPFv6",
    45: "IoE",
    46: "PTP",
    47: "REP",
    48: "CAPWAP",
    49: "LLDP",
    50: "SPAN",
    51: "IoE-TCP",
    52: "USB",
    53: "BLUETOOTH",
    54: "PPPoED",
    55: "PPP",
    56: "EAPOL",
    57: "Meraki",
    58: "MODBUS",
    59: "PROFINET",
    60: "IEC",
    1000: "CUSTOM",
}


class ModuleSlot(BaseModel):
    slot: str = Field(..., description="Slot path used by add_module_to_device, e.g. '0/0'")
    module: str | None = Field(None, description="Installed module model, or null if the slot is empty")
    ports: list[str] = Field(default_factory=list, description="Ports the installed module provides")


class SupportedModule(BaseModel):
    model: str
    description: str


class DeviceModelDetails(BaseModel):
    device: str
    model: str
    slots: list[ModuleSlot]
    supported_modules: list[SupportedModule]


class DeviceConfiguration(BaseModel):
    device: str
    source: str = Field(..., description="running | startup")
    config: str


class ConfigureResult(BaseModel):
    device: str
    commands_sent: int
    errors: list[CliCommandResult] = Field(default_factory=list, description="Commands IOS rejected (status != ok)")
    saved: bool = False


class CommandLogEntry(BaseModel):
    time: str
    device: str
    prompt: str
    command: str


class PingResult(BaseModel):
    source: str
    destination: str
    sent: int | None = None
    received: int | None = None
    loss_percent: int | None = None
    success: bool
    output: str | None = Field(None, description="Raw ping output (only included on failure)")


class SimulationEvent(BaseModel):
    index: int
    time: int = Field(..., description="Simulation time of the event")
    at_device: str | None = None
    from_device: str | None = None
    protocol: str = Field(..., description="Traffic type label, e.g. ICMP, ARP, OSPF, STP")
    status: str = Field(..., description="sent | accepted | dropped | buffered | collided | in_transit | not_forwarded | unexpected")
    source: str | None = None
    destination: str | None = None


class PduHeader(BaseModel):
    header: str = Field(..., description="Header/PDU type, e.g. EthernetIIHeader, IpHeader, IcmpMessage")
    fields: dict = Field(default_factory=dict)


class SimulationEventDetails(SimulationEvent):
    decisions: list[str] = Field(default_factory=list, description="Packet Tracer's OSI-layer explanation of what the device did")
    inbound_pdu: list[PduHeader] = Field(default_factory=list, description="Headers as received, outermost first")
    outbound_pdu: list[PduHeader] = Field(default_factory=list, description="Headers as sent, outermost first")


class TopologyDevice(BaseModel, extra="ignore"):
    name: str = Field(..., description="Device display name")
    device_type: str = Field(..., description="router, switch, pc, server, ... (see add_device_to_network)")
    model: str = Field(..., description="Model, e.g. 2911, 2960-24TT, PC-PT")
    x: float = 100
    y: float = 100
    modules: list[dict] = Field(default_factory=list, description='Modules to install, e.g. [{"slot": "0/0", "module": "HWIC-2T"}]')
    config: str | None = Field(None, description="IOS configuration to apply (Cisco devices)")


class TopologyLink(BaseModel, extra="ignore"):
    device_a: str
    port_a: str
    device_b: str
    port_b: str
    cable: str = "auto"


class TopologyHost(BaseModel, extra="ignore"):
    name: str
    port: str = "FastEthernet0"
    ip_address: str | None = None
    subnet_mask: str | None = None
    default_gateway: str | None = None
    dns_server: str | None = None
    dhcp: bool | None = None


class Topology(BaseModel, extra="ignore"):
    description: str | None = Field(None, description="Network description (Packet Tracer's File > Network description)")
    devices: list[TopologyDevice] = Field(default_factory=list)
    links: list[TopologyLink] = Field(default_factory=list)
    hosts: list[TopologyHost] = Field(default_factory=list, description="IPv4 settings for PCs/servers/laptops")


class TopologyBuildResult(BaseModel):
    devices: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ActivityInstructions(BaseModel):
    is_activity: bool
    page_count: int = 0
    pages: list[str] = Field(default_factory=list, description="Instruction pages as plain text")


class Annotation(BaseModel):
    id: str
    kind: str = Field(..., description="note | line | ellipse | rectangle | polygon")
    x: int | None = Field(None, description="Note position, or line start")
    y: int | None = None
    end_x: int | None = Field(None, description="Line end")
    end_y: int | None = None
    color: str | None = Field(None, description="Line color 'r,g,b'")
    text: str | None = None
