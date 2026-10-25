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

"""
`pt-mcp setup` and `pt-mcp doctor`: find Packet Tracer, register pt-mcp as an ExApp, and diagnose the connection.

setup builds the ExApp meta file (.pta) with the installed Packet Tracer's own `meta` tool, using a random key
generated for this install, and writes the matching PT_APP_ID / PT_APP_KEY to the user config file that the server
reads. The user then adds the .pta in Packet Tracer once (Extensions > IPC > Configure Apps > Add).
"""

import glob
import os
import re
import secrets
import socket
import subprocess
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

DEFAULT_APP_ID = "net.netacad.cisco.ptmcp"
VERSION_RE = re.compile(rb"(?<![\d.])(\d{1,2}\.\d{1,2}\.\d{1,2}\.\d{4})(?![\d.])")


def config_dir() -> Path:
    """Per-user config directory (no extra dependency): macOS Application Support, Windows %APPDATA%, XDG elsewhere."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "pt-mcp"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "pt-mcp"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "pt-mcp"


def exapp_dir() -> Path:
    """Where setup puts PTMCP.pta (and the launcher it is tied to): ~/pt-mcp, easy to find in Packet Tracer's file
    dialog. The key itself stays in config_dir(), which is per-user and not something people browse or share."""
    return Path.home() / "pt-mcp"


def reveal(path: Path) -> None:
    """Show the file in Finder / Explorer so the user can pick it in Packet Tracer. Best effort."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)], check=False, capture_output=True)
        elif os.name == "nt":
            subprocess.run(["explorer", f"/select,{path}"], check=False, capture_output=True)
    except OSError:
        pass


def config_file() -> Path:
    return config_dir() / "pt-mcp.env"


@dataclass
class PacketTracerInstall:
    root: Path
    binary: Path
    meta: Path | None
    version: str | None


def _candidates() -> list[tuple[Path, Path, Path]]:
    """(install root, main binary, meta tool) for every Packet Tracer we can find, newest-looking first."""
    found = []
    if sys.platform == "darwin":
        for app in glob.glob("/Applications/Cisco Packet Tracer*/Cisco Packet Tracer*.app") + glob.glob(
            "/Applications/Cisco Packet Tracer*.app"
        ):
            c = Path(app) / "Contents"
            found.append((Path(app), c / "MacOS" / "PacketTracer", c / "extensions" / "meta"))
    elif os.name == "nt":
        for base in filter(None, {os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), r"C:\Program Files"}):
            for d in glob.glob(os.path.join(base, "Cisco Packet Tracer*")):
                found.append((Path(d), Path(d) / "bin" / "PacketTracer.exe", Path(d) / "bin" / "meta.exe"))
    else:
        for d in ["/opt/pt", *glob.glob("/opt/packettracer*"), *glob.glob("/opt/Cisco Packet Tracer*")]:
            found.append((Path(d), Path(d) / "bin" / "PacketTracer", Path(d) / "bin" / "meta"))
    return sorted((f for f in found if f[1].exists()), key=lambda f: _natural(str(f[0])), reverse=True)


def _natural(s: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def _binary_version(binary: Path) -> str | None:
    """Packet Tracer embeds its full version (e.g. 9.0.1.0858) as a string in the main binary."""
    try:
        data = binary.read_bytes()
    except OSError:
        return None
    for m in VERSION_RE.finditer(data):
        v = m.group(1).decode()
        if not v.startswith(("0.", "1.", "2.", "3.", "4.", "5.")):  # skip bundled library versions
            return v
    return None


def find_packet_tracer(root: str | None = None) -> PacketTracerInstall:
    if root:
        matches = [c for c in _candidates() if str(c[0]) == root] or [
            (Path(root), *_layout(Path(root)))  # explicit path that isn't in a standard location
        ]
    else:
        matches = _candidates()
    if not matches:
        raise FileNotFoundError("No Cisco Packet Tracer installation found (pass --pt-path to point at one)")
    r, binary, meta = matches[0]
    return PacketTracerInstall(root=r, binary=binary, meta=meta if meta.exists() else None, version=_binary_version(binary))


def _layout(root: Path) -> tuple[Path, Path]:
    if (root / "Contents").exists():
        return root / "Contents" / "MacOS" / "PacketTracer", root / "Contents" / "extensions" / "meta"
    exe = ".exe" if os.name == "nt" else ""
    return root / "bin" / f"PacketTracer{exe}", root / "bin" / f"meta{exe}"


def read_config() -> dict[str, str]:
    out = {}
    if config_file().exists():
        for line in config_file().read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def setup(
    pt_path: str | None = None,
    app_id: str = DEFAULT_APP_ID,
    key: str | None = None,
    rotate: bool = False,
    out_dir: str | None = None,
    open_folder: bool = True,
) -> int:
    pt = find_packet_tracer(pt_path)
    print(f"Packet Tracer: {pt.root}  (version {pt.version or 'unknown'})")
    if pt.meta is None:
        print(f"ERROR: Packet Tracer's meta tool was not found next to {pt.binary}")
        return 1

    existing = read_config()
    if key is None:
        key = existing.get("PT_APP_KEY") if existing.get("PT_APP_KEY") and not rotate else secrets.token_hex(16)
    out = Path(out_dir).expanduser() if out_dir else exapp_dir()
    out.mkdir(parents=True, exist_ok=True)
    old = config_dir() / "exapp"  # location used by earlier versions (hidden in file dialogs)
    if old.is_dir() and old.resolve() != out.resolve():
        for f in old.iterdir():
            f.unlink(missing_ok=True)
        old.rmdir()

    # The integrity file: PT records its hash in the .pta. pt-mcp is started by the MCP client, not by PT, so it
    # is a no-op launcher; it must not change after the .pta is built.
    launcher = out / ("launch.cmd" if os.name == "nt" else "launch.sh")
    launcher.write_text("@exit /b 0\r\n" if os.name == "nt" else "#!/bin/sh\n# pt-mcp ExApp integrity file. Do not edit.\nexit 0\n")
    if os.name != "nt":
        launcher.chmod(0o755)

    template = resources.files("pt_mcp.data").joinpath("exapp_meta.xml.in").read_text()
    xml = (
        template.replace("@APP_ID@", app_id)
        .replace("@APP_KEY@", key)
        .replace("@EXE_PATH@", str(launcher))
        .replace("@PT_VERSION@", pt.version or "9.0.1.0858")
    )
    (out / "README.txt").write_text(
        "pt-mcp ExApp registration for Cisco Packet Tracer\n\n"
        "Add PTMCP.pta in Packet Tracer: Extensions > IPC > Configure Apps... > Add.\n"
        f"Keep {launcher.name} next to it and unchanged: Packet Tracer checks its hash.\n"
        "Created by `pt-mcp setup`; re-run setup to rebuild (add the new .pta again if the key changed).\n"
    )
    (out / "PTMCP.xml").write_text(xml, encoding="iso-8859-1")
    pta = out / "PTMCP.pta"
    result = subprocess.run([str(pt.meta), pta.name, "PTMCP.xml", "-i", launcher.name], cwd=out, capture_output=True, text=True)
    (out / "PTMCP.xml").unlink(missing_ok=True)  # contains the key in clear text; the .pta is what PT needs
    if result.returncode != 0 or not pta.exists():
        print("ERROR: meta failed:\n" + (result.stdout + result.stderr).strip())
        return 1

    config_file().write_text(
        "# Written by `pt-mcp setup`. Must match the ExApp registered in Packet Tracer (exapp/PTMCP.pta).\n"
        f"PT_APP_ID={app_id}\nPT_APP_KEY={key}\n"
    )
    if os.name != "nt":
        config_file().chmod(0o600)
    changed = existing.get("PT_APP_KEY") not in (None, key)
    print(f"Wrote {config_file()}")
    print(f"Built {pta}")
    if _already_registered(app_id, key):
        print()
        print("Packet Tracer already accepts this ExApp ID and key: nothing to add. Run `pt-mcp doctor` to double-check.")
        return 0
    if open_folder:
        reveal(pta)
    print()
    print("Next, in Packet Tracer (one time" + (", and again now because the key changed" if changed else "") + "):")
    print("  Extensions > IPC > Configure Apps... > Add  ->  choose the file above, accept the prompt.")
    print("  Leave its startup setting at 'On Demand' ('Disabled' refuses connections).")
    print("Then run:  pt-mcp doctor")
    return 0


def _already_registered(app_id: str, key: str) -> bool:
    """True if a running Packet Tracer on this machine already authenticates this ID/key (best effort, quick)."""
    from pt_mcp.ptmp import PtmpClient, PtmpError

    port = _listening_port("127.0.0.1", 39000, 10)
    if port is None:
        return False
    client = PtmpClient(port=port, app_id=app_id, secret=key, timeout=5, port_scan=1)
    try:
        client.connect()
        return True
    except (PtmpError, OSError):
        return False
    finally:
        client.close()


def _listening_port(host: str, start: int, scan: int) -> int | None:
    for port in range(start, start + scan):
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return port
        except OSError:
            continue
    return None


def doctor() -> int:
    from pt_mcp.pt_client import available_specs, pick_spec
    from pt_mcp.ptmp import PtmpClient, PtmpError
    from pt_mcp.settings import settings

    ok = True

    def report(good: bool, label: str, detail: str = "", fix: str = "") -> None:
        nonlocal ok
        ok &= good
        print(f"[{'OK' if good else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
        if not good and fix:
            print(f"       fix: {fix}")

    try:
        pt = find_packet_tracer()
        report(True, "Packet Tracer installed", f"{pt.root} ({pt.version or 'version unknown'})")
    except FileNotFoundError as e:
        report(False, "Packet Tracer installed", str(e), "install Cisco Packet Tracer (NetAcad) or set PT_HOST to a remote one")

    cfg = read_config()
    report(
        bool(cfg.get("PT_APP_KEY")) or settings.pt_app_key != "ptmcp",
        "ExApp key configured",
        str(config_file()) if cfg else "using the built-in default key",
        "run `pt-mcp setup` (generates a key and the .pta to register)",
    )

    port = _listening_port(settings.pt_host, settings.pt_port, settings.pt_port_scan)
    report(
        port is not None,
        "Packet Tracer IPC listening",
        (
            f"{settings.pt_host}:{port}"
            if port
            else f"nothing on {settings.pt_host}:{settings.pt_port}-{settings.pt_port + settings.pt_port_scan - 1}"
        ),
        "start Packet Tracer and finish the NetAcad login; check Extensions > IPC > Options (Start Listening, port)",
    )
    if port is None:
        return 1

    client = PtmpClient(host=settings.pt_host, port=port, app_id=settings.pt_app_id, secret=settings.pt_app_key, timeout=10, port_scan=1)
    try:
        client.connect()
        version = re.search(r"PTVER([\d.]+)", client.server_info.get("reserved", ""))
        report(True, "ExApp authenticated", f"as {settings.pt_app_id}, Packet Tracer {version.group(1) if version else '?'}")
        if version:
            spec = pick_spec(version.group(1), settings.pt_api_spec)
            exact = spec == f"ipc_api_{'.'.join(version.group(1).split('.')[:3])}.json"
            report(
                exact,
                "IPC API spec",
                spec + ("" if exact else f" (closest match; bundled: {sorted(available_specs())})"),
                "run `just spec` on this Packet Tracer version to extract an exact spec",
            )
    except PtmpError as e:
        msg = str(e)
        fix = (
            "add the .pta from `pt-mcp setup` under Extensions > IPC > Configure Apps (re-add it if you re-ran setup)"
            if "auth" in msg or "disconnect" in msg
            else "check that the port belongs to Packet Tracer"
        )
        report(False, "ExApp authenticated", msg, fix)
    except OSError as e:
        report(False, "IPC connection", str(e))
    finally:
        client.close()
    print()
    print("All checks passed." if ok else "Some checks failed; see the fixes above.")
    return 0 if ok else 1
