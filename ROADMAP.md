# Maintainer roadmap

Open work is ordered by impact. The current architecture and implemented features
are documented separately in [ARCHITECTURE.md](ARCHITECTURE.md) and the README.
Each item below has a concrete completion condition so work can resume without
access to a prior chat or review session.

| Priority | Work item | Next action and completion criterion | Constraint |
|---|---|---|---|
| High | Ship the reviewed fixes as 2.0.1 | After the maintenance PR passes, update package/runtime/registry versions, publish a new patch, verify anonymous image pulls and active registry metadata. Include the verified-email and token allow-list behavior in migration notes. | 2.0.0 is already published; never overwrite its tag or image. PyPI remains disabled. |
| High | Complete OAuth lifecycle controls | Expire/prune abandoned authorization states and codes; add public-client refresh rotation and family revocation. Test replay, expiry, restart and real MCP-client login/refresh. | Current JSON store is single-process; changing token semantics requires protocol tests and client validation. |
| High | Validate current AppFlowy SaaS | Configure the protected Cloud job with a dedicated disposable workspace; run reads, then authorized mutations and cleanup. Commit only a sanitized report. | Needs operator-managed test account/secrets; no credentials in chat or repository. |
| Medium | Reproduce the historical decoder failure | Obtain a sanitized failing database snapshot; demonstrate decode/mutation behavior on supported and candidate pycrdt versions. Propose an upstream patch or upgrade only with representative evidence. | The committed fresh fixture passes 0.13.0/0.14.1 and is not the historical reproducer. |
| Medium | Broaden visible typed-cell coverage | Add live/browser cases for select/multi-select, Number, DateTime, options and Board grouping; verify both visible values and authoritative readback. | Existing UI checks cover document text and a Grid title; do not infer coverage for every field type. |
| Medium | Validate Formula/Timeline behavior | Test evaluated formulas and rendered Timeline settings in AppFlowy Web; verify permissions with separate owner/member/guest accounts. | Current evidence proves schema/ACL persistence, not every effective permission or view behavior. |
| Medium | Validate AI before expanding its default support | Run chat/context/answer/partial-stream scenarios against an AI-enabled disposable deployment, including denied workspace-wide context and cleanup. | Experimental AI stays opt-in. |
| Medium | Reject ignored command-specific inputs | Define and test the applicable fields for each compact command, including document text supplied to cell-only updates and Markdown supplied to database creation. Return a validation error instead of silently ignoring intent. | Avoid a large schema expansion without measuring manifest size and compatibility. |
| Medium | Define field-deletion dependency cleanup | Test fields used by filters, sorts, grouping, formulas and Timeline layouts; remove dependent settings or reject the deletion explicitly. | Current deletion removes schema, field orders and direct field settings but leaves other references to the client. |
| Medium | Reduce backend coupling | Extract API/session handling, Markdown/CRDT conversion and legacy adapters in separate, behavior-preserving changes. Keep existing protocol and integrity tests green. | The large backend is working; a wholesale rewrite would add regression risk. |
| Medium | Consolidate release/dependency metadata | Choose one runtime-version source and one dependency declaration, validate the registry image version, and automate public wheel/source attachment to GitHub Releases. | Current version/dependency copies must be updated together; 2.0.0 wheel upload failed, while CI artifacts and GHCR/source installs succeeded. |
| Low | Modernize workflow dependencies | Upgrade deprecated action runtimes in an isolated PR; rerun Linux/Windows, container and self-hosted checks. Consider dependency-update automation. | Do not mix action major upgrades into runtime fixes. |
| Low | Improve export/large-workspace efficiency | Measure representative workspace/snapshot sizes, then address full-list reads and repeated fetches; define response/continuation behavior before adding caches. | Output bounds currently do not bound the upstream snapshot/list fetched. |
| Low | Extend media and view workflows | Prioritize multipart files, media insertion, additional view controls or page-subtree authorization from actual user demand. | Small payload upload is implemented; rich-media orchestration and per-client subtree scopes are separate features. |

PyPI publication is deferred until explicitly requested. Third-party listings,
competitor comparisons and model-recommendation promises are not part of the
repository documentation.
