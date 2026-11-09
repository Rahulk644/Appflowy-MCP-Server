"""Command-line entry point for local and HTTP MCP transports."""

import argparse
import asyncio
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from dotenv import load_dotenv


def main() -> None:
    try:
        package_version = version("appflowy-mcp-server")
    except PackageNotFoundError:
        package_version = "development"

    parser = argparse.ArgumentParser(description="AppFlowy MCP server")
    parser.add_argument("--version", action="version", version=package_version)
    parser.add_argument(
        "--transport", choices=("stdio", "streamable-http"), default="stdio"
    )
    parser.add_argument(
        "--env-file", type=Path, help="Configuration file (default: .env in cwd)"
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address")
    parser.add_argument("--port", type=int, default=8000, help="HTTP bind port")
    parser.add_argument(
        "--forwarded-allow-ips",
        default="127.0.0.1",
        help="Comma-separated trusted proxy IPs (HTTP only)",
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    env_file = args.env_file if args.env_file is not None else Path.cwd() / ".env"
    if args.env_file is not None and not env_file.is_file():
        parser.error("--env-file must name an existing file")
    load_dotenv(env_file, override=False)

    if args.transport == "stdio":
        # Import after loading configuration, and leave stdout for JSON-RPC only.
        from .server import _run_stdio_with_lifecycle

        asyncio.run(_run_stdio_with_lifecycle())
    else:
        import uvicorn

        uvicorn.run(
            "appflowy_mcp.server:app",
            host=args.host,
            port=args.port,
            proxy_headers=True,
            forwarded_allow_ips=args.forwarded_allow_ips,
        )
