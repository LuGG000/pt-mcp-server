# Development Guide

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Daily Workflow](#daily-workflow)
- [How the Server Talks to Packet Tracer](#how-the-server-talks-to-packet-tracer)
- [Adding a New Tool](#adding-a-new-tool)
- [Crash Protection and the Verified-Methods Allow-List](#crash-protection-and-the-verified-methods-allow-list)
- [Supporting a New Packet Tracer Version](#supporting-a-new-packet-tracer-version)
- [Debugging and Inspecting the Server](#debugging-and-inspecting-the-server)
- [Testing](#testing)
- [Code Style](#code-style)
- [Project Structure](#project-structure)
- [Branching, Commits, and Pull Requests](#branching-commits-and-pull-requests)
- [Publishing and Release](#publishing-and-release)

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12–3.14 for you)
- [just](https://github.com/casey/just) (task runner; optional, but recipes wrap the standard arguments)
- Cisco Packet Tracer 9.0.1 for live testing (not needed for the offline test suite)

## Quick Start

```sh
git clone https://github.com/kiskander/pt-mcp-server.git
cd pt-mcp-server
just dev-install          # uv sync
just test                 # offline suite against the fake Packet Tracer
just setup                # build this machine's .pta, then register it in Packet Tracer
just doctor               # confirm the live connection
just test-live            # live suite (builds and removes its own devices; use a scratch network)
```

## Daily Workflow

| Recipe | Purpose |
|---|---|
| `just dev-install` | Sync the venv with dev dependencies |
| `just test [args]` | Offline tests (`USE_MOCKS=true`) against `tests/fake_pt.py` |
| `just test-live [args]` | Tests against the running Packet Tracer (`USE_MOCKS=false`) |
| `just check` | `black --check`, `isort --check-only`, `flake8` over `src/` and `tests/` |
| `just setup` / `just doctor` | Register with / diagnose the local Packet Tracer |
| `just verify-methods` | Re-record the verified IPC method allow-list (live; scratch network) |
| `just build` | Build the wheel |

**Before finishing any change, run `just check` and `just test`.** Both must be green. For changes that touch IPC
calls, also run `just test-live`.

## How the Server Talks to Packet Tracer

```
MCP client ──stdio/HTTP──► FastMCP tools (tools/*.py)
                               │  await client.run(lambda c: ...)   (worker thread)
                               ▼
                           PTClient (pt_client.py)  ── picks the IPC API spec for the running PT version
                               │
                           Ref (ipc.py)             ── remote object = call chain from the IPC root
                               │                       wire types from data/ipc_api_<ver>.json
                           CallGuard (safety.py)    ── refuses unverified / crashing methods
                               │
                           PtmpClient (ptmp.py)     ── PTMP: negotiate, MD5 auth, IPC messages, events
                               ▼
                    Packet Tracer IPC server (localhost:39000)
```

- **Objects are call chains.** `network() → getDevice("R1") → getPort("Gi0/0") → getIpAddress()` is sent as one IPC
  message; the protocol is stateless. Methods that return objects give a new `Ref`.
- **Wire types matter.** `string` (8) and `QString` (9) are distinct on the wire, and Packet Tracer rejects the wrong
  one. `Ref.call` takes every parameter type from the bundled spec; never guess.
- **Events** (terminal output, command completion) are pushed by Packet Tracer after an LTV 104 subscription;
  `PtmpClient.pump()` reads them.

## Adding a New Tool

1. **Pick the module** in `src/pt_mcp/tools/` by functional area, or add one with a `register_tools(mcp)` function and
   register it in `server.py`.
2. **Write the IPC logic as a plain sync function** taking a `PTClient` (e.g. `devices.add_device`), so it is
   testable and reusable. The tool body only calls `await client.run(lambda c: helper(c, ...))`.
3. **Follow the tool conventions** (from cml-mcp):
   - `annotations={"title": ..., "readOnlyHint": ..., "destructiveHint": ...}`
   - flat primitive arguments; constrained types (`DeviceName`, `PortName`, `IPv4String`, `Literal[...]`) from
     `types.py`
   - a docstring that states what the tool does, its constraints, and 2–3 example prompts
   - destructive tools: a `CRITICAL:` line telling the model to confirm with the user, plus `elicit_confirmation(ctx, ...)`
   - typed Pydantic return models, dumped with `model_dump(exclude_none=True)`
   - errors raised as `ToolError`
4. **Check every IPC method it calls is verified.** Look up signatures with `describe_ipc_class`. If a method is not
   in `data/verified_methods.json`, follow [the probe procedure](#verifying-a-new-ipc-method) before using it.
5. **Teach the fake.** Add the behavior to `tests/fake_pt.py`, mirroring what live Packet Tracer actually does,
   including its quirks, and write tests.
6. Run `just check`, `just test`, and `just test-live`.

## Crash Protection and the Verified-Methods Allow-List

Some IPC methods crash Packet Tracer outright (the process exits and the open network is lost);
`LogicalWorkspace.getEllipseItemData` is confirmed on 9.0.1. Every IPC call goes through `safety.CallGuard`:

- methods in `safety.CRASHING_METHODS` are **never** sent;
- other methods are sent only if they are in `data/verified_methods.json`, unless `PT_ALLOW_UNVERIFIED_IPC=true`;
- `tests/test_ccna_tools.py::test_every_tool_method_is_on_the_allow_list` fails if tool code calls a method that
  isn't on the list.

### Verifying a new IPC method

1. **Save your network first.** A crash loses it.
2. Probe the method **in its own process**, one call at a time, checking afterwards that Packet Tracer is still alive
   (listening on 39000). Use the arguments the documentation in Packet Tracer's
   `help/default/IpcAPI/` describes; don't guess.
3. If it crashes Packet Tracer, add it to `CRASHING_METHODS` with a note, and don't use it.
4. If it's safe, use it in a tool, then re-record the allow-list with `just verify-methods`. That runs the live suite
   with `PT_RECORD_CALLS` set, and only methods Packet Tracer answered successfully are recorded.

## Supporting a New Packet Tracer Version

The IPC API spec (`data/ipc_api_<version>.json`: classes, methods, wire types, privileges) and the PDU field tables
(`data/pdu_fields_<version>.json`) are extracted from a Packet Tracer installation by maintainer tooling that is not
part of this repository. For a new release:

1. Extract the new spec and PDU tables, and diff them against the previous version.
2. Diff the `DeviceType`, `ConnectType`, and `TrafficType` enums against `types.py`.
3. Check the ExApp privilege table hasn't changed.
4. Re-run `just test-live` and `just verify-methods` on the new version.

`PTClient` picks the spec matching the version Packet Tracer reports in the PTMP handshake (`:PTVER9.0.1.0858`), falling
back to the closest bundled version.

## Debugging and Inspecting the Server

### Run the server locally

```sh
uv run pt-mcp                                     # stdio (what MCP clients use)
PT_MCP_TRANSPORT=http uv run pt-mcp               # HTTP on 127.0.0.1:9000/mcp
```

### Use the MCP Inspector

```sh
npx @modelcontextprotocol/inspector uv run pt-mcp
```

### Verbose logging

Set `DEBUG=true`. Logs go to stderr, because stdout carries the stdio transport.

### Inspecting the live tool surface from Python

```python
import asyncio
from fastmcp import Client
from pt_mcp.server import server_mcp

async def main():
    async with Client(server_mcp) as c:
        print([t.name for t in await c.list_tools()])
        print((await c.call_tool("get_pt_information", {})).data)

asyncio.run(main())
```

## Testing

See [tests/README.md](tests/README.md). In short: `just test` runs everything against an in-process fake Packet
Tracer that speaks real PTMP over a socket. `just test-live` runs the same suite, plus live-only end-to-end scenarios,
against your Packet Tracer.

## Code Style

[black](https://black.readthedocs.io/), [isort](https://pycqa.github.io/isort/) (black profile), and
[flake8](https://flake8.pycqa.org/), with line length 140. Fix formatting drift with:

```sh
uv run black src/ tests/
uv run isort src/ tests/
```

## Project Structure

```
src/pt_mcp/
  __main__.py        # `pt-mcp` CLI: serve (default), `setup`, `doctor`
  server.py          # FastMCP app wiring; registers all tool modules
  settings.py        # pydantic-settings (PT_* env vars + the user config written by setup)
  install.py         # setup/doctor: find Packet Tracer, build the .pta with PT's meta tool, diagnose
  pt_client.py       # async facade over the PTMP session; spec selection by PT version
  ptmp.py            # PTMP protocol client
  ipc.py             # typed remote-object layer (Ref)
  safety.py          # CallGuard: verified-method allow-list, known crashers
  pdu.py             # decode simulation-mode PDUs into labelled headers
  types.py           # enums (DeviceType, ConnectType, TrafficType, ...) and response models
  data/              # IPC API specs, PDU field tables, verified methods, ExApp meta template
  tools/             # one module per functional area, each with register_tools(mcp)
tests/
  fake_pt.py         # in-process fake Packet Tracer (real PTMP; behavior mirrors live 9.0.1 quirks)
  conftest.py        # USE_MOCKS switches fake <-> live
examples/skill/      # example agent skill for MCP clients
```

### Modular tool architecture

Each tool module is independent and registers its tools with `register_tools(mcp)`, the same pattern as
[cml-mcp](https://github.com/xorrkaz/cml-mcp). Shared IPC helpers live in the modules that own them
(`devices.add_device`, `links.connect`, `cli.run_ios`, …) and are reused by higher-level tools such as
`create_full_network_topology`.

## Branching, Commits, and Pull Requests

- Branch from `main`; keep pull requests focused.
- Include the Packet Tracer version and platform you tested on in the PR description.
- `just check` and `just test` must pass; mention whether you ran `just test-live`.

## Publishing and Release

The PyPI distribution name is **`pt-mcp-server`** (the import name stays `pt_mcp`; the console commands are `pt-mcp`
and `pt-mcp-server`). Don't publish as `pt-mcp`: that name belongs to an unrelated project on PyPI.

```sh
uv build                      # dist/pt_mcp_server-<version>-py3-none-any.whl + sdist
uvx --from dist/pt_mcp_server-*.whl pt-mcp-server doctor   # smoke-test the built wheel
uv publish                    # needs a PyPI token
```

After the first PyPI release, switch the README and INSTALLATION.md install commands and client configs from
`uvx --from git+https://github.com/kiskander/pt-mcp-server pt-mcp` to `uvx pt-mcp-server`, which needs no git.
Keep `version` in `pyproject.toml` and `server.json` in sync.
