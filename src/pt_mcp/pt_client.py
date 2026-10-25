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
Async facade over the synchronous PTMP client.

Packet Tracer serves one IPC session per ExApp connection and answers requests in order, so calls are
serialized by the PTMP client's lock and run in a worker thread to keep the event loop free.
"""

import asyncio
import logging
import re
from collections.abc import Callable
from importlib import resources
from typing import Any, TypeVar

from pt_mcp.ipc import Api, Ref
from pt_mcp.ptmp import PtmpClient
from pt_mcp.safety import guard_from_env

logger = logging.getLogger("pt-mcp.client")

T = TypeVar("T")


def available_specs() -> dict[str, str]:
    """Map 'major.minor.patch' -> spec file name for every bundled IPC API spec."""
    out = {}
    for f in resources.files("pt_mcp.data").iterdir():
        m = re.fullmatch(r"ipc_api_(\d+\.\d+\.\d+)\.json", f.name)
        if m:
            out[m.group(1)] = f.name
    return out


def _version_key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split(".") if x.isdigit())


def pick_spec(pt_version: str | None, override: str | None = None) -> str:
    """Choose the bundled spec for a Packet Tracer version string such as '9.0.1.0858'."""
    specs = available_specs()
    if override:
        if override not in specs:
            raise ValueError(f"No IPC API spec for {override}; bundled: {sorted(specs)}")
        return specs[override]
    if pt_version:
        want = _version_key(pt_version)[:3]
        exact = [v for v in specs if _version_key(v) == want]
        if exact:
            return specs[exact[0]]
        same_minor = [v for v in specs if _version_key(v)[:2] == want[:2] and _version_key(v) <= want]
        if same_minor:
            return specs[max(same_minor, key=_version_key)]
    return specs[max(specs, key=_version_key)]


class PTClient:
    """Packet Tracer client: PTMP session plus the IPC API spec that matches the running version."""

    def __init__(
        self,
        host: str,
        port: int,
        app_id: str,
        app_key: str,
        timeout: float = 30.0,
        api_spec: str | None = None,
        port_scan: int = 10,
        allow_unverified: bool = False,
    ):
        self.ptmp = PtmpClient(
            host=host,
            port=port,
            app_id=app_id,
            secret=app_key,
            timeout=timeout,
            port_scan=port_scan,
            guard=guard_from_env(allow_unverified),
        )
        self._api_override = api_spec
        self._api: Api | None = None

    @property
    def pt_version(self) -> str | None:
        reserved = self.ptmp.server_info.get("reserved", "")
        m = re.search(r"PTVER([\d.]+)", reserved)
        return m.group(1) if m else None

    def _ensure(self) -> Api:
        if not self.ptmp.connected:
            self.ptmp.connect()
            self._api = None
        if self._api is None:
            name = pick_spec(self.pt_version, self._api_override)
            logger.info("Packet Tracer %s; using IPC API spec %s", self.pt_version, name)
            self._api = Api.load(name)
        return self._api

    @property
    def api(self) -> Api:
        return self._ensure()

    def offline_api(self) -> Api:
        """The connected version's spec if known, else the configured or newest bundled spec (no IPC needed)."""
        if self._api is not None:
            return self._api
        return Api.load(pick_spec(None, self._api_override))

    def root(self) -> Ref:
        return Ref.root(self.ptmp, self._ensure())

    async def run(self, fn: Callable[["PTClient"], T]) -> T:
        """Run a blocking IPC routine in a worker thread."""
        return await asyncio.to_thread(self._run_sync, fn)

    def _run_sync(self, fn: Callable[["PTClient"], T]) -> T:
        self._ensure()
        return fn(self)

    def close(self) -> None:
        self.ptmp.close()

    def logical_workspace(self) -> Ref:
        return self.root().appWindow().getActiveWorkspace().getLogicalWorkspace()

    def device(self, name: str) -> Ref:
        """Device by display name; raises LookupError if Packet Tracer has no such device."""
        dev = self.root().network().getDevice(name)
        try:
            dev.class_name
        except Exception as e:
            raise LookupError(f"No device named {name!r} in the active Packet Tracer network") from e
        return dev

    def is_a(self, ref: Ref, class_name: str) -> bool:
        return class_name in self.api.lineage(ref.class_name)

    @staticmethod
    def plain(value: Any) -> Any:
        """Convert IPC results into JSON-friendly values."""
        if isinstance(value, Ref):
            return {"object": value.class_name, "path": value.path}
        if isinstance(value, (list, tuple)):
            return [PTClient.plain(v) for v in value]
        if hasattr(value, "subtype") and hasattr(value, "fields"):
            return {"data": value.subtype, "fields": value.fields}
        return value
