"""Measure real serialized manifests. This does not claim LLM selection accuracy."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path


async def measure(profile: str) -> dict:
    os.environ["APPFLOWY_TOOL_PROFILE"] = "legacy" if profile == "legacy" else "compact"
    os.environ["APPFLOWY_ENABLE_AI"] = "true" if profile == "compact_ai" else "false"
    os.environ["APPFLOWY_READ_ONLY"] = "true" if profile == "read_only" else "false"
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from appflowy_mcp.server import mcp

    tools = await mcp.list_tools()
    manifest = [
        tool.model_dump(mode="json", exclude_none=True, by_alias=True) for tool in tools
    ]
    return {
        "profile": profile,
        "tool_count": len(tools),
        "schema_bytes": len(json.dumps(manifest, ensure_ascii=False).encode()),
        "instructions_bytes": len((mcp.instructions or "").encode()),
        "async_tools": sum(
            mcp._tool_manager.get_tool(tool.name).is_async for tool in tools
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", choices=("legacy", "compact", "compact_ai", "read_only")
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.profile:
        print(json.dumps(asyncio.run(measure(args.profile))))
        return
    root = Path(__file__).resolve().parent.parent
    baseline = json.loads((root / "benchmarks/baseline.json").read_text())
    profiles = [
        json.loads(
            subprocess.check_output(
                [sys.executable, str(Path(__file__).resolve()), "--profile", profile],
                text=True,
            )
        )
        for profile in ("legacy", "compact", "compact_ai", "read_only")
    ]
    for item in profiles:
        item["schema_reduction_vs_v1_percent"] = round(
            (1 - item["schema_bytes"] / baseline["schema_bytes"]) * 100, 1
        )
    result = {
        "baseline": baseline,
        "profiles": profiles,
        "measurement": "UTF-8 bytes of serialized tool definitions; excludes client-specific lazy loading and tokenization",
        "llm_selection_accuracy_measured": False,
    }
    output = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(output)
    print(output)


if __name__ == "__main__":
    main()
