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
contract tests and the disposable live integration suite. `evaluation.xml` supplies
10 read-only agent evaluation cases with independently verifiable expected results.
