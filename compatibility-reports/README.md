# Compatibility evidence

The current reproducible baseline is AppFlowy Cloud 0.20.5 and Web 0.20.11 from
the pinned first-party commercial stack. See [COMPATIBILITY.md](../COMPATIBILITY.md)
for deployment commits, image digest, commands and validation limits.

| Report | Coverage |
|---|---|
| [Live lifecycle](selfhost-0.20.5-2026-11-10.json) | 31 successful checks, including authentication, exact-token refresh readback, native tables, uploaded image blocks, document and row persistence, field-deletion guards, scoped folders, export continuation, chunk reassembly, document/row/published-page comments and replies, and a positive keyword search hit |
| [Browser](browser-0.20.11-2026-11-10.json) | Ten visible-content categories: documents, native tables, loaded uploaded images, Number, DateTime/ranges, select, multi-select, Formula, Board and Timeline |

Each JSON records its source commit, workflow run and artifact digest. Reports
contain check outcomes rather than credentials or private response bodies. CI
retains fresh reports and failure diagnostics as run artifacts. Historical
contributor reports for older deployments remain available in Git history; they
are not evidence for the current baseline.

These reports do not validate AppFlowy SaaS, real Google sign-in, AI answers,
member/guest authorization, or the historical pycrdt regression. The relevant
operator requirements and completion criteria are in [ROADMAP.md](../ROADMAP.md).
