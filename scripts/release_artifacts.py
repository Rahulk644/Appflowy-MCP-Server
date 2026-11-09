"""Publish gated distribution assets and inspect immutable GHCR version tags."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def image_exists(identifier: str) -> bool:
    match = re.fullmatch(
        r"ghcr\.io/([a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)+):([A-Za-z0-9_][A-Za-z0-9_.-]{0,127})",
        identifier,
    )
    if not match:
        raise ValueError("Expected a versioned ghcr.io repository image")
    repository, tag = match.groups()
    query = urllib.parse.urlencode(
        {"service": "ghcr.io", "scope": f"repository:{repository}:pull"}
    )
    with urllib.request.urlopen(
        "https://ghcr.io/token?" + query, timeout=30
    ) as response:
        token = json.load(response)["token"]
    request = urllib.request.Request(
        f"https://ghcr.io/v2/{repository}/manifests/{tag}",
        method="HEAD",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError("Unexpected GHCR manifest response")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise
    return True


def sha256_file(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def asset_digest(asset: dict) -> str:
    digest = asset.get("digest") or ""
    if digest.startswith("sha256:"):
        return digest.removeprefix("sha256:")
    # Public release assets from older uploads may not include a server digest.
    # No Authorization header is sent through GitHub's download redirect.
    digest = hashlib.sha256()
    with urllib.request.urlopen(asset["browser_download_url"], timeout=30) as response:
        for chunk in iter(lambda: response.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def attach_assets(directory: Path, repository: str, tag: str, version: str) -> None:
    if tag != "v" + version:
        raise ValueError("Asset release tag does not match the validated version")
    wheels = list(directory.glob("*.whl"))
    sources = list(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("Expected exactly one gated wheel and source distribution")
    files = wheels + sources
    if (
        not wheels[0].name.startswith(f"appflowy_mcp_server-{version}-")
        or sources[0].name != f"appflowy_mcp_server-{version}.tar.gz"
    ):
        raise ValueError("Distribution filenames do not match the release version")
    release = json.loads(
        subprocess.check_output(
            [
                "gh",
                "api",
                f"repos/{repository}/releases/tags/{urllib.parse.quote(tag, safe='')}",
            ],
            text=True,
        )
    )
    existing = {asset["name"]: asset for asset in release["assets"]}
    uploads = []
    # Check every conflict before making any change to the release.
    for file in files:
        asset = existing.get(file.name)
        if asset is None:
            uploads.append(file)
        elif asset_digest(asset) != sha256_file(file):
            raise ValueError(
                f"Refusing to replace different published asset: {file.name}"
            )
        else:
            print(f"Verified existing asset: {file.name}")
    for file in uploads:
        subprocess.run(
            ["gh", "release", "upload", tag, str(file), "--repo", repository],
            check=True,
        )
        print(f"Attached: {file.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("image", "assets"))
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    registry = json.loads((root / "server.json").read_text())
    if args.command == "image":
        identifier = registry["packages"][0]["identifier"]
        exists = image_exists(identifier)
        print(f"Versioned image exists: {str(exists).lower()}")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as output:
                output.write(f"image={identifier}\nexists={str(exists).lower()}\n")
    else:
        attach_assets(
            args.dist,
            os.environ["GH_REPO"],
            os.environ["RELEASE_TAG"],
            registry["version"],
        )


if __name__ == "__main__":
    main()
