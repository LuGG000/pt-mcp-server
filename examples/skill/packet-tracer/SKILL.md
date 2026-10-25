---
name: packet-tracer
description: Build, configure, verify, and explain Cisco Packet Tracer networks through the Packet Tracer MCP server (pt-mcp). Use whenever the user wants to create or modify a Packet Tracer topology, add or cable routers/switches/PCs, configure IOS, test connectivity, watch packets in simulation mode, or study for the CCNA with Packet Tracer — even when phrased loosely as "build me a lab," "set up OSPF," "why can't PC1 ping PC2," or referencing a .pkt/.pka file. Prefer this skill over recalling Packet Tracer behavior from memory; several Packet Tracer conventions differ from real IOS.
---

# Packet Tracer

Build and operate Packet Tracer networks through the pt-mcp tools. This covers the conventions and pitfalls an agent
won't infer on its own; general networking knowledge is assumed.

**Who you are probably helping:** a CCNA student. Explain what each step does and why, verify instead of assuming, and
prefer teaching over doing on graded work (see Activities).

## Start every session with get_pt_information

It confirms the connection and tells you the Packet Tracer version, device count, and whether you're in Realtime or
Simulation mode. If it fails, tell the user to run `pt-mcp doctor`; don't retry blindly.

## Names, not IDs

Devices are addressed by their **display name** (`R1`, `PC0`). Ports use **full names** (`GigabitEthernet0/0`,
`FastEthernet0`, `Serial0/0/0`), not abbreviations. If you aren't sure of a name, list first with
`get_devices_in_network` or `get_interfaces_for_device`; never guess.

## Building

- Discover valid models with `get_device_models` (e.g. routers `1941`, `2911`, `ISR4331`; switches `2960-24TT`; PCs
  `PC-PT`). Don't invent model names.
- **Small changes:** `add_device_to_network` with `name` and `x`/`y`, then `connect_two_devices` (leave `cable` as
  `auto`; it picks serial, console, straight-through, or crossover like the GUI).
- **Whole labs:** `create_full_network_topology` is robust here. Errors are collected per step, not fatal, so use it for
  multi-device builds and read its `errors` list afterwards.
- **Serial WAN links need a module.** Most routers ship without serial ports: `get_device_model_details` shows free
  slots and supported cards; `add_module_to_device(name, "0/0", "HWIC-2T")` (or `NIM-2T` on ISR4000s) adds
  `Serial0/0/0-1`. Adding or removing a module **power-cycles the device and discards its unsaved config**, so add
  modules before configuring, or save first.
- Layout: keep ~150–250 px between devices, put routers above switches above end devices, and align peers on a row.

## Configuring

| Task | Tool |
|---|---|
| Multi-line config (interfaces, routing, VLANs, ACLs) | `configure_device` (paste config; indentation marks sub-mode lines) |
| A few config lines | `send_cli_command(..., config_command=true)` (no `configure terminal`/`end`) |
| Show/exec commands | `send_cli_command` (default exec mode) |
| PC/server IP settings | `configure_host_interface` (not CLI) |
| PC Command Prompt (`ping`, `ipconfig`, `tracert`) | `send_terminal_command` |

- Check every result's `status`: `invalid`/`incomplete`/`ambiguous` are parser rejections, and `rejected` means IOS
  printed a `% …` error (e.g. overlapping subnet). Fix and re-send; don't report success when lines were rejected.
- Router interfaces are **shut down by default**: include `no shutdown`.
- On serial links, the DCE side needs `clock rate` (Packet Tracer often sets a default; check `show controllers` if the
  link stays down).
- `save_device_configuration` before anything that reboots a device (module changes, power cycle).

## Verifying

- `verify_connectivity(source, [destinations])` gives sent/received/loss per destination. Fresh switch links take ~30 s
  (STP) and the first ping often loses a packet to ARP; the tool retries total failures, so treat partial loss on a
  first ping as normal.
- Back up claims with evidence: `show ip interface brief`, `show ip route`, `show vlan brief`, `show running-config`.
- `get_console_log` shows `%LINK`/`%LINEPROTO` messages, useful for "is the link up?".

## Simulation mode: show, don't tell

To explain how something works (ARP, switching, routing, encapsulation):

1. `set_simulation_mode(true)`, `reset_simulation()`
2. `send_simple_pdu(source, destination)`
3. `step_simulation(steps=N)`, then `get_simulation_events` (filter by `protocol`)
4. `get_simulation_event_details(index)`: Packet Tracer's own OSI-layer decisions and decoded headers. Quote the
   decisions; they're authoritative and great for teaching (e.g. TTL decrement and HDLC encapsulation at a router).
5. Read everything you need **before** `set_simulation_mode(false)`, because returning to Realtime clears the event
   list.

## Activities (.pka) and academic integrity

`get_activity_instructions` reads the instructions. The server cannot read answers, scores, or completion %, by
design. When the open file is a graded activity, **teach and hint**: explain concepts, point at the relevant step, help
debug the student's own config. Don't configure the graded devices for them unless they explicitly say it's not graded
work.

## Destructive tools

`delete_device_from_network`, `delete_link`, `remove_module_from_device`, `erase_device_configuration`,
`create_new_network`, and `open_network_file` lose work. Ask the user first, and offer `save_network_file` before
replacing the network.

## If a call is refused

"Refusing to call … not been verified" is the server's crash protection: some Packet Tracer IPC calls crash the app.
Don't try to work around it. Tell the user which capability isn't available yet.
