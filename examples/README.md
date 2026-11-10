# Client setup and workflow examples

These recipes use standard MCP transports. The automated suite validates protocol
behavior; individual Claude, Cursor and Codex desktop interfaces are not certified.
Store credentials in a private `.env`, with a dedicated bot account and
`ALLOWED_WORKSPACE_IDS` set. Run `appflowy-mcp doctor --check` to verify access.

## Claude Desktop / Cursor stdio configuration

```json
{"mcpServers":{"appflowy":{"command":"uvx","args":["--from","git+https://github.com/Rahulk644/Appflowy-MCP-Server@v2.2.0","appflowy-mcp","--env-file","/absolute/path/to/.env"]}}}
```

For a checked-out development build, use the installed `appflowy-mcp` executable
instead. Restart the client when configuration or tool profiles change.

## Claude Code

```bash
claude mcp add appflowy -- uvx --from git+https://github.com/Rahulk644/Appflowy-MCP-Server@v2.2.0 appflowy-mcp --env-file /absolute/path/to/.env
```

## Codex TOML

```toml
[mcp_servers.appflowy]
command = "uvx"
args = ["--from", "git+https://github.com/Rahulk644/Appflowy-MCP-Server@v2.2.0", "appflowy-mcp", "--env-file", "/absolute/path/to/.env"]
```

## Docker stdio

```json
{"mcpServers":{"appflowy":{"command":"docker","args":["run","--rm","-i","--env-file","/absolute/path/to/.env","ghcr.io/rahulk644/appflowy-mcp-server:2.2.0","appflowy-mcp"]}}}
```

## Remote HTTP

```json
{"mcpServers":{"appflowy":{"url":"https://mcp.example.com/mcp/","headers":{"Authorization":"Bearer YOUR_MCP_SECRET_TOKEN"}}}}
```

For clients supporting interactive OAuth, configure Google OAuth per the README
and use the endpoint URL without a shared secret. Serve over HTTPS. OAuth email
allow-list and workspace allow-list have different purposes; configure both.

## Starter tasks

- “List accessible workspaces, then show the top-level folder tree.”
- “Find the project board, inspect its field types, and move row ROW_ID to Done.
  Update that row rather than creating a second one.”
- “Read page PAGE_ID, then append a checklist. Read it again to confirm the result.”
- “Export this document subtree as Markdown. Follow continuations and report skipped documents.”

All compact tool arguments are wrapped in `request`. Read `appflowy://guide` for
command-specific examples. Use `APPFLOWY_READ_ONLY=true` for discovery-only use.
