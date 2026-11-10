"""Configuration diagnostics that never print credentials or upstream bodies."""

import json
import os
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__


async def diagnose(check_connection: bool = False) -> dict:
    checks = []

    def add(name, ok, hint=""):
        checks.append({"name": name, "ok": ok, "hint": hint})

    try:
        url = urlsplit(
            os.environ.get("APPFLOWY_BASE_URL", "https://beta.appflowy.cloud")
        )
        valid_url = (
            url.scheme in {"http", "https"}
            and bool(url.hostname)
            and not url.username
            and not url.password
            and not url.query
            and not url.fragment
            and url.path in {"", "/"}
            and (url.port is None or 1 <= url.port <= 65535)
        )
    except ValueError:
        valid_url = False
    add(
        "base_url",
        bool(valid_url),
        "APPFLOWY_BASE_URL must be an http(s) origin without credentials",
    )
    if os.environ.get("APPFLOWY_PUBLIC_URL") is not None:
        from . import api

        try:
            api.public_file_origin()
            public_origin_valid = True
        except ValueError:
            public_origin_valid = False
        add(
            "public_file_origin",
            public_origin_valid,
            "APPFLOWY_PUBLIC_URL must be an http(s) origin without credentials",
        )
    credentials = bool(os.environ.get("APPFLOWY_ACCESS_TOKEN")) or bool(
        os.environ.get("APPFLOWY_EMAIL") and os.environ.get("APPFLOWY_PASSWORD")
    )
    add(
        "credentials_present",
        credentials,
        "Set APPFLOWY_ACCESS_TOKEN or APPFLOWY_EMAIL and APPFLOWY_PASSWORD",
    )
    add(
        "tool_profile",
        os.environ.get("APPFLOWY_TOOL_PROFILE", "compact") in {"compact", "legacy"},
        "Choose compact or legacy",
    )
    add(
        "pycrdt",
        version("pycrdt") == "0.13.0",
        "Use the tested pycrdt pin until the snapshot matrix validates an upgrade",
    )
    guide = files("appflowy_mcp").joinpath("KNOWLEDGE.md")
    if guide.is_file():
        add("agent_guide", True)
    else:
        add(
            "agent_guide",
            (Path(__file__).resolve().parent.parent / "KNOWLEDGE.md").is_file(),
        )
    connection_checked = False
    if check_connection and all(item["ok"] for item in checks):
        connection_checked = True
        from . import server

        try:
            workspaces = await server.get_workspaces()
            add(
                "workspace_access",
                bool(workspaces),
                f"{len(workspaces)} permitted workspace(s)"
                if workspaces
                else "No permitted workspaces; check membership and ALLOWED_WORKSPACE_IDS",
            )
        except (ValueError, RuntimeError) as exc:
            add(
                "workspace_access",
                False,
                f"{type(exc).__name__}: check credentials, account initialization, base URL and workspace allow-list",
            )
        finally:
            await server._close_async_client()
    return {
        "ok": all(item["ok"] for item in checks),
        "version": __version__,
        "connection_checked": connection_checked,
        "checks": checks,
    }


def report(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        for item in result["checks"]:
            print(f"{'OK' if item['ok'] else 'FAIL'} {item['name']}: {item['hint']}")
