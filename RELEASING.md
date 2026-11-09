# Packaging and releases

The distribution is `appflowy-mcp-server`; its executable is `appflowy-mcp`.
The package includes the server, Google OAuth provider, and `appflowy://guide`.
MCP 2.3+ uses `MCPServer`; pycrdt remains pinned to 0.13.0. Python 3.11+ is required.

## Build and verify locally

```bash
pip install -e '.[dev]'
ruff check .
ruff format --check .
pytest -q
python -m build
python -m twine check dist/*
python scripts/check_package.py
docker build -t appflowy-mcp .
python scripts/smoke_mcp.py --docker-image appflowy-mcp
python scripts/smoke_mcp.py --docker-image appflowy-mcp --transport streamable-http
```

Remove older files from `dist/` before building another version. The installation
check expects one wheel, creates a temporary virtual environment, installs that
wheel, and runs outside the checkout. It checks the module/executable, stdio and
HTTP initialization, tool discovery, guide loading, OAuth discovery, and HTTP
authentication. No AppFlowy credentials are required; it enables OAuth with dummy
settings to check that the optional provider is packaged.

## One-time publisher setup

PyPI publication is deferred and disabled by default. Container releases work
independently. Enable the repository variable `ENABLE_PYPI_PUBLISH=true` only when
ready to publish to PyPI and after completing the publisher setup below.

1. Create a GitHub Actions environment named `pypi` in this repository. Set any
   desired release reviewers on that environment.
2. In PyPI's **Publishing** settings, add a pending Trusted Publisher:
   project `appflowy-mcp-server`, owner `Rahulk644`, repository
   `Appflowy-MCP-Server`, workflow `release.yml`, environment `pypi`.
   The workflow uses OIDC; no PyPI API token belongs in repository secrets.
3. Ensure GitHub Actions may publish to GitHub Container Registry. Its workflow
   uses the repository's `GITHUB_TOKEN` with `packages: write`.
4. After the first GHCR publication, set the package's visibility to **Public**
   so users can pull it without signing in. Check anonymous installation and pulls
   before adding release installation commands to the README quick start.

## Publish a release

1. Update `project.version`, the runtime server version, and both versions in `server.json`; finalize the changelog.
2. Merge the reviewed change and wait for CI to pass.
3. Publish a GitHub Release tagged `v<project.version>`, such as `v2.0.0`.

Publishing the GitHub Release triggers `.github/workflows/release.yml`. It reruns
CI for the release, verifies that the tag matches the package version, and publishes
the checked Python distribution to PyPI (only when explicitly enabled) and a
Linux amd64/arm64 image to GHCR.
Stable container releases receive version and `latest` tags. These two registries
publish independently; inspect both jobs, and rerun only a failed job if one succeeds.
An existing PyPI version cannot be overwritten.

No package or image is published by pull-request CI or an ordinary push to `main`.

## Installation after publication

These commands require a successfully published release. Until then, use the
GitHub-source command in the README or build Docker locally.

PyPI commands are intentionally omitted until that distribution is published.
The source installation works without PyPI:

```bash
uvx --from git+https://github.com/Rahulk644/Appflowy-MCP-Server@v2.0.0 appflowy-mcp --env-file /absolute/path/to/.env
```

```bash
docker run --rm --env-file .env -p 127.0.0.1:8000:8000 \
  ghcr.io/rahulk644/appflowy-mcp-server:2.0.0
```

For stdio, use `-i` instead of publishing a port and append `appflowy-mcp` to
override the image's HTTP command. Persist `OAUTH_STORE_PATH` on a volume for
remote OAuth deployments, as in the existing Compose file.

## Official MCP Registry

`server.json` publishes an OCI package under
`io.github.Rahulk644/appflowy-mcp-server`. Its ownership label is embedded in the
Dockerfile. After the container job, the registry job verifies anonymous access,
verifies the pinned publisher's Sigstore bundle, logs in with GitHub OIDC and
publishes the metadata. A private initial GHCR package must be made Public in
GitHub package settings before that job can succeed. Rerun only the failed
registry job after fixing visibility. Registry publication is independent of PyPI.

The release gate also runs the pinned commercial self-hosted lifecycle/browser
suite and required supported-decoder fixture check. Candidate decoders are
informational. Cloud/AI validation is documented separately in COMPATIBILITY.md.
