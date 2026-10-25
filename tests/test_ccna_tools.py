"""
Tests for the cml-mcp-parity and CCNA study tools (mock mode: tests/fake_pt.py).
"""

import json

import pytest
from fastmcp.exceptions import ToolError

from pt_mcp.tools.configuration import config_lines
from tests.conftest import result_data


async def call(client, tool, **args):
    return result_data(await client.call_tool(tool, args))


def test_config_lines_accepts_show_run_output():
    show_run = (
        "Building configuration...\n\nCurrent configuration : 812 bytes\n!\nversion 15.1\n!\nhostname R1\n!\n"
        "interface Gi0/0\n ip address 10.0.0.1 255.255.255.0\n!\nend\n"
    )
    assert config_lines(show_run) == ["hostname R1", "interface Gi0/0", " ip address 10.0.0.1 255.255.255.0"]
    assert config_lines("enable\nconf t\nR1(config)#\nrouter ospf 1\n network 10.0.0.0 0.255.255.255 area 0\nend") == [
        "router ospf 1",
        " network 10.0.0.0 0.255.255.255 area 0",
    ]


async def test_configure_save_and_read_config(main_mcp_client, fake_pt):
    await call(main_mcp_client, "add_device_to_network", device_type="router", model="2911", name="R1")
    res = await call(
        main_mcp_client,
        "configure_device",
        name="R1",
        config="!\ninterface GigabitEthernet0/0\n ip address 10.0.0.1 255.255.255.0\n no shutdown\nbogus line\n"
        "ip route 0.0.0.0 0.0.0.0 10.0.0.2\nend",
        save=True,
    )
    assert res["commands_sent"] == 5 and res["saved"] is True
    assert [e["command"] for e in res["errors"]] == ["bogus line"]
    running = await call(main_mcp_client, "get_device_configuration", name="R1")
    assert "ip address 10.0.0.1 255.255.255.0" in running["config"]
    assert "ip route 0.0.0.0 0.0.0.0 10.0.0.2" in running["config"]  # top-level line ran from global config
    startup = await call(main_mcp_client, "get_device_configuration", name="R1", source="startup")
    assert "ip address 10.0.0.1" in startup["config"]
    steps = await call(main_mcp_client, "erase_device_configuration", name="R1")
    assert [s["command"] for s in steps] == ["write erase", "<enter>", "reload", "no", "<enter>"]


async def test_modules(main_mcp_client, fake_pt):
    await call(main_mcp_client, "add_device_to_network", device_type="router", model="2911", name="R1")
    details = await call(main_mcp_client, "get_device_model_details", name="R1")
    assert details["supported_modules"][0]["model"] == "HWIC-2T"
    assert "2-Port Serial" in details["supported_modules"][0]["description"]
    assert [s["slot"] for s in details["slots"]] == ["0/0", "0/1", "0/2", "0/3"] and all("module" not in s for s in details["slots"])

    assert await call(main_mcp_client, "add_module_to_device", name="R1", slot="0/0", module="HWIC-2T") == ["Serial0/0/0", "Serial0/0/1"]
    details = await call(main_mcp_client, "get_device_model_details", name="R1")
    assert details["slots"][0] == {"slot": "0/0", "module": "HWIC-2T", "ports": ["Serial0/0/0", "Serial0/0/1"]}
    assert fake_pt.network.getDevice("R1").power is True  # power restored after the change

    with pytest.raises(ToolError, match="Unknown module"):
        await main_mcp_client.call_tool("add_module_to_device", {"name": "R1", "slot": "0/1", "module": "HWIC-99X"})
    assert await call(main_mcp_client, "remove_module_from_device", name="R1", slot="0/0") is True


async def test_full_topology_roundtrip(main_mcp_client, fake_pt):
    topo = {
        "description": "CCNA serial WAN lab",
        "devices": [
            {
                "name": "R1",
                "device_type": "router",
                "model": "2911",
                "modules": [{"slot": "0/0", "module": "HWIC-2T"}],
                "config": "hostname R1",
            },
            {"name": "R2", "device_type": "router", "model": "2911", "modules": [{"slot": "0/0", "module": "HWIC-2T"}]},
            {"name": "PC1", "device_type": "pc", "model": "PC-PT"},
            {"name": "X", "device_type": "toaster", "model": "?"},
        ],
        "links": [
            {"device_a": "R1", "port_a": "Serial0/0/0", "device_b": "R2", "port_b": "Serial0/0/0"},
            {"device_a": "PC1", "port_a": "FastEthernet0", "device_b": "R1", "port_b": "GigabitEthernet0/0"},
        ],
        "hosts": [{"name": "PC1", "ip_address": "192.168.1.10", "default_gateway": "192.168.1.1", "dns_server": "8.8.8.8"}],
    }
    built = await call(main_mcp_client, "create_full_network_topology", topology=json.dumps(topo))
    assert built["devices"] == ["R1", "R2", "PC1"]
    assert built["links"] == ["R1:Serial0/0/0 <-> R2:Serial0/0/0 (serial)", "PC1:FastEthernet0 <-> R1:GigabitEthernet0/0 (cross)"]
    assert built["errors"] == ["X: unknown device_type 'toaster'"]

    exported = await call(main_mcp_client, "export_network_topology")
    assert exported["description"] == "CCNA serial WAN lab"
    r1 = next(d for d in exported["devices"] if d["name"] == "R1")
    assert r1["modules"] == [{"slot": "0/0", "module": "HWIC-2T"}] and "hostname R1" in r1["config"]
    assert exported["hosts"] == [
        {
            "name": "PC1",
            "port": "FastEthernet0",
            "ip_address": "192.168.1.10",
            "subnet_mask": "255.255.255.0",
            "default_gateway": "192.168.1.1",
            "dns_server": "8.8.8.8",
        }
    ]
    # re-adding an already installed module is a no-op, so an export rebuilds cleanly
    assert await call(main_mcp_client, "add_module_to_device", name="R1", slot="0/0", module="HWIC-2T") == []
    assert len(exported["links"]) == 2
    assert all(d["name"] != "Power Distribution Device0" for d in exported["devices"])


async def test_simulation_walkthrough(main_mcp_client, fake_pt):
    for t, m, n in (("pc", "PC-PT", "PC1"), ("switch", "2960-24TT", "SW1"), ("router", "2911", "R1")):
        await call(main_mcp_client, "add_device_to_network", device_type=t, model=m, name=n)
    with pytest.raises(ToolError, match="Realtime mode"):
        await main_mcp_client.call_tool("step_simulation", {"steps": 1})
    assert await call(main_mcp_client, "set_simulation_mode", enabled=True) is True
    assert await call(main_mcp_client, "send_simple_pdu", source="PC1", destination="R1") == 0
    stepped = await call(main_mcp_client, "step_simulation", steps=3)
    assert stepped["event_count"] == 3 and stepped["new_events"] == 3

    events = await call(main_mcp_client, "get_simulation_events")
    assert [(e["at_device"], e.get("from_device"), e["protocol"], e["status"]) for e in events] == [
        ("PC1", None, "ICMP", "sent"),
        ("SW1", "PC1", "ICMP", "sent"),
        ("R1", "SW1", "ICMP", "accepted"),
    ]
    detail = await call(main_mcp_client, "get_simulation_event_details", index=1)
    assert "floods the frame" in detail["decisions"][1]
    headers = {h["header"]: h["fields"] for h in detail["inbound_pdu"]}
    assert headers["IpHeader"]["srcAddress"] == "192.168.1.11" and headers["IpHeader"]["protocol"] == "1 (ICMP)"
    assert headers["IcmpMessage"]["icmpType"] == "8 (echo-request)"
    assert headers["EthernetIIHeader"]["frameType"] == "2048 (IPv4)"
    assert await call(main_mcp_client, "reset_simulation") is True
    assert await call(main_mcp_client, "get_simulation_events") == []
    await call(main_mcp_client, "set_simulation_mode", enabled=False)


async def test_notes(main_mcp_client, fake_pt):
    nid = await call(main_mcp_client, "add_text_note", text="LAN A 192.168.1.0/24", x=10, y=20)
    lid = await call(main_mcp_client, "add_line_annotation", start_x=0, start_y=300, end_x=800, end_y=300, color="255,0,0")
    notes = await call(main_mcp_client, "get_annotations")
    assert notes == [
        {"id": nid, "kind": "note", "x": 10, "y": 20, "text": "LAN A 192.168.1.0/24"},
        {"id": lid, "kind": "line", "x": 0, "y": 300, "end_x": 800, "end_y": 300, "color": "255,0,0"},
        {"id": "{00000000-0000-0000-0000-0000000000e1}", "kind": "ellipse"},  # listed by id only: details crash PT
    ]
    assert await call(main_mcp_client, "edit_text_note", annotation_id=nid, text="LAN A 10.1.1.0/24") is True
    assert (await call(main_mcp_client, "get_annotations"))[0]["text"] == "LAN A 10.1.1.0/24"
    assert await call(main_mcp_client, "delete_annotation", annotation_id=nid) is True
    assert await call(main_mcp_client, "delete_annotation", annotation_id=lid) is True
    cid = await call(main_mcp_client, "add_circle_annotation", center_x=400, center_y=300, radius=80)
    assert {"id": cid, "kind": "ellipse"} in await call(main_mcp_client, "get_annotations")  # no getEllipseItemData call
    assert await call(main_mcp_client, "delete_annotation", annotation_id=cid) is True


async def test_verification_and_logs(main_mcp_client, fake_pt):
    await call(main_mcp_client, "add_device_to_network", device_type="pc", model="PC-PT", name="PC1")
    log = await call(main_mcp_client, "get_command_history", name="R1")
    assert log == [{"time": "Thu Oct 22 21:34:21 2026", "device": "R1", "prompt": "R1(config)#", "command": "router ospf 1"}]
    assert "%LINK-5-CHANGED" in await call(main_mcp_client, "get_console_log", name="PC1")


def test_ping_parsing():
    from pt_mcp.tools.cli import parse_ping

    win = "Ping statistics for 10.0.0.1:\n    Packets: Sent = 4, Received = 3, Lost = 1 (25% loss),"
    assert parse_ping("PC1", "10.0.0.1", win).model_dump(exclude_none=True) == {
        "source": "PC1",
        "destination": "10.0.0.1",
        "sent": 4,
        "received": 3,
        "loss_percent": 25,
        "success": True,
    }
    ios = "Sending 5, 100-byte ICMP Echos to 10.0.0.2, timeout is 2 seconds:\n.!!!!\nSuccess rate is 80 percent (4/5), round-trip 0/0/1 ms"
    r = parse_ping("R1", "10.0.0.2", ios)
    assert (r.sent, r.received, r.loss_percent, r.success) == (5, 4, 20, True)
    fail = parse_ping("PC1", "10.9.9.9", "Packets: Sent = 4, Received = 0, Lost = 4 (100% loss),")
    assert fail.success is False and "100% loss" in fail.output


async def test_activity_instructions(main_mcp_client, fake_pt):
    assert await call(main_mcp_client, "get_activity_instructions") == {"is_activity": False, "page_count": 0, "pages": []}
    from tests.fake_pt import ActivityFile

    app = fake_pt.root._app
    app.file, saved = ActivityFile(), app.file
    try:
        info = await call(main_mcp_client, "get_activity_instructions")
        assert info["is_activity"] is True and info["page_count"] == 2
        assert info["pages"][0] == "Objectives\n- Configure OSPF\n- Verify connectivity"
    finally:
        app.file = saved


async def test_exapp_does_not_request_activity_wizard():
    """Academic integrity: the ExApp must not hold the privilege that exposes activity answers and scores."""
    from pathlib import Path

    meta = (Path(__file__).parent.parent / "src" / "pt_mcp" / "data" / "exapp_meta.xml.in").read_text()
    assert "ACTIVITY_WIZARD" not in meta


async def test_flat_config_mode_recovery(main_mcp_client, fake_pt):
    """LLM-style unindented config: global commands after a sub-mode, a typo inside it, and a bad interface name."""
    await call(main_mcp_client, "add_device_to_network", device_type="router", model="2911", name="R1")
    res = await call(
        main_mcp_client,
        "configure_device",
        name="R1",
        config=(
            "interface GigabitEthernet0/0\nip address 10.0.0.1 255.255.255.0\nbogus typo\nno shutdown\n"
            "ip route 0.0.0.0 0.0.0.0 10.0.0.2\ninterface Serial9/9/9\nip address 10.9.9.1 255.255.255.0\nhostname EDGE"
        ),
    )
    assert [e["command"] for e in res["errors"]] == ["bogus typo", "interface Serial9/9/9", "ip address 10.9.9.1 255.255.255.0"]
    cfg = (await call(main_mcp_client, "get_device_configuration", name="R1"))["config"]
    assert "no shutdown" in cfg  # typo did not knock the rest of the interface block out of config-if
    assert "ip route 0.0.0.0 0.0.0.0 10.0.0.2" in cfg and "hostname EDGE" in cfg
    assert "10.9.9.1" not in cfg  # the line after the bad interface did not land on Gi0/0


async def test_ios_percent_error_is_rejected(main_mcp_client, fake_pt):
    await call(main_mcp_client, "add_device_to_network", device_type="router", model="2911", name="R1")
    fake_pt.network.getDevice("R1")._next = "overlap"
    out = await call(
        main_mcp_client,
        "send_cli_command",
        name="R1",
        commands="interface GigabitEthernet0/1\nip address 10.0.12.1 255.255.255.252",
        config_command=True,
    )
    assert [r["status"] for r in out] == ["ok", "rejected"]


def test_config_lines_startup_semantics_and_noise():
    show_run = (
        "version 15.1\nlicense udi pid CISCO2911/K9 sn FTX1524N529-\nip classless\nspanning-tree extend system-id\n!\n"
        "interface GigabitEthernet0/0\n ip address 192.168.1.1 255.255.255.0\n duplex auto\n!\n"
        "interface GigabitEthernet0/1\n no ip address\n shutdown\n!\nline con 0\n login\n!\nline vty 0 4\n password cisco\n login\nend"
    )
    assert config_lines(show_run, startup_semantics=True) == [
        "interface GigabitEthernet0/0",
        " ip address 192.168.1.1 255.255.255.0",
        " duplex auto",
        " no shutdown",
        "interface GigabitEthernet0/1",
        " no ip address",
        " shutdown",
        "line con 0",
        "line vty 0 4",
        " password cisco",
        " login",
    ]
    assert " no shutdown" not in config_lines(show_run)  # pasting a partial config never forces interfaces up


async def test_raw_ipc_refuses_known_crashing_methods(raw_ipc_client, fake_pt):
    with pytest.raises(ToolError, match="crashes Packet Tracer"):
        await raw_ipc_client.call_tool(
            "call_ipc_api", {"chain": [["appWindow"], ["getActiveWorkspace"], ["getLogicalWorkspace"], ["getEllipseItemData", "{x}"]]}
        )


async def test_raw_ipc_refuses_unverified_methods(raw_ipc_client, fake_pt):
    with pytest.raises(ToolError, match="not been verified"):
        await raw_ipc_client.call_tool("call_ipc_api", {"chain": [["network"], ["getTotalDeviceAttributeValue", "power"]]})


def test_call_guard():
    from pt_mcp.safety import CallGuard, UnsafeCallError

    strict, lenient = CallGuard(), CallGuard(allow_unverified=True)
    strict.check(["appWindow", "getActiveWorkspace", "getLogicalWorkspace", "addDevice"])
    with pytest.raises(UnsafeCallError, match="not been verified"):
        strict.check(["network", "getTotalDeviceAttributeValue"])
    lenient.check(["network", "getTotalDeviceAttributeValue"])
    with pytest.raises(UnsafeCallError, match="crashes"):
        lenient.check(["getEllipseItemData"])  # known crashers stay blocked even when unverified calls are allowed
    assert "getEllipseItemData" not in strict.verified


def test_every_tool_method_is_on_the_allow_list():
    """Guard against regressions: IPC method names used in tool code must be verified (or tools would just fail)."""
    import ast
    import pathlib

    from pt_mcp.safety import verified_methods

    allowed = verified_methods()
    src = pathlib.Path(__file__).parent.parent / "src" / "pt_mcp" / "tools"
    used = set()
    for f in src.glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr[:1].islower():
                name = node.func.attr
                if name.startswith(("get", "set", "add", "remove", "is", "enter", "create", "delete", "draw", "file", "skip")):
                    used.add(name)
    python_side = {"getLogger", "get", "setdefault", "is_a", "set_simulation_mode", "get_pt_client_dep"}
    missing = sorted(m for m in used - allowed - python_side if not m.startswith(("get_", "set_", "add_", "is_")))
    assert missing == [], f"tool code calls IPC methods that were never verified live: {missing}"


def test_qt_rich_text_description_becomes_plain_text():
    from pt_mcp.tools.activity import html_to_text

    qt = (
        '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0//EN" "http://www.w3.org/TR/REC-html40/strict.dtd">\n<html><head>'
        '<meta name="qrichtext" content="1" /><style type="text/css">\np, li { white-space: pre-wrap; }\n</style></head>'
        '<body style=" font-family:\'Verdana\';">\n<p style=" margin-top:0px;">coverage run</p></body></html>'
    )
    assert html_to_text(qt) == "coverage run"
    assert html_to_text("plain description") == "plain description"
