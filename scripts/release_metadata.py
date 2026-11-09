"""Stamp/check MCP Registry metadata from the canonical package version."""

import argparse
import ast
import json
import re
from pathlib import Path

IMAGE = "ghcr.io/rahulk644/appflowy-mcp-server"


def package_version(root: Path) -> str:
    tree = ast.parse((root / "appflowy_mcp/__init__.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and re.fullmatch(
                r"[0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9.-]*", value
            ):
                return value
            break
    raise ValueError("Declare a literal release version in appflowy_mcp/__init__.py")


def check_registry(registry: dict, version: str, tag: str | None = None) -> None:
    if tag is not None and tag != "v" + version:
        raise ValueError(
            "Release tag must be v followed by the canonical package version"
        )
    if registry["version"] != version:
        raise ValueError(
            "server.json version is stale; run scripts/release_metadata.py --write"
        )
    packages = registry["packages"]
    if (
        len(packages) != 1
        or packages[0]["registryType"] != "oci"
        or packages[0]["identifier"] != f"{IMAGE}:{version}"
    ):
        raise ValueError("server.json must identify the matching versioned GHCR image")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Stamp generated registry version/image fields",
    )
    parser.add_argument("--tag", help="Also validate the release tag")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    version = package_version(root)
    path = root / "server.json"
    registry = json.loads(path.read_text())
    if args.write:
        registry["version"] = version
        registry["packages"][0]["identifier"] = f"{IMAGE}:{version}"
    check_registry(registry, version, args.tag)
    if args.write:
        path.write_text(json.dumps(registry, indent=2) + "\n")
    print(version)


if __name__ == "__main__":
    main()
