#!/usr/bin/env python3
"""E2B API helper for ebox. Prints JSON / plain fields. Never prints API keys."""
from __future__ import annotations

import json
import shutil
import os
import subprocess
import sys
import time
from pathlib import Path


def _load_api_key() -> str:
    if os.environ.get("E2B_API_KEY"):
        return os.environ["E2B_API_KEY"]
    cfg = Path.home() / ".e2b" / "config.json"
    if not cfg.is_file():
        raise SystemExit("ebox: missing ~/.e2b/config.json — run: e2b auth login")
    data = json.loads(cfg.read_text())
    key = data.get("projectApiKey")
    if not key:
        raise SystemExit("ebox: no projectApiKey in ~/.e2b/config.json")
    os.environ["E2B_API_KEY"] = key
    return key


def _Sandbox():
    _load_api_key()
    from e2b import Sandbox

    return Sandbox


def _lifecycle():
    return {"on_timeout": "pause", "auto_resume": True}


def _stub_web(sbx, name: str, port: int) -> str:
    html = f"""<!doctype html><html><head><meta charset=utf-8><title>{name}</title>
<style>body{{font-family:system-ui;background:#0f1a14;color:#d8ffe8;display:grid;place-items:center;min-height:100vh;margin:0}}
main{{max-width:40rem;padding:2rem;border:1px solid #2a4a3a;border-radius:12px;background:#13241c}}
h1{{margin:0 0 .5rem}}code{{color:#86efac}}</style></head>
<body><main>
<h1>ebox: {name}</h1>
<p>E2B box (auto-pause). Friendly DNS via <code>ebox proxy</code>.</p>
<p>Id: <code>{sbx.sandbox_id}</code></p>
<p>Host: <code id=h></code></p>
<script>document.getElementById('h').textContent=location.host</script>
</main></body></html>"""
    sbx.files.write("/home/user/ebox-www/index.html", html)
    sbx.commands.run(
        f"python3 -m http.server {port} --directory /home/user/ebox-www",
        background=True,
        timeout=0,
    )
    time.sleep(0.6)
    return f"https://{sbx.get_host(port)}"




def _desktop_tools_present(sbx) -> bool:
    try:
        r = sbx.commands.run(
            "bash -lc 'command -v Xvfb >/dev/null && command -v x11vnc >/dev/null "
            "&& [ -x /opt/noVNC/utils/novnc_proxy ] && command -v startxfce4 >/dev/null'",
            timeout=20,
        )
        return r.exit_code == 0
    except Exception:
        return False


def _port_open(sbx, port: int) -> bool:
    try:
        r = sbx.commands.run(
            f"bash -lc 'ss -lntp 2>/dev/null | grep -q \":{port} \"'",
            timeout=10,
        )
        return r.exit_code == 0
    except Exception:
        return False


def _proc_running(sbx, name: str) -> bool:
    """Exact process-name match (avoids shell-quoting pitfalls of pgrep -f)."""
    try:
        r = sbx.commands.run(
            f"bash -lc 'pgrep -x {name} >/dev/null'",
            timeout=10,
        )
        return r.exit_code == 0
    except Exception:
        return False


def _wait_port(sbx, port: int, attempts: int = 40, delay: float = 0.25) -> bool:
    for _ in range(attempts):
        if _port_open(sbx, port):
            return True
        time.sleep(delay)
    return False


def _desktop_healthy(sbx, *, vnc_port: int = 5900, novnc_port: int = 6080) -> bool:
    """Require the full stack — HTML on 6080 alone is a bear trap."""
    return (
        _proc_running(sbx, "Xvfb")
        and _proc_running(sbx, "x11vnc")
        and _port_open(sbx, vnc_port)
        and _port_open(sbx, novnc_port)
    )


def _kill_stale_desktop(sbx) -> None:
    # Best-effort cleanup of half-dead stacks (e.g. noVNC up, Xvfb/x11vnc gone).
    script = r"""
set +e
for p in novnc_proxy websockify x11vnc startxfce4 xfce4-session Xvfb; do
  pkill -x "$p" >/dev/null 2>&1
done
pkill -f 'novnc_proxy|websockify/run|/opt/noVNC' >/dev/null 2>&1
# websockify often shows up as python3 — free the ports directly
if command -v fuser >/dev/null 2>&1; then
  fuser -k 5900/tcp 6080/tcp >/dev/null 2>&1
fi
# last resort
for port in 5900 6080; do
  pids=$(ss -lptn "sport = :$port" 2>/dev/null | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | sort -u)
  for pid in $pids; do kill -9 "$pid" >/dev/null 2>&1; done
done
sleep 0.5
"""
    try:
        sbx.files.write("/tmp/ebox-kill-desktop.sh", script)
        sbx.commands.run("bash /tmp/ebox-kill-desktop.sh", timeout=20)
    except Exception:
        pass
    time.sleep(0.3)


def _ensure_desktop(
    sbx,
    *,
    display: str = ":0",
    width: int = 1280,
    height: int = 800,
    dpi: int = 96,
    vnc_port: int = 5900,
    novnc_port: int = 6080,
) -> dict:
    """Idempotently start Xvfb + XFCE + x11vnc + noVNC when desktop tools exist."""
    if not _desktop_tools_present(sbx):
        return {"desktop": False, "running": False, "reason": "not_desktop"}

    if _desktop_healthy(sbx, vnc_port=vnc_port, novnc_port=novnc_port):
        return {
            "desktop": True,
            "running": True,
            "already": True,
            "novnc_port": novnc_port,
            "upstream": f"https://{sbx.get_host(novnc_port)}",
        }

    # Half-open stacks (common after pause/resume or partial kill) must be reset.
    _kill_stale_desktop(sbx)

    # Xvfb
    sbx.commands.run(
        f"bash -lc 'Xvfb {display} -ac -screen 0 {width}x{height}x24 -retro -dpi {dpi} "
        f"-nolisten tcp -nolisten unix >/tmp/xvfb.log 2>&1'",
        background=True,
        timeout=0,
    )
    ok = False
    for _ in range(40):
        try:
            r = sbx.commands.run(
                f"bash -lc 'xdpyinfo -display {display} >/dev/null'",
                timeout=10,
            )
            if r.exit_code == 0:
                ok = True
                break
        except Exception:
            pass
        time.sleep(0.25)
    if not ok:
        raise SystemExit("ebox-api ensure_desktop: Xvfb failed to start")

    # XFCE
    sbx.commands.run(
        f"bash -lc 'export DISPLAY={display} HOME=/home/user; "
        f"eval \"$(dbus-launch --sh-syntax)\"; "
        f"startxfce4 >/tmp/xfce4.log 2>&1'",
        background=True,
        timeout=0,
    )
    time.sleep(1.5)

    # x11vnc ( -bg parent can exit non-zero; judge by listening port)
    try:
        sbx.commands.run(
            f"bash -lc 'x11vnc -bg -display {display} -forever -wait 50 -shared "
            f"-rfbport {vnc_port} -nopw >/tmp/x11vnc.log 2>&1 || true'",
            timeout=20,
        )
    except Exception:
        pass
    if not _wait_port(sbx, vnc_port):
        raise SystemExit("ebox-api ensure_desktop: x11vnc port did not open")

    # noVNC
    sbx.commands.run(
        f"bash -lc 'cd /opt/noVNC/utils && ./novnc_proxy --vnc localhost:{vnc_port} "
        f"--listen {novnc_port} --web /opt/noVNC >/tmp/novnc.log 2>&1'",
        background=True,
        timeout=0,
    )
    if not _wait_port(sbx, novnc_port):
        raise SystemExit("ebox-api ensure_desktop: noVNC port did not open")

    if not _desktop_healthy(sbx, vnc_port=vnc_port, novnc_port=novnc_port):
        raise SystemExit("ebox-api ensure_desktop: desktop stack unhealthy after start")

    return {
        "desktop": True,
        "running": True,
        "already": False,
        "novnc_port": novnc_port,
        "upstream": f"https://{sbx.get_host(novnc_port)}",
    }


def cmd_ensure_desktop(args: list[str]) -> None:
    """ensure_desktop <sandbox_id> — start desktop/VNC if tools are present."""
    if not args:
        raise SystemExit("ebox-api ensure_desktop: sandbox_id required")
    sid = args[0]
    Sandbox = _Sandbox()
    sbx = Sandbox.connect(sid, timeout=60)
    print(json.dumps(_ensure_desktop(sbx)))

def cmd_create(args: list[str]) -> None:
    """create <name> (--template T | --snapshot S) [--timeout SECS] [--port PORT] [--stub-web 0|1]"""
    if not args:
        raise SystemExit("ebox-api create: name required")
    name = args[0]
    template = None
    snapshot = None
    timeout = 60
    port = 8080
    stub_web = True
    i = 1
    while i < len(args):
        if args[i] == "--template" and i + 1 < len(args):
            template = args[i + 1]
            i += 2
        elif args[i] == "--snapshot" and i + 1 < len(args):
            snapshot = args[i + 1]
            i += 2
        elif args[i] == "--timeout" and i + 1 < len(args):
            timeout = int(args[i + 1])
            i += 2
        elif args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        elif args[i] == "--stub-web" and i + 1 < len(args):
            stub_web = args[i + 1] not in ("0", "false", "no")
            i += 2
        else:
            raise SystemExit(f"ebox-api create: unknown arg {args[i]}")

    if bool(template) == bool(snapshot):
        raise SystemExit("ebox-api create: pass exactly one of --template or --snapshot")

    Sandbox = _Sandbox()
    meta = {"ebox_name": name, "ebox": "1"}
    if snapshot:
        meta["ebox_from"] = "snapshot"
        meta["ebox_snapshot"] = snapshot
        sbx = Sandbox.create(
            snapshot,
            timeout=timeout,
            metadata=meta,
            lifecycle=_lifecycle(),
        )
        source = {"kind": "snapshot", "ref": snapshot}
        # clones already have filesystem; optional stub only if missing
        if stub_web:
            try:
                sbx.files.read("/home/user/ebox-www/index.html")
                stub_web = False
            except Exception:
                stub_web = True
    else:
        meta["ebox_from"] = "template"
        meta["ebox_template"] = template or "base"
        tpl = None if template in (None, "base") else template
        sbx = Sandbox.create(
            tpl,
            timeout=timeout,
            metadata=meta,
            lifecycle=_lifecycle(),
        )
        source = {"kind": "template", "ref": template or "base"}

    app_url = None
    if stub_web:
        app_url = _stub_web(sbx, name, port)
    else:
        try:
            app_url = f"https://{sbx.get_host(port)}"
        except Exception:
            app_url = f"https://{port}-{sbx.sandbox_id}.e2b.app"

    # Desktop templates/snapshots ship the tools but do NOT auto-start the stream.
    # Start it here so VNC links are not bear traps.
    desktop_info = _ensure_desktop(sbx)

    print(
        json.dumps(
            {
                "name": name,
                "sandbox_id": sbx.sandbox_id,
                "timeout": timeout,
                "app_port": port,
                "app_url": app_url,
                "source": source,
                "dashboard": f"https://e2b.dev/dashboard/inspect/sandbox/{sbx.sandbox_id}",
                "desktop": bool(desktop_info.get("desktop")),
                "vnc_upstream": desktop_info.get("upstream"),
            }
        )
    )


def cmd_snapshot(args: list[str]) -> None:
    """snapshot <sandbox_id> [--name LABEL]"""
    if not args:
        raise SystemExit("ebox-api snapshot: sandbox_id required")
    sid = args[0]
    label = None
    i = 1
    while i < len(args):
        if args[i] == "--name" and i + 1 < len(args):
            label = args[i + 1]
            i += 2
        else:
            raise SystemExit(f"ebox-api snapshot: unknown arg {args[i]}")

    Sandbox = _Sandbox()
    sbx = Sandbox.connect(sid, timeout=60)
    info = sbx.create_snapshot(name=label) if label else sbx.create_snapshot()
    print(
        json.dumps(
            {
                "snapshot_id": info.snapshot_id,
                "names": list(getattr(info, "names", None) or []),
                "sandbox_id": sid,
            }
        )
    )


def cmd_url(args: list[str]) -> None:
    sid = args[0]
    port = int(args[1]) if len(args) > 1 else 8080
    Sandbox = _Sandbox()
    sbx = Sandbox.connect(sid, timeout=60)
    print(f"https://{sbx.get_host(port)}")


def cmd_ensure_web(args: list[str]) -> None:
    sid = args[0]
    port = int(args[1]) if len(args) > 1 else 8080
    Sandbox = _Sandbox()
    sbx = Sandbox.connect(sid, timeout=60)
    sbx.commands.run(
        f"bash -lc 'ss -lntp 2>/dev/null | grep -q :{port} || "
        f"(mkdir -p /home/user/ebox-www && "
        f"python3 -m http.server {port} --directory /home/user/ebox-www)'",
        background=True,
        timeout=0,
    )
    print(f"https://{sbx.get_host(port)}")


def cmd_list_templates(_args: list[str]) -> None:
    """Public aliases + private templates from CLI."""
    public = [
        {"id": "base", "name": "base", "access": "public", "hint": "headless Debian + Node (stock)"},
        {"id": "desktop", "name": "desktop", "access": "public", "hint": "XFCE + Chrome + noVNC"},
    ]
    private = []
    try:
        raw = subprocess.check_output(
            ["e2b", "template", "list", "-f", "json"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for t in json.loads(raw or "[]"):
            tid = t.get("templateID") or t.get("templateId") or t.get("template_id")
            names = t.get("names") or t.get("aliases") or []
            alias = names[0] if names else tid
            private.append(
                {
                    "id": tid,
                    "name": alias,
                    "access": "private",
                    "hint": f"vCPU={t.get('cpuCount')} RAM={t.get('memoryMB')}MiB",
                }
            )
    except Exception:
        pass
    print(json.dumps({"public": public, "private": private}))


def _read_project(path: Path) -> dict:
    if not path.is_file():
        return {"default_base": None, "app_port": 8080, "timeout": 60, "bases": {}}
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore
    data = tomllib.loads(path.read_text())
    bases = data.get("bases") or {}
    # normalize
    norm = {}
    for k, v in bases.items():
        if isinstance(v, dict):
            norm[k] = v
    return {
        "default_base": data.get("default_base"),
        "app_port": int(data.get("app_port") or 8080),
        "timeout": int(data.get("timeout") or 60),
        "bases": norm,
    }


def _write_project(path: Path, data: dict) -> None:
    lines: list[str] = [
        "# ebox project config — blessed carbon-copy bases (snapshots)",
        "# https://github.com/ — managed by `ebox`",
        "",
    ]
    db = data.get("default_base")
    if db:
        lines.append(f'default_base = "{db}"')
    lines.append(f"app_port = {int(data.get('app_port') or 8080)}")
    lines.append(f"timeout = {int(data.get('timeout') or 60)}")
    lines.append("")
    for name in sorted((data.get("bases") or {}).keys()):
        b = data["bases"][name]
        lines.append(f"[bases.{name}]")
        lines.append(f'snapshot = "{b["snapshot"]}"')
        if b.get("source_box"):
            lines.append(f'source_box = "{b["source_box"]}"')
        if b.get("saved_at"):
            lines.append(f'saved_at = "{b["saved_at"]}"')
        if b.get("seed"):
            lines.append(f'seed = "{b["seed"]}"')
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def cmd_project(args: list[str]) -> None:
    """project get|set-base|set-default|init ..."""
    if not args:
        raise SystemExit("ebox-api project: subcommand required")
    sub = args[0]
    if sub == "get":
        path = Path(args[1])
        print(json.dumps(_read_project(path)))
    elif sub == "init":
        path = Path(args[1])
        if path.is_file():
            raise SystemExit(f"ebox-api project init: already exists: {path}")
        _write_project(
            path,
            {"default_base": None, "app_port": 8080, "timeout": 60, "bases": {}},
        )
        print(json.dumps({"path": str(path)}))
    elif sub == "set-base":
        # set-base <path> <base_name> <snapshot_id> [--source-box B] [--seed S] [--default]
        path = Path(args[1])
        base_name = args[2]
        snapshot_id = args[3]
        source_box = None
        seed = None
        make_default = False
        i = 4
        while i < len(args):
            if args[i] == "--source-box" and i + 1 < len(args):
                source_box = args[i + 1]
                i += 2
            elif args[i] == "--seed" and i + 1 < len(args):
                seed = args[i + 1]
                i += 2
            elif args[i] == "--default":
                make_default = True
                i += 1
            else:
                raise SystemExit(f"ebox-api project set-base: bad arg {args[i]}")
        data = _read_project(path)
        from datetime import datetime, timezone

        entry = {
            "snapshot": snapshot_id,
            "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if source_box:
            entry["source_box"] = source_box
        if seed:
            entry["seed"] = seed
        elif base_name in data["bases"] and data["bases"][base_name].get("seed"):
            entry["seed"] = data["bases"][base_name]["seed"]
        data["bases"][base_name] = entry
        if make_default or not data.get("default_base"):
            data["default_base"] = base_name
        _write_project(path, data)
        print(json.dumps(data))
    elif sub == "set-default":
        path = Path(args[1])
        base_name = args[2]
        data = _read_project(path)
        if base_name not in data["bases"]:
            raise SystemExit(f"ebox-api: unknown base '{base_name}'")
        data["default_base"] = base_name
        _write_project(path, data)
        print(json.dumps(data))
    else:
        raise SystemExit(f"ebox-api project: unknown sub {sub}")



def _activity_probe_script(idle_threshold_ms: int) -> str:
    # Runs inside the sandbox. Uses XScreenSaver idle (same as xprintidle)
    # + established VNC/noVNC sockets. Connection alone is NOT activity —
    # a forgotten browser tab keeps the websocket up while idle_ms grows.
    return f"""
import ctypes, ctypes.util, json, os, subprocess
os.environ.setdefault("DISPLAY", ":0")
idle_ms = None
err = None
try:
    X11 = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11"))
    Xss = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Xss") or "libXss.so.1")
    class Info(ctypes.Structure):
        _fields_ = [
            ("window", ctypes.c_ulong),
            ("state", ctypes.c_int),
            ("kind", ctypes.c_int),
            ("til_or_since", ctypes.c_ulong),
            ("idle", ctypes.c_ulong),
            ("eventMask", ctypes.c_ulong),
        ]
    X11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    X11.XOpenDisplay.restype = ctypes.c_void_p
    X11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    X11.XDefaultRootWindow.restype = ctypes.c_ulong
    Xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(Info)
    Xss.XScreenSaverQueryInfo.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Info)]
    Xss.XScreenSaverQueryInfo.restype = ctypes.c_int
    dpy = X11.XOpenDisplay(None)
    if not dpy:
        raise RuntimeError("XOpenDisplay failed")
    info = Xss.XScreenSaverAllocInfo()
    rc = Xss.XScreenSaverQueryInfo(dpy, X11.XDefaultRootWindow(dpy), info)
    if not rc:
        raise RuntimeError("XScreenSaverQueryInfo failed")
    idle_ms = int(info.contents.idle)
except Exception as e:
    err = str(e)
try:
    out = subprocess.check_output(
        ["bash", "-lc", "ss -H -tn state established '( sport = :6080 or sport = :5900 )' | wc -l"],
        text=True,
    )
    vnc_clients = int(out.strip() or 0)
except Exception:
    vnc_clients = 0
threshold = {idle_threshold_ms}
vnc_connected = vnc_clients > 0
vnc_active = bool(vnc_connected and idle_ms is not None and idle_ms < threshold)
print(json.dumps({{
    "vnc_clients": vnc_clients,
    "vnc_connected": vnc_connected,
    "idle_ms": idle_ms,
    "idle_threshold_ms": threshold,
    "vnc_active": vnc_active,
    "error": err,
}}))
"""


def cmd_set_timeout(args: list[str]) -> None:
    """set_timeout <sandbox_id> <seconds> — reset TTL from now (keepalive beat)."""
    if len(args) < 2:
        raise SystemExit("ebox-api set_timeout: sandbox_id seconds required")
    sid = args[0]
    timeout = int(args[1])
    Sandbox = _Sandbox()
    _load_api_key()
    Sandbox.set_timeout(sid, timeout)
    print(json.dumps({"sandbox_id": sid, "timeout": timeout}))


def cmd_activity(args: list[str]) -> None:
    """activity <sandbox_id> [--idle-secs N]

    Hybrid VNC signal:
      connected sockets on :6080/:5900  AND  X11 idle < threshold
    Forgotten tabs stay connected but idle_ms grows → vnc_active=false.
    """
    if not args:
        raise SystemExit("ebox-api activity: sandbox_id required")
    sid = args[0]
    idle_secs = 300
    i = 1
    while i < len(args):
        if args[i] == "--idle-secs" and i + 1 < len(args):
            idle_secs = int(args[i + 1])
            i += 2
        else:
            raise SystemExit(f"ebox-api activity: unknown arg {args[i]}")
    import base64

    Sandbox = _Sandbox()
    sbx = Sandbox.connect(sid, timeout=60)
    script = _activity_probe_script(idle_secs * 1000)
    # Avoid /tmp permission races — feed the probe over stdin.
    b64 = base64.b64encode(script.encode()).decode()
    r = sbx.commands.run(
        f"echo {b64} | base64 -d | DISPLAY=:0 python3 -",
        timeout=20,
    )
    out = (r.stdout or "").strip()
    if r.exit_code != 0 or not out:
        raise SystemExit(
            f"ebox-api activity: probe failed code={r.exit_code} stderr={r.stderr!r} stdout={r.stdout!r}"
        )
    data = json.loads(out.splitlines()[-1])
    print(json.dumps(data))



def cmd_console_session(args: list[str]) -> None:
    """console_session <sandbox_id> [--timeout SECS] [--idle-secs N] [--interval SECS]

    Run `e2b sbx connect` under a local PTY and beat set_timeout ONLY when the
    PTY recently saw stdin OR stdout/stderr bytes.

    Why not "attached = active":
      - Coffee at an idle prompt should sleep the box.
      - A quiet agent mid-turn still produces periodic output; idle window
        (default 300s) covers thinking gaps without needing agent APIs.
      - Classic bash TMOUT is stdin-only — wrong for agents. We use either direction.
    """
    import errno
    import fcntl
    import pty
    import select
    import signal
    import struct
    import termios
    import threading
    import tty

    if not args:
        raise SystemExit("ebox-api console_session: sandbox_id required")
    sid = args[0]
    timeout = 60
    idle_secs = 300
    interval = 200
    i = 1
    while i < len(args):
        if args[i] == "--timeout" and i + 1 < len(args):
            timeout = int(args[i + 1]); i += 2
        elif args[i] == "--idle-secs" and i + 1 < len(args):
            idle_secs = int(args[i + 1]); i += 2
        elif args[i] == "--interval" and i + 1 < len(args):
            interval = int(args[i + 1]); i += 2
        else:
            raise SystemExit(f"ebox-api console_session: unknown arg {args[i]}")

    if not sys.stdin.isatty():
        # Non-interactive fallback: plain connect, no keepalive.
        raise SystemExit(subprocess.call(["e2b", "sbx", "connect", sid]))

    Sandbox = _Sandbox()
    _load_api_key()

    last_io = time.monotonic()
    stop = threading.Event()
    child_pid = None

    def note_io() -> None:
        nonlocal last_io
        last_io = time.monotonic()

    def keepalive() -> None:
        # Beat only while recent PTY traffic exists. Silent gaps < idle_secs are OK.
        while not stop.wait(interval):
            age = time.monotonic() - last_io
            if age <= idle_secs:
                try:
                    Sandbox.set_timeout(sid, timeout)
                except Exception:
                    # Sandbox may already be gone/paused — keep looping until PTY exits.
                    pass

    def _set_winsize(fd: int) -> None:
        try:
            cols, rows = shutil.get_terminal_size(fallback=(80, 24))
            packed = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)
        except Exception:
            pass

    def _on_winch(_signum, _frame) -> None:
        if master_fd is not None:
            _set_winsize(master_fd)
            if child_pid:
                try:
                    os.kill(child_pid, signal.SIGWINCH)
                except ProcessLookupError:
                    pass

    master_fd = None
    stdin_fd = sys.stdin.fileno()
    old = termios.tcgetattr(stdin_fd)
    try:
        master_fd, slave_fd = pty.openpty()
        _set_winsize(master_fd)
        note_io()  # connecting counts as activity kickoff
        child_pid = os.fork()
        if child_pid == 0:
            # Child: become the session leader on the slave PTY.
            try:
                os.setsid()
            except OSError:
                pass
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)
            os.close(master_fd)
            os.execvp("e2b", ["e2b", "sbx", "connect", sid])
            os._exit(127)

        os.close(slave_fd)
        signal.signal(signal.SIGWINCH, _on_winch)
        tty.setraw(stdin_fd)

        t = threading.Thread(target=keepalive, name="ebox-console-keepalive", daemon=True)
        t.start()

        # Initial beat so a fresh connect doesn't race the first interval.
        try:
            Sandbox.set_timeout(sid, timeout)
        except Exception:
            pass

        while True:
            try:
                r, _, _ = select.select([master_fd, stdin_fd], [], [])
            except (InterruptedError, select.error) as e:
                if getattr(e, "errno", None) == errno.EINTR or isinstance(e, InterruptedError):
                    continue
                raise
            if master_fd in r:
                try:
                    data = os.read(master_fd, 8192)
                except OSError:
                    data = b""
                if not data:
                    break
                note_io()
                os.write(1, data)
            if stdin_fd in r:
                try:
                    data = os.read(stdin_fd, 8192)
                except OSError:
                    data = b""
                if not data:
                    # stdin closed — still wait for remote EOF
                    continue
                note_io()
                os.write(master_fd, data)
    finally:
        stop.set()
        try:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old)
        except Exception:
            pass
        if master_fd is not None:
            try:
                os.close(master_fd)
            except Exception:
                pass
        rc = 0
        if child_pid:
            try:
                _, status = os.waitpid(child_pid, 0)
                if os.WIFEXITED(status):
                    rc = os.WEXITSTATUS(status)
                elif os.WIFSIGNALED(status):
                    rc = 128 + os.WTERMSIG(status)
            except ChildProcessError:
                pass
        raise SystemExit(rc)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: ebox-api <create|snapshot|url|ensure_web|ensure_desktop|list_templates|project|set_timeout|activity|console_session> ..."
        )
    cmd = sys.argv[1]
    args = sys.argv[2:]
    dispatch = {
        "create": cmd_create,
        "snapshot": cmd_snapshot,
        "url": cmd_url,
        "ensure_web": cmd_ensure_web,
        "ensure_desktop": cmd_ensure_desktop,
        "list_templates": cmd_list_templates,
        "project": cmd_project,
        "set_timeout": cmd_set_timeout,
        "activity": cmd_activity,
        "console_session": cmd_console_session,
    }
    if cmd not in dispatch:
        raise SystemExit(f"unknown command: {cmd}")
    dispatch[cmd](args)


if __name__ == "__main__":
    main()
