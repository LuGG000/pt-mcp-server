"""
End-to-end tool tests. In mock mode every call goes over PTMP to tests/fake_pt.py.
"""

import os

import pytest
from fastmcp.exceptions import ToolError

from tests.conftest import USE_MOCKS, result_data


async def call(client, tool, **args):
    return result_data(await client.call_tool(tool, args))


async def test_tools_registered(main_mcp_client):
    names = {t.name for t in await main_mcp_client.list_tools()}
    assert {
        "get_pt_information",
        "get_devices_in_network",
        "add_device_to_network",
        "connect_two_devices",
        "send_cli_command",
        "send_terminal_command",
        "describe_ipc_class",
    } <= names
    assert "call_ipc_api" not in names  # raw IPC is opt-in (PT_MCP_ENABLE_RAW_IPC): it could reach untested methods


async def test_destructive_tools_are_annotated(main_mcp_client):
    tools = {t.name: t for t in await main_mcp_client.list_tools()}
    for name in ("delete_device_from_network", "delete_link", "create_new_network", "send_cli_command"):
        assert tools[name].annotations.destructiveHint is True
        assert "CRITICAL" in tools[name].description
    assert tools["get_devices_in_network"].annotations.readOnlyHint is True


async def test_system_information(main_mcp_client):
    info = await call(main_mcp_client, "get_pt_information")
    assert info["pt_version"].startswith("9.0.1")
    assert info["ipc_api_spec"].startswith("9.0.1")


async def test_build_small_topology(main_mcp_client, fake_pt):
    assert await call(main_mcp_client, "get_device_models", device_type="router") == ["1941", "2911", "ISR4331"]  # deduped
    r1 = await call(main_mcp_client, "add_device_to_network", device_type="router", model="2911", x=100, y=100, name="R1")
    assert r1 == "R1"
    pc = await call(main_mcp_client, "add_device_to_network", device_type="pc", model="PC-PT")
    assert pc == "PC0"
    assert await call(
        main_mcp_client, "connect_two_devices", device_a="R1", port_a="GigabitEthernet0/0", device_b="PC0", port_b="FastEthernet0"
    )

    devices = await call(main_mcp_client, "get_devices_in_network")
    assert {d["name"]: d["type"] for d in devices} == {"R1": "router", "PC0": "pc"}
    everything = await call(main_mcp_client, "get_devices_in_network", include_infrastructure=True)
    assert "Power Distribution Device0" in {d["name"] for d in everything}

    links = await call(main_mcp_client, "get_all_links")
    assert len(links) == 1
    assert {(links[0]["device_a"], links[0]["port_a"]), (links[0]["device_b"], links[0]["port_b"])} == {
        ("R1", "GigabitEthernet0/0"),
        ("PC0", "FastEthernet0"),
    }
    assert links[0]["cable"] == "cross"

    cfg = await call(
        main_mcp_client,
        "configure_host_interface",
        name="PC0",
        port="FastEthernet0",
        ip_address="192.168.1.10",
        default_gateway="192.168.1.1",
    )
    assert cfg == {"ip_address": "192.168.1.10", "subnet_mask": "255.255.255.0", "dhcp": False}

    ports = await call(main_mcp_client, "get_interfaces_for_device", name="PC0")
    assert ports[0]["ip_address"] == "192.168.1.10"
    assert (ports[0]["remote_device"], ports[0]["remote_port"]) == ("R1", "GigabitEthernet0/0")


async def test_cli_modes(main_mcp_client, fake_pt):
    await call(main_mcp_client, "add_device_to_network", device_type="router", model="2911", name="R1")
    exec_out = await call(main_mcp_client, "send_cli_command", name="R1", commands="show ip interface brief")
    assert exec_out == [{"command": "show ip interface brief", "status": "ok", "output": "[enable] show ip interface brief"}]

    cfg = await call(
        main_mcp_client,
        "send_cli_command",
        name="R1",
        commands="interface GigabitEthernet0/0\nip address 10.0.0.1 255.255.255.0\nbogus command",
        config_command=True,
    )
    assert [r["status"] for r in cfg] == ["ok", "ok", "invalid"]
    assert cfg[1]["output"].startswith("[config-if]")  # sub-mode carried over


async def test_terminal_command_collects_events(main_mcp_client, fake_pt):
    await call(main_mcp_client, "add_device_to_network", device_type="pc", model="PC-PT")
    out = await call(main_mcp_client, "send_terminal_command", name="PC0", command="ping 10.0.0.1", timeout=5)
    assert out == {"output": "Reply to ping 10.0.0.1\n", "completed": True, "status": "ok"}


async def test_delete_and_errors(main_mcp_client, fake_pt):
    await call(main_mcp_client, "add_device_to_network", device_type="switch", model="2960-24TT")
    assert await call(main_mcp_client, "delete_device_from_network", name="Switch0") is True
    with pytest.raises(ToolError):
        await main_mcp_client.call_tool("rename_device", {"name": "NoSuchDevice", "new_name": "X"})
    with pytest.raises(ToolError, match="not an IOS device"):
        await call(main_mcp_client, "add_device_to_network", device_type="pc", model="PC-PT")
        await main_mcp_client.call_tool("send_cli_command", {"name": "PC0", "commands": "show version"})


async def test_raw_ipc_and_describe(main_mcp_client, raw_ipc_client, fake_pt):
    await call(main_mcp_client, "add_device_to_network", device_type="router", model="ISR4331", name="R9")
    model = await call(raw_ipc_client, "call_ipc_api", chain=[["network"], ["getDevice", "R9"], ["getModel"]])
    assert model == "ISR4331"
    obj = await call(raw_ipc_client, "call_ipc_api", chain='[["network"], ["getDevice", "R9"]]')
    assert obj["object"] == "Router"
    desc = await call(main_mcp_client, "describe_ipc_class", class_name="CiscoDevice", name_filter="enterCommand")
    assert desc["methods"]["enterCommand"] == ["(string, string) -> pair  [CHANGE_NETWORK_INFO]"]


async def test_save_network(main_mcp_client, fake_pt, tmp_path):
    path = await call(main_mcp_client, "save_network_file", path=str(tmp_path / "lab"))
    assert path.endswith("lab.pkt") and os.path.exists(path)


@pytest.mark.skipif(USE_MOCKS, reason="live-only")
async def test_live_inventory(main_mcp_client):
    info = await call(main_mcp_client, "get_pt_information")
    devices = await call(main_mcp_client, "get_devices_in_network", include_infrastructure=True)
    assert info["device_count"] == len(devices)
