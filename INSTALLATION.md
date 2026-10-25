# Installation Guide

This guide sets up the Packet Tracer MCP server so you can drive Cisco Packet Tracer from AI assistants like Claude
Desktop, Claude Code, and Cursor.

**Choose your path:**

- **Just want to use it?** → [Quick install with uvx](#quick-install-with-uvx)
- **Want to change the code or run the tests?** → [Install from a clone](#install-from-a-clone)
- **On Windows?** → Read [Windows notes](#windows-notes) too
- **Want one server for a classroom or another machine?** → [HTTP transport](#http-transport)

## Table of Contents

- [Requirements](#requirements)
- [How it connects](#how-it-connects)
- [Quick install with uvx](#quick-install-with-uvx)
- [Install from a clone](#install-from-a-clone)
- [Registering with Packet Tracer](#registering-with-packet-tracer)
- [Configuring MCP clients](#configuring-mcp-clients)
- [Windows notes](#windows-notes)
- [HTTP transport](#http-transport)
- [Environment variables reference](#environment-variables-reference)
- [Troubleshooting](#troubleshooting)
- [Uninstalling](#uninstalling)

## Requirements

### What You'll Need

**On your computer:**

- **Cisco Packet Tracer 9.0.1**, installed, running, and logged in to NetAcad
  ([download from NetAcad](https://www.netacad.com/resources/lab-downloads))
- **[uv](https://docs.astral.sh/uv/)**, a Python package manager that also installs Python for you
  ([install instructions](https://docs.astral.sh/uv/getting-started/installation/)):
  - macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

**Supported platforms:**

| Platform | Status |
|---|---|
| macOS (Apple silicon and Intel) + Packet Tracer 9.0.1 | Tested |
| Windows 10/11 x64 + Packet Tracer 9.0.1 | Tested |
| Linux + Packet Tracer 9.0.1 | Detected by `setup`, untested |
| Packet Tracer 8.2.0 | API data bundled, not re-verified |

## How it connects

Packet Tracer has a built-in interface for external applications ("ExApps"): an IPC server, by default on
`localhost:39000`, that speaks Cisco's PTMP protocol. Packet Tracer only accepts ExApps that have been registered with
an **ExApp meta file (`.pta`)**. The `.pta` says who the app is, which privileges it gets, and the secret key it uses to
log in (an MD5 challenge/response).

`pt-mcp setup` creates that `.pta` for your machine:

- it finds your Packet Tracer installation,
- generates a **random key unique to this install**,
- builds `PTMCP.pta` with Packet Tracer's own `meta` tool,
- writes `PTMCP.pta` (plus the small `launch` file it is tied to) to **`pt-mcp` in your home folder**,
  `~/pt-mcp/` or `C:\Users\<you>\pt-mcp\`, and opens it in Finder/Explorer,
- and saves the matching ID and key to your private user config, where the server reads them:
  - macOS: `~/Library/Application Support/pt-mcp/pt-mcp.env`
  - Windows: `%APPDATA%\pt-mcp\pt-mcp.env`
  - Linux: `~/.config/pt-mcp/pt-mcp.env`

You add the `.pta` to Packet Tracer once. After that, any MCP client on that machine can use the server.

## Quick install with uvx

`uvx` downloads and runs the server without a manual install.

**Step 1: Run setup**

```sh
uvx --from git+https://github.com/kiskander/pt-mcp-server pt-mcp setup
```

**Step 2: [Register the `.pta` with Packet Tracer](#registering-with-packet-tracer)**

**Step 3: Check it**

```sh
uvx --from git+https://github.com/kiskander/pt-mcp-server pt-mcp doctor
```

Expected output:

```
[OK] Packet Tracer installed: C:\Program Files\Cisco Packet Tracer 9.0.1 (9.0.1.0858)
[OK] ExApp key configured: C:\Users\alice\AppData\Roaming\pt-mcp\pt-mcp.env
[OK] Packet Tracer IPC listening: 127.0.0.1:39000
[OK] ExApp authenticated: as net.netacad.cisco.ptmcp, Packet Tracer 9.0.1.0858
[OK] IPC API spec: ipc_api_9.0.1.json
All checks passed.
```

**Step 4: [Configure your MCP client](#configuring-mcp-clients)**

## Install from a clone

```sh
git clone https://github.com/kiskander/pt-mcp-server.git
cd pt-mcp-server
uv sync
uv run pt-mcp setup        # then register the .pta (below)
uv run pt-mcp doctor
```

Your MCP client then runs `uv run --project /path/to/pt-mcp-server pt-mcp`.

## Registering with Packet Tracer

Do this once per computer, and again only if you re-run `setup` with `--rotate-key` or move to a new Packet Tracer
install.

1. Open Packet Tracer and finish the NetAcad login.
2. Go to **Extensions → IPC → Configure Apps…**
3. If there is an old **PT MCP Bridge** entry, select it and click **Remove**.
4. Click **Add** and choose **`PTMCP.pta`** in the **`pt-mcp`** folder in your home folder (`~/pt-mcp/` on macOS,
   `C:\Users\<you>\pt-mcp\` on Windows). `setup` opens that folder for you in Finder/Explorer.
5. Accept the prompt. The `.pta` is unsigned, so Packet Tracer asks whether to trust it.
6. Leave its startup setting at **On Demand**. *Disabled* refuses connections, and *On Startup* is not needed, because
   your MCP client starts the server, not Packet Tracer.

**What the server is allowed to do.** The `.pta` requests these privileges: read network info, change network,
simulation mode, GUI, files, preferences, IPC, and application. It deliberately does **not** request `ACTIVITY_WIZARD`
(activity answers, scores, password hashes) or `MULTIUSER`.

## Configuring MCP clients

> [!NOTE]
> **About command paths:** MCP clients may not inherit your terminal's `PATH`. If you get "command not found" for
> `uvx` or `uv`, use the full path: `which uvx` (macOS/Linux), `where uvx` (Command Prompt), or
> `(Get-Command uvx).Source` (PowerShell).

### Claude Desktop

Edit `claude_desktop_config.json`:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "Cisco Packet Tracer": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/kiskander/pt-mcp-server", "pt-mcp"]
    }
  }
}
```

Restart Claude Desktop after saving.

### Claude Code

```sh
claude mcp add --scope user packet-tracer -- uvx --from git+https://github.com/kiskander/pt-mcp-server pt-mcp
```

Or, from a clone, add a project `.mcp.json`:

```json
{
  "mcpServers": {
    "packet-tracer": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/pt-mcp-server", "pt-mcp"]
    }
  }
}
```

### Cursor / VS Code

Use the same `command`/`args` as above in `.cursor/mcp.json` or VS Code's MCP settings.

> [!IMPORTANT]
> Don't put `PT_APP_KEY` in the client config unless you mean to. Environment variables override the key that
> `setup` saved, and a stale key there is the most common cause of "authentication rejected".

## Windows notes

- **Packet Tracer must run in your desktop session.** Start it normally from the Start menu. The MCP server itself is
  an ordinary process and only needs to reach `localhost:39000`, so it can run from any terminal or MCP client, even
  over SSH.
- The `meta` tool is `C:\Program Files\Cisco Packet Tracer 9.0.1\bin\meta.exe`; `setup` finds it automatically. Use
  `--pt-path` if Packet Tracer is installed somewhere else.
- `.pkt` files made on macOS open on Windows and vice versa.

## HTTP transport

By default the server uses stdio: your MCP client starts it. To run it as a long-lived HTTP server instead, for example
on the machine running Packet Tracer:

```sh
PT_MCP_TRANSPORT=http PT_MCP_BIND=127.0.0.1 PT_MCP_PORT=9000 uv run pt-mcp
```

Point clients at `http://127.0.0.1:9000/mcp`. The HTTP transport has no authentication of its own, so keep it bound to
localhost or put it behind something that provides authentication.

To control a Packet Tracer on **another** machine (untested), set `PT_HOST` and enable **Allow Remote Applications**
in that Packet Tracer's **Extensions → IPC → Options**. Only do this on a trusted network: PTMP is not encrypted. The
tested setup is the server running on the same machine as Packet Tracer.

## Environment variables reference

All settings are optional. `setup` writes `PT_APP_ID`/`PT_APP_KEY` to the user config file. A `.env` in the working
directory and real environment variables override it, in that order.

| Variable | Default | Description |
|---|---|---|
| `PT_HOST` | `127.0.0.1` | Host running Packet Tracer |
| `PT_PORT` | `39000` | IPC port (Extensions → IPC → Options) |
| `PT_PORT_SCAN` | `10` | If `PT_PORT` refuses, also try the next ports (PT moves to 39001… when 39000 is busy) |
| `PT_APP_ID` | `net.netacad.cisco.ptmcp` | ExApp ID; must match the registered `.pta` |
| `PT_APP_KEY` | from `setup` | ExApp key; must match the registered `.pta` |
| `PT_TIMEOUT` | `30` | Seconds to wait for an IPC reply |
| `PT_API_SPEC` | auto | Force a bundled IPC API spec (`9.0.1`, `8.2.0`) instead of matching the running version |
| `PT_MCP_ENABLE_RAW_IPC` | `false` | Register the `call_ipc_api` tool |
| `PT_ALLOW_UNVERIFIED_IPC` | `false` | Allow IPC methods not verified live (**can crash Packet Tracer**) |
| `PT_MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `PT_MCP_BIND` / `PT_MCP_PORT` | `127.0.0.1` / `9000` | HTTP transport bind address and port |
| `DEBUG` | `false` | Verbose logging (to stderr) |

**Test environment variables:**

| Variable | Default | Description |
|---|---|---|
| `USE_MOCKS` | `true` | `false` runs the test suite against the live Packet Tracer |
| `PT_RECORD_CALLS` | unset | File to record the IPC methods Packet Tracer answers (builds the allow-list) |

## Troubleshooting

Run `pt-mcp doctor` first. Each failing check prints its fix.

| Symptom | Cause and fix |
|---|---|
| `nothing on 127.0.0.1:39000-39009` | Packet Tracer isn't running, or hasn't finished the NetAcad login. IPC starts after login. Check **Extensions → IPC → Options → Start Listening**. |
| `authentication rejected` | The registered `.pta` doesn't match this machine's key. Remove the old *PT MCP Bridge* entry and add the `.pta` from the latest `setup`. Make sure no stale `PT_APP_KEY` is set in your MCP client config. |
| `did not pass integrity check` in Packet Tracer | The `launch` file next to the `.pta` (in `~/pt-mcp/`) changed or moved. Re-run `setup` and re-add the `.pta`. |
| `meta tool was not found` | `setup` couldn't find Packet Tracer's `meta`. Pass `--pt-path "<Packet Tracer folder or .app>"`. |
| `Refusing to call …: it has not been verified` | Crash protection. Please open an issue with the method and your Packet Tracer version. |
| A tool waits for its full timeout | Fresh switch links take ~30 s (STP) before traffic flows; `verify_connectivity` retries for you. |
| Packet Tracer shows "initial configuration dialog" | Normal after a reload with no startup-config. The terminal tools answer it automatically. |

## Uninstalling

1. In Packet Tracer: **Extensions → IPC → Configure Apps**, select *PT MCP Bridge*, then **Remove**.
2. Delete `~/pt-mcp/` and the config folder (`~/Library/Application Support/pt-mcp`, `%APPDATA%\pt-mcp`, or `~/.config/pt-mcp`).
3. Remove the server entry from your MCP client's config.
