# Contributing

Keep tests with their module: API/session checks in `tests/test_api.py`, local
document conversion in `tests/test_documents.py`, and collaboration helpers in
`tests/test_collab.py`. Patch HTTP/client state in `appflowy_mcp.api`; the server's
compatibility function aliases are not a second session store. Use the shared
`mock_appflowy_api` fixture for HTTP-level backend tests.

Declare runtime and development dependencies in `pyproject.toml`. The source
`requirements.txt` delegates to that project; it is not a separate dependency list.
Run `python scripts/release_metadata.py` when validating a candidate, and see
[RELEASING.md](RELEASING.md) before changing version metadata.

Workflow actions are pinned to reviewed release commits. Dependabot proposes
weekly updates, grouping minor/patch maintenance while leaving major upgrades
separate. Review action release notes and require Linux/Windows, container and
disposable compatibility checks before merging a workflow upgrade.

## Development setup

Python 3.11+ is required. From a fork or checkout:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

On Windows, activate with `.venv\Scripts\Activate.ps1`. Copy `.env.example` only
when no `.env` exists, then configure a dedicated bot account. For source testing:

```bash
appflowy-mcp doctor --check --env-file /absolute/path/to/.env
appflowy-mcp
```

Offline tests use dummy configuration and require no AppFlowy account. Selected
files run independently; shared defaults are in `tests/conftest.py`.

## Checks

```bash
ruff check .
ruff format --check .
python -m pytest -q
```

Use `ruff format .` to apply formatting. Add regressions for changed behavior;
avoid tests that merely repeat implementation details. For packaging, transport
or dependency changes, follow [RELEASING.md](RELEASING.md). Backend/CRDT changes
also need the disposable [compatibility suite](COMPATIBILITY.md). Keep test data
isolated from production and remove disposable services with the runner's `down`.

## Code and documentation

- Keep network work async and reuse the AppFlowy client/session lifecycle.
- Enforce workspace policy below routing; behavior hints are not permissions.
- Preserve incremental collaboration updates and explicit partial failures.
- Keep the default manifest compact; preserve documented legacy entry points.
- Prefer small domain functions over new generic factories or speculative layers.
- Update the relevant user, architecture and compatibility docs with behavior
  changes. Current docs must stand alone without the PR conversation.
- Maintain open work in [ROADMAP.md](ROADMAP.md) and release changes in
  [CHANGELOG.md](CHANGELOG.md). [AGENTS.md](AGENTS.md) holds durable project context.

## Pull requests and issues

Start from `main` and describe the concrete problem, resulting behavior, relevant
checks and remaining limits. Keep unrelated refactors separate. Explain any
compatibility change, especially profile schemas or OAuth session behavior.

For bug reports, include server release, Python/runtime, deployment type, AppFlowy
backend/Web versions, expected behavior and a minimal reproduction. Redact tokens,
passwords, emails and private workspace content. Feature requests should describe
the user task and acceptance criteria. Report vulnerabilities privately through
[SECURITY.md](SECURITY.md).
