# Compatibility evidence

The current reproducible baseline is AppFlowy Cloud 0.21.4 and Web 0.20.12 from
the pinned first-party commercial stack. Fresh run reports are uploaded by the
[compatibility workflow](https://github.com/Rahulk644/Appflowy-MCP-Server/actions/workflows/compatibility.yml).
The committed reports below cover the current and previous baselines.
See [COMPATIBILITY.md](../COMPATIBILITY.md)
for deployment commits, image digest, commands and validation limits.

| Report | Coverage |
|---|---|
| [Cloud 0.21.4 lifecycle](selfhost-0.21.4-2026-11-14.json) | 31 successful checks, including authentication, exact-token refresh readback, native tables, uploaded image blocks, document and row persistence, field-deletion guards, scoped folders, export continuation, chunk reassembly, comments/replies and a positive keyword search hit |
| [Web 0.20.12 browser](browser-0.20.12-2026-11-14.json) | Ten visible-content categories: documents, native tables, loaded uploaded images, Number, DateTime/ranges, select, multi-select, Formula, Board and Timeline |
| [Current database decoders](decoders-0.21.4-2026-11-14.json) | Required 0.13.0, candidate 0.14.1 and resolved latest 0.14.13 pass decoding and incremental structural-update convergence on the same job-local snapshot; raw bytes are not published |
| Previous Cloud 0.20.5 / Web 0.20.11 | [31 live checks](selfhost-0.20.5-2026-11-10.json) and [ten browser categories](browser-0.20.11-2026-11-10.json) |

Each JSON records its source commit, workflow run and artifact digest. Reports
contain check outcomes rather than credentials or private response bodies. CI
retains fresh reports and failure diagnostics as run artifacts. Historical
contributor reports for older deployments remain available in Git history; they
are not evidence for the current baseline.

These reports do not validate AppFlowy SaaS, real Google sign-in, AI answers,
member/guest authorization, or the historical pycrdt regression. The relevant
operator requirements and completion criteria are in [ROADMAP.md](../ROADMAP.md).
