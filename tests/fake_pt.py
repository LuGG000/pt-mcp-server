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
A fake Packet Tracer IPC server for offline tests.

Speaks real PTMP (text encoding, MD5 auth) on a local socket and evaluates call chains against a small
in-memory network model. Return values are typed using the bundled IPC API spec, so the wire format the
client sees matches what Packet Tracer would send.
"""

import hashlib
import socket
import threading
import uuid

from pt_mcp.ipc import Api

SPEC = Api.load("ipc_api_9.0.1.json")
TYPE_CODES = {
    "void": 0, "byte": 1, "bool": 2, "short": 3, "int": 4, "long": 5, "float": 6, "double": 7,
    "string": 8, "QString": 9, "ip": 10, "ipv6": 11, "mac": 12, "uuid": 13,
}  # fmt: skip


class Obj:
    ipc_class = "Object"

    def __init__(self):
        self.uuid = "{" + str(uuid.uuid4()) + "}"

    def getClassName(self):
        return self.ipc_class

    def getObjectUuid(self):
        return self.uuid


class Link(Obj):
    ipc_class = "Cable"

    def __init__(self, a, b, ctype):
        super().__init__()
        self.a, self.b, self.ctype = a, b, ctype

    def getConnectionType(self):
        return self.ctype

    def getPort1(self):
        return self.a

    def getPort2(self):
        return self.b

    def getOtherPort(self, device, port):
        return self.b if (self.a.owner.name, self.a.name) == (device, port) else self.a


class Port(Obj):
    ipc_class = "RouterPort"

    def __init__(self, name, host=True):
        super().__init__()
        self.owner = None
        self.name, self.link, self.ip, self.mask, self.power, self.dhcp = name, None, "0.0.0.0", "0.0.0.0", True, False
        self.ipc_class = "HostPort" if host else "SwitchPort"

    def getName(self):
        return self.name

    def isPortUp(self):
        return self.link is not None

    def isProtocolUp(self):
        return self.link is not None

    def getMacAddress(self):
        return "0001.4200.0001"

    def getIpAddress(self):
        return self.ip

    def getSubnetMask(self):
        return self.mask

    def setIpSubnetMask(self, ip, mask):
        self.ip, self.mask = ip, mask

    def setDefaultGateway(self, gw):
        self.gw = gw

    def setDnsServerIp(self, dns):
        self.dns = dns

    def setDhcpClientFlag(self, on):
        self.dhcp = on

    def isDhcpClientOn(self):
        return self.dhcp

    def setPower(self, on):
        self.power = on

    def getLink(self):
        return self.link

    def getRemotePortName(self):
        return ""  # Packet Tracer 9.0.1 returns "" even for cabled ports

    def getOwnerDevice(self):
        return self.owner


class TerminalLine(Obj):
    ipc_class = "TerminalLine"

    def __init__(self, server):
        super().__init__()
        self.server = server

    def enterCommand(self, cmd):
        self.server.queue_event(self.ipc_class, self.uuid, "outputWritten", [(8, f"Reply to {cmd}\n"), (2, False), (4, 0)])
        self.server.queue_event(self.ipc_class, self.uuid, "commandEnded", [(8, cmd), (4, 0)])


class Device(Obj):
    def __init__(self, server, name, dtype, model, x, y):
        super().__init__()
        self.server, self.name, self.dtype, self.model, self.x, self.y, self.power = server, name, dtype, model, x, y, True
        self.mode = "user"
        if dtype == 0:
            self.ipc_class, self.ports = "Router", [Port("GigabitEthernet0/0"), Port("GigabitEthernet0/1")]
        elif dtype == 1:
            self.ipc_class, self.ports = "CiscoDevice", [Port(f"FastEthernet0/{i}", host=False) for i in range(1, 5)]
        elif dtype == 45:
            self.ipc_class, self.ports = "Device", []
        else:
            self.ipc_class, self.ports = "Pc", [Port("FastEthernet0")]
        for p in self.ports:
            p.owner = self
        self.prompt = TerminalLine(server)

    def getName(self):
        return self.name

    def setName(self, n):
        self.name = n

    def getModel(self):
        return self.model

    def getType(self):
        return self.dtype

    def getPower(self):
        return self.power

    def setPower(self, on):
        self.power = on

    def getXCoordinate(self):
        return self.x

    def getYCoordinate(self):
        return self.y

    def getPortCount(self):
        return len(self.ports)

    def getPortAt(self, i):
        return self.ports[i]

    def getPort(self, name):
        return next(p for p in self.ports if p.name == name)

    def getCommandPrompt(self):
        return self.prompt

    def getCommandLine(self):
        return self.prompt

    def isBooting(self):
        return False

    def skipBoot(self):
        pass

    def enterCommand(self, cmd, mode):
        if mode:
            self.mode = {"global": "config"}.get(mode, mode)
        if cmd == "end":
            self.mode = "enable"
        elif cmd.startswith("interface"):
            self.mode = "config-if"
        if cmd.startswith("bogus"):
            return (2, "% Invalid input detected at '^' marker.")
        if self.mode == "config-if" and cmd.startswith(("ip route", "hostname", "router ")):
            return (2, "")  # Packet Tracer does not fall back to the parent mode
        if self.mode == "config" and cmd.startswith(("ip address", "no shutdown", "clock rate")):
            return (2, "")
        if cmd.startswith("interface") and not any(p.name == cmd.split(" ", 1)[1] for p in self.ports):
            return (2, "")
        if cmd.startswith("ip address") and "overlap" in getattr(self, "_next", ""):
            return (0, "% 10.0.12.0 overlaps with GigabitEthernet0/0")
        return (0, f"[{self.mode}] {cmd}")


class Network(Obj):
    ipc_class = "Network"

    def __init__(self, server):
        super().__init__()
        self.server = server

    def getDeviceCount(self):
        return len(self.server.devices)

    def getDeviceAt(self, i):
        return self.server.devices[i]

    def getDevice(self, name):
        return next((d for d in self.server.devices if d.name == name), None)

    def getLinkCount(self):
        return len(self.server.links)

    def getLinkAt(self, i):
        return self.server.links[i]


class LogicalWorkspace(Obj):
    ipc_class = "LogicalWorkspace"

    def __init__(self, server):
        super().__init__()
        self.server = server

    def addDevice(self, dtype, model, x, y):
        prefix = {0: "Router", 1: "Switch", 8: "PC"}.get(dtype, "Device")
        n = sum(1 for d in self.server.devices if d.name.startswith(prefix))
        if not any(d.dtype == 45 for d in self.server.devices):
            self.server.devices.append(Device(self.server, "Power Distribution Device0", 45, "Power Distribution Device", 3901, 3999))
        dev = Device(self.server, f"{prefix}{n}", dtype, model, x, y)
        self.server.devices.append(dev)
        return dev.name

    def removeDevice(self, name):
        dev = self.server.network.getDevice(name)
        if not dev:
            return False
        for p in dev.ports:
            if p.link:
                self._unlink(p.link)
        self.server.devices.remove(dev)
        return True

    def createLink(self, d1, p1, d2, p2, ctype):
        a, b = self.server.network.getDevice(d1).getPort(p1), self.server.network.getDevice(d2).getPort(p2)
        if ctype == 8107 or a.link or b.link:
            return False
        a.link = b.link = Link(a, b, ctype)
        self.server.links.append(a.link)
        return True

    def deleteLink(self, d, p):
        port = self.server.network.getDevice(d).getPort(p)
        if not port.link:
            return False
        self._unlink(port.link)
        return True

    def _unlink(self, link):
        link.a.link = link.b.link = None
        self.server.links.remove(link)


class Workspace(Obj):
    ipc_class = "Workspace"

    def __init__(self, server):
        super().__init__()
        self.lw = LogicalWorkspace(server)

    def getLogicalWorkspace(self):
        return self.lw


class NetworkFile(Obj):
    ipc_class = "NetworkFile"

    def getSavedFilename(self):
        return ""


class AppWindow(Obj):
    ipc_class = "AppWindow"

    def __init__(self, server):
        super().__init__()
        self.server, self.ws, self.file = server, Workspace(server), NetworkFile()

    def getVersion(self):
        return "9.0.1.0858"

    def getActiveWorkspace(self):
        return self.ws

    def getActiveFile(self):
        return self.file

    def isLogicalMode(self):
        return True

    def isSimulationMode(self):
        return False

    def fileNew(self, prompt):
        self.server.devices.clear()
        self.server.links.clear()
        return True

    def fileSaveAsNoPrompt(self, path, overwrite):
        open(path, "w").write("fake pkt")


class Descriptor(Obj):
    ipc_class = "DeviceDescriptor"

    def __init__(self, model):
        super().__init__()
        self.model = model

    def getModel(self):
        return self.model


class DeviceFactory(Obj):
    ipc_class = "DeviceFactory"
    MODELS = {0: ["1941", "2911", "2911", "ISR4331"], 1: ["2960-24TT", "2960-24TT", "3650-24PS"], 8: ["PC-PT", "PC-PT"]}

    def getAvailableDeviceForTypeCount(self, t):
        return len(self.MODELS.get(t, []))

    def getAvailableDeviceForTypeAt(self, t, i):
        return Descriptor(self.MODELS[t][i])


class HardwareFactory(Obj):
    ipc_class = "HardwareFactory"

    def __init__(self):
        super().__init__()
        self.df = DeviceFactory()

    def devices(self):
        return self.df


class Root(Obj):
    ipc_class = "IPC"

    def __init__(self, server):
        super().__init__()
        self._network, self._app, self._hw = server.network, AppWindow(server), HardwareFactory()

    def network(self):
        return self._network

    def appWindow(self):
        return self._app

    def hardwareFactory(self):
        return self._hw


def frame(fields):
    payload = b"".join(str(f).encode() + b"\0" for f in fields)
    return str(len(payload)).encode() + b"\0" + payload


class FakePacketTracer:
    def __init__(self, app_id="net.netacad.cisco.ptmcp", key="ptmcp"):
        self.app_id, self.key = app_id, key
        self.devices, self.links = [], []
        self.network = Network(self)
        self.root = Root(self)
        self.subscriptions: set[tuple[str, str, str]] = set()
        self._pending = []
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(4)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def queue_event(self, cls, uid, name, params):
        if (cls, uid.lower(), name) in self.subscriptions:
            fields = [103, 1, cls, uid, name]
            for t, v in params:
                fields += [t, v]
            self._pending.append(frame(fields + [0]))

    def _accept(self):
        while True:
            conn, _ = self.srv.accept()
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    @staticmethod
    def _frames(conn):
        buf = b""
        while True:
            while b"\0" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buf += chunk
            head, buf = buf.split(b"\0", 1)
            n = int(head)
            while len(buf) < n:
                buf += conn.recv(65536)
            payload, buf = buf[:n], buf[n:]
            yield payload.decode().split("\0")[:-1]

    def _serve(self, conn):
        frames = self._frames(conn)
        try:
            next(frames)
            conn.sendall(frame([1, "PTMP", 1, "{fake-server}", 1, 1, 1, 4, "20261022000000", 0, ":PTVER9.0.1.0858"]))
            if next(frames)[1] != self.app_id:
                conn.sendall(frame([7]))
                return
            conn.sendall(frame([3, "CHALLENGE"]))
            resp = next(frames)
            ok = resp[2] == hashlib.md5(("CHALLENGE" + self.key).encode()).hexdigest().upper()
            conn.sendall(frame([5, "true" if ok else "false"]))
            for f in frames:
                kind = int(f[0])
                if kind == 104:
                    key = (f[1], f[2].lower(), f[3])
                    (self.subscriptions.add if f[4] == "true" else self.subscriptions.discard)(key)
                elif kind == 100:
                    conn.sendall(self._evaluate(f[1], f[2:]))
                    while self._pending:
                        conn.sendall(self._pending.pop(0))
                elif kind == 7:
                    return
        except StopIteration:
            return

    def _evaluate(self, msg_id, tokens):
        obj, i, last = self.root, 0, None
        try:
            while i < len(tokens):
                name, i, args = tokens[i], i + 1, []
                while tokens[i] != "0":
                    t, v = int(tokens[i]), tokens[i + 1]
                    args.append({2: lambda s: s == "true", 4: int, 7: float}.get(t, str)(v))
                    i += 2
                i += 1
                if obj is None:
                    raise AttributeError("null object")
                last = (obj, name)
                obj = getattr(obj, name)(*args)
        except Exception as e:
            return frame([101, msg_id, type(e).__name__, str(e)])
        return frame([102, msg_id] + self._typed(last, obj))

    def _typed(self, last, value):
        if value is None:
            return []
        cls, method = last[0].ipc_class, last[1]
        sigs = SPEC.overloads(cls, method)
        ret = sigs[0]["returns"] if sigs else None
        if isinstance(value, tuple):
            return [14] + [x for v in value for x in ([4, v] if isinstance(v, int) else [8, v])]
        if isinstance(value, list):
            return [15, 8, len(value)] + list(value)
        if isinstance(value, FakeData):
            return [16, value.subtype] + list(value.fields)
        if isinstance(value, bool):
            return [2, "true" if value else "false"]
        code = TYPE_CODES.get(ret)
        if code is None:
            code = 4 if isinstance(value, int) else 7 if isinstance(value, float) else 8
        return [code, value]


# ---- CCNA / cml-parity surface: modules, configs, console, command log, simulation, notes, activities ----


class FakeData:
    def __init__(self, subtype, fields):
        self.subtype, self.fields = subtype, fields


# The ICMP echo frame captured from live Packet Tracer 9.0.1 (PC1 192.168.1.11 -> R1 192.168.1.1)
ICMP_FRAME = FakeData(
    "EthernetIIHeader",
    (
        "16 IpHeader 16 IcmpMessage 16 VariableSizePdu 4 0 1 8 1 0 3 0 3 5 3 13 1 4 1 5 1 0 3 28 3 13 1 0 3 0 "
        "3 255 3 1 3 0 10 192.168.1.11 10 192.168.1.1 4 0 4 0 12 0030.F27C.2601 12 00E0.8F66.C658 4 0 3 2048"
    ).split(),
)


class ModuleDescriptor(Obj):
    ipc_class = "ModuleDescriptor"

    def __init__(self, model, mtype=2):
        super().__init__()
        self.model, self.mtype = model, mtype

    def getModel(self):
        return self.model

    def getType(self):
        return self.mtype


class Module(Obj):
    ipc_class = "Module"

    def __init__(self, model, path, slots=0, ports=()):
        super().__init__()
        self.model, self.path, self.children, self.ports = model, path, [None] * slots, list(ports)

    def getSlotCount(self):
        return len(self.children)

    def getModuleCount(self):
        return len(self.children)

    def getModuleAt(self, i):
        if self.children[i] is None:
            raise LookupError("Module: IPC Cache entry: ")
        return self.children[i]

    def getSlotPath(self):
        return self.path

    def getDescriptor(self):
        return ModuleDescriptor(self.model)

    def getModuleNameAsString(self):
        return "None"

    def getModuleType(self):
        return 18 if self.path == "" else 2

    def getPortCount(self):
        return len(self.ports)

    def getPortAt(self, i):
        return self.ports[i]


class ModuleFactory(Obj):
    ipc_class = "ModuleFactory"
    CATALOG = [("HWIC-2T", 2), ("HWIC-4ESW", 2), ("NIM-2T", 2), ("WIC-2T", 2)]

    def getAvailableModuleCount(self):
        return len(self.CATALOG)

    def getAvailableModuleAt(self, i):
        return ModuleDescriptor(*self.CATALOG[i])


HardwareFactory.modules = lambda self: ModuleFactory()


class Process(Obj):
    ipc_class = "HostIp"

    def __init__(self, dev):
        super().__init__()
        self.dev = dev

    def getDefaultGateway(self):
        return getattr(self.dev.ports[0], "gw", "0.0.0.0") if self.dev.ports else "0.0.0.0"

    def getServerIp(self):
        return getattr(self.dev.ports[0], "dns", "0.0.0.0") if self.dev.ports else "0.0.0.0"


def _get_process(self, name):
    if name not in ("HostIpProcess", "DnsClient"):  # PT 9.0.1 process names (not "HostIp")
        raise LookupError("Process: IPC Cache entry: ")
    return Process(self)


class ConsoleLine(TerminalLine):
    ipc_class = "ConsoleLine"

    def getOutput(self):
        return self.server.console.get(id(self), "%LINK-5-CHANGED: Interface GigabitEthernet0/0, changed state to up\n")


_orig_device_init = Device.__init__


def _device_init(self, server, name, dtype, model, x, y):
    _orig_device_init(self, server, name, dtype, model, x, y)
    self.running, self.startup, self.prompt = [], None, ConsoleLine(server)
    board = Module("CISCO2911-MB", "", slots=4) if dtype == 0 else Module("None", "", slots=0)
    self.root = Module("None", "", slots=1)
    self.root.children[0] = board


Device.__init__ = _device_init
Device.getRootModule = lambda self: self.root
Device.getConsoleLine = lambda self: self.prompt
Device.getProcess = _get_process
Device.getSupportedModule = lambda self: (
    ["HWIC-2T:../art/PhysicalView/gModuleHWIC-2T.pngThe HWIC-2T is a Cisco 2-Port Serial High-Speed WAN Interface Card."]
    if self.dtype == 0
    else []
)


def _add_module(self, slot, mtype, model):
    if self.power or self.dtype != 0 or not slot.startswith("0/"):
        return False
    i = int(slot.split("/")[1])
    board = self.root.children[0]
    if i >= len(board.children) or board.children[i] is not None:
        return False
    ports = [Port(f"Serial{slot}/{n}") for n in range(2)]
    for p in ports:
        p.owner = self
    board.children[i] = Module(model, slot, ports=ports)
    self.ports += ports
    return True


def _remove_module(self, slot):
    board = self.root.children[0]
    for i, m in enumerate(board.children):
        if m is not None and m.path == slot and not self.power:
            self.ports = [p for p in self.ports if p not in m.ports]
            board.children[i] = None
            return True
    return False


Device.addModule = _add_module
Device.removeModule = _remove_module
_orig_enter = Device.enterCommand


def _enter(self, cmd, mode):
    if cmd == "show running-config":
        self.mode = "enable"
        return (0, "Building configuration...\n\nCurrent configuration : 100 bytes\n!\nversion 15.1\n!\nhostname " + self.name + "\n"
                + "".join(c + "\n" for c in self.running) + "!\nend\n")  # fmt: skip
    if cmd == "show startup-config":
        return (0, "startup-config is not present\n" if self.startup is None else self.startup)
    if cmd == "write memory":
        self.startup = "\n".join(self.running)
        return (0, "Building configuration...\n[OK]\n")
    if cmd == "write erase":
        return (0, "Erasing the nvram filesystem will remove all configuration files! Continue? [confirm]")
    if cmd == "reload":
        return (0, "System configuration has been modified. Save? [yes/no]:")
    if cmd == "no" and mode == "":
        return (0, "Proceed with reload? [confirm]")
    if cmd == "" and mode == "":
        self.startup = None
        return (0, "[OK]\n")
    status, out = _orig_enter(self, cmd, mode)
    if status == 0 and self.mode.startswith("config") and cmd not in ("end",):
        self.running.append(cmd)
    return (status, out)


Device.enterCommand = _enter


class CommandLogEntry(Obj):
    ipc_class = "CommandLogEntry"

    def __init__(self, device, prompt, command):
        super().__init__()
        self.e = (device, prompt, command)

    def getDeviceName(self):
        return self.e[0]

    def getPrompt(self):
        return self.e[1]

    def getCommand(self):
        return self.e[2]

    def getTimeToString(self):
        return "Thu Oct 22 21:34:21 2026"


class CommandLog(Obj):
    ipc_class = "CommandLog"

    def __init__(self, server):
        super().__init__()
        self.server = server

    def getEntryCount(self):
        return len(self.server.cmdlog)

    def getEntryAt(self, i):
        return CommandLogEntry(*self.server.cmdlog[i])


class FrameInstance(Obj):
    ipc_class = "FrameInstance"

    def __init__(self, t, at, frm, status, decisions):
        super().__init__()
        self.t, self.at, self.frm, self.status, self.decisions = t, at, frm, status, decisions

    def getTime(self):
        return self.t

    def getDevice(self):
        return self.at

    def getPreviousDevice(self):
        return self.frm

    def getUserTrafficType(self):
        return 0

    def getSourceString(self):
        return ""

    def getDestinationString(self):
        return ""

    def getDecisionAt(self, i):
        if i >= len(self.decisions):
            raise IndexError("vector subscript")
        return self.decisions[i]

    def getInFrame(self):
        return ICMP_FRAME

    def getOutFrame(self):
        return ICMP_FRAME


for _m, _s in (("isFrameDropped", "dropped"), ("isFrameAccepted", "accepted"), ("isFrameSent", "sent")):
    setattr(FrameInstance, _m, (lambda st: lambda self: self.status == st)(_s))
for _m in (
    "isFrameCollidedOnLink",
    "isFrameCollidedAtDevice",
    "isFrameBuffered",
    "isFrameNotForwarded",
    "isFrameUnexpected",
    "isFrameOnTransit",
):
    setattr(FrameInstance, _m, lambda self: False)


class Simulation(Obj):
    ipc_class = "Simulation"

    def __init__(self, server):
        super().__init__()
        self.server, self.on, self.events, self.pending, self.time = server, False, [], [], 0

    def setSimulationMode(self, on):
        self.on = on

    def isSimulationMode(self):
        return self.on

    def resetSimulation(self):
        self.events, self.time = [], 0

    def forward(self):
        if self.pending:
            self.events.append(self.pending.pop(0))
        self.time += 1

    def backward(self):
        self.time = max(0, self.time - 1)

    def getFrameInstanceCount(self):
        return len(self.events)

    def getFrameInstanceAt(self, i):
        return self.events[i]

    def getCurrentSimTime(self):
        return self.time

    def getCurrentFrameInstanceIndex(self):
        return len(self.events) - 1


class UserCreatedPDU(Obj):
    ipc_class = "UserCreatedPDU"

    def __init__(self, server):
        super().__init__()
        self.server = server

    def addSimplePdu(self, src, dst):
        net = self.server.network
        a, b = net.getDevice(src), net.getDevice(dst)
        sw = next((d for d in self.server.devices if d.dtype == 1), None)
        flood = "The frame destination MAC address is not in the MAC table. The Switch floods the frame to all ports in the same VLAN."
        self.server.sim.pending += [
            FrameInstance(0, a, None, "sent", ["The device creates an ICMP Echo Request."]),
            FrameInstance(1, sw, a, "sent", ["FastEthernet0/1 receives the frame.", flood]),
            FrameInstance(2, b, sw, "accepted", ["The destination IP address matches the device's interface IP address."]),
        ]
        return 0


class ActivityFile(NetworkFile):
    ipc_class = "ActivityFile"

    def isActivityFile(self):
        return True

    def getInstructionCount(self):
        return 2

    def getInstruction(self, i):
        return [
            "<h2>Objectives</h2><ul><li>Configure OSPF</li><li>Verify connectivity</li></ul>",
            "<p>Part 2: Use <b>show ip route</b>.</p>",
        ][i]


NetworkFile.isActivityFile = lambda self: False
NetworkFile.getNetworkDescription = lambda self: getattr(self, "desc", "")
NetworkFile.setNetworkDescription = lambda self, d: setattr(self, "desc", d)


def _lw_notes(cls):
    cls.addNote = lambda self, x, y, z, text: self.server.add_note(x, y, text)
    cls.getIncNoteZOrder = lambda self: 1.0
    cls.getCanvasNoteIds = lambda self: list(self.server.notes)
    cls.getCanvasEllipseIds = lambda self: list(self.server.ellipses)
    cls.getCanvasRectIds = cls.getCanvasPolygonIds = lambda self: []
    cls.getCanvasLineIds = lambda self: list(self.server.lines)
    cls.getLineItemData = lambda self, uid: [str(v) for v in self.server.lines[uid][:4]] + [self.server.lines[uid][4]]
    cls.drawLine = lambda self, sx, sy, ex, ey, layer, w, r, g, b: self.server.add_shape(
        self.server.lines, (sx, sy, ex, ey, f"{r},{g},{b}")
    )

    cls.drawCircle = lambda self, cx, cy, layer, radius, r, g, b: self.server.add_shape(self.server.ellipses, (cx, cy, radius))

    def _boom(self, uid):
        raise RuntimeError("getEllipseItemData would crash Packet Tracer 9.0.1")

    cls.getEllipseItemData = _boom
    cls.getCanvasNoteText = lambda self, uid: self.server.notes[uid][2]
    cls.getCanvasItemRealX = lambda self, uid: self.server.notes[uid][0]
    cls.getCanvasItemRealY = lambda self, uid: self.server.notes[uid][1]
    cls.changeNoteText = lambda self, uid, t: bool(self.server.notes.__setitem__(uid, self.server.notes[uid][:2] + (t,)) or True)
    cls.removeCanvasItem = lambda self, uid: any(
        d.pop(uid, None) is not None for d in (self.server.notes, self.server.lines, self.server.ellipses)
    )


_lw_notes(LogicalWorkspace)
_orig_fpt_init = FakePacketTracer.__init__


def _fpt_init(self, *a, **kw):
    self.cmdlog = [("R1", "R1(config)#", "router ospf 1"), ("PC1", "C:\\>", "ping 10.0.0.1")]
    self.console = {}
    # PT 9 keeps hidden, empty placeholder notes in every network
    self.notes = {"{00000000-0000-0000-0000-00000000000%d}" % i: (3, 9, "") for i in range(3)}
    self.lines, self.ellipses = {}, {"{00000000-0000-0000-0000-0000000000e1}": (0, 0, 1)}
    self.sim = Simulation(self)
    _orig_fpt_init(self, *a, **kw)
    self.root._commandlog, self.root._sim, self.root._app.pdu = CommandLog(self), self.sim, UserCreatedPDU(self)


def _add_note(self, x, y, text):
    uid = "{" + str(uuid.uuid4()) + "}"
    self.notes[uid] = (x, y, text)
    return uid


def _add_shape(self, store, data):
    uid = "{" + str(uuid.uuid4()) + "}"
    store[uid] = data
    return uid


FakePacketTracer.__init__ = _fpt_init
FakePacketTracer.add_shape = _add_shape
FakePacketTracer.add_note = _add_note
Root.commandLog = lambda self: self._commandlog
Root.simulation = lambda self: self._sim
AppWindow.getUserCreatedPDU = lambda self: self.pdu
