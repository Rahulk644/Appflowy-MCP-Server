# Packaging and releases

The Python distribution is `appflowy-mcp-server`; the command is `appflowy-mcp`.
Wheels include the implementation, OAuth provider and `appflowy://guide`.
Supported releases are available from GitHub source and public GHCR images.
**PyPI publishing is explicitly deferred and unconditionally disabled.**

## Verify a candidate

Use Python 3.11+ and the development dependencies:

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
python -m pytest -q
python -m build
python -m twine check dist/*
python scripts/check_package.py
```

Start with an empty `dist/` so older distributions cannot be uploaded accidentally.
`check_package.py` expects one wheel, installs it into a clean environment outside
the checkout, and checks the CLI, stdio/HTTP protocol, guide, OAuth discovery and
HTTP authentication using dummy configuration. It requires no AppFlowy account.

```bash
docker build -t appflowy-mcp .
python scripts/smoke_mcp.py --docker-image appflowy-mcp
python scripts/smoke_mcp.py --docker-image appflowy-mcp --transport streamable-http
```

Backend/CRDT changes also require [disposable compatibility checks](COMPATIBILITY.md).
Do not use production data to validate a release.

## Publish

1. Update `project.version` in `pyproject.toml`, the runtime MCP version, and both
   version references in `server.json`. Keep dependencies in `requirements.txt`
   consistent with the project metadata.
2. Finalize `CHANGELOG.md`, migration notes and relevant compatibility evidence.
   Merge the candidate after required checks pass.
3. Publish a GitHub Release tagged `v<project.version>` at the verified commit.
   Never move an existing release tag or replace an existing versioned image.
4. Monitor the release workflow. It reruns package and compatibility gates,
   verifies version metadata, and pushes Linux amd64/arm64 images to GHCR.
   Stable releases receive version and `latest` tags; prereleases do not move
   `latest`. The PyPI job must remain skipped while publication is deferred.
5. Confirm an anonymous image pull, then verify successful registry publication.
   Update installation examples only after artifacts actually exist.

Pull requests and ordinary `main` pushes do not publish packages. Wheel/source
builds are retained as CI artifacts; automatic attachment to GitHub Releases is
an open item in [ROADMAP.md](ROADMAP.md).

## MCP Registry and GHCR

The identity is `io.github.Rahulk644/appflowy-mcp-server`. `server.json` describes
an OCI stdio package, and the Dockerfile embeds its matching ownership label.
The workflow verifies the pinned publisher's Sigstore bundle, authenticates using
GitHub OIDC, and publishes the metadata after the image succeeds.

GHCR publishing uses the workflow's `GITHUB_TOKEN` with `packages: write`. Images
must be public. If an initial package is private, change its package settings to
Public, verify an anonymous pull, and rerun the failed registry job. Container and
registry jobs are distinct; avoid rebuilding or overwriting an already-published
version to repair a metadata-publication failure. For download/network failures,
run **Publish MCP Registry metadata** manually with the existing release tag.
This recovery workflow checks out that immutable tag, checks versions, retries
verified downloads with time bounds, and never rebuilds or republishes the image.

## Future PyPI setup

Enable PyPI only after explicit maintainer authorization: remove the unconditional
`false` guard in `release.yml` and set `ENABLE_PYPI_PUBLISH=true`. Configure the
`pypi` GitHub environment and a PyPI Trusted Publisher for project
`appflowy-mcp-server`, owner `Rahulk644`, repository `Appflowy-MCP-Server`, workflow
`release.yml`, environment `pypi`. Use OIDC; do not add a PyPI API token to the repo.
