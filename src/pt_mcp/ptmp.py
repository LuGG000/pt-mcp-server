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

"""Packet Tracer Messaging Protocol (PTMP) client, text encoding.

Reconstructed from Cisco's pt-cep-java-framework-8.1.0.0.jar (bundled in PT's help/default/ipc)
and cross-checked against the PacketTracer 8.2.0 binary.

Wire format (text encoding, no encryption, no compression):
  frame   := <decimal payload length> NUL <payload>
  payload := <ltv type> NUL <field> NUL <field> NUL ...
Every scalar is written as its decimal / dotted / "{uuid}" string followed by NUL.

Session: negotiate (type 0) -> auth request (2) -> challenge (3) -> auth response (4) -> status (5),
then IPC messages (100) answered by responses (102) or errors (101); events arrive as 103.
"""

from __future__ import annotations

import hashlib
import socket
import threading
import time
import uuid as uuidlib
from dataclasses import dataclass, field
from typing import Any

# LTV message types
NEGOTIATE = 0
NEGOTIATE_REPLY = 1
AUTH_REQUEST = 2
AUTH_CHALLENGE = 3
AUTH_RESPONSE = 4
AUTH_STATUS = 5
KEEP_ALIVE = 6
DISCONNECT = 7
IPC_MESSAGE = 100
IPC_ERROR = 101
IPC_RESPONSE = 102
IPC_EVENT = 103
IPC_EVENT_SUBSCRIPTION = 104

# Negotiation option values (OptionsManager.connectOptions)
TEXT_ENCODING = 1
NO_ENCRYPTION = 1
NOT_COMPRESSED = 1
CLEAR_TEXT_AUTH = 1
SIMPLE_AUTH = 2
MD5_AUTH = 4

# IPC value type codes (IPCMessageConstants)
T_VOID, T_BYTE, T_BOOL, T_SHORT, T_INT, T_LONG, T_FLOAT, T_DOUBLE = range(8)
T_STRING, T_QSTRING, T_IP, T_IPV6, T_MAC, T_UUID, T_PAIR, T_VECTOR, T_DATA = range(8, 17)

TYPE_CODES = {
    "void": T_VOID,
    "byte": T_BYTE,
    "bool": T_BOOL,
    "short": T_SHORT,
    "int": T_INT,
    "long": T_LONG,
    "float": T_FLOAT,
    "double": T_DOUBLE,
    "string": T_STRING,
    "QString": T_QSTRING,
    "ip": T_IP,
    "ipv6": T_IPV6,
    "mac": T_MAC,
    "uuid": T_UUID,
}

ENCODING = "utf-8"


class PtmpError(Exception):
    pass


class IpcCallError(PtmpError):
    def __init__(self, source: str, message: str):
        super().__init__(f"{source}: {message}" if source else message)
        self.source = source
        self.message = message


@dataclass
class Data:
    """An IPC data structure (type 16). Field layout is struct-specific, so fields stay raw."""

    subtype: str
    fields: list[str]


@dataclass
class Event:
    class_name: str
    uuid: str
    name: str
    params: list[Any]
    seq: int = 0  # position in the client's event stream (monotonic; the buffer itself is trimmed)


@dataclass
class Call:
    name: str
    args: list[tuple[int, Any]] = field(default_factory=list)  # (type code, value)


def _fmt(type_code: int, value: Any) -> str:
    if type_code == T_BOOL:
        return "true" if value else "false"
    if type_code == T_UUID:
        s = str(value)
        return s if s.startswith("{") else "{" + s + "}"
    if type_code in (T_FLOAT, T_DOUBLE):
        return repr(float(value))
    if type_code in (T_BYTE, T_SHORT, T_INT, T_LONG):
        return str(int(value))
    return str(value)


def _encode(fields: list[str]) -> bytes:
    payload = b"".join(f.encode(ENCODING) + b"\0" for f in fields)
    return str(len(payload)).encode() + b"\0" + payload


class _Tokens:
    def __init__(self, parts: list[str]):
        self.parts = parts
        self.i = 0

    def remaining(self) -> int:
        return len(self.parts) - self.i

    def next(self) -> str:
        if self.i >= len(self.parts):
            raise PtmpError("truncated PTMP message")
        v = self.parts[self.i]
        self.i += 1
        return v

    def rest(self) -> list[str]:
        v = self.parts[self.i :]
        self.i = len(self.parts)
        return v


def _read_value(tok: _Tokens, type_code: int | None = None) -> Any:
    t = int(tok.next()) if type_code is None else type_code
    if t == T_VOID:
        return None
    if t == T_BOOL:
        return tok.next().lower() == "true"
    if t in (T_BYTE, T_SHORT, T_INT, T_LONG):
        return int(tok.next())
    if t in (T_FLOAT, T_DOUBLE):
        return float(tok.next())
    if t in (T_STRING, T_QSTRING, T_IP, T_IPV6, T_MAC, T_UUID):
        return tok.next()
    if t == T_PAIR:
        return (_read_value(tok), _read_value(tok))
    if t == T_VECTOR:
        sub = int(tok.next())
        n = int(tok.next())
        return [_read_value(tok, sub) for _ in range(n)]
    if t == T_DATA:
        # Struct layouts are per-subtype (IPCResponseFactory.getIPCData); a response holds one value,
        # so the remaining tokens all belong to it.
        return Data(tok.next(), tok.rest())
    raise PtmpError(f"unhandled IPC value type {t}")


class PtmpClient:
    """Synchronous PTMP client. One request in flight at a time; events are queued."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 39000,
        app_id: str = "net.netacad.cisco.ipctest",
        secret: str = "cisco",
        auth: int = MD5_AUTH,
        timeout: float = 30.0,
        port_scan: int = 10,
        guard=None,
    ):
        self.guard = guard  # pt_mcp.safety.CallGuard: vets every method before it is sent
        self.host, self.port = host, port
        # PT takes the next free port when its configured one is busy (a second instance, or the old port still
        # held after a crash), so on "connection refused" try port, port+1, ... port+port_scan-1.
        self.port_scan = max(1, port_scan)
        self.app_id, self.secret, self.auth = app_id, secret, auth
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self._buf = b""
        self._msg_id = 1
        self._lock = threading.Lock()
        self.events: list[Event] = []  # most recent 1000 events
        self.event_seq = 0  # total events received; use events_since(seq) rather than list indexes
        self.server_info: dict[str, str] = {}

    # ---- framing -------------------------------------------------------------------------------
    def _send(self, fields: list[str]) -> None:
        assert self.sock is not None
        self.sock.sendall(_encode(fields))

    def _recv_frame(self) -> list[str]:
        assert self.sock is not None
        while b"\0" not in self._buf:
            self._fill()
        head, self._buf = self._buf.split(b"\0", 1)
        length = int(head.decode())
        while len(self._buf) < length:
            self._fill()
        payload, self._buf = self._buf[:length], self._buf[length:]
        parts = payload.decode(ENCODING, errors="replace").split("\0")
        if parts and parts[-1] == "":
            parts.pop()
        return parts

    def _fill(self) -> None:
        chunk = self.sock.recv(65536)
        if not chunk:
            raise PtmpError("connection closed by Packet Tracer")
        self._buf += chunk

    # ---- session -------------------------------------------------------------------------------
    def connect(self) -> None:
        self.close()
        refused: OSError | None = None
        for port in [self.port] + [p for p in range(self.port, self.port + self.port_scan) if p != self.port]:
            try:
                self.sock = socket.create_connection((self.host, port), timeout=self.timeout)
            except ConnectionRefusedError as e:
                refused = refused or e
                continue
            self.port = port
            break
        else:
            raise refused
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self._buf = b""
        self._negotiate()
        self._authenticate()

    def _negotiate(self) -> None:
        self._send(
            [
                str(NEGOTIATE),
                "PTMP",
                "1",
                "{" + str(uuidlib.uuid4()) + "}",
                str(TEXT_ENCODING),
                str(NO_ENCRYPTION),
                str(NOT_COMPRESSED),
                str(self.auth),
                time.strftime("%Y%m%d%I%M%S"),
                "0",
                "null",
            ]
        )
        parts = self._recv_frame()
        if parts and parts[0] == str(DISCONNECT):
            raise PtmpError("negotiation rejected: " + " ".join(parts[1:]))
        if len(parts) < 10 or parts[0] not in (str(NEGOTIATE), str(NEGOTIATE_REPLY)):
            raise PtmpError(f"unexpected negotiation reply: {parts!r}")
        keys = [
            "signature",
            "version",
            "server_uid",
            "encoding",
            "encryption",
            "compression",
            "authentication",
            "server_timestamp",
            "keep_alive",
            "reserved",
        ]
        self.server_info = dict(zip(keys, parts[1:]))
        for k, want in (("encoding", TEXT_ENCODING), ("encryption", NO_ENCRYPTION), ("compression", NOT_COMPRESSED)):
            if self.server_info.get(k) != str(want):
                raise PtmpError(f"server negotiated unsupported {k}={self.server_info.get(k)}")

    def _authenticate(self) -> None:
        self._send([str(AUTH_REQUEST), self.app_id])
        parts = self._recv_frame()
        if parts[0] == str(DISCONNECT):
            raise PtmpError("Packet Tracer disconnected during auth (is the ExApp registered and enabled?)")
        if parts[0] != str(AUTH_CHALLENGE):
            raise PtmpError(f"expected auth challenge, got {parts!r}")
        challenge = parts[1] if len(parts) > 1 else ""
        if self.auth == MD5_AUTH:
            digest = hashlib.md5((challenge + self.secret).encode(ENCODING)).hexdigest().upper()
        elif self.auth == SIMPLE_AUTH:
            digest = "".join(chr(158 - b) for b in self.secret.encode(ENCODING))
        else:
            digest = self.secret
        self._send([str(AUTH_RESPONSE), self.app_id, digest, ""])
        while True:
            parts = self._recv_frame()
            if parts[0] == str(KEEP_ALIVE):
                continue
            break
        if parts[0] == str(DISCONNECT):
            raise PtmpError("authentication rejected (wrong ExApp ID/KEY, or ExApp disabled in PT)")
        if parts[0] != str(AUTH_STATUS) or len(parts) < 2 or parts[1].lower() != "true":
            raise PtmpError(f"authentication failed: {parts!r}")

    def close(self) -> None:
        if self.sock is not None:
            try:
                self._send([str(DISCONNECT)])
            except OSError:
                pass
            try:
                self.sock.close()
            finally:
                self.sock = None

    @property
    def connected(self) -> bool:
        return self.sock is not None

    # ---- IPC -----------------------------------------------------------------------------------
    def call(self, calls: list[Call]) -> Any:
        """Send one IPC message (a call chain evaluated left to right) and return the last value."""
        names = [c.name for c in calls]
        if self.guard is not None:
            self.guard.check(names)
        result = self._call(calls)
        if self.guard is not None:
            self.guard.recorded(names)
        return result

    def _call(self, calls: list[Call]) -> Any:
        with self._lock:
            if self.sock is None:
                self.connect()
            msg_id = self._msg_id
            self._msg_id += 1
            fields = [str(IPC_MESSAGE), str(msg_id)]
            for c in calls:
                fields.append(c.name)
                for type_code, value in c.args:
                    fields += [str(type_code), _fmt(type_code, value)]
                fields.append(str(T_VOID))
            try:
                self._send(fields)
                return self._await(msg_id)
            except (OSError, PtmpError):
                self.sock = None
                raise

    def _await(self, msg_id: int) -> Any:
        while True:
            parts = self._recv_frame()
            kind = int(parts[0])
            tok = _Tokens(parts[1:])
            if kind == IPC_RESPONSE:
                if int(tok.next()) != msg_id:
                    continue
                return _read_value(tok) if tok.remaining() else None
            if kind == IPC_ERROR:
                if int(tok.next()) != msg_id:
                    continue
                src = tok.next() if tok.remaining() else ""
                msg = tok.next() if tok.remaining() else ""
                raise IpcCallError(src, msg)
            self._handle_unsolicited(kind, tok)

    def _handle_unsolicited(self, kind: int, tok: _Tokens) -> None:
        if kind == IPC_EVENT:
            tok.next()  # event id
            cls, uid, name = tok.next(), tok.next(), tok.next()
            params = []
            while tok.remaining():
                v = _read_value(tok)
                if v is None:
                    break
                params.append(v)
            self.event_seq += 1
            self.events.append(Event(cls, uid, name, params, self.event_seq))
            del self.events[:-1000]
        elif kind == KEEP_ALIVE:
            self._send([str(KEEP_ALIVE)])
        elif kind == DISCONNECT:
            self.sock = None
            raise PtmpError("Packet Tracer closed the IPC session")
        # Multi-user and unknown messages are ignored.

    def pump(self, seconds: float, until=None, since: int | None = None) -> list[Event]:
        """
        Read unsolicited frames for up to `seconds`, or until `until(event)` is true. Returns events after `since`
        (default: the current position). Events already received after `since` (e.g. while a call awaited its reply)
        are checked against `until` first.
        """
        start = self.event_seq if since is None else since
        if until and any(until(e) for e in self.events_since(start)):
            return self.events_since(start)
        deadline = time.monotonic() + seconds
        with self._lock:
            if self.sock is None:
                return []
            try:
                while (left := deadline - time.monotonic()) > 0:
                    if b"\0" not in self._buf:
                        self.sock.settimeout(left)
                        try:
                            self._fill()
                        except socket.timeout:
                            break
                        continue
                    parts = self._recv_frame()
                    before = self.event_seq
                    self._handle_unsolicited(int(parts[0]), _Tokens(parts[1:]))
                    if until and self.event_seq > before and until(self.events[-1]):
                        break
            finally:
                if self.sock is not None:
                    self.sock.settimeout(self.timeout)
        return self.events_since(start)

    def events_since(self, seq: int) -> list[Event]:
        """Events received after the stream position `seq` (take it from `event_seq` before acting)."""
        return [e for e in self.events if e.seq > seq]

    def subscribe(self, class_name: str, object_uuid: str, event_name: str, on: bool = True) -> None:
        """LTV 104. Use the all-zero UUID to subscribe to every object of `class_name`."""
        with self._lock:
            if self.sock is None:
                self.connect()
            self._send([str(IPC_EVENT_SUBSCRIPTION), class_name, _fmt(T_UUID, object_uuid), event_name, "true" if on else "false"])
