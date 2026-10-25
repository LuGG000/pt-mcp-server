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
Crash protection.

Some Packet Tracer IPC methods crash the application (it exits and the open network is lost); the one confirmed
so far is LogicalWorkspace.getEllipseItemData on 9.0.1. Packet Tracer has 4,500+ IPC methods and most have never
been exercised, so the client only sends methods on an allow-list of calls verified live (data/verified_methods.json,
produced by recording the live test suite: PT_RECORD_CALLS=<file> USE_MOCKS=false pytest). Anything else is
refused before it reaches Packet Tracer.
"""

import json
import os
import threading
from importlib import resources

# Confirmed to crash Packet Tracer. Never sent, even with the allow-list disabled.
CRASHING_METHODS: dict[str, str] = {
    "getEllipseItemData": "LogicalWorkspace.getEllipseItemData crashes Packet Tracer 9.0.1",
}


class UnsafeCallError(RuntimeError):
    """Raised instead of sending an IPC call that could crash Packet Tracer."""


def verified_methods() -> frozenset[str]:
    data = json.loads(resources.files("pt_mcp.data").joinpath("verified_methods.json").read_text())
    return frozenset(data["methods"])


class CallGuard:
    """Checks every method in an IPC call chain before it is sent; optionally records what was sent."""

    def __init__(self, allow_unverified: bool = False, record_path: str | None = None):
        self.allow_unverified = allow_unverified
        self.verified = verified_methods()
        self.record_path = record_path
        self._recorded: set[str] = set()
        self._lock = threading.Lock()

    def check(self, methods: list[str]) -> None:
        for m in methods:
            if m in CRASHING_METHODS:
                raise UnsafeCallError(f"Refusing to call {m}: {CRASHING_METHODS[m]}")
            if self.record_path is None and not self.allow_unverified and m not in self.verified:
                raise UnsafeCallError(
                    f"Refusing to call {m}: it has not been verified against a live Packet Tracer, and unverified IPC "
                    "calls can crash Packet Tracer (losing the open network). See pt_mcp/safety.py."
                )

    def recorded(self, methods: list[str]) -> None:
        """Note methods that Packet Tracer answered successfully (recording mode only)."""
        if self.record_path is None:
            return
        with self._lock:
            new = set(methods) - self._recorded
            if new:
                self._recorded |= new
                with open(self.record_path, "a") as f:
                    f.writelines(m + "\n" for m in sorted(new))


def guard_from_env(allow_unverified: bool) -> CallGuard:
    return CallGuard(allow_unverified=allow_unverified, record_path=os.environ.get("PT_RECORD_CALLS") or None)
