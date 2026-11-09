# Maintainer roadmap

Open work is ordered by impact. The current architecture and implemented features
are documented separately in [ARCHITECTURE.md](ARCHITECTURE.md) and the README.
Each item below has a concrete completion condition so work can resume without
access to a prior chat or review session.

| Priority | Work item | Next action and completion criterion | Constraint |
|---|---|---|---|
| High | Validate actual Google sign-in in a desktop client | Complete a real browser sign-in/refresh/revocation round trip against the deployed Google OAuth client. | Official MCP SDK HTTP flow is validated with mocked Google identity; no Google client deployment is configured here. |
| High | Validate current AppFlowy SaaS | Configure the protected Cloud job with a dedicated disposable workspace; run reads, then authorized mutations and cleanup. Commit only a sanitized report. | Needs operator-managed test account/secrets; no credentials in chat or repository. |
| Medium | Reproduce the historical decoder failure | Obtain a sanitized failing database snapshot; demonstrate decode/mutation behavior on supported and candidate pycrdt versions. Propose an upstream patch or upgrade only with representative evidence. | The committed fresh fixture passes 0.13.0/0.14.1 and is not the historical reproducer. |
| Medium | Validate multi-user space permissions | Run owner/member/guest read and write checks across public, private and custom spaces on a suitably licensed disposable deployment. | The unlicensed commercial stack rejects a second initialized user with `LicenseLimitHit` (1120); owner ACL persistence is validated. |
| Medium | Validate AI before expanding its default support | Run chat/context/answer/partial-stream scenarios against an AI-enabled disposable deployment, including denied workspace-wide context and cleanup. | Experimental AI stays opt-in. |
| Medium | Define field-deletion dependency cleanup | Test fields used by filters, sorts, grouping, formulas and Timeline layouts; remove dependent settings or reject the deletion explicitly. | Current deletion removes schema, field orders and direct field settings but leaves other references to the client. |
| Medium | Reduce backend coupling | Extract API/session handling, Markdown/CRDT conversion and legacy adapters in separate, behavior-preserving changes. Keep existing protocol and integrity tests green. | The large backend is working; a wholesale rewrite would add regression risk. |
| Medium | Consolidate release/dependency metadata | Choose one runtime-version source and one dependency declaration, validate the registry image version, and automate public wheel/source attachment to GitHub Releases. | Current version/dependency copies must be updated together; 2.0.0 wheel upload failed, while CI artifacts and GHCR/source installs succeeded. |
| Low | Modernize workflow dependencies | Upgrade deprecated action runtimes in an isolated PR; rerun Linux/Windows, container and self-hosted checks. Consider dependency-update automation. | Do not mix action major upgrades into runtime fixes. |
| Low | Improve export/large-workspace efficiency | Measure representative workspace/snapshot sizes, then address full-list reads and repeated fetches; define response/continuation behavior before adding caches. | Output bounds currently do not bound the upstream snapshot/list fetched. |
| Low | Extend media and view workflows | Prioritize multipart files, media insertion, additional view controls or page-subtree authorization from actual user demand. | Small payload upload is implemented; rich-media orchestration and per-client subtree scopes are separate features. |

PyPI publication is deferred until explicitly requested. Third-party listings,
competitor comparisons and model-recommendation promises are not part of the
repository documentation.
