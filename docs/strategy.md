# Trading Strategy

## One-Sentence Summary

Buy or sell Kalshi crypto prediction contracts when our Black-Scholes model (fed by real-time Binance/Coinbase spot prices) disagrees with the Kalshi order book by more than 4%, sized by Kelly criterion.

## The Edge

Kalshi lists binary contracts on BTC and ETH prices: "Will BTC be above $74,400 at 4pm ET?" or "Will ETH be in the $2,330-$2,370 range at 5pm ET?" These contracts are priced by Kalshi's order book participants.

**The latency arb thesis**: Binance and Coinbase spot prices move faster than Kalshi contract prices update. When BTC jumps from $74,000 to $75,000 on Binance, Kalshi's "BTC above $74,400" contract should reprice from ~50% to ~80%+, but there's a delay (seconds to minutes) where the Kalshi book is stale. We buy during that window.

We only trade contracts expiring within 4 hours because that's where spot-to-probability convergence is fastest. Far-dated contracts can stay mispriced indefinitely — there's no force pulling them to fair value on our timeframe.

## End-to-End Data Flow

```
Binance.US WebSocket ──┐
                       ├── Tick ──► RollingWindow ──► FeatureVector ──► Signal
Coinbase WebSocket ────┘           (Welford online)  (spot, vol, z)   (if jump or z>2)
                                                                          │
Kalshi REST + WS ──► Market Cache ──────────────────────► ScannerAgent._score()
                                                            │
                                              N(d2) model_prob vs Kalshi implied_prob
                                                            │
                                              TradeOpportunity (if edge > 4%)
                                                            │
                                                  RiskAgent._evaluate()
                                              (Kelly sizing, position limits, cooldown)
                                                            │
                                              ExecutionAgent._paper_order()
                                              (fill at ask, log to SQLite)
                                                            │
                                              ResolutionAgent._resolve_cycle()
                                              (poll settlements, compute P&L, free slot)
```

## Step-by-Step Execution

### 1. Ingest CEX spot prices (`quant/agents/crypto_feed_agent.py`)

Two persistent WebSocket connections run simultaneously:
- **Binance.US** `wss://stream.binance.us:9443/stream` — `btcusdt@aggTrade` and `ethusdt@aggTrade`
- **Coinbase** `wss://ws-feed.exchange.coinbase.com` — `ticker` channel for `BTC-USD` and `ETH-USD`

Every trade on either exchange becomes a `Tick(exchange, symbol, price, timestamp, volume)`. Both push to the same `tick_queue`. Independent reconnect logic with exponential backoff (1s to 60s).

### 2. Compute rolling features (`quant/agents/feature_agent.py` + `quant/core/features.py`)

Each `Tick` is fed into a per-symbol `RollingWindow` — a time-bounded deque (60-second lookback) with Welford's online algorithm for O(1) amortized variance tracking.

On each tick, after 10+ observations have accumulated, `compute_features()` produces:

| Feature | Computation | Purpose |
|---------|------------|---------|
| `spot_price` | Raw tick price | Current BTC/ETH price |
| `short_return` | Price return over last 5 seconds | Detect rapid moves |
| `realized_vol` | `std(log_returns) × sqrt(365×24×3600)` | Annualized vol for BS model |
| `jump_detected` | `abs(short_return) >= 0.002` (0.2%) | Trigger signal on sudden moves |
| `momentum_z` | `(short_return - mean_return) / std` | Z-score of recent move |

### 3. Fire signals (`quant/core/pricing.py:features_to_signal`)

A `Signal` fires if either:
- **Jump detected**: `abs(5-second return) >= 0.2%`
- **Momentum z-score exceeds 2.0**: the recent return is 2+ standard deviations from the rolling mean

Signal confidence: `min(0.95, 0.55 + 0.05 × (z - 2.0))`. Direction: `MOMENTUM_UP` if return > 0, else `MOMENTUM_DOWN`.

### 4. Score Kalshi contracts (`quant/agents/scanner_agent.py`)

Two concurrent scan loops:
- **Signal-triggered** (every ~5 seconds when signals fire): re-prices cached markets matching the signal's crypto symbol
- **Periodic** (every 120 seconds): re-fetches all KXBTC/KXETH markets from Kalshi and re-prices everything

Both call `_score()` which:

**Filters first:**
1. Skip if < 5 minutes to close (too late to trade)
2. Skip if > 4 hours to close (too far for latency arb)
3. Apply real-time Kalshi WS price override if available
4. Skip if no spot data or vol data (warmup period)
5. Apply vol floor of 0.30 annualized for low-vol regimes

**Prices the contract:**

For **threshold contracts** ("BTC above $74,400?"):
```
model_prob = N(d2)
d2 = (ln(spot/strike) - 0.5 × vol² × t) / (vol × √t)
t  = hours_to_expiry / 8760
```
This is Black-Scholes N(d2) without risk-free rate (no carry cost in prediction markets). For "less" contracts (YES = spot < strike): `model_prob = 1 - N(d2)`.

For **bracket contracts** ("ETH in $2,330-$2,370?"):
```
model_prob = N(d2_floor) - N(d2_cap)
           = P(spot > floor) - P(spot > cap)
           = P(floor < spot < cap)
```

**Checks edge:**
```
edge = abs(model_prob - market_implied_prob)
if edge < 0.04: skip  # 4% minimum accounts for Kalshi taker fee drag
```

**Picks side:**
```
if model_prob > market_implied_prob: buy YES
if model_prob < market_implied_prob: buy NO
```

### 5. Kelly sizing (`quant/core/kelly.py`)

The Kelly criterion determines optimal bet fraction for a binary outcome:
```
effective_price = ask + taker_fee
taker_fee = 0.07 × P × (1-P)        # Kalshi's parabolic fee schedule
b = (1 / effective_price) - 1         # net odds
f* = (model_prob × b - (1-model_prob)) / b
```
Capped at 25% of bankroll. Negative Kelly (no edge after fees) = no trade.

### 6. Risk gating (`quant/agents/risk_agent.py`)

Before any trade reaches execution, it must pass:

| Gate | Threshold | Purpose |
|------|-----------|---------|
| Circuit breaker | Daily loss > 20% of bankroll | Emergency halt |
| Position limit | Max 5 concurrent open | Capital preservation |
| Spread floor | Bid-ask spread < 4% | Fee protection (no maker rebates) |
| Duplicate check | Same ticker already open | No doubling down |
| Burst cooldown | < 30 seconds since last fill | Prevent signal cascade |
| Symbol concentration | > 2 positions per BTC/ETH | Diversification |
| Size minimum | Kelly size < $1 | Filter noise |
| Single exposure cap | > 10% of bankroll per trade | Concentration limit |

### 7. Execution (`quant/agents/execution_agent.py`)

**Paper mode** (current): simulates fill at current market ask, zero slippage. Every trade logged to SQLite with full audit trail including `spot_price_at_signal` and `signal_latency_ms`.

**Live mode** (not yet enabled): will place real orders via Kalshi API. Requires `EXECUTION_MODE=live` env var. Blocked until paper Sharpe >= 1.0 over 2+ weeks.

### 8. Resolution (`quant/agents/resolution_agent.py`)

Polls every 60 seconds. For each open position, calls Kalshi API to check settlement status:
- Primary: Kalshi's `status == "settled"` + `result` field
- Fallback: price heuristic (`yes_bid >= 0.99` = YES, `yes_ask <= 0.01` = NO)

P&L calculation (binary with fee):
```
Won:  gross = (size / entry_price) - size;  pnl = gross - fee
Lost: pnl = -(size + fee)
Fee:  ceil(0.07 × num_contracts × P × (1-P) × 100) / 100
```

Calls `risk_agent.record_fill()` to free the position slot. Without resolution, all 5 slots fill up and trading halts permanently.

## Key Constants

| Constant | Value | Location | Rationale |
|----------|-------|----------|-----------|
| `MIN_EDGE` | 4% | `kelly.py` | Covers Kalshi taker fee drag |
| `MIN_SPREAD_PCT` | 4% | `risk_agent.py` | No maker rebates on Kalshi |
| `MAX_KELLY_FRACTION` | 0.25 | `kelly.py` | Conservative half-Kelly |
| `MAX_CONCURRENT_POSITIONS` | 5 | `risk_agent.py` | Capital preservation |
| `MAX_SINGLE_EXPOSURE_PCT` | 10% | `risk_agent.py` | Concentration limit |
| `MAX_DAILY_LOSS_PCT` | 20% | `risk_agent.py` | Circuit breaker |
| `MAX_HOURS_TO_CLOSE` | 4 | `scanner_agent.py` | Latency arb needs fast convergence |
| `MIN_SECONDS_BETWEEN_FILLS` | 30 | `risk_agent.py` | Prevent burst-filling from signal cascade |
| `MAX_POSITIONS_PER_SYMBOL` | 2 | `risk_agent.py` | Crypto diversification |
| `MIN_CRYPTO_VOL` | 0.30 | `scanner_agent.py` | Vol floor for BS model |
| `SCAN_INTERVAL_SECONDS` | 120 | `scanner_agent.py` | Periodic re-pricing cadence |
| `SIGNAL_COOLDOWN_SECONDS` | 5 | `scanner_agent.py` | Signal dedup rate limit |
| `MAX_BRACKET_YES_PRICE` | 0.30 | `scanner_agent.py` | Don't buy YES on brackets above 30c (risk/reward inverts) |
| `BRACKET_CALIBRATION` | 0.70 | `pricing.py` | 30% haircut on N(d2) bracket prob (discrete jumps + CF avg) |
| `MAX_SIGNAL_AGE_SECONDS` | 2.0 | `risk_agent.py` | Reject stale signals (latency arb needs sub-2s freshness) |

## What "Pure Math" Means

The entire pricing path is deterministic:
1. `spot_to_implied_prob()` — Black-Scholes N(d2), standard closed-form
2. `bracket_prob()` — Difference of two N(d2) calls
3. `capped_kelly()` — Kelly criterion with fee adjustment
4. `position_size()` — Kelly fraction times bankroll

Zero learned parameters. Zero heuristics. Zero LLM calls. The edge claim is mathematically defensible: if our vol estimate is accurate and there's genuine latency between CEX and Kalshi, the model will correctly identify mispriced contracts. The risk is that vol is wrong, the latency gap doesn't exist, or Kalshi fees eat the edge.

## Contract Types on Kalshi

| Type | `strike_type` | Ticker suffix | Example | Model |
|------|--------------|---------------|---------|-------|
| Threshold | `greater`/`less` | `-T` | "BTC above $74,400?" | `N(d2)` |
| Bracket | `between` | `-B` | "ETH in $2,330-$2,370?" | `N(d2_floor) - N(d2_cap)` |

Resolution source: **CF Benchmarks Real-Time Index** (60-second average before cutoff), not raw exchange spot. This matters — our spot feed (Binance/Coinbase) may differ slightly from the resolution benchmark.

## Process Management

```bash
./scripts/run.sh start|stop|restart|status    # manages the daemon (logs to data/)
python3 -m research.health_check              # P&L + process health summary
python3 scripts/force_resolve.py              # clear stuck positions manually
```

## Go-Live Gate

Paper trading runs indefinitely until:
- Sharpe ratio >= 1.0 demonstrated over 2+ weeks of continuous paper trading
- Then set `EXECUTION_MODE=live` in `.env` and restart — no code changes needed
