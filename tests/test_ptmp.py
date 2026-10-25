import hashlib
import socket
import threading

import pytest

from pt_mcp.ipc import Api, Ref
from pt_mcp.ptmp import Data, IpcCallError, PtmpClient, PtmpError


def frame(*fields):
    payload = b"".join(str(f).encode() + b"\0" for f in fields)
    return str(len(payload)).encode() + b"\0" + payload


class FakePT:
    """Minimal PTMP server: negotiation, MD5 auth, and scripted IPC responses."""

    def __init__(self, responder, key="k", challenge="CHAL"):
        self.responder, self.key, self.challenge = responder, key, challenge
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.received = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _frames(self, conn):
        buf = b""
        while True:
            while b"\0" not in buf:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                buf += chunk
            head, buf = buf.split(b"\0", 1)
            n = int(head)
            while len(buf) < n:
                buf += conn.recv(4096)
            payload, buf = buf[:n], buf[n:]
            yield payload.decode().split("\0")[:-1]

    def _serve(self):
        conn, _ = self.srv.accept()
        frames = self._frames(conn)
        nego = next(frames)
        assert nego[:2] == ["0", "PTMP"]
        conn.sendall(frame(1, "PTMP", 1, "{server}", 1, 1, 1, 4, "20261022000000", 0, ":PTVER8.2.0.0162"))
        assert next(frames) == ["2", "app"]
        conn.sendall(frame(3, self.challenge))
        resp = next(frames)
        ok = resp[2] == hashlib.md5((self.challenge + self.key).encode()).hexdigest().upper()
        conn.sendall(frame(5, "true" if ok else "false"))
        for f in frames:
            self.received.append(f)
            if f[0] == "100":
                for out in self.responder(f):
                    conn.sendall(out)


def client(fake, key="k"):
    c = PtmpClient(port=fake.port, app_id="app", secret=key, timeout=5)
    c.connect()
    return c


def test_handshake_and_call_encoding():
    fake = FakePT(lambda f: [frame(102, f[1], 4, 3)])
    c = client(fake)
    assert c.server_info["server_uid"] == "{server}"
    api = Api.load()
    assert Ref.root(c, api).network().getDeviceCount() == 3
    # chain: network() then getDeviceCount(), each terminated by a VOID type code
    assert fake.received[0][2:] == ["network", "0", "getDeviceCount", "0"]


def test_typed_args_follow_spec():
    fake = FakePT(lambda f: [frame(102, f[1], 9, "Router0")])
    c = client(fake)
    lw = Ref(c, Api.load(), [], "IPC").appWindow().getActiveWorkspace().getLogicalWorkspace()
    lw._cls = "LogicalWorkspace"  # skip the getClassName round trip
    assert lw.addDevice(0, "2911", 10.0, 20.5) == "Router0"
    call = fake.received[0]
    i = call.index("addDevice")
    # int, std::string, double, double
    assert call[i + 1 : i + 10] == ["4", "0", "8", "2911", "7", "10.0", "7", "20.5", "0"]


def test_pair_vector_data_and_events():
    def responder(f):
        if "enterCommand" in f:
            return [frame(103, 1, "TerminalLine", "{u}", "outputWritten", 8, "hi", 0), frame(102, f[1], 14, 4, 0, 8, "R1#")]
        if "getPorts" in f:
            return [frame(102, f[1], 15, 8, 2, "Fa0/0", "Fa0/1")]
        return [frame(102, f[1], 16, "ArpEntry", "1.1.1.1", "aaaa.bbbb.cccc")]

    fake = FakePT(responder)
    c = client(fake)
    api = Api.load()
    dev = Ref(c, api, [], "CiscoDevice")
    assert dev.enterCommand("show ver", "") == (0, "R1#")
    assert c.events[-1].name == "outputWritten" and c.events[-1].params == ["hi"]
    assert dev.getPorts() == ["Fa0/0", "Fa0/1"]
    assert c.call([]) == Data("ArpEntry", ["1.1.1.1", "aaaa.bbbb.cccc"])


def test_ipc_error_and_bad_auth():
    fake = FakePT(lambda f: [frame(101, f[1], "CNetwork", "no such device")])
    c = client(fake)
    with pytest.raises(IpcCallError, match="no such device"):
        Ref.root(c, Api.load()).network().getDeviceCount()
    with pytest.raises(PtmpError, match="authentication failed"):
        client(FakePT(lambda f: []), key="wrong")


def test_unknown_class_falls_back_to_shared_signature():
    api = Api.load()
    sigs = api.overloads("SomeFutureSwitch", "getPortCount")
    assert sigs and sigs[0]["params"] == [] and sigs[0]["returns"] == "int"
