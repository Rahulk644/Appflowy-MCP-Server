"""Configuration diagnostics that never print credentials or upstream bodies."""

import json
import os
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit


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
        )
    except ValueError:
        valid_url = False
    add(
        "base_url",
        bool(valid_url),
        "APPFLOWY_BASE_URL must be an http(s) origin without credentials",
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
    if check_connection and credentials and valid_url:
        from . import server

        try:
            workspaces = await server.get_workspaces()
            add("workspace_access", True, f"{len(workspaces)} permitted workspace(s)")
        except (ValueError, RuntimeError) as exc:
            add(
                "workspace_access",
                False,
                f"{type(exc).__name__}: check credentials, account initialization, base URL and workspace allow-list",
            )
        finally:
            await server._close_async_client()
    try:
        package_version = version("appflowy-mcp-server")
    except PackageNotFoundError:
        package_version = "development"
    return {
        "ok": all(item["ok"] for item in checks),
        "version": package_version,
        "connection_checked": check_connection and credentials and valid_url,
        "checks": checks,
    }


def report(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        for item in result["checks"]:
            print(f"{'OK' if item['ok'] else 'FAIL'} {item['name']}: {item['hint']}")
