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

from enum import StrEnum
from ipaddress import IPv4Address

from pydantic import Field, IPvAnyAddress
from pydantic_settings import BaseSettings, SettingsConfigDict

from pt_mcp.install import config_file


class TransportEnum(StrEnum):
    """Transport types supported by the MCP server."""

    HTTP = "http"
    STDIO = "stdio"


class Settings(BaseSettings):
    """Settings for the Packet Tracer MCP server."""

    model_config = SettingsConfigDict(
        # Later files win: the per-user config written by `pt-mcp setup`, then a project .env. Real env vars beat both.
        env_file=(config_file(), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    pt_host: str = Field(default="127.0.0.1", description="Host running Cisco Packet Tracer (IPC listener)")
    pt_port: int = Field(default=39000, description="Packet Tracer IPC (PTMP) port; see Extensions > IPC > Options")
    pt_port_scan: int = Field(default=10, description="If PT_PORT refuses, also try the next N-1 ports (PT moves to the next free port)")
    pt_app_id: str = Field(default="net.netacad.cisco.ptmcp", description="ExApp ID; must match <ID> in the registered .pta")
    pt_app_key: str = Field(default="ptmcp", description="ExApp key; must match <KEY> in the registered .pta")
    pt_timeout: float = Field(default=30.0, description="Seconds to wait for a Packet Tracer IPC reply")
    pt_api_spec: str | None = Field(
        default=None,
        description="IPC API spec to use (e.g. '9.0.1'). Default: picked from the version Packet Tracer reports.",
    )
    pt_mcp_enable_raw_ipc: bool = Field(
        default=False,
        description="Register the call_ipc_api tool (raw IPC call chains). Off by default: it can reach untested methods.",
    )
    pt_allow_unverified_ipc: bool = Field(
        default=False,
        description=(
            "Allow IPC methods that have not been verified against a live Packet Tracer. Unverified calls can crash "
            "Packet Tracer and lose the open network. Known crashing methods stay blocked regardless."
        ),
    )
    pt_mcp_transport: TransportEnum = Field(default=TransportEnum.STDIO, description="Transport type for the MCP server")
    pt_mcp_bind: IPvAnyAddress = Field(
        default_factory=lambda: IPv4Address("127.0.0.1"),
        description="IP address to bind the MCP server when transport is HTTP",
    )
    pt_mcp_port: int = Field(default=9000, description="Port to bind the MCP server when transport is HTTP")


settings = Settings()
