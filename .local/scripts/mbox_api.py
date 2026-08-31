#!/usr/bin/env python3
"""Morph Devbox API helper for mbox. Prints JSON. Never prints API keys."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

_READY = "ready"
_TRANSIENT = {"provisioning", "pending", "resuming", "rebooting", "starting"}
_RESUMEABLE = {"paused", "pausing", "stopped", "stopping"}
_FAILURE = {"error", "failed", "terminated", "deleting", "deleted"}

# Account-level approved seeds (morph.new aliases) — like ebox public base/desktop.
# Not project boxes; not the full morph.new catalog.
MBOX_APPROVED_SEEDS: list[dict] = [
    {
        "id": "desktop",
        "alias": "fullstack-devbox",
        "name": "desktop",
        "access": "public",
        "hint": "XFCE + noVNC + Next.js + Codex CLI (headed visual QA)",
        "desktop": True,
        "app_port": 3000,
    },
    {
        "id": "base",
        "alias": "codex-agent-workspace",
        "name": "base",
        "access": "public",
        "hint": "Headless tmux agent workspace (Codex / GitHub)",
        "desktop": False,
        "app_port": 8080,
    },
]


def _morphcli() -> str:
    env = os.environ.get("MBOX_MORPHCLI", "").strip()
    if env and Path(env).is_file():
        return env
    which = shutil.which("morphcloud")
    if which:
        return which
    venv = Path.home() / ".local/share/mbox/venv/bin/morphcloud"
    if venv.is_file():
        return str(venv)
    raise SystemExit("mbox-api: morphcloud not found — install CLI or set MBOX_MORPHCLI")


def _resolve_seed(ref: str) -> dict:
    for seed in MBOX_APPROVED_SEEDS:
        if ref in (seed["id"], seed["alias"], seed["name"]):
            return dict(seed)
    return {
        "id": ref,
        "alias": ref,
        "name": ref,
        "access": "seed",
        "hint": ref,
        "desktop": _is_desktop_seed(ref),
        "app_port": 8080,
    }


def _run_template_alias(alias: str, timeout: int = 600) -> Any:
    morph = _morphcli()
    proc = subprocess.run(
        [morph, "devbox", "template", "run", alias, "--plain", "--json"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"mbox-api: template run '{alias}' failed: {err}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"mbox-api: template run returned non-JSON: {exc}") from exc
    devbox_id = data.get("devbox_id")
    if not devbox_id and isinstance(data.get("devbox"), dict):
        devbox_id = data["devbox"].get("id")
    if not devbox_id:
        raise SystemExit("mbox-api: template run returned no devbox_id")
    client = _client()
    db = _db(client)
    return _wait_ready(db, devbox_id, timeout=timeout)


def _load_api_key() -> str:
    key = os.environ.get("MORPH_API_KEY", "").strip()
    if key:
        return key
    cfg = Path.home() / ".config" / "mbox" / "config.json"
    if cfg.is_file():
        data = json.loads(cfg.read_text())
        key = (data.get("api_key") or data.get("morph_api_key") or "").strip()
        if key:
            os.environ["MORPH_API_KEY"] = key
            return key
    try:
        from morphcloud.config import resolve_settings

        settings = resolve_settings()
        if settings.api_key:
            os.environ["MORPH_API_KEY"] = settings.api_key
            return settings.api_key
    except Exception:
        pass
    raise SystemExit(
        "mbox: missing MORPH_API_KEY — export it or save to ~/.config/mbox/config.json\n"
        "  create keys: https://cloud.morph.so/web/keys"
    )


def _client():
    _load_api_key()
    from morphcloud.api import MorphCloudClient

    return MorphCloudClient()


def _db(client):
    return client.devbox


def _norm_status(status: Optional[str]) -> str:
    return (status or "").strip().lower()


def _find_http_url(devbox: Any, name: str) -> Optional[str]:
    networking = getattr(devbox, "networking", None)
    if not networking:
        return None
    for svc in getattr(networking, "http_services", None) or []:
        if getattr(svc, "name", None) == name:
            url = getattr(svc, "url", None)
            if isinstance(url, str) and url:
                return url
    return None


def _devbox_json(devbox: Any) -> dict:
    return json.loads(devbox.model_dump_json())


def _wait_ready(db, devbox_id: str, timeout: int = 300) -> Any:
    deadline = time.time() + max(timeout, 1)
    last = None
    while True:
        devbox = db.devboxes_core.get_devbox(devbox_id)
        status = _norm_status(getattr(devbox, "status", None))
        if status == _READY:
            return devbox
        if status in _FAILURE:
            raise SystemExit(f"mbox-api: devbox {devbox_id} failed status={status}")
        if time.time() >= deadline:
            raise SystemExit(
                f"mbox-api: timeout waiting for {devbox_id} (last status={last or status})"
            )
        last = status
        time.sleep(3)


def _ensure_resumed(db, devbox_id: str) -> Any:
    devbox = db.devboxes_core.get_devbox(devbox_id)
    status = _norm_status(getattr(devbox, "status", None))
    if status in _RESUMEABLE:
        devbox = db.devboxes_actions.resume_devbox(devbox_id)
    elif status not in {_READY} | _TRANSIENT:
        pass
    return _wait_ready(db, devbox_id)


def _expose(db, devbox_id: str, name: str, port: int) -> Any:
    try:
        return db.devboxes_actions.expose_http_service_on_devbox(
            devbox_id, name=name, port=port, auth_mode="none"
        )
    except Exception as exc:
        # already exposed — refresh devbox
        if "already" in str(exc).lower() or "409" in str(exc):
            return db.devboxes_core.get_devbox(devbox_id)
        raise


def _is_desktop_seed(ref: str, hint: str = "") -> bool:
    blob = f"{ref} {hint}".lower()
    return any(x in blob for x in ("desktop", "vnc", "novnc", "xfce", "codex"))


def _morph_desktop_url(devbox_id: str) -> str:
    return f"https://cloud.morph.so/web/devboxes/{devbox_id}"


def _finish_create(
    devbox: Any,
    name: str,
    port: int,
    source: dict,
    desktop: bool,
    template_ref: str = "",
) -> dict:
    client = _client()
    db = _db(client)
    devbox = _ensure_resumed(db, devbox.id)

    # Templates often pre-expose services (e.g. desktop/nextjs, guide).
    app_url = (
        _find_http_url(devbox, "app")
        or _find_http_url(devbox, "nextjs")
        or _find_http_url(devbox, "guide")
    )
    vnc_upstream = _find_http_url(devbox, "vnc") or _find_http_url(devbox, "desktop")

    if not app_url:
        try:
            devbox = _expose(db, devbox.id, "app", port)
            app_url = _find_http_url(devbox, "app")
        except Exception:
            pass

    morph_desktop_url = _morph_desktop_url(devbox.id)
    if desktop and not vnc_upstream:
        try:
            devbox = _expose(db, devbox.id, "vnc", 6080)
            vnc_upstream = _find_http_url(devbox, "vnc") or _find_http_url(devbox, "desktop")
        except Exception:
            vnc_upstream = None
        if not vnc_upstream:
            vnc_upstream = morph_desktop_url

    if not app_url:
        app_url = vnc_upstream or morph_desktop_url

    return {
        "name": name,
        "devbox_id": devbox.id,
        "sandbox_id": devbox.id,
        "app_port": port,
        "app_url": app_url or "",
        "app_upstream": app_url or "",
        "vnc_upstream": vnc_upstream,
        "morph_desktop_url": morph_desktop_url,
        "source": source,
        "desktop": desktop,
        "dashboard": morph_desktop_url,
    }


def cmd_create(args: list[str]) -> None:
    """create <name> (--template T | --snapshot S) [--port PORT]"""
    if not args:
        raise SystemExit("mbox-api create: name required")
    name = args[0]
    template = None
    snapshot = None
    port = 8080
    i = 1
    while i < len(args):
        if args[i] == "--template" and i + 1 < len(args):
            template = args[i + 1]
            i += 2
        elif args[i] == "--snapshot" and i + 1 < len(args):
            snapshot = args[i + 1]
            i += 2
        elif args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        else:
            raise SystemExit(f"mbox-api create: unknown arg {args[i]}")

    if bool(template) == bool(snapshot):
        raise SystemExit("mbox-api create: pass exactly one of --template or --snapshot")

    client = _client()
    db = _db(client)
    meta = {"mbox_name": name, "mbox": "1"}
    desktop = False

    if snapshot:
        meta["mbox_from"] = "snapshot"
        meta["mbox_snapshot"] = snapshot
        devbox = db.devboxes_lifecycle.create_devbox_from_snapshot(
            snapshot_id=snapshot, name=name, metadata=meta
        )
        source = {"kind": "snapshot", "ref": snapshot}
        desktop = _is_desktop_seed(snapshot)
    else:
        seed = _resolve_seed(template or "base")
        alias = seed["alias"]
        seed_id = seed["id"]
        port = int(seed.get("app_port") or port)
        desktop = bool(seed.get("desktop"))
        meta["mbox_from"] = "seed"
        meta["mbox_seed"] = seed_id
        meta["mbox_alias"] = alias
        meta["template_id"] = alias

        if alias.startswith("tpl_"):
            devbox = client.devbox.start(template_id=alias, name=name, metadata=meta)
        else:
            devbox = _run_template_alias(alias)
            try:
                db.devboxes_actions.update_devbox_display_name(devbox.id, display_name=name)
            except Exception:
                pass
            try:
                db.devboxes_actions.update_devbox_metadata(devbox.id, request=meta)
            except Exception:
                pass

        source = {"kind": "seed", "ref": seed_id}

    out = _finish_create(devbox, name, port, source, desktop, template or "")
    print(json.dumps(out))


def cmd_fork(args: list[str]) -> None:
    """fork <parent_devbox_id> <name> [--port PORT]"""
    if len(args) < 2:
        raise SystemExit("mbox-api fork: parent_devbox_id name required")
    parent = args[0]
    name = args[1]
    port = 8080
    i = 2
    while i < len(args):
        if args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        else:
            raise SystemExit(f"mbox-api fork: unknown arg {args[i]}")

    client = _client()
    db = _db(client)
    _ensure_resumed(db, parent)
    branch = db.devboxes_actions.branch_devbox(parent, name=name)
    instances = list(getattr(branch, "instances", None) or [])
    if not instances:
        raise SystemExit("mbox-api fork: branch returned no instances")
    devbox = instances[0]
    parent_meta = dict(getattr(db.devboxes_core.get_devbox(parent), "metadata", None) or {})
    desktop = _is_desktop_seed(
        parent_meta.get("mbox_template", ""),
        parent_meta.get("template_id", ""),
    )
    source = {"kind": "box", "ref": parent}
    out = _finish_create(devbox, name, port, source, desktop)
    print(json.dumps(out))


def cmd_snapshot(args: list[str]) -> None:
    """snapshot <devbox_id> [--name LABEL]"""
    if not args:
        raise SystemExit("mbox-api snapshot: devbox_id required")
    devbox_id = args[0]
    label = "snapshot"
    i = 1
    while i < len(args):
        if args[i] == "--name" and i + 1 < len(args):
            label = args[i + 1]
            i += 2
        else:
            raise SystemExit(f"mbox-api snapshot: unknown arg {args[i]}")

    client = _client()
    db = _db(client)
    _ensure_resumed(db, devbox_id)
    snap = db.devboxes_actions.save_devbox(devbox_id, name=label)
    print(
        json.dumps(
            {
                "snapshot_id": getattr(snap, "id", ""),
                "name": getattr(snap, "name", label),
                "devbox_id": devbox_id,
            }
        )
    )


def cmd_url(args: list[str]) -> None:
    devbox_id = args[0]
    port = int(args[1]) if len(args) > 1 else 8080
    client = _client()
    db = _db(client)
    devbox = _ensure_resumed(db, devbox_id)
    url = _find_http_url(devbox, "app")
    if not url:
        devbox = _expose(db, devbox_id, "app", port)
        url = _find_http_url(devbox, "app")
    if not url:
        raise SystemExit("mbox-api url: no app HTTP service — run mbox wake")
    print(url)


def cmd_ensure_web(args: list[str]) -> None:
    cmd_url(args)


def _fetch_catalog_aliases() -> list[dict]:
    """Public morph.new aliases (shared catalog), excluding curated approved seeds."""
    approved = {s["alias"] for s in MBOX_APPROVED_SEEDS}
    try:
        req = urllib.request.Request(
            "https://devbox.svc.cloud.morph.so/api/aliases",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
    except Exception:
        return []
    items = payload.get("data") or payload.get("aliases") or []
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        alias = (item.get("alias") or "").strip()
        if not alias or alias in approved:
            continue
        desc = (item.get("description") or "").strip()
        tags = item.get("tags") or []
        hint = desc or ", ".join(str(t) for t in tags) or alias
        out.append(
            {
                "id": alias,
                "alias": alias,
                "name": alias,
                "access": "catalog",
                "hint": hint[:160],
                "desktop": _is_desktop_seed(alias, hint),
                "app_port": 8080,
            }
        )
    out.sort(key=lambda x: x["name"])
    return out


def cmd_list_templates(_args: list[str]) -> None:
    """Approved seeds, morph.new catalog aliases, and your account templates (tpl_*)."""
    public = [dict(s) for s in MBOX_APPROVED_SEEDS]
    catalog = _fetch_catalog_aliases()
    private = []
    try:
        client = _client()
        db = _db(client)
        result = db.templates.list_templates()
        for t in getattr(result, "data", None) or getattr(result, "templates", None) or []:
            tid = getattr(t, "id", "")
            if not tid:
                continue
            tname = getattr(t, "name", tid)
            desc = (getattr(t, "description", None) or "").strip()
            cached = getattr(t, "cached_step_count", 0)
            total = getattr(t, "step_count", 0)
            hint = desc or f"your template cached={cached}/{total}"
            private.append(
                {
                    "id": tid,
                    "name": tname,
                    "access": "private",
                    "hint": hint,
                    "desktop": _is_desktop_seed(tname, hint),
                }
            )
    except Exception:
        pass
    print(json.dumps({"public": public, "catalog": catalog, "private": private}))


def _read_project(path: Path) -> dict:
    if not path.is_file():
        return {"default_base": None, "app_port": 8080, "timeout": 60, "bases": {}}
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore
    data = tomllib.loads(path.read_text())
    bases = data.get("bases") or {}
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
    lines = [
        "# mbox project config — blessed carbon-copy bases (Morph snapshots)",
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
    if not args:
        raise SystemExit("mbox-api project: subcommand required")
    sub = args[0]
    if sub == "get":
        print(json.dumps(_read_project(Path(args[1]))))
    elif sub == "init":
        path = Path(args[1])
        if path.is_file():
            raise SystemExit(f"mbox-api project init: already exists: {path}")
        _write_project(
            path,
            {"default_base": None, "app_port": 8080, "timeout": 60, "bases": {}},
        )
        print(json.dumps({"path": str(path)}))
    elif sub == "set-base":
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
                raise SystemExit(f"mbox-api project set-base: bad arg {args[i]}")
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
            raise SystemExit(f"mbox-api: unknown base '{base_name}'")
        data["default_base"] = base_name
        _write_project(path, data)
        print(json.dumps(data))
    else:
        raise SystemExit(f"mbox-api project: unknown sub {sub}")


def cmd_pause(args: list[str]) -> None:
    if not args:
        raise SystemExit("mbox-api pause: devbox_id required")
    client = _client()
    db = _db(client)
    db.devboxes_actions.pause_devbox(args[0])
    print(json.dumps({"devbox_id": args[0], "status": "paused"}))


def cmd_resume(args: list[str]) -> None:
    if not args:
        raise SystemExit("mbox-api resume: devbox_id required")
    client = _client()
    db = _db(client)
    devbox = db.devboxes_actions.resume_devbox(args[0])
    print(json.dumps({"devbox_id": args[0], "status": getattr(devbox, "status", "resuming")}))


def cmd_list_live(_args: list[str]) -> None:
    client = _client()
    db = _db(client)
    result = db.devboxes_core.list_devboxes()
    print(result.model_dump_json())


def cmd_console_session(args: list[str]) -> None:
    """Delegate interactive shell to morphcloud devbox ssh."""
    if not args:
        raise SystemExit("mbox-api console_session: devbox_id required")
    devbox_id = args[0]
    morph = _morphcli()
    rc = subprocess.call([morph, "devbox", "ssh", devbox_id])
    raise SystemExit(rc)


def cmd_set_timeout(args: list[str]) -> None:
    """Morph auto-pauses on idle — no E2B-style TTL beat. Ack for keepalive callers."""
    if len(args) < 2:
        raise SystemExit("mbox-api set_timeout: devbox_id seconds required")
    print(json.dumps({"devbox_id": args[0], "timeout": int(args[1]), "note": "morph_auto_pause"}))


def cmd_activity(args: list[str]) -> None:
    """Stub — Morph remote desktop activity not wired yet."""
    print(
        json.dumps(
            {
                "vnc_clients": 0,
                "vnc_connected": False,
                "idle_ms": None,
                "vnc_active": False,
                "note": "use morph web desktop or mbox open",
            }
        )
    )


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: mbox-api <create|fork|snapshot|url|list_templates|project|pause|resume|list_live|console_session|set_timeout|activity> ..."
        )
    cmd = sys.argv[1]
    args = sys.argv[2:]
    dispatch = {
        "create": cmd_create,
        "fork": cmd_fork,
        "snapshot": cmd_snapshot,
        "url": cmd_url,
        "ensure_web": cmd_ensure_web,
        "list_templates": cmd_list_templates,
        "project": cmd_project,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "list_live": cmd_list_live,
        "console_session": cmd_console_session,
        "set_timeout": cmd_set_timeout,
        "activity": cmd_activity,
    }
    if cmd not in dispatch:
        raise SystemExit(f"unknown command: {cmd}")
    dispatch[cmd](args)


if __name__ == "__main__":
    main()
