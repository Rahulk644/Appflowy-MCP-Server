"""Install the built wheel into a clean venv and test it outside the checkout."""

import subprocess
import tempfile
import venv
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    wheels = list((root / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit("Build exactly one wheel into dist/ before checking it")
    with tempfile.TemporaryDirectory(prefix="appflowy-package-") as temporary:
        directory = Path(temporary)
        builder = venv.EnvBuilder(with_pip=True)
        builder.create(directory / "venv")
        context = builder.ensure_directories(directory / "venv")
        python = context.env_exe
        subprocess.run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--quiet",
                "--no-cache-dir",
                "--disable-pip-version-check",
                str(wheels[0]),
            ],
            cwd=directory,
            check=True,
        )
        subprocess.run(
            [python, "-m", "appflowy_mcp", "--version"], cwd=directory, check=True
        )
        subprocess.run(
            [python, str(root / "scripts" / "smoke_mcp.py")],
            cwd=directory,
            check=True,
        )
        subprocess.run(
            [
                python,
                str(root / "scripts" / "smoke_mcp.py"),
                "--transport",
                "streamable-http",
            ],
            cwd=directory,
            check=True,
        )


if __name__ == "__main__":
    main()
