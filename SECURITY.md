# Security policy

## Deployment model

The server holds a bot account's AppFlowy credentials or access token. Treat these
as account credentials unless the target AppFlowy deployment documents narrower
permissions. Use a dedicated account invited only to the workspaces it needs.

`ALLOWED_WORKSPACE_IDS` restricts the server's workspace access. This is a global
policy: all approved MCP clients use the same AppFlowy identity and allowed
workspaces. Google OAuth identifies the connecting person; it does not impersonate
that person's AppFlowy account or provide per-client page-subtree permissions.

For remote HTTP, require `MCP_SECRET_TOKEN` or configured Google OAuth, serve over
HTTPS, and restrict network access as appropriate for the deployment. Without
configured HTTP authentication, the endpoint is open to callers who can reach it.
Stdio is intended for a local client process.

Use a Bearer header where possible. The supported `?token=` form can leak through
URLs, browser history and upstream proxy logs. The application redacts that query
parameter in its own access logs; it cannot redact another service's logs.

DNS-rebinding checks are enabled by default. Configure public hosts/origins,
including custom ports, when using a reverse proxy. `APPFLOWY_READ_ONLY=true`
rejects workspace mutations independently of tool registration. Advisory MCP tool
annotations are not an authorization boundary.

## Credentials and OAuth state

Protect `.env`, access tokens and `OAUTH_STORE_PATH`. The OAuth file contains
client credentials and bearer/refresh tokens; use a private persistent volume and
one server worker. Atomic replacement prevents partial writes but does not provide
cross-process coordination, encryption at rest or a token database.

Google sign-in must use an allowed, verified email. On current `main`, persisted
access and refresh tokens are checked against the current email allow-list;
legacy tokens without a subject require sign-in again. OAuth tokens must carry
the `appflowy` scope. Refreshes preserve resource binding and the requested scope.
See [CHANGELOG.md](CHANGELOG.md) for fixes not yet present in the published release
and [ROADMAP.md](ROADMAP.md) for remaining lifecycle controls.

Keep secrets and private response bodies out of issues, fixtures, benchmarks,
reports and screenshots. Disposable integration accounts are test-only.

## Supported versions and reporting

Security fixes are developed on `main` and distributed in new releases. Do not
assume an existing immutable image/tag includes later fixes; check the changelog.

Report vulnerabilities privately through
[GitHub private vulnerability reporting](https://github.com/Rahulk644/Appflowy-MCP-Server/security/advisories/new)
when available, or contact the [maintainer](https://github.com/Rahulk644) privately.
Include affected versions, impact, reproduction steps and any proposed fix. Avoid
posting credentials or exploit details in a public issue.
