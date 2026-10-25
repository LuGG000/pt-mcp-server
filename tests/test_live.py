"""
Live scenario against a running Packet Tracer (USE_MOCKS=false). Creates uniquely named devices, verifies
cabling, IOS config and an end-to-end ping, then deletes everything it created.
"""

import uuid

import pytest

from tests.conftest import USE_MOCKS, result_data

pytestmark = pytest.mark.skipif(USE_MOCKS, reason="live-only")


async def call(client, tool, **args):
    return result_data(await client.call_tool(tool, args))


async def test_router_switch_pc_ping(main_mcp_client):
    tag = uuid.uuid4().hex[:4]
    r, sw, pc = f"T{tag}-R", f"T{tag}-SW", f"T{tag}-PC"
    created = []
    try:
        for args in (
            dict(device_type="router", model="2911", x=100, y=600, name=r),
            dict(device_type="switch", model="2960-24TT", x=300, y=600, name=sw),
            dict(device_type="pc", model="PC-PT", x=500, y=600, name=pc),
        ):
            created.append(await call(main_mcp_client, "add_device_to_network", **args))
        assert created == [r, sw, pc]

        assert (
            await call(
                main_mcp_client, "connect_two_devices", device_a=r, port_a="GigabitEthernet0/0", device_b=sw, port_b="GigabitEthernet0/1"
            )
            == "straight"
        )
        assert (
            await call(main_mcp_client, "connect_two_devices", device_a=pc, port_a="FastEthernet0", device_b=sw, port_b="FastEthernet0/1")
            == "straight"
        )

        links = await call(main_mcp_client, "get_all_links")
        mine = {
            frozenset({(lk["device_a"], lk["port_a"]), (lk["device_b"], lk["port_b"])})
            for lk in links
            if r in (lk["device_a"], lk["device_b"]) or pc in (lk["device_a"], lk["device_b"])
        }
        assert mine == {
            frozenset({(r, "GigabitEthernet0/0"), (sw, "GigabitEthernet0/1")}),
            frozenset({(pc, "FastEthernet0"), (sw, "FastEthernet0/1")}),
        }

        cfg = await call(
            main_mcp_client,
            "send_cli_command",
            name=r,
            commands="interface GigabitEthernet0/0\nip address 10.99.0.1 255.255.255.0\nno shutdown",
            config_command=True,
        )
        assert [c["status"] for c in cfg] == ["ok", "ok", "ok"]
        brief = await call(main_mcp_client, "send_cli_command", name=r, commands="show ip interface brief")
        assert "10.99.0.1" in brief[0]["output"]

        await call(
            main_mcp_client, "configure_host_interface", name=pc, port="FastEthernet0", ip_address="10.99.0.10", default_gateway="10.99.0.1"
        )
        ports = await call(main_mcp_client, "get_interfaces_for_device", name=pc)
        assert (ports[0]["remote_device"], ports[0]["remote_port"]) == (sw, "FastEthernet0/1")

        # Switch ports go through STP listening/learning first; retry until the ping gets replies.
        for _ in range(4):
            out = await call(main_mcp_client, "send_terminal_command", name=pc, command="ping 10.99.0.1", timeout=30)
            assert out["completed"]
            if "Received = 4" in out["output"]:
                break
        assert "Received = 4" in out["output"], out["output"]
    finally:
        for name in reversed(created):
            await main_mcp_client.call_tool("delete_device_from_network", {"name": name}, raise_on_error=False)
    names = {d["name"] for d in await call(main_mcp_client, "get_devices_in_network")}
    assert not names & {r, sw, pc}


async def test_ccna_serial_wan_lab(main_mcp_client):
    """Build a serial WAN lab with modules + configs, ping across it, watch it in simulation, export/inspect, clean up."""
    tag = uuid.uuid4().hex[:4]
    r1, r2, pc1, pc2 = (f"W{tag}-{n}" for n in ("R1", "R2", "PC1", "PC2"))
    wan = "10.77.12"
    topo = {
        "devices": [
            {"name": r1, "device_type": "router", "model": "2911", "x": 100, "y": 800, "modules": [{"slot": "0/0", "module": "HWIC-2T"}],
             "config": f"interface GigabitEthernet0/0\n ip address 10.77.1.1 255.255.255.0\n"
                       f"interface Serial0/0/0\n ip address {wan}.1 255.255.255.252\nip route 10.77.2.0 255.255.255.0 {wan}.2"},
            {"name": r2, "device_type": "router", "model": "2911", "x": 400, "y": 800, "modules": [{"slot": "0/0", "module": "HWIC-2T"}],
             "config": f"interface GigabitEthernet0/0\n ip address 10.77.2.1 255.255.255.0\n"
                       f"interface Serial0/0/0\n ip address {wan}.2 255.255.255.252\nip route 10.77.1.0 255.255.255.0 {wan}.1"},
            {"name": pc1, "device_type": "pc", "model": "PC-PT", "x": 100, "y": 950},
            {"name": pc2, "device_type": "pc", "model": "PC-PT", "x": 400, "y": 950},
        ],
        "links": [
            {"device_a": r1, "port_a": "Serial0/0/0", "device_b": r2, "port_b": "Serial0/0/0"},
            {"device_a": pc1, "port_a": "FastEthernet0", "device_b": r1, "port_b": "GigabitEthernet0/0"},
            {"device_a": pc2, "port_a": "FastEthernet0", "device_b": r2, "port_b": "GigabitEthernet0/0"},
        ],
        "hosts": [
            {"name": pc1, "ip_address": "10.77.1.10", "subnet_mask": "255.255.255.0", "default_gateway": "10.77.1.1"},
            {"name": pc2, "ip_address": "10.77.2.10", "subnet_mask": "255.255.255.0", "default_gateway": "10.77.2.1"},
        ],
    }  # fmt: skip
    try:
        built = await call(main_mcp_client, "create_full_network_topology", topology=topo)
        assert built["errors"] == [] and len(built["links"]) == 3
        assert "(serial)" in built["links"][0]

        ping = (await call(main_mcp_client, "verify_connectivity", source=pc1, destinations=["10.77.2.10"], attempts=4))[0]
        assert ping["success"], ping

        assert await call(main_mcp_client, "set_simulation_mode", enabled=True)
        await call(main_mcp_client, "reset_simulation")
        await call(main_mcp_client, "send_simple_pdu", source=pc1, destination=pc2)
        await call(main_mcp_client, "step_simulation", steps=8)
        events = await call(main_mcp_client, "get_simulation_events", protocol="ICMP")
        at_r1 = next(e for e in events if e.get("at_device") == r1)
        detail = await call(main_mcp_client, "get_simulation_event_details", index=at_r1["index"])
        assert any("HDLC" in d for d in detail["decisions"])
        ip = next(h["fields"] for h in detail["outbound_pdu"] if h["header"] == "IpHeader")
        assert ip["dstAddress"] == "10.77.2.10" and ip["ttl"] < 255
    finally:
        await main_mcp_client.call_tool("set_simulation_mode", {"enabled": False}, raise_on_error=False)
        for name in (pc2, pc1, r2, r1):
            await main_mcp_client.call_tool("delete_device_from_network", {"name": name}, raise_on_error=False)
