"""Measure bounded workflows with synthetic workspaces, without network access."""

import argparse
import asyncio
import json
import os
import platform
import sys
import time
import tracemalloc
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

import httpx
from pycrdt import Array, Doc, Map, Text

sys.path.insert(
    0,
    os.environ.get(
        "APPFLOWY_BENCHMARK_ROOT", str(Path(__file__).resolve().parent.parent)
    ),
)
from appflowy_mcp import api as a
from appflowy_mcp import collab as c
from appflowy_mcp import documents as d
from appflowy_mcp import models as m
from appflowy_mcp import server as b
from appflowy_mcp import workflows as w


async def measure(name, operation, metrics):
    tracemalloc.start()
    started = time.perf_counter()
    result = await operation()
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "case": name,
        **metrics,
        "elapsed_ms_with_tracemalloc": round(elapsed * 1000, 2),
        "peak_python_allocation_bytes": peak,
        "result_chars": len(json.dumps(result, ensure_ascii=False)),
        "returned_items": len(result.get("items", result.get("entries", []))),
        "generic_preview": "preview" in result,
        "has_more": result.get("has_more"),
        "next_offset": result.get("next_offset"),
    }


async def rows_case(count, cell_chars):
    metrics = {
        "workspace_rows": count,
        "cell_chars": cell_chars,
        "requests": 0,
        "simulated_http_bytes": 0,
    }

    async def request(method, path, **kwargs):
        if path.endswith("/row"):
            data = [{"id": f"row-{i}"} for i in range(count)]
        elif path.endswith("/row/detail"):
            data = [
                {"row_id": item, "cells": {"Name": item, "Notes": "x" * cell_chars}}
                for item in kwargs["params"]["ids"].split(",")
            ]
        else:
            raise AssertionError(path)
        response = httpx.Response(200, json={"code": 0, "data": data})
        metrics["requests"] += 1
        metrics["simulated_http_bytes"] += len(response.content)
        return response

    async def run():
        return await w.appflowy_rows(
            m.RowsInput(
                workspace_id="benchmark", database_id="db", command="list", limit=50
            )
        )

    with patch.object(a, "_api_call_async", request):
        return await measure("row_list", run, metrics)


async def export_case(children, markdown_chars, unrelated=1000):
    folder = {
        "view_id": "root",
        "name": "Root",
        "children": [
            {"view_id": f"page-{i}", "name": f"Page {i}"} for i in range(children)
        ],
    }
    workspace = {
        "view_id": "benchmark",
        "children": [folder]
        + [
            {"view_id": f"unrelated-{i}", "name": f"Unrelated {i}"}
            for i in range(unrelated)
        ],
    }
    metrics = {
        "child_pages": children,
        "markdown_chars_per_page": markdown_chars,
        "folder_reads": 0,
        "document_reads": 0,
        "fixture_text_bytes_fetched": 0,
        "unrelated_workspace_pages": unrelated,
        "fixture_folder_json_bytes": 0,
    }

    async def get_folder(*args, **kwargs):
        metrics["folder_reads"] += 1
        response = httpx.Response(200, json={"data": workspace})
        metrics["fixture_folder_json_bytes"] += len(response.content)
        return response.json()["data"]

    async def get_subtree(method, path, **kwargs):
        assert (method, path) == ("GET", "/api/workspace/benchmark/view/root")
        metrics["folder_reads"] += 1
        response = httpx.Response(200, json={"data": folder})
        metrics["fixture_folder_json_bytes"] += len(response.content)
        return response

    async def get_markdown(*args):
        metrics["document_reads"] += 1
        metrics["fixture_text_bytes_fetched"] += markdown_chars
        return "x" * markdown_chars

    async def run():
        return await w.appflowy_export(
            m.ExportInput(workspace_id="benchmark", view_id="root", depth=1, limit=50)
        )

    with (
        patch.object(b, "get_workspace_folder_async", get_folder),
        patch.object(a, "_api_call", get_subtree),
        patch.object(b, "get_page_markdown_async", get_markdown),
    ):
        return await measure("markdown_export", run, metrics)


async def snapshot_case(block_count):
    doc = Doc()
    root = doc.get("data", type=Map)
    with doc.transaction():
        root["document"] = Map(
            {
                "page_id": "page",
                "blocks": Map(
                    {"page": Map({"ty": "page", "children": "pc", "data": "{}"})}
                ),
                "meta": Map(
                    {"children_map": Map({"pc": Array([])}), "text_map": Map()}
                ),
            }
        )
        document = root["document"]
        blocks, meta = document["blocks"], document["meta"]
        for i in range(block_count):
            bid, child_id, text_id = f"b{i}", f"c{i}", f"t{i}"
            blocks[bid] = Map(
                {
                    "ty": "paragraph",
                    "children": child_id,
                    "external_id": text_id,
                    "parent": "page",
                    "data": "{}",
                }
            )
            meta["children_map"]["pc"].append(bid)
            meta["children_map"][child_id] = Array([])
            meta["text_map"][text_id] = Text("x" * 200)
    snapshot = doc.get_update()
    metrics = {"blocks": block_count, "snapshot_bytes": len(snapshot)}

    async def run():
        decoded = c._decode_collab(snapshot, 0)
        markdown = d._doc_to_markdown(decoded.get("data", type=Map)["document"])
        return {"markdown_chars": len(markdown)}

    return await measure("snapshot_decode_render", run, metrics)


async def benchmark():
    with patch.dict(
        os.environ,
        {"ALLOWED_WORKSPACE_IDS": "benchmark", "APPFLOWY_READ_ONLY": "false"},
    ):
        cases = [
            await rows_case(count, size)
            for count, size in ((10, 100), (1000, 100), (10000, 100), (1000, 2000))
        ]
        cases += [await export_case(1000, size) for size in (500, 2500, 100000)]
        cases += [await export_case(10, 500, unrelated=10000)]
        cases += [await snapshot_case(count) for count in (100, 1000, 5000)]
    return {
        "schema": "appflowy-mcp.workspace-benchmark.v1",
        "environment": {
            "python": platform.python_version(),
            "pycrdt": version("pycrdt"),
        },
        "method": "Synthetic fixtures; direct workflow calls; no real network latency. Fixture construction excluded. Python allocation tracking excludes native Rust allocations.",
        "cases": cases,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(benchmark())
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    for case in result["cases"]:
        print(json.dumps(case))


if __name__ == "__main__":
    main()
