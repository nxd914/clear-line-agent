"""
Execution Agent

Receives approved (opportunity, size_usdc) pairs from the risk agent
and places orders on Kalshi via the authenticated API.

Modes:
  PAPER  — simulates fills at current market mid, logs to SQLite
  LIVE   — places real orders via KalshiClient (disabled until paper validates)

Switch via EXECUTION_MODE env var: "paper" (default) or "live"
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..core.models import Order, OrderStatus, Side, TradeOpportunity

logger = logging.getLogger(__name__)

EXECUTION_MODE = os.environ.get("EXECUTION_MODE", "paper")
DB_PATH = Path(__file__).parent.parent / "data" / "paper_trades.db"


class ExecutionAgent:
    """
    Places orders (paper or live) and persists trade records.
    """

    def __init__(
        self,
        approved_queue: asyncio.Queue[tuple[TradeOpportunity, float]],
        risk_agent=None,   # typed weakly to avoid circular import
    ) -> None:
        self._approved = approved_queue
        self._risk_agent = risk_agent
        self._db = self._init_db()

    async def run(self) -> None:
        while True:
            opp, size_usdc = await self._approved.get()
            order = await self._execute(opp, size_usdc)
            self._persist(order)
            logger.info(
                "Order %s | %s | %.2f USDC | fill=%.4f",
                order.status.value,
                opp.market.title[:50],
                size_usdc,
                order.fill_price or 0.0,
            )

    async def _execute(
        self, opp: TradeOpportunity, size_usdc: float
    ) -> Order:
        if EXECUTION_MODE == "live":
            return await self._live_order(opp, size_usdc)
        return self._paper_order(opp, size_usdc)

    def _paper_order(self, opp: TradeOpportunity, size_usdc: float) -> Order:
        """Simulate fill at current market ask (no slippage model yet)."""
        fill_price = (
            opp.market.yes_ask
            if opp.side == Side.YES
            else opp.market.no_ask
        )
        now = datetime.now(tz=timezone.utc)
        return Order(
            opportunity=opp,
            size_usdc=size_usdc,
            status=OrderStatus.FILLED,
            fill_price=fill_price,
            placed_at=now,
            filled_at=now,
            order_id=f"paper_{uuid.uuid4().hex[:12]}",
        )

    async def _live_order(self, opp: TradeOpportunity, size_usdc: float) -> Order:
        """
        Place a real order via KalshiClient.
        NOT activated until paper trading validates the edge.
        """
        raise NotImplementedError(
            "Live execution is disabled. Set EXECUTION_MODE=paper to run paper trades. "
            "Enable live trading only after paper Sharpe >= 1.0 over 2+ weeks."
        )

    def _persist(self, order: Order) -> None:
        opp = order.opportunity
        # Audit: spot price at the moment the signal fired
        spot_price = opp.signal.features.spot_price if opp.signal else 0.0
        # Audit: latency from signal to order placement
        signal_latency_ms = 0.0
        if opp.signal and opp.signal.timestamp:
            delta = (order.placed_at - opp.signal.timestamp).total_seconds()
            signal_latency_ms = delta * 1000.0
        realized_vol = opp.signal.features.realized_vol_long if opp.signal else 0.0
        kelly_fraction = opp.capped_fraction
        try:
            self._db.execute(
                """
                INSERT INTO trades (
                    order_id, ticker, title, side,
                    model_prob, market_prob, edge,
                    size_usdc, fill_price, status,
                    placed_at, filled_at,
                    spot_price_at_signal, signal_latency_ms,
                    realized_vol, kelly_fraction
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.order_id,
                    opp.market.ticker,
                    opp.market.title[:200],
                    opp.side.value,
                    opp.model_prob,
                    opp.market_prob,
                    opp.edge,
                    order.size_usdc,
                    order.fill_price,
                    order.status.value,
                    order.placed_at.isoformat(),
                    order.filled_at.isoformat() if order.filled_at else None,
                    spot_price,
                    signal_latency_ms,
                    realized_vol,
                    kelly_fraction,
                ),
            )
            self._db.commit()
        except sqlite3.Error as exc:
            logger.error("DB write error: %s", exc)

    def _init_db(self) -> sqlite3.Connection:
        # Ensure data directory exists and table is initialized
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT,
                ticker TEXT,
                title TEXT,
                side TEXT,
                model_prob REAL,
                market_prob REAL,
                edge REAL,
                size_usdc REAL,
                fill_price REAL,
                status TEXT,
                placed_at TEXT,
                filled_at TEXT,
                resolved_at TEXT,
                resolution TEXT,
                pnl_usdc REAL,
                spot_price_at_signal REAL,
                signal_latency_ms REAL,
                realized_vol REAL,
                kelly_fraction REAL
            )
        """)
        # Migrate existing DBs: add new audit columns if missing
        existing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()
        }
        for col in ("spot_price_at_signal", "signal_latency_ms", "realized_vol", "kelly_fraction"):
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE trades ADD COLUMN {col} REAL")
        conn.commit()
        return conn
