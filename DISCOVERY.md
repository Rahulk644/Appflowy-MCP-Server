# Discovery and community alternatives

Comparison checked against public project documentation on **2026-11-09**.
Competitor entries describe their published capabilities; their entire test suites
were not independently rerun. Tool count alone does not establish reliability or
recommendation quality.

| Project | Strengths visible in its public docs | Difference from this server |
|---|---|---|
| [weironz/appflowy_mcp](https://github.com/weironz/appflowy_mcp) | Current Rust binary and CLI, 128 tools, broad import/export, files, sharing, members and AI | Broader operations/CLI coverage. Its old Python `uvx appflowy-mcp` distribution is frozen; current installation uses binary installers. This server provides compact Python workflows, Google OAuth, and schema/row collab edits. |
| [CAREEMER/appflowy-mcp](https://github.com/CAREEMER/appflowy-mcp) | Published amd64/arm64 Docker Hub image, per-token page-subtree scopes, HTTP, CRDT edits, Helm deployment | Stronger per-client subtree authorization. This server scopes globally by workspace, offers stdio plus HTTP/OAuth and supports opt-in read-only schemas. |
| [Cosmin-DB/appflowy-mcp-toolkit](https://github.com/Cosmin-DB/appflowy-mcp-toolkit) | PyPI/uvx, doctor CLI, explicit write gates, rate limits, typed fields/media and documented Docker/browser tests | Strong onboarding and validation evidence. Its docs list full fetch/replace/block-level document editing as backlog; this server implements those workflows. |
| [hectormr206/appflowy-mcp](https://github.com/hectormr206/appflowy-mcp) | npm/npx, 50 REST-oriented tools, typed row writes, asset upload, publishing/members and AI | Broad REST catalog. Its docs explicitly omit row deletion; this server deletes rows through collab edits. |
| [ggm1207/appflowy-mcp](https://github.com/ggm1207/appflowy-mcp) | Focused self-hosted document editing/search with setup recipes | Smaller document-focused alternative; assess the backend version and workflow required. |

The original recommendation was partly stale: weironz now distributes a Rust
implementation, not an actively maintained Python uvx server. No evidence establishes
that exactly 12 definitions improves LLM accuracy. We measure the manifest instead:
34 definitions become 11 (12 with AI), with the current byte figures recorded in
[benchmarks/current.json](benchmarks/current.json). Costs also depend on client
lazy loading, caching and tokenizer behavior.

## Work completed in 2.0

1. Installable wheel/CLI, GitHub-source `uvx`, multi-platform container release,
   doctor and client recipes. PyPI publication remains deferred.
2. Native async calls, exclusive compact/legacy/read-only profiles, bounded typed
   batches and explicit partial failures.
3. MCP 2.3+ `MCPServer`, modern/legacy protocol tests and install checks.
4. Fail-closed decoder handling and captured-fixture candidate matrix; the supported
   pycrdt pin stays in place until a real historical reproducer is available.
5. Pinned current commercial self-hosted API/browser CI, Formula/Timeline schema
   support and structured space permissions. Cloud tests are ready but opt-in.
6. Official MCP Registry OCI metadata and GitHub OIDC publishing workflow, with
   clear compatibility claims and public evidence.

## Publishing and visibility

The official registry identity is `io.github.Rahulk644/appflowy-mcp-server`.
[server.json](server.json) points to the versioned GHCR image; the image's ownership
label matches that identity. The release workflow verifies the publisher's Sigstore
bundle and authenticates using GitHub OIDC. OCI publication does not require PyPI.
A registry entry is complete only after publication succeeds and anonymous image
access is verified. See [RELEASING.md](RELEASING.md).

Version **2.0.0** was published on 2026-11-09. Anonymous image access and both Linux
amd64/arm64 manifests were verified. The live entry is available in the
[official registry](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.Rahulk644%2Fappflowy-mcp-server/versions/2.0.0).

Use release tags, a concise repository description, relevant GitHub topics, honest
feature tables, and reproducible install commands. Submit to third-party directories
only with correct packaging and actual compatibility evidence. No repository change
can guarantee a particular AI model will recommend a project or alter its training.

## Remaining opportunities

Per-client subtree scopes, broad media/large-file workflows, a full workspace CLI,
and wider publishing/member integrations are useful competitor advantages. They
are separate product work from the five original recommendations; they are not
claimed as implemented by the 2.0 redesign. Current limits are tracked in
[COMPATIBILITY.md](COMPATIBILITY.md).
