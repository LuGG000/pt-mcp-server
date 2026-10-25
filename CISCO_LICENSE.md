# Cisco Proprietary License

These data files are derived from Cisco Packet Tracer

Copyright (c) 2007-2026, Cisco Systems, Inc.

All rights reserved.

## Notice

The following files are derived from Cisco Packet Tracer and its bundled IPC framework, and are subject to Cisco's
proprietary license terms:

- `src/pt_mcp/data/ipc_api_*.json`: the Packet Tracer IPC API (classes, methods, parameter and return types, required
  privileges)
- `src/pt_mcp/data/pdu_fields_*.json`: the field layout of Packet Tracer's simulation-mode PDUs
- `src/pt_mcp/data/verified_methods.json`: the Packet Tracer IPC methods verified against a running Packet Tracer
- `src/pt_mcp/data/exapp_meta.xml.in`: the Packet Tracer ExApp meta file format
- the PDU sample captured from Packet Tracer in `tests/fake_pt.py` (`ICMP_FRAME`)

These files are included in this project for the purpose of providing proper type definitions and API compatibility
with Packet Tracer's IPC interface.

The rest of this project (excluding these files) is licensed under the BSD 2-Clause "Simplified" License. See the
[LICENSE](LICENSE) file for details.
