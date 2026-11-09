"""Exercise an installed command or container without AppFlowy credentials.

Run outside the checkout using the installed wheel's Python interpreter. This
checks the JSON-RPC channel and bundled resources, rather than importing source.
"""

import argparse
import asyncio
import os
import socket
import subprocess
import sysconfig
from contextlib import contextmanager
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client


def fixture_environment() -> dict[str, str]:
    return {
        "APPFLOWY_BASE_URL": "http://127.0.0.1:1",
        "MCP_SECRET_TOKEN": "packaging-smoke-token",
        "MCP_ALLOWED_HOSTS": "127.0.0.1:*",
        "ALLOWED_WORKSPACE_IDS": "packaging-smoke-workspace",
        # Enable the optional provider to prove that its module is bundled too.
        "GOOGLE_CLIENT_ID": "packaging-smoke-client",
        "GOOGLE_CLIENT_SECRET": "packaging-smoke-secret",
        "OAUTH_ISSUER": "http://localhost:8000",
        "ALLOWED_EMAILS": "smoke@example.com",
    }


def installed_command() -> str:
    suffix = ".exe" if os.name == "nt" else ""
    return str(Path(sysconfig.get_path("scripts")) / f"appflowy-mcp{suffix}")


def docker_command(environment: dict[str, str]) -> list[str]:
    args = ["docker", "run", "--rm"]
    for key, value in environment.items():
        args.extend(["-e", f"{key}={value}"])
    return args


async def check_session(read, write) -> None:
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        assert any(tool.name == "get_workspaces" for tool in tools.tools)
        guide = await session.read_resource("appflowy://guide")
        assert any(
            "AppFlowy Agent Guide" in getattr(part, "text", "")
            for part in guide.contents
        )
        print(f"Installed MCP smoke passed: {len(tools.tools)} tools and guide")


async def smoke_stdio(docker_image: str | None) -> None:
    fixture_env = fixture_environment()
    if docker_image:
        command, *args = docker_command(fixture_env)
        args.extend(["-i", docker_image, "appflowy-mcp"])
    else:
        command = installed_command()
        args = []
    params = StdioServerParameters(command=command, args=args, env=fixture_env)
    async with stdio_client(params) as (read, write):
        await check_session(read, write)


@contextmanager
def http_server(docker_image: str | None):
    fixture_env = fixture_environment()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = None
    container = None
    try:
        if docker_image:
            args = docker_command(fixture_env)
            args.extend(["-d", "-p", f"127.0.0.1:{port}:8000", docker_image])
            container = subprocess.check_output(args, text=True, timeout=30).strip()
        else:
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith(
                    ("APPFLOWY_", "MCP_", "GOOGLE_", "OAUTH_", "ALLOWED_")
                )
            }
            environment.update(fixture_env)
            process = subprocess.Popen(
                [
                    installed_command(),
                    "--transport",
                    "streamable-http",
                    "--port",
                    str(port),
                ],
                env=environment,
            )
        yield f"http://127.0.0.1:{port}"
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        if container:
            subprocess.run(["docker", "rm", "-f", container], check=True, timeout=15)


async def smoke_http(docker_image: str | None) -> None:
    with http_server(docker_image) as url:
        async with httpx.AsyncClient() as client:
            for _ in range(100):
                try:
                    response = await client.get(f"{url}/robots.txt", timeout=1)
                    if response.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("Installed HTTP server did not become ready")
            assert (await client.get(f"{url}/mcp/")).status_code == 401
            metadata = await client.get(f"{url}/.well-known/oauth-authorization-server")
            assert metadata.status_code == 200
        async with streamablehttp_client(
            f"{url}/mcp/",
            headers={"Authorization": "Bearer packaging-smoke-token"},
        ) as (read, write, _):
            await check_session(read, write)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-image")
    parser.add_argument(
        "--transport", choices=("stdio", "streamable-http"), default="stdio"
    )
    arguments = parser.parse_args()
    operation = smoke_stdio if arguments.transport == "stdio" else smoke_http
    asyncio.run(asyncio.wait_for(operation(arguments.docker_image), timeout=60))
