# Repository context

This file is durable context for maintainers and coding agents. It describes the
current project; temporary progress and conversation summaries do not belong here.

## Read first

- `README.md`: supported installation and user interface.
- `ARCHITECTURE.md`: module boundaries and integrity constraints.
- `COMPATIBILITY.md`: exact validated deployment and unvalidated paths.
- `ROADMAP.md`: open tasks, priority and completion criteria.
- `CONTRIBUTING.md` / `RELEASING.md`: development and publication checks.

## Project invariants

- Python 3.11+, official MCP 2.3+ `MCPServer`, native async network I/O.
- Compact: 11 tools, 12 only with experimental AI enabled. Legacy: 34 separate
  names. Read-only compact: five tools. Never register aliases alongside compact.
- `ALLOWED_WORKSPACE_IDS` is server-wide. Approved HTTP users share the bot's
  AppFlowy identity; do not claim per-client page scopes or AppFlowy user roles.
- Collab changes send incremental diffs. Never write an empty replacement after a
  decode error. Keep pycrdt 0.13.0 pinned until representative fixtures justify change.
- OAuth refreshes rotate within a persisted login family. Replays revoke that family.
  Keep the JSON store single-process; do not issue tokens before a successful commit.
- Preserve root compatibility entry points and documented commands.
- PyPI publication is explicitly deferred; retain the unconditional workflow guard.
- Cloud/AI checks require suitable disposable deployments. Self-hosted success is
  not SaaS certification. Do not commit credentials or raw private response bodies.
- DateTime cells store the timestamp in `data` and range/time attributes beside it;
  JSON serialized into `data` can persist successfully while rendering an empty date.

## Validation

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
python -m pytest -q
```

For package/transport changes: build a fresh `dist/`, run `twine check` and
`scripts/check_package.py`; verify Docker stdio/HTTP. For backend/CRDT changes,
run the disposable suite in `COMPATIBILITY.md` and decoder checks. Integration
checks are opt-in locally; no test should target user production data.

## Documentation maintenance

Describe current behavior for someone without the chat history. Keep installation
in README, design in ARCHITECTURE, evidence in COMPATIBILITY, open work in ROADMAP,
and release history in CHANGELOG. Update affected docs with interface changes.
Record a release as published only after anonymous access and registry state are
verified. Never retag or overwrite an existing release to ship fixes.
