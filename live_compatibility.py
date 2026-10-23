"""Opt-in AppFlowy live compatibility validation harness.

This module intentionally does not register MCP tools. It is a developer/operator
runner for validating the currently configured AppFlowy deployment and producing a
sanitized report for the v2 compatibility gate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import server

LIVE_VALIDATED = "live_validated"
CURRENT_WEB_OBSERVED = "current_web_observed"
HISTORICAL_CANDIDATE = "historical_candidate"
FAILED = "failed"
SKIPPED = "skipped"

CI_ENV_MARKERS = (
    "CI",
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "BUILDKITE",
    "CIRCLECI",
    "TRAVIS",
    "APPVEYOR",
    "TF_BUILD",
    "JENKINS_URL",
    "TEAMCITY_VERSION",
)


@dataclass(frozen=True)
class CompatibilityConfig:
    deployment_type: str
    version: str
    build: str
    workspace_id: str
    database_id: str
    document_id: str
    parent_view_id: str
    row_field_id: str = ""
    run_reversible: bool = False
    validate_token_refresh: bool = False

    @classmethod
    def from_env(
        cls,
        *,
        run_reversible: bool = False,
        validate_token_refresh: bool = False,
    ) -> CompatibilityConfig:
        return cls(
            deployment_type=os.environ.get(
                "APPFLOWY_COMPAT_DEPLOYMENT_TYPE", "unspecified"
            ),
            version=os.environ.get("APPFLOWY_COMPAT_VERSION", "unspecified"),
            build=os.environ.get("APPFLOWY_COMPAT_BUILD", "unspecified"),
            workspace_id=os.environ.get("APPFLOWY_COMPAT_WORKSPACE_ID", ""),
            database_id=os.environ.get("APPFLOWY_COMPAT_DATABASE_ID", ""),
            row_field_id=os.environ.get("APPFLOWY_COMPAT_ROW_FIELD_ID", ""),
            document_id=os.environ.get("APPFLOWY_COMPAT_DOCUMENT_ID", ""),
            parent_view_id=os.environ.get("APPFLOWY_COMPAT_PARENT_VIEW_ID", ""),
            run_reversible=run_reversible,
            validate_token_refresh=validate_token_refresh,
        )


class CompatibilityRecorder:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    async def record(
        self,
        *,
        name: str,
        operation,
        evidence_basis: str = CURRENT_WEB_OBSERVED,
        route: str = "",
        method: str = "GET",
        destructive: bool = False,
        reversible: bool = False,
    ) -> Any:
        started = time.perf_counter()
        try:
            value = await operation()
        except Exception as exc:  # noqa: BLE001 - report any live route failure.
            self.checks.append(
                {
                    "name": name,
                    "classification": FAILED,
                    "evidence_basis": evidence_basis,
                    "ok": False,
                    "method": method,
                    "route": route,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "destructive": destructive,
                    "reversible": reversible,
                    "error": _sanitize_error(exc),
                }
            )
            return None

        self.checks.append(
            {
                "name": name,
                "classification": LIVE_VALIDATED,
                "evidence_basis": evidence_basis,
                "ok": True,
                "method": method,
                "route": route,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "destructive": destructive,
                "reversible": reversible,
                "response_shape": _shape(value),
            }
        )
        return value

    def skip(
        self,
        name: str,
        reason: str,
        *,
        evidence_basis: str = HISTORICAL_CANDIDATE,
    ) -> None:
        self.checks.append(
            {
                "name": name,
                "classification": SKIPPED,
                "evidence_basis": evidence_basis,
                "ok": None,
                "skipped": True,
                "reason": reason,
            }
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sanitize_error(exc: Exception) -> dict[str, str]:
    # Reports are meant to be shareable in issues/PRs. Do not copy exception
    # messages because upstream errors can include URLs, credentials, emails,
    # private object names, or raw server response bodies.
    error = {"type": type(exc).__name__}
    status = _extract_http_status(exc)
    if status is not None:
        error["http_status"] = str(status)
    appflowy_code = _extract_appflowy_code(exc)
    if appflowy_code is not None:
        error["appflowy_code"] = str(appflowy_code)
    return error


def _extract_http_status(exc: BaseException) -> int | None:
    current: BaseException | None = exc
    while current is not None:
        response = getattr(current, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
        current = current.__cause__
    match = re.search(r"\bAppFlowy API (\d{3})\b", str(exc))
    return int(match.group(1)) if match else None


def _extract_appflowy_code(exc: BaseException) -> int | None:
    match = re.search(r"\bAppFlowy API code (\d+)\b", str(exc))
    return int(match.group(1)) if match else None


def _shape(value: Any, *, depth: int = 0) -> Any:
    if depth >= 3:
        return type(value).__name__
    if isinstance(value, dict):
        return {
            "type": "object",
            "keys": sorted(str(k) for k in value)[:20],
            "fields": {
                str(k): _shape(v, depth=depth + 1) for k, v in list(value.items())[:10]
            },
        }
    if isinstance(value, list):
        return {
            "type": "array",
            "count": len(value),
            "item": _shape(value[0], depth=depth + 1) if value else None,
        }
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return "number"
    return type(value).__name__


def _extract_workspace_id(workspaces: Any, preferred: str) -> str:
    if preferred:
        return preferred
    if isinstance(workspaces, list) and len(workspaces) == 1:
        workspace = workspaces[0]
        if isinstance(workspace, dict):
            return workspace.get("workspace_id") or workspace.get("id") or ""
    return ""


def _iter_nodes(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_nodes(child)


def _extract_database_id(databases: Any, preferred: str) -> str:
    if preferred:
        return preferred
    for node in _iter_nodes(databases):
        for key in ("database_id", "databaseId", "id"):
            value = node.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _extract_document_id(folder: Any, preferred: str) -> str:
    if preferred:
        return preferred
    for node in _iter_nodes(folder):
        view_id = node.get("view_id") or node.get("id")
        layout = node.get("layout")
        if (
            isinstance(view_id, str)
            and view_id
            and layout in (0, "document")
            and node.get("parent_view_id")
            and not node.get("is_space")
        ):
            return view_id
    return ""


def _extract_row_field_id(fields: Any, preferred: str) -> str:
    """Pick a writable text field for a disposable row-edit check."""
    if preferred:
        return preferred
    candidates = list(_iter_nodes(fields))
    for node in candidates:
        field_id = node.get("id") or node.get("field_id") or node.get("fieldId")
        if isinstance(field_id, str) and field_id and node.get("is_primary") is True:
            return field_id
    for node in candidates:
        field_id = node.get("id") or node.get("field_id") or node.get("fieldId")
        field_type = node.get("field_type", node.get("fieldType", node.get("type")))
        if (
            isinstance(field_id, str)
            and field_id
            and field_type in (0, "0", "rich_text")
        ):
            return field_id
    return ""


async def _api_json(method: str, path: str, **kwargs) -> Any:
    return (await server._api_call_async(method, path, **kwargs)).json().get("data")


async def run_compatibility_checks(config: CompatibilityConfig) -> dict[str, Any]:
    recorder = CompatibilityRecorder()

    workspaces = await recorder.record(
        name="auth_and_workspace_listing",
        method="GET",
        route="/api/workspace",
        operation=lambda: _api_json("GET", "/api/workspace"),
    )
    if config.validate_token_refresh:
        refreshed = await recorder.record(
            name="auth_token_refresh",
            method="POST",
            route="/gotrue/token?grant_type=refresh_token",
            operation=_validate_token_refresh,
        )
        if refreshed is not None:
            await recorder.record(
                name="auth_after_token_refresh",
                method="GET",
                route="/api/workspace",
                operation=lambda: _api_json("GET", "/api/workspace"),
            )
        return _report(config, recorder)
    workspace_id = _extract_workspace_id(workspaces, config.workspace_id)
    if not workspace_id:
        recorder.skip(
            "workspace_dependent_checks",
            "Set APPFLOWY_COMPAT_WORKSPACE_ID when more than one workspace is visible.",
        )
        return _report(config, recorder)

    folder = await recorder.record(
        name="folder_traversal_depth_1",
        method="GET",
        route="/api/workspace/{workspace_id}/folder",
        operation=lambda: server.get_workspace_folder_async(workspace_id, depth=1),
    )

    databases = await recorder.record(
        name="database_discovery",
        method="GET",
        route="/api/workspace/{workspace_id}/database",
        operation=lambda: _api_json("GET", f"/api/workspace/{workspace_id}/database"),
    )
    database_id = _extract_database_id(databases, config.database_id)
    database_fields = None
    if database_id:
        database_fields = await recorder.record(
            name="database_fields",
            method="GET",
            route="/api/workspace/{workspace_id}/database/{database_id}/fields",
            operation=lambda: _api_json(
                "GET", f"/api/workspace/{workspace_id}/database/{database_id}/fields"
            ),
        )
        await recorder.record(
            name="database_row_ids",
            method="GET",
            route="/api/workspace/{workspace_id}/database/{database_id}/row",
            operation=lambda: _api_json(
                "GET", f"/api/workspace/{workspace_id}/database/{database_id}/row"
            ),
        )
    else:
        recorder.skip(
            "representative_database_checks",
            "No database id was provided or discovered.",
        )

    document_id = _extract_document_id(folder, config.document_id)
    if document_id:
        await recorder.record(
            name="page_metadata",
            method="GET",
            route="/api/workspace/{workspace_id}/page-view/{view_id}",
            operation=lambda: _api_json(
                "GET", f"/api/workspace/{workspace_id}/page-view/{document_id}"
            ),
        )
        await recorder.record(
            name="collab_document_markdown_read",
            method="GET",
            route="/api/workspace/v1/{workspace_id}/collab/{object_id}",
            operation=lambda: server.get_page_markdown_async(workspace_id, document_id),
        )
    else:
        recorder.skip(
            "collab_document_checks",
            "Set APPFLOWY_COMPAT_DOCUMENT_ID or provide a folder with a document page.",
        )

    if config.run_reversible:
        await _run_reversible_checks(
            recorder,
            config,
            workspace_id,
            database_id=database_id,
            database_fields=database_fields,
        )
    else:
        recorder.skip(
            "reversible_create_read_trash",
            "Pass --run-reversible and APPFLOWY_COMPAT_PARENT_VIEW_ID to enable.",
        )

    return _report(config, recorder)


async def _validate_token_refresh() -> dict[str, bool]:
    """Exercise GoTrue refresh without exposing either token to the report."""
    if not server._refresh_token:
        raise RuntimeError("Initial login did not provide a refresh token")

    previous_access_token = server._access_token
    refresh_succeeded = await server._refresh_async()
    if not refresh_succeeded:
        raise RuntimeError("Refresh was rejected and fell back to password login")
    if not server._access_token:
        raise RuntimeError("Refresh did not provide an access token")

    return {
        "refresh_succeeded": True,
        "access_token_rotated": server._access_token != previous_access_token,
        "refresh_token_present": bool(server._refresh_token),
    }


async def _run_reversible_checks(
    recorder: CompatibilityRecorder,
    config: CompatibilityConfig,
    workspace_id: str,
    *,
    database_id: str,
    database_fields: Any,
) -> None:
    if not config.parent_view_id:
        recorder.skip(
            "reversible_create_read_trash",
            "APPFLOWY_COMPAT_PARENT_VIEW_ID is required for reversible checks.",
        )
        return

    marker = uuid.uuid4().hex[:12]
    page_name = f"compatibility-smoke-{marker[:8]}"
    initial_text = f"compatibility-before-{marker}"
    updated_text = f"compatibility-after-{marker}"
    body = {
        "parent_view_id": config.parent_view_id,
        "layout": 0,
        "name": page_name,
        "page_data": {
            "type": "page",
            "children": [
                {
                    "type": "paragraph",
                    "data": {"delta": [{"insert": initial_text}]},
                }
            ],
        },
    }

    created = await recorder.record(
        name="reversible_page_create",
        method="POST",
        route="/api/workspace/{workspace_id}/page-view",
        reversible=True,
        operation=lambda: _api_json(
            "POST", f"/api/workspace/{workspace_id}/page-view", json=body
        ),
    )
    view_id = created.get("view_id") if isinstance(created, dict) else created
    if not isinstance(view_id, str) or not view_id:
        recorder.skip(
            "reversible_page_read_trash",
            "Create did not return a view id; refusing follow-up write checks.",
        )
        return

    await recorder.record(
        name="reversible_page_read",
        method="GET",
        route="/api/workspace/{workspace_id}/page-view/{view_id}",
        reversible=True,
        operation=lambda: _api_json(
            "GET", f"/api/workspace/{workspace_id}/page-view/{view_id}"
        ),
    )
    await recorder.record(
        name="reversible_collab_document_edit",
        method="POST",
        route=server._COLLAB_WEB_UPDATE_ROUTE,
        reversible=True,
        operation=lambda: asyncio.to_thread(
            server.replace_text,
            workspace_id,
            view_id,
            initial_text,
            updated_text,
        ),
    )
    await recorder.record(
        name="reversible_collab_document_verify",
        method="GET",
        route="/api/workspace/v1/{workspace_id}/collab/{object_id}",
        reversible=True,
        operation=lambda: _verify_document_text(workspace_id, view_id, updated_text),
    )
    await recorder.record(
        name="reversible_page_trash",
        method="POST",
        route="/api/workspace/{workspace_id}/page-view/{view_id}/move-to-trash",
        destructive=True,
        reversible=True,
        operation=lambda: _api_json(
            "POST",
            f"/api/workspace/{workspace_id}/page-view/{view_id}/move-to-trash",
            json={},
        ),
    )

    await _run_reversible_row_check(
        recorder,
        config,
        workspace_id,
        database_id=database_id,
        database_fields=database_fields,
        marker=marker,
    )


async def _verify_document_text(
    workspace_id: str, view_id: str, expected: str
) -> dict[str, bool]:
    markdown = await server.get_page_markdown_async(workspace_id, view_id)
    if expected not in markdown:
        raise RuntimeError("Collab document edit was not visible on read-back")
    return {"verified": True}


async def _run_reversible_row_check(
    recorder: CompatibilityRecorder,
    config: CompatibilityConfig,
    workspace_id: str,
    *,
    database_id: str,
    database_fields: Any,
    marker: str,
) -> None:
    if not database_id:
        recorder.skip(
            "reversible_database_row_edit",
            "Set APPFLOWY_COMPAT_DATABASE_ID to enable the disposable row check.",
        )
        return
    field_id = _extract_row_field_id(database_fields, config.row_field_id)
    if not field_id:
        recorder.skip(
            "reversible_database_row_edit",
            "Set APPFLOWY_COMPAT_ROW_FIELD_ID to a writable text field.",
        )
        return

    initial_value = f"compatibility-row-before-{marker}"
    updated_value = f"compatibility-row-after-{marker}"
    row = await recorder.record(
        name="reversible_database_row_create",
        method="POST",
        route="/api/workspace/{workspace_id}/database/{database_id}/row",
        reversible=True,
        operation=lambda: _api_json(
            "POST",
            f"/api/workspace/{workspace_id}/database/{database_id}/row",
            json={"cells": {field_id: initial_value}},
        ),
    )
    row_id = _extract_created_id(row)
    if not row_id:
        recorder.skip(
            "reversible_database_row_update_delete",
            "Create did not return a row id; refusing follow-up collab checks.",
        )
        return

    await recorder.record(
        name="reversible_database_row_collab_edit",
        method="POST",
        route=server._COLLAB_WEB_UPDATE_ROUTE,
        reversible=True,
        operation=lambda: asyncio.to_thread(
            server.update_row_cells,
            workspace_id,
            database_id,
            row_id,
            json.dumps({field_id: updated_value}),
        ),
    )
    await recorder.record(
        name="reversible_database_row_delete",
        method="DELETE",
        route="/api/workspace/{workspace_id}/collab/{object_id}",
        destructive=True,
        reversible=True,
        operation=lambda: asyncio.to_thread(
            server._delete_row_strict, workspace_id, database_id, row_id
        ),
    )


def _extract_created_id(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("row_id", "rowId", "id"):
            item = value.get(key)
            if isinstance(item, str) and item:
                return item
    return ""


def _report(
    config: CompatibilityConfig, recorder: CompatibilityRecorder
) -> dict[str, Any]:
    return {
        "schema": "appflowy-mcp.live-compatibility-report.v1",
        "generated_at": _utc_now(),
        "deployment": {
            "type": config.deployment_type,
            "version": config.version,
            "build": config.build,
        },
        "base_url": _public_base_url(),
        "modes": {
            "read_only_default": True,
            "reversible_checks_enabled": config.run_reversible,
            "token_refresh_validation_enabled": config.validate_token_refresh,
            "live_credentials_in_ci": False,
        },
        "checks": recorder.checks,
        "summary": _summary(recorder.checks),
    }


def _public_base_url() -> str:
    # Keep host-level context without leaking paths, query strings, credentials, or
    # tokens that may appear in custom test URLs.
    parsed = urlsplit(server.BASE_URL)
    if not parsed.scheme or not parsed.hostname:
        return "unspecified"
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme.lower(), host, "", "", ""))


def _summary(checks: list[dict[str, Any]]) -> dict[str, int]:
    passed = sum(1 for check in checks if check.get("ok") is True)
    failed = sum(1 for check in checks if check.get("ok") is False)
    skipped = sum(1 for check in checks if check.get("skipped"))
    return {"passed": passed, "failed": failed, "skipped": skipped}


def _refuse_ci_without_explicit_opt_in() -> None:
    if any(_truthy_env(marker) for marker in CI_ENV_MARKERS):
        raise SystemExit(
            "Refusing to run live AppFlowy compatibility checks in CI. "
            "Run this harness only from an operator-controlled environment with "
            "explicitly provisioned live credentials."
        )


def _truthy_env(name: str) -> bool:
    value = os.environ.get(name)
    if value is None:
        return False
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


async def _main_async(args: argparse.Namespace) -> int:
    _refuse_ci_without_explicit_opt_in()
    config = CompatibilityConfig.from_env(
        run_reversible=args.run_reversible,
        validate_token_refresh=args.validate_token_refresh,
    )
    report = await run_compatibility_checks(config)
    output = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    return 1 if report["summary"]["failed"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run opt-in live AppFlowy compatibility checks."
    )
    parser.add_argument(
        "--run-reversible",
        action="store_true",
        help=(
            "Enable disposable page create/read/collab-edit/trash checks and, "
            "when configured, database row create/collab-edit/delete checks. "
            "Requires APPFLOWY_COMPAT_PARENT_VIEW_ID."
        ),
    )
    parser.add_argument(
        "--validate-token-refresh",
        action="store_true",
        help=(
            "Exercise the GoTrue refresh-token flow and verify a subsequent "
            "authenticated request (disabled by default)."
        ),
    )
    parser.add_argument(
        "--output", help="Write the sanitized JSON report to this path."
    )
    args = parser.parse_args(argv)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
