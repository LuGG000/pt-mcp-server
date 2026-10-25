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

import argparse
import asyncio
import sys


async def run():
    from pt_mcp.server import server_mcp
    from pt_mcp.settings import TransportEnum, settings
    from pt_mcp.tools.dependencies import cleanup_pt_client

    try:
        if settings.pt_mcp_transport == TransportEnum.STDIO:
            await server_mcp.run_async()
        else:
            await server_mcp.run_async(transport="http", host=str(settings.pt_mcp_bind), port=settings.pt_mcp_port)
    finally:
        cleanup_pt_client()


def main():
    parser = argparse.ArgumentParser(prog="pt-mcp", description="MCP server for Cisco Packet Tracer (run with no command to serve)")
    sub = parser.add_subparsers(dest="command")
    s = sub.add_parser("setup", help="build the ExApp .pta for this machine (random key) and write the server config")
    s.add_argument("--pt-path", help="Packet Tracer install folder / .app (default: newest found)")
    s.add_argument("--app-id", default=None, help="ExApp ID (default: net.netacad.cisco.ptmcp)")
    s.add_argument("--rotate-key", action="store_true", help="generate a new key even if one is configured")
    s.add_argument("--out", help="folder for PTMCP.pta and its launcher (default: ~/pt-mcp)")
    s.add_argument("--no-open", action="store_true", help="don't open the folder in Finder/Explorer afterwards")
    sub.add_parser("doctor", help="check Packet Tracer, IPC, ExApp registration and API spec")
    args = parser.parse_args()

    if args.command == "setup":
        from pt_mcp.install import DEFAULT_APP_ID, setup

        sys.exit(setup(args.pt_path, args.app_id or DEFAULT_APP_ID, rotate=args.rotate_key, out_dir=args.out, open_folder=not args.no_open))
    if args.command == "doctor":
        from pt_mcp.install import doctor

        sys.exit(doctor())
    asyncio.run(run())


if __name__ == "__main__":
    main()
