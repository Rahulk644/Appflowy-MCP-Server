# Tool surface measurements

Run `python scripts/benchmark_tools.py --output benchmarks/current.json` after
installing the development dependencies. Each profile runs in a fresh process and
measures the actual MCP tool manifest using the same JSON serialization.

The baseline was captured from the 34-tool implementation before SDK migration.
The current report includes legacy, compact, compact with opt-in AI, and read-only
profiles, along with the number of native async tool functions and instruction
size. Profiles are exclusive: legacy names are never loaded beside compact names.

These are byte measurements, not token counts or measured LLM tool-selection
accuracy. Client lazy loading, tokenizer choice and prompt caching affect actual
cost and latency. Workflow task completion is tested separately through MCP
contract tests and the disposable live integration suite. [tests/evaluation.xml](../tests/evaluation.xml) supplies
10 read-only agent evaluation cases with independently verifiable expected results.

## Workspace response and read costs

Run `python scripts/benchmark_workspace.py --output /tmp/workspace.json` from an
installed development checkout. This uses synthetic HTTP responses for row lists
and folder trees, synthetic document text for exports, and actual pycrdt binary
snapshots for decode/render cases. It never contacts AppFlowy.

[Before](workspace-before.json) is commit
`e3075299361e78b40693214b60d2263383897280`; [after](workspace-after.json) includes
scoped subtree reads and bounded continuations. Both used Python 3.12.14 and
pycrdt 0.13.0 on the same host. For comparison against another checkout, set
`APPFLOWY_BENCHMARK_ROOT=/absolute/path/to/checkout` while running this script.

Each export below requests up to 50 attempts. Counts and bytes describe one
response, not the cost of completing the entire export.

| Synthetic case | Before | After |
|---|---|---|
| 1,000 rows, 2,000-character cell, requested limit 50 | Text preview; no usable cursor | 24 complete records; `next_offset:24` |
| 1,000 child pages, 500 characters each | 50 document reads; 50 files; no cursor | 50 reads; 50 files; `next_offset:50` |
| 1,000 child pages, 2,500 characters each | 50 reads / 125,000 text bytes; preview | 16 reads / 40,000 text bytes; 15 complete files and continuation |
| 1,000 child pages, 100,000 characters each | 50 reads / 5,000,000 text bytes; preview | One read / 100,000 text bytes; explicit chunk-fetch warning and tree continuation |
| 10 child pages, 10,000 unrelated workspace pages | 528,241 fixture folder JSON bytes | 424 fixture folder JSON bytes; same 11 files |

Response limits do not bound upstream input. In both reports, listing 10,000 row
IDs plus 50 details reads 186,758 simulated HTTP bytes. A 5,000-paragraph document
is about 2.14 MB of binary snapshot and still requires full local decoding. Each
Markdown chunk fetches that full snapshot again. These are remaining candidates
for verified upstream paging/conditional-read support, rather than justification
for an unmeasured cache.

Fixture construction is excluded from timing. Python allocation tracking excludes
native Rust allocations and is not whole-process memory. Timings include
`tracemalloc` overhead, cold-call effects and host noise; the reports do not establish
production latency, SaaS throughput or a CPU speedup. The useful comparisons are
response correctness, read counts and fixture bytes. Live persistence and browser
behavior are validated separately in the disposable compatibility suite.
