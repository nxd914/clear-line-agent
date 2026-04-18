"""
Core data models for the Quant prediction market trading system.
All types are immutable dataclasses — no mutation anywhere in the pipeline.
Exchange: Kalshi (CFTC-regulated, US-legal).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Side(str, Enum):
    YES = "YES"
    NO = "NO"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class SignalType(str, Enum):
    MOMENTUM_UP = "MOMENTUM_UP"
    MOMENTUM_DOWN = "MOMENTUM_DOWN"


@dataclass(frozen=True)
class Tick:
    """Normalized price tick from a CEX (Binance or Coinbase)."""
    exchange: str          # "binance" | "coinbase"
    symbol: str            # e.g. "BTCUSDT"
    price: float
    timestamp: datetime
    volume: float = 0.0


@dataclass(frozen=True)
class FeatureVector:
    """
    Spot-derived features computed by the feature agent.
    Separating feature computation from decision logic keeps the decision
    rule mathematically defensible and avoids overfitting.
    """
    symbol: str
    timestamp: datetime
    spot_price: float         # current CEX spot price at feature computation time
    short_return: float       # return over last N seconds
    realized_vol: float       # rolling annualized vol (60s window, for signal detection)
    jump_detected: bool       # True if return exceeds jump threshold
    momentum_z: float         # z-score of short return vs rolling mean
    realized_vol_long: float = 0.0  # rolling annualized vol (15min window, for pricing). Falls back to realized_vol if 0.


@dataclass(frozen=True)
class Signal:
    """
    Deterministic output of the decision rule: features → implied prob shift.
    No learned model — pure math so the edge is defensible.
    """
    signal_type: SignalType
    symbol: str
    timestamp: datetime
    features: FeatureVector
    implied_prob_shift: float   # estimated direction of market prob move
    confidence: float           # in [0, 1], derived from feature strength
    # Optional: both clubs + actor (e.g. scorer) for Kalshi title matching
    match_teams: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class KalshiMarket:
    """A Kalshi prediction market that may be tradeable."""
    ticker: str              # unique market identifier, e.g. "KXFED-25MAY-T5.25"
    title: str               # market title / question (up to 200 chars)
    event_ticker: str        # parent event ticker
    yes_bid: float           # best bid for YES side (0–1 USD)
    yes_ask: float           # best ask for YES side (0–1 USD)
    no_bid: float            # best bid for NO side (0–1 USD)
    no_ask: float            # best ask for NO side (0–1 USD)
    implied_prob: float      # mid of yes_bid / yes_ask
    spread_pct: float        # (yes_ask - yes_bid) / implied_prob
    volume_24h: float        # 24-hour traded volume in USD
    liquidity: float         # available liquidity depth in USD
    close_time: str          # ISO datetime when the market closes
    timestamp: datetime      # snapshot time
    strike_type: str = ""    # "greater" | "less" | "between" | "" (from Kalshi API)
    floor_strike: Optional[float] = None  # lower bound (threshold floor or bracket floor)
    cap_strike: Optional[float] = None    # upper bound (bracket cap only)
    status: str = ""         # "unopened" | "open" | "closed" | "settled"
    result: str = ""         # "yes" | "no" | "" (populated when settled)


@dataclass(frozen=True)
class TradeOpportunity:
    """
    A scored market opportunity where model probability diverges from
    Kalshi's implied probability enough to justify a position.
    """
    signal: Signal
    market: KalshiMarket
    side: Side
    model_prob: float        # our estimated probability
    market_prob: float       # Kalshi's current implied probability (market mid)
    edge: float              # |model_prob - market_prob|
    kelly_fraction: float    # unconstrained Kelly bet fraction
    capped_fraction: float   # Kelly capped at MAX_KELLY_FRACTION


@dataclass(frozen=True)
class Order:
    """A paper or live order placed on Kalshi."""
    opportunity: TradeOpportunity
    size_usdc: float
    status: OrderStatus
    fill_price: Optional[float]
    placed_at: datetime
    filled_at: Optional[datetime] = None
    order_id: Optional[str] = None
    error: Optional[str] = None


