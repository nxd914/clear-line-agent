"""
Kalshi WebSocket Agent

Maintains a real-time cache of market prices and volume by listening to the 
global 'ticker' channel. Reduces discovery latency from minutes to milliseconds.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional

from ..core.kalshi_client import KalshiWebsocketClient, _load_rsa_key
from ..core.models import KalshiMarket

logger = logging.getLogger(__name__)

class WebsocketAgent:
    """
    Manages the real-time WebSocket connection to Kalshi.
    Updates an in-memory price_cache that other agents can query.
    """
    def __init__(self, api_key: str, private_key_path: str):
        self.api_key = api_key
        expanded_path = Path(os.path.expanduser(str(private_key_path))) if private_key_path else None
        self.private_key = _load_rsa_key(expanded_path) if expanded_path else None
        self.client: Optional[KalshiWebsocketClient] = None
        self.price_cache: Dict[str, Dict[str, Any]] = {}
        self.is_running = False

    async def run(self):
        """Main loop with reconnection logic."""
        if not self.private_key:
            logger.error("WebsocketAgent: No private key found. Aborting.")
            return

        self.client = KalshiWebsocketClient(self.api_key, self.private_key)
        self.is_running = True
        
        retry_delay = 1.0
        while self.is_running:
            try:
                logger.info("WebsocketAgent: Connecting to Kalshi...")
                await self.client.connect()
                
                # Subscribe to the global ticker channel (no tickers param = all markets)
                logger.info("WebsocketAgent: Subscribing to global ticker channel...")
                await self.client.subscribe(channels=["ticker"])
                
                retry_delay = 1.0 # reset on success
                
                while self.is_running:
                    msg = await self.client.recv()
                    if not msg:
                        break # connection closed
                        
                    self._handle_message(msg)
                    
            except Exception as e:
                logger.warning(f"WebsocketAgent error: {e}. Retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(60.0, retry_delay * 2)

    def _handle_message(self, msg: Dict[str, Any]):
        """Parse incoming ticker messages and update the cache."""
        # Ticker message format: {"type": "ticker", "ticker": "...", "yes_bid": ..., "yes_ask": ..., ...}
        if msg.get("type") != "ticker":
            return
            
        ticker = msg.get("ticker")
        if not ticker:
            return
            
        # Update cache with normalized prices (integer cents -> prob 0-1)
        self.price_cache[ticker] = {
            "yes_bid": msg.get("yes_bid", 0) / 100.0,
            "yes_ask": msg.get("yes_ask", 0) / 100.0,
            "no_bid": msg.get("no_bid", 0) / 100.0,
            "no_ask": msg.get("no_ask", 0) / 100.0,
            "volume_24h": msg.get("volume_24h", 0), # ticker channel usually returns float USD
            "liquidity": msg.get("liquidity", 0),
            "last_price": msg.get("last_price", 0) / 100.0,
            "ts": msg.get("ts")
        }

    def get_price(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Query the latest price for a ticker."""
        return self.price_cache.get(ticker)
