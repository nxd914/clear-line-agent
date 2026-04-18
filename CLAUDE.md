# Contributing to chiron

## Architecture

```
CryptoFeedAgent → FeatureAgent → WebsocketAgent → ScannerAgent → RiskAgent → ExecutionAgent → ResolutionAgent
```

All agents are async. Entry point: `daemon.py` at repo root.

Package: `chiron/` (implicit namespace package, no `__init__.py`). Run with `PYTHONPATH=/path/to/repo`.

## Key invariants

- `pricing.py` and `kelly.py` are pure math — no side effects, no I/O.
- Paper mode is default. `EXECUTION_MODE=live` raises `NotImplementedError` by design.
- Every trade logs to SQLite with full audit trail.
- Spread floor 4%. Kelly cap 0.25×. Max 5 concurrent positions.

## Running locally

```bash
pip install -e ".[dev]"
PYTHONPATH=. python3 daemon.py          # run all agents
pytest chiron/tests/                    # run tests
python3 -m chiron.research.health_check # P&L + process health
```

## Kalshi API

- Base: `https://api.elections.kalshi.com/trade-api/v2`
- Auth: RSA-PSS. Env vars: `KALSHI_API_KEY` (UUID) + `KALSHI_PRIVATE_KEY_PATH` (PEM)
- V2 price fields: `yes_ask`/`yes_bid` in integer cents (1–99), divide by 100.
- Rate limits: 429 = exponential backoff. Never run two processes against the same key.
