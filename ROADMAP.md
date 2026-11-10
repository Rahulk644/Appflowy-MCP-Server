# Maintainer roadmap

Open work is ordered by impact. The current architecture and implemented features
are documented separately in [ARCHITECTURE.md](ARCHITECTURE.md) and the README.
Each item below has a concrete completion condition so work can resume without
access to a prior chat or review session.

| Priority | Work item | Next action and completion criterion | Constraint |
|---|---|---|---|
| High | Validate actual Google sign-in in a desktop client | Complete a real browser sign-in/refresh/revocation round trip against the deployed Google OAuth client. | Official MCP SDK HTTP flow is validated with mocked Google identity; no Google client deployment is configured here. |
| High | Validate current AppFlowy SaaS | Configure the protected Cloud job with a dedicated disposable workspace; run reads, then authorized mutations and cleanup, including the row-body paths from [#1](https://github.com/Rahulk644/Appflowy-MCP-Server/issues/1). Commit only a sanitized report. | Needs operator-managed test account/secrets; no credentials in chat or repository. |
| Medium | Reproduce the historical decoder failure | Obtain a sanitized failing database snapshot; demonstrate decode/mutation behavior on supported and candidate pycrdt versions. Propose an upstream patch or upgrade only with representative evidence. | The committed fresh fixture passes 0.13.0/0.14.1 and is not the historical reproducer. |
| Medium | Validate multi-user space permissions | Run owner/member/guest read and write checks across public, private and custom spaces on a suitably licensed disposable deployment. | The unlicensed commercial stack rejects a second initialized user with `LicenseLimitHit` (1120); owner ACL persistence is validated. |
| Medium | Validate AI before expanding its default support | Run chat/context/answer/partial-stream scenarios against an AI-enabled disposable deployment, including denied workspace-wide context and cleanup. | Experimental AI stays opt-in. |
| Medium | Apply repository presentation settings | Set the About description/topics from [CONTRIBUTING.md](CONTRIBUTING.md#repository-presentation) and upload `assets/social-preview.jpg` as the custom social preview. Verify the public fields and preview changed. | Requires repository-settings access; committing the banner does not replace GitHub’s configured preview. |
| Low | Reduce remaining upstream full reads | Confirm supported paged row-ID and conditional snapshot-read contracts against current Web and the live stack; benchmark any proposed change before adding caches. | Scoped export and bounded continuations are implemented. Row-ID lists and each Markdown chunk still require full upstream reads; synthetic evidence is in `benchmarks/`. |
| Low | Extend media and view workflows | Prioritize multipart/large files, additional media types, view controls or page-subtree authorization from actual user demand. | Bounded payload upload and optional image insertion are implemented. Larger files need a streaming/multipart design; per-client subtree scopes are separate work. |

PyPI publication is deferred until explicitly requested. Third-party listings,
competitor comparisons and model-recommendation promises are not part of the
repository documentation.
