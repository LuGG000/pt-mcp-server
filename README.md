# Model Context Protocol (MCP) Server for Cisco Packet Tracer

mcp-name: io.github.kiskander/pt-mcp-server

## Overview

`pt-mcp` brings AI assistants to your Packet Tracer labs. It lets you work with a running
[Cisco Packet Tracer](https://www.netacad.com/cisco-packet-tracer) in natural language from AI applications like
Claude Desktop, Claude Code, and Cursor.

Instead of dragging devices around and typing every command by hand, tell the AI what you want in plain English, like
"Build two routers with a serial link and static routes, then prove the PCs can ping each other" or "Step my ping through
simulation mode and explain what the switch does with the frame". Then watch it happen in Packet Tracer.

This works through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/docs/getting-started/intro), a
standard way for AI applications to use external tools. `pt-mcp` connects to Packet Tracer through Packet Tracer's
**own** external-application interface: the IPC API over PTMP, the same channel Cisco's "ExApps" use. That means no
plugins inside Packet Tracer, no patched binaries, and no screen scraping.

It is built with **CCNA students** in mind. It can show you *why* the network behaves the way it does (Packet Tracer's
own per-hop explanations in simulation mode), it verifies the way the exam expects, and by design it cannot read the
answers or score of a graded activity.

## Features

- **Build Topologies:** Add devices, cable them (with automatic cable selection like the GUI), or build an entire lab
  (devices, expansion cards, cables, host IPs, IOS configs) in one call.
- **Export and Rebuild Labs:** Export the open network, configs included, in the same format, and rebuild it anywhere.
- **Configure Devices:** Paste whole IOS configs (`show running-config` output works as-is), run exec or config
  commands, and get each command's status. Read, save, and erase running and startup configs.
- **Expansion Modules:** See a device's slots and supported cards (HWIC-2T, NIM-2T, WIC, SFPs…) and install or remove
  them. Power cycling is handled for you.
- **End Devices:** Set PC/server IP settings, and run Command Prompt commands (`ping`, `ipconfig`, `tracert`) with
  their output.
- **Verify Connectivity:** Ping matrices with loss statistics, retrying the usual ARP/STP first-ping failures.
- **Simulation Mode (Packet Tracer's "packet capture"):** Send PDUs, step time, list events, and read Packet Tracer's
  own OSI-layer explanation of each hop plus decoded headers (Ethernet, 802.1Q, IP, ICMP, ARP, HDLC, TCP/UDP, STP,
  OSPF, DHCP, DNS, CDP…).
- **Console and Command Logs:** Read a device's console buffer (`%LINK`/`%LINEPROTO` messages) and Packet Tracer's log
  of typed commands.
- **Annotations:** Add, edit, and delete notes, lines, and circles on the logical workspace.
- **Activities (.pka):** Read an activity's instructions. Answers and scores are deliberately out of reach.
- **Crash Protection:** Only IPC calls verified against a live Packet Tracer are ever sent, and known crashing calls
  are blocked (see [Crash protection](#crash-protection)).
- **Cross-Platform:** Tested on macOS and Windows with Packet Tracer 9.0.1. `.pkt` files move between them.
- **Modular Architecture:** Tools are organized into modules (devices, links, cli, simulation, etc.), following
  [cml-mcp](https://github.com/xorrkaz/cml-mcp).

## Quick Start

### Requirements

- **Cisco Packet Tracer 9.0.1**, running and logged in to NetAcad (8.2.0 API data is included but not re-verified)
- **macOS or Windows** (Linux is detected but untested)
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)**, which brings its own Python (3.12–3.14)
- **[git](https://git-scm.com/downloads)**, which `uvx` uses to fetch the server from GitHub

### Step 1: Register `pt-mcp` with Packet Tracer (one time per computer)

```sh
uvx --from git+https://github.com/kiskander/pt-mcp-server pt-mcp setup
```

This finds Packet Tracer, generates a private key for this computer, creates **`PTMCP.pta`** in a `pt-mcp` folder in
your home folder (`~/pt-mcp/` or `C:\Users\<you>\pt-mcp\`), and opens that folder for you.

Then in Packet Tracer:

1. **Extensions → IPC → Configure Apps… → Add**
2. Choose **`PTMCP.pta`** from the `pt-mcp` folder
3. Accept the prompt and leave it on **On Demand**

### Step 2: Check the connection

```sh
uvx --from git+https://github.com/kiskander/pt-mcp-server pt-mcp doctor
```

Every line should say `[OK]`. If one doesn't, it tells you how to fix it.

### Step 3: Add the server to your MCP client

Copy the block for your client into its MCP configuration file. No keys or passwords go here: the server reads the
key that `setup` saved.

**Claude Desktop:** `claude_desktop_config.json`
(macOS `~/Library/Application Support/Claude/`, Windows `%APPDATA%\Claude\`, Linux `~/.config/Claude/`)

```json
{
  "mcpServers": {
    "Cisco Packet Tracer": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/kiskander/pt-mcp-server", "pt-mcp"]
    }
  }
}
```

**Claude Code:** `.mcp.json` in your project (or run
`claude mcp add --scope user packet-tracer -- uvx --from git+https://github.com/kiskander/pt-mcp-server pt-mcp`)

```json
{
  "mcpServers": {
    "packet-tracer": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/kiskander/pt-mcp-server", "pt-mcp"]
    }
  }
}
```

**Cursor:** `~/.cursor/mcp.json` (or `.cursor/mcp.json` in a project)

```json
{
  "mcpServers": {
    "packet-tracer": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/kiskander/pt-mcp-server", "pt-mcp"]
    }
  }
}
```

**VS Code (GitHub Copilot):** `.vscode/mcp.json`

```json
{
  "servers": {
    "packet-tracer": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/kiskander/pt-mcp-server", "pt-mcp"]
    }
  }
}
```

Restart your client after saving, then ask: *"Is Packet Tracer connected?"*

> [!TIP]
> **"Command not found" for `uvx`?** MCP clients don't always inherit your shell's `PATH`. Replace `"uvx"` with its
> full path: run `which uvx` on macOS/Linux or `where uvx` on Windows (e.g. `"/Users/alice/.local/bin/uvx"` or
> `"C:\\Users\\alice\\.local\\bin\\uvx.exe"`; JSON needs doubled backslashes).

> [!WARNING]
> Use the `--from git+https://github.com/kiskander/pt-mcp-server` form exactly. A *different*, unrelated package
> called `pt-mcp` exists on PyPI, so `uvx pt-mcp` would run that instead.

<details>
<summary><b>Optional: set everything explicitly in the config</b> (other port, remote Packet Tracer, shared classroom key)</summary>

Any setting can also go in an `env` block. If you set `PT_APP_KEY` here, it must match the key in the `.pta` that is
registered in Packet Tracer (the one in `pt-mcp.env`, written by `setup`). A stale key here is the most common cause of
"authentication rejected".

```json
{
  "mcpServers": {
    "Cisco Packet Tracer": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/kiskander/pt-mcp-server", "pt-mcp"],
      "env": {
        "PT_HOST": "127.0.0.1",
        "PT_PORT": "39000",
        "PT_APP_ID": "net.netacad.cisco.ptmcp",
        "PT_APP_KEY": "<key from pt-mcp.env>"
      }
    }
  }
}
```

`pt-mcp.env` is in `~/Library/Application Support/pt-mcp/` (macOS), `%APPDATA%\pt-mcp\` (Windows), or
`~/.config/pt-mcp/` (Linux). All settings are listed in [INSTALLATION.md](INSTALLATION.md#environment-variables-reference).

</details>

For running from a clone, HTTP mode, Windows notes, and troubleshooting, see [INSTALLATION.md](INSTALLATION.md).

## Available MCP Tools

The server provides 45 MCP tools by default (plus one opt-in), organized into the following categories:

### Connection

- **get_pt_information** - Connection check: Packet Tracer version, device/link counts, workspace mode, open file

### Network Topology

- **create_full_network_topology** - Build a whole lab (devices, modules, links, host IPs, IOS configs) in one call; errors are collected, not fatal
- **export_network_topology** - Export the open network (with configs) in the same format, for rebuilding or review
- **set_network_description** - Set the file's description (objectives, addressing table…)

### Device Management

- **get_devices_in_network** - List devices with type, model, power, and position
- **get_device_models** - List models for a device type (router, switch, pc, server, …)
- **add_device_to_network** - Add a device, optionally named and positioned
- **rename_device** - Change a device's display name
- **set_device_power** - Power a device on or off
- **delete_device_from_network** - Delete a device and its cables (asks for confirmation)

### Device Configuration

- **get_device_configuration** - Read the running-config or startup-config
- **configure_device** - Apply an IOS config block (handles `show run` output and sub-modes; reports only rejected lines)
- **save_device_configuration** - `write memory`
- **erase_device_configuration** - Erase startup-config and reload to a blank config (asks for confirmation)

### Expansion Modules

- **get_device_model_details** - Show slots (installed or empty) and every supported module with its description
- **add_module_to_device** - Install a module (e.g. HWIC-2T) and return the new ports
- **remove_module_from_device** - Remove a module (asks for confirmation)

### Interface & Link Management

- **get_interfaces_for_device** - Ports with status, MAC, IP/mask, and the remote device/port
- **configure_host_interface** - IP, mask, gateway, DNS, or DHCP on PCs, servers, and laptops
- **set_interface_power** - Turn a single port on or off
- **connect_two_devices** - Cable two ports (`auto` picks serial, console, straight-through, or crossover)
- **get_all_links** - Every cable with both ends and its type
- **delete_link** - Remove the cable on a port (asks for confirmation)

### CLI & Verification

- **send_cli_command** - Run IOS commands in exec or config mode, with per-command status (`ok`, `invalid`, `rejected`, …) and output
- **send_terminal_command** - Run a command in a PC/server Command Prompt (or a device terminal) and collect the output
- **verify_connectivity** - Ping a list of destinations from a device and report sent/received/loss for each
- **get_console_log** - The device's console buffer (boot and link messages)
- **get_command_history** - Packet Tracer's log of commands typed into terminals

### Simulation Mode

- **set_simulation_mode** - Switch between Realtime and Simulation
- **send_simple_pdu** - Send an ICMP PDU between two devices (the envelope tool)
- **step_simulation** - Step forward or backward
- **get_simulation_events** - The event list: where each PDU is, where it came from, protocol, and what happened
- **get_simulation_event_details** - Packet Tracer's OSI-layer explanation of an event plus decoded inbound/outbound headers
- **reset_simulation** - Clear the event list

### Annotations (Visual Elements)

- **get_annotations** - Notes, lines, and shapes on the workspace
- **add_text_note** - Add a text note
- **edit_text_note** - Change a note's text
- **add_line_annotation** - Draw a line
- **add_circle_annotation** - Draw a circle
- **delete_annotation** - Delete a note or shape (asks for confirmation)

### Activities

- **get_activity_instructions** - Read a `.pka` activity's instruction pages as plain text (not answers or scores)

### Files

- **create_new_network** - Start a new, empty network (asks for confirmation)
- **open_network_file** - Open a `.pkt` or `.pka`
- **save_network_file** - Save the network as a `.pkt`

### IPC API Reference

- **describe_ipc_class** - Look up the methods and wire types of any Packet Tracer IPC class (offline)
- **call_ipc_api** - *(opt-in, `PT_MCP_ENABLE_RAW_IPC=true`)* Call the raw IPC API; still limited to verified methods

## Usage

Once configured, make sure Packet Tracer is open and logged in, restart your MCP client, and start chatting.

### What Can You Do?

Here are some example prompts to try:

**Getting Started:**

- "Is Packet Tracer connected? What version is it?"
- "What router models can I add?"
- "What's in my network right now?"

**Building Labs:**

- "Add a 2911 router called R1 and a 2960 switch called SW1, and connect them"
- "Give R1 a serial card so I can do a WAN link"
- "Build two routers with a serial link between them and a PC behind each one"

**Configuration & Testing:**

- "Configure the router interfaces with 192.168.1.1/24 and 10.0.12.1/30 and bring them up"
- "Add static routes so both LANs can reach each other, then save the configs"
- "Can PC1 ping PC2? If not, why not?"
- "Show me R1's routing table and running config"

**Learning:**

- "Switch to simulation mode, send a ping from PC1 to PC2, and explain each hop"
- "Why did the switch flood that frame?"
- "Show me the IP and Ethernet headers at the router. What changed?"
- "What does this activity ask me to do?"

**Complete Workflow Example:**

1. "Start a new network"
2. "Add two 2911 routers R1 and R2, each with an HWIC-2T, a 2960 switch, and two PCs"
3. "Connect R1 and R2 over Serial0/0/0, R1 to the switch, PC1 to the switch, and PC2 directly to R2"
4. "Address R1's LAN as 192.168.1.0/24, R2's as 192.168.2.0/24, the WAN as 10.0.12.0/30, configure static routes, and save"
5. "Verify PC1 can reach PC2"
6. "In simulation mode, send a PDU from PC1 to PC2 and walk me through what R1 does with it"
7. "Add a note labelling the WAN link, then save the lab to ~/labs/serial-wan.pkt"

### System Prompt

If your LLM tool supports a system prompt, this works well:

> You are a networking lab assistant for Cisco Packet Tracer, helping a student studying for the CCNA. You can build
> and configure topologies, verify connectivity, and use simulation mode to show how packets move. Explain what each
> step does and why. Verify with show commands and pings rather than assuming. On graded activities (.pka files),
> teach and give hints instead of completing the tasks for the student.

An example [agent skill](examples/skill/packet-tracer/SKILL.md) with Packet Tracer-specific conventions is also included.

## Crash protection

Some Packet Tracer IPC calls crash the application (it exits and the open network is lost). The one confirmed so far
is `LogicalWorkspace.getEllipseItemData` on 9.0.1. Packet Tracer exposes 4,500+ IPC methods and most have never been
exercised, so:

- **The client only sends methods on an allow-list** recorded while every tool ran successfully against a live
  Packet Tracer. Anything else is refused *before* it reaches Packet Tracer.
- **Known crashing calls are blocked unconditionally.**
- **The raw `call_ipc_api` tool is off by default**, and even when enabled it is limited to verified methods unless
  you also set `PT_ALLOW_UNVERIFIED_IPC=true`.

## Academic integrity

The ExApp file that `setup` builds deliberately does **not** request Packet Tracer's `ACTIVITY_WIZARD` privilege, the
one that exposes a `.pka` activity's answer network, assessment, score, and password hash. Packet Tracer itself
refuses those calls, so no client can use this server to pull answers. A test enforces that the privilege stays out.

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

For development setup, testing, and code style, see [DEVELOPMENT.md](DEVELOPMENT.md).

## Troubleshooting

### Common Issues

Start with `pt-mcp doctor`. It checks each step and prints the fix for whatever fails.

#### "authentication rejected"

The ExApp isn't registered with the key this machine is using. Re-run `pt-mcp setup`, then in **Extensions → IPC →
Configure Apps** remove any old *PT MCP Bridge* entry and **Add** the new `.pta`.

#### "Cannot reach Packet Tracer" / nothing listening

Packet Tracer must be running **and past the NetAcad login**; IPC starts after you log in. Check **Extensions → IPC →
Options** (Start Listening, port). If 39000 is busy (a second instance, or right after a crash), Packet Tracer moves to
39001+, and the server scans for it automatically.

#### "Refusing to call …: it has not been verified"

That's crash protection working. The tool you used needs an IPC method that hasn't been verified on your Packet
Tracer version. Please open an issue with the method name and your Packet Tracer version.

#### Commands rejected right after adding a module

Adding or removing a module power-cycles the device (Packet Tracer requires it), and unsaved configuration on that
device is lost. Save first, and give the device a moment to boot; the tools wait for it automatically.

For more troubleshooting help, see [INSTALLATION.md](INSTALLATION.md#troubleshooting).

### Getting Help

- Check the [Issues](https://github.com/kiskander/pt-mcp-server/issues) page for known problems
- See [CONTRIBUTING.md](CONTRIBUTING.md) for how to report bugs

## Documentation

- **[INSTALLATION.md](INSTALLATION.md)** - Detailed installation for macOS and Windows, MCP clients, HTTP mode, and every setting
- **[DEVELOPMENT.md](DEVELOPMENT.md)** - Development setup, testing, adding tools, and the crash-protection workflow
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - How to contribute to the project
- **[tests/README.md](tests/README.md)** - Mock vs live test modes and the fake Packet Tracer
- **[examples/skill/packet-tracer/SKILL.md](examples/skill/packet-tracer/SKILL.md)** - Example agent skill with Packet Tracer conventions for the model
- **[examples/skill/INSTALL.md](examples/skill/INSTALL.md)** - How to install the skill into Claude Code, Claude Desktop, Cursor, and VS Code + GitHub Copilot

## License

The MCP server portion of this project is licensed under the [BSD 2-Clause "Simplified" License](https://github.com/kiskander/pt-mcp-server/blob/main/LICENSE). However, it leverages
IPC API definitions and data derived from Cisco Packet Tracer itself, which are covered under a [proprietary Cisco license](https://github.com/kiskander/pt-mcp-server/blob/main/CISCO_LICENSE.md).
