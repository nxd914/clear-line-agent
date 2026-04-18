"""Kalshi-native maker P&L simulator.

Unlike Polymarket which paid a flat 0.75% maker rebate, Kalshi charges a fee:
  Maker Fee = 0.0175 * C * P * (1-P)
Because maker EV comes entirely from capturing the spread rather than a rebate,
we must model the expected value of earning the half-spread minus the fee.
Toxicity (adverse selection) penalizes this edge.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterable


# --- Kalshi Fee Constants ----------------------------------------------------
# Maker fee is 1.75% * P * (1-P) per contract
KALSHI_MAKER_MULT = 0.0175
NOTIONAL_PER_FILL = 1.0


# --- Sim parameters ----------------------------------------------------------
DEFAULT_TICK_COUNT = 500_000
DEFAULT_PRICE_VOL = 0.005     # per-tick stdev of mid price
DEFAULT_MID_START = 0.50
MID_FLOOR = 0.02
MID_CEIL = 0.98
BASE_FILL_PROB = 0.20
SPREAD_DECAY = 40.0
INFORMED_IMPACT_MULT = 1.0


@dataclass(frozen=True)
class SimParams:
    half_spread: float
    toxicity: float
    price_vol: float = DEFAULT_PRICE_VOL
    tick_count: int = DEFAULT_TICK_COUNT
    seed: int = 42


@dataclass(frozen=True)
class SimResult:
    params: SimParams
    fills: int
    spread_pnl: float
    fee_paid: float
    adverse_pnl: float
    net_pnl: float
    pnl_per_1k_fills: float
    sharpe_like: float


def _fill_prob(half_spread: float) -> float:
    return BASE_FILL_PROB * math.exp(-SPREAD_DECAY * half_spread)

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def get_kalshi_maker_fee(price: float, notional: float = 1.0) -> float:
    """Returns the Kalshi maker fee expected for a given price level."""
    # Maker fee = 1.75% * P * (1-P)
    return KALSHI_MAKER_MULT * price * (1.0 - price) * notional

def run_sim(params: SimParams) -> SimResult:
    """Run Kalshi-specific maker simulation."""
    rng = random.Random(params.seed)
    mid = DEFAULT_MID_START
    fill_p = _fill_prob(params.half_spread)

    fills = 0
    spread_pnl = 0.0
    fee_paid = 0.0
    adverse_pnl = 0.0
    pnl_per_tick: list[float] = []

    for _ in range(params.tick_count):
        mid = _clamp(mid + rng.gauss(0.0, params.price_vol), MID_FLOOR, MID_CEIL)
        tick_pnl = 0.0

        for side_sign in (+1, -1): 
            if rng.random() >= fill_p:
                continue
            fills += 1
            
            # Kalshi Edge: We earn the half_spread (bought at mid-hs when true value is mid)
            edge = params.half_spread * NOTIONAL_PER_FILL
            
            # Kalshi Fee: Paid on every trade based on price
            # Quote price is mid - side_sign * hs
            fill_price = _clamp(mid - side_sign * params.half_spread, 0.01, 0.99)
            fee = get_kalshi_maker_fee(fill_price, NOTIONAL_PER_FILL)
            
            spread_pnl += edge
            fee_paid += fee
            tick_pnl += edge - fee

            if rng.random() < params.toxicity:
                # Informed toxic flow moves price against us
                adverse_move = params.half_spread * INFORMED_IMPACT_MULT
                loss = adverse_move * NOTIONAL_PER_FILL
                
                # If they lift our relative edge is entirely wiped by the info move
                # They took the edge, the true mid is now fill_price. Re-evaluate loss purely.
                # Standard adverse selection = expected price change
                adverse_pnl -= loss
                tick_pnl -= loss
                mid = _clamp(mid - side_sign * adverse_move, MID_FLOOR, MID_CEIL)

        pnl_per_tick.append(tick_pnl)

    net_pnl = spread_pnl - fee_paid + adverse_pnl
    pnl_per_1k = (net_pnl / fills * 1000.0) if fills > 0 else 0.0

    if len(pnl_per_tick) > 1:
        mean = sum(pnl_per_tick) / len(pnl_per_tick)
        var = sum((x - mean) ** 2 for x in pnl_per_tick) / (len(pnl_per_tick) - 1)
        sd = math.sqrt(var) if var > 0 else 0.0
        sharpe_like = (mean / sd * math.sqrt(len(pnl_per_tick))) if sd > 0 else 0.0
    else:
        sharpe_like = 0.0

    return SimResult(
        params=params,
        fills=fills,
        spread_pnl=spread_pnl,
        fee_paid=fee_paid,
        adverse_pnl=adverse_pnl,
        net_pnl=net_pnl,
        pnl_per_1k_fills=pnl_per_1k,
        sharpe_like=sharpe_like,
    )


def run_grid(
    half_spreads: Iterable[float],
    toxicities: Iterable[float],
) -> list[SimResult]:
    return [
        run_sim(SimParams(half_spread=hs, toxicity=tox))
        for hs in half_spreads
        for tox in toxicities
    ]


def _fmt_pnl(x: float) -> str:
    return f"{x * 100:+.3f}%"


def print_report(results: list[SimResult]) -> None:
    spreads = sorted({r.params.half_spread for r in results})
    toxes = sorted({r.params.toxicity for r in results})

    print("\n=== Kalshi Maker P&L grid (P&L per fill, % of notional) ===")
    header = "half_spread \\ toxicity  " + "  ".join(f"{t:>8.2f}" for t in toxes)
    print(header)
    for hs in spreads:
        row_cells = []
        for tox in toxes:
            r = next(r for r in results if r.params.half_spread == hs and r.params.toxicity == tox)
            per_fill = r.net_pnl / r.fills if r.fills > 0 else 0.0
            row_cells.append(f"{_fmt_pnl(per_fill):>8}")
        print(f"  hs={hs*100:>5.2f}%           " + "  ".join(row_cells))

    print("\n=== Sample fills & sharpe-like per config ===")
    for r in results:
        per_fill_pct = (r.net_pnl / r.fills * 100.0) if r.fills > 0 else 0.0
        # Only print viable configurations (> -0.1% edge)
        if per_fill_pct > -0.1:
            print(
                f"  hs={r.params.half_spread*100:>5.2f}%  tox={r.params.toxicity:.2f}  "
                f"fills={r.fills:>6}  "
                f"per_fill={per_fill_pct:+.3f}%  "
                f"fees_paid={r.fee_paid/r.fills*100:.3f}% "
                f"sharpe~={r.sharpe_like:+.2f}"
            )


def main() -> None:
    # Tested spreads: from 0.5% half-spread up to 4% half-spread
    half_spreads = [0.005, 0.01, 0.02, 0.03, 0.04]  
    toxicities = [0.10, 0.20, 0.30, 0.40, 0.50]

    results = run_grid(half_spreads, toxicities)
    print_report(results)


if __name__ == "__main__":
    main()
