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

"""Typed IPC object layer over PTMP, driven by the API spec decoded from Ipc::_<Class>_getApi()."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from .ptmp import TYPE_CODES, Call, PtmpClient

ROOT_CLASS = "IPC"


class Api:
    def __init__(self, spec: dict):
        self.version = spec.get("pt_version")
        self.classes: dict[str, dict] = spec["classes"]

    @classmethod
    def load(cls, name: str = "ipc_api_8.2.0.json") -> "Api":
        return cls(json.loads(resources.files("pt_mcp.data").joinpath(name).read_text()))

    def lineage(self, cls: str) -> list[str]:
        seen, order, todo = set(), [], [cls]
        while todo:
            c = todo.pop(0)
            if c in seen or c not in self.classes:
                continue
            seen.add(c)
            order.append(c)
            todo += self.classes[c]["bases"]
        return order

    def overloads(self, cls: str, method: str) -> list[dict]:
        for c in self.lineage(cls):
            sigs = self.classes[c]["methods"].get(method)
            if sigs:
                return sigs
        # Runtime class without its own API table (or a method inherited from an undeclared base):
        # fall back to the signatures used by every class that declares this method.
        found: dict[tuple, list] = {}
        for c in self.classes.values():
            for s in c["methods"].get(method, []):
                found.setdefault((tuple(s["params"]), s["returns"]), [s, 0])[1] += 1
        return [s for s, _ in sorted(found.values(), key=lambda e: -e[1])]  # most widely used first

    def methods(self, cls: str) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for c in reversed(self.lineage(cls)):
            out.update(self.classes[c]["methods"])
        return out


def typed(type_name: str, value: Any) -> tuple[int, Any]:
    if type_name not in TYPE_CODES:
        raise TypeError(f"cannot pass a {type_name!r} argument over PTMP")
    return TYPE_CODES[type_name], value


class Ref:
    """A remote object, addressed by the call chain that reaches it from the IPC root."""

    def __init__(self, client: PtmpClient, api: Api, path: list[Call], cls: str | None):
        self._client, self._api, self._path, self._cls = client, api, path, cls

    @classmethod
    def root(cls, client: PtmpClient, api: Api) -> "Ref":
        return cls(client, api, [], ROOT_CLASS)

    @property
    def class_name(self) -> str:
        if self._cls is None:
            self._cls = self._client.call(self._path + [Call("getClassName")])
        return self._cls

    @property
    def path(self) -> str:
        return ".".join(f'{c.name}({", ".join(repr(v) for _, v in c.args)})' for c in self._path) or "ipc"

    def call(self, method: str, *args: Any, types: list[str] | None = None, fetch: bool = False) -> Any:
        """Call a remote method. Object-returning methods give a new Ref unless fetch=True, which sends the
        call and returns whatever PT replies (some "object" methods, e.g. FrameInstance.getInFrame, reply with data)."""
        sig = None
        if self._cls is None:
            # Avoid a getClassName round trip when every class agrees on this method's signature.
            cands = [s for s in self._api.overloads("", method) if len(s["params"]) == len(args)]
            if len(cands) == 1:
                sig = cands[0]
        if sig is None:
            sigs = self._api.overloads(self.class_name, method)
            sig = next((s for s in sigs if len(s["params"]) == len(args)), None)
        else:
            sigs = [sig]
        if types is None:
            if sig is None:
                known = [s["params"] for s in sigs]
                raise TypeError(
                    f'{self.class_name}.{method} takes {known or "no known signature"}, '
                    f"got {len(args)} args (pass explicit types to override)"
                )
            types = sig["params"]
        call = Call(method, [typed(t, a) for t, a in zip(types, args)])
        returns = sig["returns"] if sig else None
        if returns == "object" and not fetch:
            return Ref(self._client, self._api, self._path + [call], None)
        return self._client.call(self._path + [call])

    def __getattr__(self, method: str):
        if method.startswith("_"):
            raise AttributeError(method)
        return lambda *args, **kw: self.call(method, *args, **kw)

    def __repr__(self) -> str:
        return f'<{self._cls or "?"} {self.path}>'
