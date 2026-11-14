"""Start, test and remove the disposable, pinned first-party AppFlowy stack."""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

UPSTREAM_COMMIT = "e39869a2bae964e951832e577407e35a548b48c8"
CLOUD_VERSION = "0.21.4"
WEB_VERSION = "0.20.12"
SERVICES = (
    "postgres",
    "redis",
    "minio",
    "gotrue",
    "appflowy_search",
    "appflowy_cloud",
    "appflowy_worker",
    "appflowy_web",
    "mcp_proxy",
)


def run(*args, **kwargs):
    subprocess.run(list(args), check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("up", "test", "down"))
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(tempfile.gettempdir()) / "appflowy-mcp-selfhost",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    directory = args.directory.resolve()
    checkout = directory / "upstream"
    if args.command != "down" and not (checkout / ".git").is_dir():
        directory.mkdir(parents=True, exist_ok=True)
        run("git", "init", str(checkout))
        run(
            "git",
            "-C",
            str(checkout),
            "remote",
            "add",
            "origin",
            "https://github.com/AppFlowy-IO/AppFlowy-SelfHost-Commercial.git",
        )
        run(
            "git",
            "-C",
            str(checkout),
            "fetch",
            "--depth",
            "1",
            "origin",
            UPSTREAM_COMMIT,
        )
        run("git", "-C", str(checkout), "checkout", "--detach", "FETCH_HEAD")
    if args.command != "down":
        actual = subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
        ).strip()
        if actual != UPSTREAM_COMMIT:
            raise SystemExit(
                "Disposable stack checkout does not match the pinned commit"
            )
        source = (checkout / "deploy.env").read_text()
        source += "\nSCHEME=http\nFQDN=127.0.0.1:18080\nAPPFLOWY_BASE_URL=http://127.0.0.1:18080\nAPPFLOWY_WEB_URL=http://127.0.0.1:18080\nAPI_EXTERNAL_URL=http://127.0.0.1:18080/gotrue\nGOTRUE_MAILER_AUTOCONFIRM=true\nGOTRUE_ADMIN_EMAIL=system-admin@example.com\nGOTRUE_ADMIN_PASSWORD=Disposable-test-2026!\nAI_ENABLED=false\n"
        source += f"APPFLOWY_MCP_PROXY_CONFIG={root / 'tests/selfhost/proxy.conf'}\nAPPFLOWY_WEBSOCKET_BASE_URL=ws://127.0.0.1:18080/ws/v2\n"
        (directory / ".env").write_text(source)
        (directory / ".env").chmod(0o600)
    compose = [
        "docker",
        "compose",
        "-p",
        "appflowy-mcp-compat",
        "--env-file",
        str(directory / ".env"),
        "-f",
        str(checkout / "docker-compose.yml"),
        "-f",
        str(root / "tests/selfhost/override.yaml"),
    ]
    if args.command == "up":
        run(*compose, "up", "-d", "--wait", "--wait-timeout", "240", *SERVICES)
    elif args.command == "down":
        # Only this test project's containers and named volumes are removed.
        run(*compose, "down", "--volumes", "--remove-orphans")
    else:
        environment = os.environ.copy()
        environment["APPFLOWY_SELFHOST_TEST"] = "true"
        environment.setdefault(
            "APPFLOWY_INTEGRATION_REPORT", str(directory / "integration.json")
        )
        run(
            sys.executable,
            "-m",
            "pytest",
            "tests/selfhost",
            "-q",
            cwd=root,
            env=environment,
        )


if __name__ == "__main__":
    main()
