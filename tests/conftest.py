"""
pytest configuration and fixtures for Packet Tracer MCP tests.

Set the USE_MOCKS environment variable to control the behavior:
- USE_MOCKS=true (default): tools talk PTMP to an in-process fake Packet Tracer (tests/fake_pt.py)
- USE_MOCKS=false: tools talk to the real Packet Tracer configured by PT_HOST/PT_PORT/PT_APP_ID/PT_APP_KEY.
  Live tests build devices in the open network; run them on an empty or scratch file.
"""

import json
import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastmcp.client import Client
from mcp.types import TextContent

USE_MOCKS = os.getenv("USE_MOCKS", "true").lower() == "true"

if USE_MOCKS:
    from tests.fake_pt import FakePacketTracer

    FAKE = FakePacketTracer()
    os.environ["PT_HOST"] = "127.0.0.1"
    os.environ["PT_PORT"] = str(FAKE.port)
    os.environ["PT_APP_ID"] = FAKE.app_id
    os.environ["PT_APP_KEY"] = FAKE.key

from pt_mcp.server import server_mcp  # noqa: E402 - must follow the env setup above


@pytest.fixture
async def main_mcp_client() -> AsyncGenerator[Client, None]:
    async with Client(server_mcp) as client:
        yield client


@pytest.fixture
async def raw_ipc_client() -> AsyncGenerator[Client, None]:
    """A server instance with the opt-in call_ipc_api tool registered (as with PT_MCP_ENABLE_RAW_IPC=true)."""
    from fastmcp import FastMCP

    from pt_mcp.tools import ipc_api

    mcp = FastMCP("raw-ipc-test")
    ipc_api.register_tools(mcp, enable_raw_ipc=True)
    async with Client(mcp) as client:
        yield client


@pytest.fixture
def fake_pt():
    if not USE_MOCKS:
        pytest.skip("mock-only test")
    FAKE.devices.clear()
    FAKE.links.clear()
    return FAKE


def result_data(result) -> Any:
    """Return a tool result as Python data (structured content if present, else parsed text)."""
    if result.structured_content is not None:
        sc = result.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    text = result.content[0]
    assert isinstance(text, TextContent)
    try:
        return json.loads(text.text)
    except json.JSONDecodeError:
        return text.text
