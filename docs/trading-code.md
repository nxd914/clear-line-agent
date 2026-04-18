---
paths:
  - "quant/**/*.py"
  - "tests/**/*.py"
---

# Trading Code Standards

## Style
- Type hints on all function signatures
- Async-first: use `asyncio` patterns, never `time.sleep` in async context
- Dataclasses are frozen (`@dataclass(frozen=True)`) for models
- f-strings only, no `.format()` or `%`

## Error handling
- Log HTTP status + truncated body on any non-2xx Kalshi response at WARNING level
- 429s: exponential backoff with jitter, max 5 retries
- Never swallow exceptions silently — log then re-raise or return empty safely

## Kalshi-specific
- Always use `ticker` not `condition_id` (KalshiMarket has no condition_id)
- Parse prices as integer cents / 100 — never trust `*_dollars` fields as primary
- Signal coalescing: drain queue, keep latest, enforce 30s cooldown between fetches
- Never hold asyncio.Lock across `await asyncio.sleep()` — deadlocks event loop

## Testing
- pytest + pytest-asyncio + pytest-mock
- Mock Kalshi client at boundary, not internals
- Run: `pytest tests/ -x -q` (fail fast, quiet)
- New agent file = new test file in `tests/`
