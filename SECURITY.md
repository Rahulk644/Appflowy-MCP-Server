# Security Policy

## Security model (read before deploying)

AppFlowy Cloud authenticates via GoTrue (email/password → JWT); **there are no
scoped API keys or personal access tokens**. Any server built on this API
therefore holds *full-account* credentials. Design accordingly:

- **Use a dedicated bot account**, invited to only the workspace(s) you expose.
  Its membership is the real blast-radius limit — never use your primary login.
- **Set `ALLOWED_WORKSPACE_IDS`** so every tool refuses workspaces outside the
  allow-list, even if the account can see more (defence-in-depth).
- **Gate the endpoint.** Either set `MCP_SECRET_TOKEN` (clients send an
  `Authorization: Bearer <token>` header, constant-time compared) **or** enable
  **Google OAuth** (`GOOGLE_CLIENT_ID` + `ALLOWED_EMAILS`) for per-user sign-in.
  A `?token=` URL form is also accepted for clients that can't set a header —
  convenient, but the token then appears in URLs/logs, so treat such a link like
  a password and prefer the header or OAuth.
- **Keep the endpoint off the open internet.** Front it with an identity gate
  (e.g. Cloudflare Access / Tunnel) or a reverse-proxy IP allow-list; the Bearer
  token is a second layer, not the only one.
- **Protect `.env`** (`chmod 600`, or use Docker secrets). It contains the
  bot account password.
- DNS-rebinding protection is on by default for the HTTP transports; set
  `MCP_ALLOWED_HOSTS` to your public host when behind a proxy.

## Supported Versions

Currently, only the latest version of the `main` branch is actively supported with security updates. 

## Reporting a Vulnerability

We take the security of our users and their data very seriously. If you discover a security vulnerability in this project, please **do not report it by creating a public GitHub issue**.

Instead, please report it privately by sending an email to the repository owner or using GitHub's private vulnerability reporting feature (if enabled).

When reporting a vulnerability, please include as much information as possible:
* A description of the vulnerability and its impact.
* Steps to reproduce the issue.
* Any potential fixes or mitigations you can suggest.

We will endeavor to respond to your report within 48 hours and work with you to resolve the issue as quickly as possible.
