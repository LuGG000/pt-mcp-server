# AGENTS.md — Packet Tracer MCP Server

## Project Overview

`pt-mcp` is an MCP server that exposes Cisco Packet Tracer operations as AI-callable tools. It is written in
Python (≥ 3.12) using [FastMCP](https://github.com/jlowin/fastmcp) 3 and talks to Packet Tracer over its
native IPC interface (PTMP on TCP 39000) as a registered ExApp. Layout and conventions mirror
[cml-mcp](https://github.com/xorrkaz/cml-mcp).

## Compatibility Goal

Like cml-mcp, optimize for the lowest-common-denominator MCP client and tool-calling LLM: flat primitive
arguments, `Literal[...]` enums (`DeviceTypeName`, `CableTypeName`), constrained `Annotated` types
(`DeviceName`, `PortName`, `IPv4String`), and typed Pydantic return models in `types.py`.

## Repository Layout

```
src/pt_mcp/
  __main__.py      # CLI entry point (pt-mcp command); stdio or HTTP
  server.py        # FastMCP app wiring; registers all tool modules
  settings.py      # Pydantic-settings config (PT_* env vars)
  pt_client.py     # Async facade (asyncio.to_thread) over the PTMP session + spec selection by PT version
  ptmp.py          # PTMP protocol client (negotiate, MD5 auth, IPC call chains, events)
  ipc.py           # Typed remote-object layer (Ref) driven by the IPC API spec
  types.py         # Enums (DeviceType, ConnectType, CommandStatus) and response models
  data/            # ipc_api_<version>.json, decoded from the PacketTracer binary (do not hand-edit)
  tools/           # One module per functional area, each with register_tools(mcp)
    dependencies.py  # Shared PTClient, elicit_confirmation (disabled, as in cml-mcp)
tests/
  fake_pt.py       # In-process fake Packet Tracer speaking real PTMP; return types from the bundled spec
  conftest.py      # USE_MOCKS switches fake <-> live Packet Tracer
examples/skill/    # example agent skill (SKILL.md) + install guide
```

## Key Conventions

- **Objects are call chains.** `Ref` stores the path from the IPC root (`network → getDevice("R1") →
  getPort("Gi0/0")`); each call replays it, because the protocol is stateless. Methods returning `object` give a new `Ref`;
  the class is resolved lazily with `getClassName` only when the spec is ambiguous.
- **Wire types come from the spec.** `string` (std::string, code 8) and `QString` (9) are distinct on the wire
  and Packet Tracer rejects the wrong one. Never guess; `Ref.call` picks the overload by arity from the spec.
- **Blocking IPC runs in a thread.** Tool bodies call `await client.run(lambda c: ...)`. Keep IPC logic in plain
  sync helpers (e.g. `devices.add_device`) so it is testable and reusable.
- **Destructive tools** (`delete_*`, `create_new_network`, `open_network_file`, `send_cli_command`,
  `call_ipc_api`) carry `destructiveHint: True`, a `CRITICAL:` docstring line, and call `elicit_confirmation`.
- **CLI.** `send_cli_command` uses `CiscoDevice.enterCommand(cmd, mode)`, which returns
  `pair<CommandStatus, output>`. Exec commands run with mode `enable`. Config sessions enter `global` once,
  then use the current mode so sub-modes carry over, and finish with `end`. `send_terminal_command` subscribes to
  `TerminalLine.outputWritten` / `commandEnded` events (LTV 104) and pumps them until the command ends.
- **Install/registration (`install.py`):** `pt-mcp setup` writes a per-install random key to `config_file()`, which
  `settings.py` reads as an env file, and builds the .pta (into `~/pt-mcp/`, revealed in Finder/Explorer) with PT's `meta` (macOS `Contents/extensions/meta`, Windows
  `bin\meta.exe`). It deletes the clear-text XML afterwards. `pt-mcp doctor` diagnoses install/IPC/auth/spec.
- **Windows:** verified on Windows 10 + PT 9.0.1 (same results as macOS). Packet Tracer must run in the user's desktop
  session (not over SSH); the server can run anywhere that reaches `localhost:39000`.
- **Live 9.0.1 quirks (verified, mirrored in tests/fake_pt.py):**
  - `createLink` rejects ConnectType AUTO (8107); `links.auto_cable` picks the type like the GUI does.
  - `Port.getRemotePortName()` returns "" even for cabled ports; walk `getLink()` → `Cable.getOtherPort(dev, port)` → `getOwnerDevice()`.
  - PT 9 adds a hidden `Power Distribution Device0` on the first device add; `get_devices_in_network` hides it unless `include_infrastructure`.
  - `DeviceFactory` lists one descriptor per hardware variant, so model names repeat; dedupe them.
  - Fresh switch links take about 30 s (STP) before pings succeed.
  - The network description comes back as Qt rich-text HTML after a save/reopen; export converts it with `html_to_text`.
- **Academic integrity (do not change without the maintainer):** `data/exapp_meta.xml.in` must not request
  `ACTIVITY_WIZARD`; that privilege exposes activity answers, scores and password hashes. `tests/test_ccna_tools.py` enforces it.
- **Simulation PDUs:** `FrameInstance.getInFrame/getOutFrame` are typed `object` but PT replies with data, so use
  `Ref.call(..., fetch=True)`. `pdu.decode` labels fields from `data/pdu_fields_<ver>.json`, which is generated by
  `analysis/tools/build_pdu_fields.py` from the Java framework's `*Impl.read()` order.
- **Modules** can only change while the device is powered off (`modules._with_power_off`). Slot paths look like `0/0`.
  ModuleType 18 (non-removable) is the chassis board, not a slot.
- **Crash protection (`safety.py`):** `PtmpClient.call` runs every chain through `CallGuard`. Only methods in
  `data/verified_methods.json` (recorded live) are sent; `CRASHING_METHODS` are never sent. A new tool that needs a
  new IPC method must be verified live first (isolated probe with a saved network), then the allow-list re-recorded
  with `just verify-methods`. `test_every_tool_method_is_on_the_allow_list` fails otherwise. `call_ipc_api` is opt-in.
- **Known crash (verified in isolation):** `LogicalWorkspace.getEllipseItemData()` makes Packet Tracer 9.0.1 exit
  (the open network is lost). `drawLine`, `getLineItemData`, `drawCircle`, `removeCanvasItem` and the id lists are safe.
  `call_ipc_api` refuses the methods in `ipc_api.CRASHING_METHODS`; add any new crashers there. Probe unverified IPC
  calls in a separate process with a saved network.
- **Config sessions** (`cli._run_config`): indented configs put unindented lines in global mode; flat configs retry
  `invalid` lines from global mode (PT does not fall back to the parent mode like IOS does) and reset after a failed
  sub-mode command. `% ...` output with an OK status is reported as `rejected`. `create_full_network_topology` applies
  configs with startup-config semantics (adds `no shutdown` to interface blocks without `shutdown`).
- **Boot:** IOS rejects commands while booting (including right after a module install's power cycle); use
  `cli.wait_until_ready`.
- **Host settings live on processes:** `Device.getProcess("HostIpProcess").getDefaultGateway()` and
  `getProcess("DnsClient").getServerIp()`. PT 9 keeps hidden empty notes in every network, and leaving Simulation
  mode clears the event list.
- **Ports:** PT moves IPC to the next free port (e.g. 39001) when 39000 is busy; the client scans `PT_PORT_SCAN` ports.
- **New Packet Tracer version:** see DEVELOPMENT.md "Supporting a New Packet Tracer Version". The spec/PDU
  extraction tooling is maintainer-side and not part of this repository.

## Licensing

- New source files start with the Cisco Systems BSD-2 header used throughout `src/` (copy it from any module).
- Files derived from Packet Tracer (IPC API specs, PDU field tables, verified methods, the ExApp meta template, captured
  PDU samples) are covered by `CISCO_LICENSE.md`; list any new derived file there.

## Development Workflow

| Recipe | Purpose |
|---|---|
| `just dev-install` | Sync venv with dev deps |
| `just test [args]` | Offline tests against `tests/fake_pt.py` |
| `just test-live [args]` | Tests against the running Packet Tracer (`USE_MOCKS=false`) |
| `just check` | black --check, isort --check-only, flake8 |
| `just setup` / `just doctor` | Register with / diagnose the local Packet Tracer |
| `just verify-methods` | Re-record the verified IPC method allow-list (live) |

**Before finishing any code change, run `just check` and `just test`.** Both must be green. Line length is 140.
