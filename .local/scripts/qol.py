#!/usr/bin/env python3
"""qol — speak a sentence to get the human's attention (OpenAI TTS + PipeWire)."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import gi

gi.require_version("Secret", "1")
from gi.repository import Secret  # noqa: E402

QOL_SCHEMA_NAME = "qol.openai"
QOL_SERVICE = "qol"
QOL_KEY_ATTR = "openai-api-key"
QOL_KEY_LABEL = "qol OpenAI API key"
TARGET_VOLUME = 0.80
VOLUME_FLOOR = 0.79
DEFAULT_MODEL = os.environ.get("QOL_MODEL", "gpt-4o-mini-tts")
DEFAULT_VOICE = os.environ.get("QOL_VOICE", "onyx")
DEFAULT_DEVICE_HINT = os.environ.get("QOL_DEFAULT_DEVICE", "built-in")
ENV_FILE = Path(os.environ.get("QOL_ENV_FILE", Path.home() / ".env"))


@dataclass(frozen=True)
class Sink:
    wpctl_id: str
    name: str
    volume: float
    muted: bool
    is_default: bool
    node_name: str = ""


def _schema() -> Secret.Schema:
    return Secret.Schema.new(
        QOL_SCHEMA_NAME,
        Secret.SchemaFlags.NONE,
        {
            "service": Secret.SchemaAttributeType.STRING,
            "key": Secret.SchemaAttributeType.STRING,
        },
    )


def _key_attrs() -> dict[str, str]:
    return {"service": QOL_SERVICE, "key": QOL_KEY_ATTR}


def key_status() -> dict[str, Any]:
    stored = Secret.password_lookup_sync(_schema(), _key_attrs(), None)
    env_val = _read_env_key()
    return {
        "keyring": bool(stored),
        "env_file": bool(env_val),
        "env_path": str(ENV_FILE),
    }


def key_lookup() -> str | None:
    return Secret.password_lookup_sync(_schema(), _key_attrs(), None)


def key_store(value: str) -> None:
    Secret.password_store_sync(
        _schema(),
        _key_attrs(),
        Secret.COLLECTION_DEFAULT,
        QOL_KEY_LABEL,
        value,
        None,
    )


def key_clear() -> bool:
    return bool(Secret.password_clear_sync(_schema(), _key_attrs(), None))


def _read_env_key() -> str | None:
    if not ENV_FILE.is_file():
        return None
    for line in ENV_FILE.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :]
        if stripped.startswith("OPENAI_API_KEY="):
            value = stripped.split("=", 1)[1].strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            return value or None
    return None


def key_migrate(remove_from_env: bool = False) -> dict[str, Any]:
    env_val = _read_env_key()
    if not env_val:
        raise SystemExit(f"qol: no OPENAI_API_KEY in {ENV_FILE}")

    key_store(env_val)
    removed = False
    if remove_from_env:
        lines = ENV_FILE.read_text().splitlines(keepends=True)
        new_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            bare = stripped.removeprefix("export ")
            if bare.startswith("OPENAI_API_KEY="):
                removed = True
                continue
            new_lines.append(line)
        ENV_FILE.write_text("".join(new_lines))
    return {"migrated": True, "removed_from_env": removed, "env_path": str(ENV_FILE)}


def resolve_api_key(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    stored = key_lookup()
    if stored:
        return stored
    env_val = _read_env_key()
    if env_val:
        return env_val
    raise SystemExit(
        "qol: no OpenAI API key. Run: qol key migrate   (or: qol key set)"
    )


def _sink_node_name(wpctl_id: str) -> str:
    out = subprocess.run(
        ["wpctl", "inspect", wpctl_id],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    match = re.search(r'node\.name = "([^"]+)"', out)
    if not match:
        raise SystemExit(f"qol: could not resolve PipeWire node for sink {wpctl_id}")
    return match.group(1)


def _with_node_name(sink: Sink) -> Sink:
    if sink.node_name:
        return sink
    return Sink(
        wpctl_id=sink.wpctl_id,
        name=sink.name,
        volume=sink.volume,
        muted=sink.muted,
        is_default=sink.is_default,
        node_name=_sink_node_name(sink.wpctl_id),
    )
    path = shutil.which(cmd)
    if not path:
        raise SystemExit(f"qol: missing dependency: {cmd}")
    return path


def list_sinks() -> list[Sink]:
    out = subprocess.run(
        ["wpctl", "status"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    sinks: list[Sink] = []
    in_sinks = False
    for line in out.splitlines():
        if "Sinks:" in line:
            in_sinks = True
            continue
        if in_sinks and "Sources:" in line:
            break
        if not in_sinks:
            continue
        match = re.search(
            r"(?P<star>\*)?\s*(?P<id>\d+)\.\s+(?P<name>.+?)\s+\[vol:\s*(?P<vol>[0-9.]+)\]",
            line,
        )
        if not match:
            continue
        name = match.group("name").strip()
        muted = "[MUTED]" in line
        sinks.append(
            Sink(
                wpctl_id=match.group("id"),
                name=name,
                volume=float(match.group("vol")),
                muted=muted,
                is_default=match.group("star") == "*",
            )
        )
    return sinks


def resolve_sink(device: str | None) -> Sink:
    sinks = list_sinks()
    if not sinks:
        raise SystemExit("qol: no audio sinks found")

    if device is None:
        # Always prefer laptop speakers over the session default (often a headset).
        for sink in sinks:
            name = sink.name.lower()
            if "built-in" in name:
                return _with_node_name(sink)
        for sink in sinks:
            name = sink.name.lower()
            if "analog stereo" in name and "usb" not in name and "jabra" not in name:
                return _with_node_name(sink)
        hint = DEFAULT_DEVICE_HINT.lower()
        for sink in sinks:
            if hint in sink.name.lower():
                return _with_node_name(sink)
        raise SystemExit(
            "qol: could not find built-in speakers; pass --device or set QOL_DEFAULT_DEVICE"
        )

    device = device.strip()
    if device.isdigit():
        for sink in sinks:
            if sink.wpctl_id == device:
                return _with_node_name(sink)
        raise SystemExit(f"qol: no sink with id {device}")

    needle = device.lower()
    aliases = {
        "speakers": "built-in",
        "speaker": "built-in",
        "builtin": "built-in",
        "built-in": "built-in",
        "loud": "built-in",
        "headset": "jabra",
        "headphones": "jabra",
    }
    needle = aliases.get(needle, needle)

    matches = [s for s in sinks if needle in s.name.lower()]
    if len(matches) == 1:
        return _with_node_name(matches[0])
    if len(matches) > 1:
        names = ", ".join(f"{s.wpctl_id}:{s.name}" for s in matches)
        raise SystemExit(f"qol: device '{device}' is ambiguous: {names}")

    raise SystemExit(
        f"qol: no sink matching '{device}'. Try: qol devices"
    )


def ensure_volume(sink: Sink) -> dict[str, Any]:
    out = subprocess.run(
        ["wpctl", "get-volume", sink.wpctl_id],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    match = re.search(r"Volume:\s*([0-9.]+)", out)
    if not match:
        raise SystemExit(f"qol: could not parse volume for sink {sink.wpctl_id}")
    current = float(match.group(1))
    changed = False
    if current < VOLUME_FLOOR:
        subprocess.run(
            ["wpctl", "set-volume", sink.wpctl_id, str(TARGET_VOLUME)],
            check=True,
        )
        changed = True
        current = TARGET_VOLUME
    return {"before": sink.volume, "after": current, "changed": changed}


def synthesize(text: str, api_key: str, model: str, voice: str) -> bytes:
    payload = json.dumps(
        {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": "wav",
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/speech",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"qol: OpenAI TTS failed ({exc.code}): {body}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"qol: network error: {exc}") from exc


def _need(cmd: str) -> str:
    path = shutil.which(cmd)
    if not path:
        raise SystemExit(f"qol: missing dependency: {cmd}")
    return path


def play_audio(data: bytes, sink: Sink) -> None:
    _need("pw-play")
    sink = _with_node_name(sink)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        path = tmp.name
        tmp.write(data)
    try:
        subprocess.run(
            ["pw-play", f"--target={sink.node_name}", path],
            check=True,
        )
    finally:
        Path(path).unlink(missing_ok=True)


def read_text(args: argparse.Namespace) -> str:
    if args.text:
        return " ".join(args.text).strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise SystemExit("qol: pass text as an argument or on stdin")


def cmd_speak(args: argparse.Namespace) -> int:
    text = read_text(args)
    if not text:
        raise SystemExit("qol: nothing to speak")
    if len(text) > 4096:
        raise SystemExit("qol: text too long (max 4096 characters)")

    api_key = resolve_api_key(args.api_key)
    sink = resolve_sink(args.device)
    volume = ensure_volume(sink)
    audio = synthesize(text, api_key, args.model, args.voice)
    play_audio(audio, sink)

    if args.json:
        print(
            json.dumps(
                {
                    "spoken": text,
                    "device": {
                        "id": sink.wpctl_id,
                        "name": sink.name,
                        "node": sink.node_name,
                    },
                    "volume": volume,
                    "model": args.model,
                    "voice": args.voice,
                },
                indent=2,
            )
        )
    return 0


def cmd_devices(_: argparse.Namespace) -> int:
    sinks = list_sinks()
    if not sinks:
        print("no sinks found", file=sys.stderr)
        return 1
    for sink in sinks:
        mark = "*" if sink.is_default else " "
        print(f"{mark} {sink.wpctl_id:>3}  {sink.name}  [vol: {sink.volume:.2f}]")
    return 0


def cmd_key_status(_: argparse.Namespace) -> int:
    status = key_status()
    print(json.dumps(status, indent=2))
    return 0


def cmd_key_migrate(args: argparse.Namespace) -> int:
    result = key_migrate(remove_from_env=args.remove_from_env)
    print(json.dumps(result, indent=2))
    if not args.remove_from_env:
        print(
            f"qol: key stored in login keyring. Re-run with --remove-from-env to drop it from {ENV_FILE}",
            file=sys.stderr,
        )
    return 0


def cmd_key_set(args: argparse.Namespace) -> int:
    value = args.value
    if value is None and not sys.stdin.isatty():
        value = sys.stdin.read().strip()
    if not value:
        raise SystemExit("qol: pass the API key as an argument or on stdin")
    key_store(value)
    print(json.dumps({"stored": True}, indent=2))
    return 0


def cmd_key_clear(_: argparse.Namespace) -> int:
    cleared = key_clear()
    print(json.dumps({"cleared": cleared}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qol",
        description="Speak a sentence to get the human's attention.",
    )

    sub = parser.add_subparsers(dest="command")

    speak = sub.add_parser("speak", help="synthesize and play speech (default)")
    speak.add_argument("text", nargs="*", help="sentence to speak")
    speak.add_argument(
        "-d",
        "--device",
        help="audio sink (wpctl id or name substring; default: built-in speakers)",
    )
    speak.add_argument("--model", default=DEFAULT_MODEL)
    speak.add_argument("--voice", default=DEFAULT_VOICE)
    speak.add_argument("--api-key", help=argparse.SUPPRESS)
    speak.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON",
    )
    speak.set_defaults(func=cmd_speak)

    devices = sub.add_parser("devices", help="list PipeWire audio sinks")
    devices.set_defaults(func=cmd_devices)

    key = sub.add_parser("key", help="manage the OpenAI API key")
    key_sub = key.add_subparsers(dest="key_command", required=True)

    key_status_p = key_sub.add_parser("status", help="show key storage status")
    key_status_p.set_defaults(func=cmd_key_status)

    key_migrate_p = key_sub.add_parser(
        "migrate", help="copy OPENAI_API_KEY from ~/.env into the login keyring"
    )
    key_migrate_p.add_argument(
        "--remove-from-env",
        action="store_true",
        help=f"remove OPENAI_API_KEY line from {ENV_FILE} after storing",
    )
    key_migrate_p.set_defaults(func=cmd_key_migrate)

    key_set_p = key_sub.add_parser("set", help="store an API key in the login keyring")
    key_set_p.add_argument("value", nargs="?", help="API key (or pass on stdin)")
    key_set_p.set_defaults(func=cmd_key_set)

    key_clear_p = key_sub.add_parser("clear", help="remove stored API key")
    key_clear_p.set_defaults(func=cmd_key_clear)

    return parser


def _is_speak_shorthand(argv: list[str]) -> bool:
    if not argv:
        return False
    if argv[0] in {"speak", "devices", "key", "-h", "--help"}:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    parser = build_parser()

    if _is_speak_shorthand(argv):
        argv = ["speak", *argv]

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    if args.command == "speak" and not args.text:
        if not sys.stdin.isatty():
            args.text = []
        else:
            parser.parse_args(["speak", "-h"])
            return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
