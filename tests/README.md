# Packet Tracer MCP Tests

## Quick Links

- Run offline: `just test`
- Run live: `just test-live` (Packet Tracer running, logged in, ExApp registered, **scratch network open**)
- Fake Packet Tracer: [`fake_pt.py`](fake_pt.py)

## Test Modes

### Mock Mode (Default)

Tools talk **real PTMP** over a local socket to `fake_pt.py`, an in-process fake Packet Tracer. It does the
negotiation and MD5 authentication, evaluates IPC call chains against a small in-memory network model, and encodes
return values with the wire types from the bundled IPC API spec. Its behavior mirrors what live Packet Tracer 9.0.1
actually does, including its quirks:

- `createLink` rejects ConnectType AUTO
- `getRemotePortName()` returns `""`
- the hidden "Power Distribution Device0" and the hidden empty notes
- IOS not falling back to the parent mode for global commands typed in a sub-mode
- `% ...` errors reported with an OK status
- module changes only allowed while powered off
- the simulation frames, which are captured from a real ICMP echo

```sh
# Run all tests in mock mode (default; prefer the just recipe)
just test

# Or with pytest directly
uv run -m pytest

# A single test
just test "-k test_simulation_walkthrough"
```

Crash protection is **enabled** in mock mode too, so a tool that calls an unverified IPC method fails the offline
suite, not just the live one.

### Live Mode

```sh
just test-live
# or
USE_MOCKS=false uv run -m pytest
```

The live tests build uniquely named devices (e.g. `T1a2b-R`), check them, and delete them. They don't touch other
devices, but use a scratch network anyway: one live scenario power-cycles routers.

## Environment Variables

### Mock Mode

`conftest.py` starts the fake and points `PT_HOST`/`PT_PORT`/`PT_APP_ID`/`PT_APP_KEY` at it. Nothing to set.

### Live Mode Configuration

| Variable | Description |
|---|---|
| `USE_MOCKS=false` | Use the running Packet Tracer |
| `PT_HOST`, `PT_PORT`, `PT_APP_ID`, `PT_APP_KEY` | Optional; default to the config written by `pt-mcp setup` |
| `PT_RECORD_CALLS=<file>` | Record every IPC method Packet Tracer answers (used by `just verify-methods`) |

## Test Files

| File | What it covers |
|---|---|
| `test_ptmp.py` | PTMP framing, negotiation, auth, typed encoding, events, errors |
| `test_pt_mcp.py` | Core tools end to end through an MCP client; tool annotations; live inventory |
| `test_ccna_tools.py` | Config sessions (sub-modes, `% ` errors, startup semantics), modules, topology export/rebuild, simulation and PDU decoding, annotations, logs, ping parsing, activities, crash protection, academic integrity |
| `test_live.py` | Live-only scenarios: router/switch/PC with ping; two-router serial WAN with HWIC-2T, static routes, ping, and simulation (HDLC, TTL) |

## Updating the Fake

When live Packet Tracer behaves differently from the fake, change `fake_pt.py` to match live behavior (with a comment
saying what Packet Tracer does), then fix the tool. The fake documents real behavior, not the behavior we wish it had.

## Troubleshooting

### Mock Mode Issues

- **`Refusing to call X: it has not been verified`:** tool code uses an IPC method that isn't in
  `src/pt_mcp/data/verified_methods.json`. See [DEVELOPMENT.md](../DEVELOPMENT.md#verifying-a-new-ipc-method).

### Live Mode Issues

- Run `pt-mcp doctor` first.
- Pings in fresh topologies fail for ~30 s while switch ports go through STP; the live tests retry.
- If Packet Tracer was restarted, IPC may come up on 39001; the client scans for it.

## Contributing

New tools need offline tests (teach `fake_pt.py` the behavior) and should be exercised live before merging.
