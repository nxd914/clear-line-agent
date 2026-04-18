---
paths:
  - "research/**/*.py"
---

# Research Scripts

These are diagnostic/one-off tools, not production code.

## Rules
- Scripts run from repo root: `python -m research.script_name`
- Always load `.env` from repo root via `python-dotenv` before any imports
- Print human-readable output — these are for eyeballing, not parsing
- Use `list_open_markets_raw()` for unfiltered market access (no volume/spread gates)
- OK to be messy — clarity over elegance for research scripts
- Import from `quant.*` (`quant.agents`, `quant.core`) — never from legacy `trading.*` paths
