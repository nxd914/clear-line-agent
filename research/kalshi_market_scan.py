"""
Kalshi Market Taxonomy Scanner
-------------------------------
Diagnostic + discovery tool. Runs a single paginated sweep of all open Kalshi
markets and prints:
  1. Raw JSON for the first two markets (field-name reference / sanity check).
  2. All markets whose category, series, or title contain sports-related keywords,
     sorted by 24h volume descending.

Usage:
    python -m trading.research.kalshi_market_scan

Requires KALSHI_API_KEY + KALSHI_PRIVATE_KEY_PATH in .env (repo root).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from pathlib import Path

import aiohttp
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
REQUEST_TIMEOUT = 15.0
MAX_PAGES = 10  # 10 × 200 = 2,000 markets — enough for field reference + sports taxonomy

SPORTS_KEYWORDS = {
    "soccer", "football", "nfl", "nba", "nhl", "mlb", "mls", "epl", "laliga",
    "bundesliga", "seriea", "ligue1", "champions", "ucl", "europa",
    "tennis", "wimbledon", "usopentennis", "golf", "masters", "pga",
    "nascar", "f1", "formula", "ufc", "boxing", "mma",
    "basketball", "baseball", "hockey", "cricket", "rugby",
    "fifa", "olympics", "superbowl", "worldcup",
    "esports", "cs2", "valorant", "league of legends",
}


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env", override=False)
    load_dotenv(override=False)


def _signed_headers(api_key: str, private_key, method: str, path: str) -> dict:
    timestamp_ms = int(time.time() * 1000)
    full_path = f"/trade-api/v2{path}"
    message = f"{timestamp_ms}{method}{full_path}".encode()
    signature = private_key.sign(
        message,
        asym_padding.PSS(
            mgf=asym_padding.MGF1(hashes.SHA256()),
            salt_length=asym_padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": api_key,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
        "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
        "User-Agent": "quant/0.3",
    }


def _load_key(path_str: str):
    expanded = Path(os.path.expanduser(path_str))
    pem_bytes = expanded.read_bytes()
    return serialization.load_pem_private_key(pem_bytes, password=None)


def _is_sports(market: dict) -> bool:
    haystack = " ".join([
        market.get("title", ""),
        market.get("subtitle", ""),
        market.get("category", ""),
        market.get("series_ticker", ""),
        market.get("event_ticker", ""),
        market.get("ticker", ""),
    ]).lower()
    return any(kw in haystack for kw in SPORTS_KEYWORDS)


async def scan(api_key: str, private_key) -> None:
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        all_markets: list[dict] = []
        cursor: str | None = None
        page = 0

        logger.info("Starting paginated sweep of /markets (status=open)...")

        while True:
            path = "/markets"
            params: dict = {"limit": 200, "status": "open"}
            if cursor:
                params["cursor"] = cursor

            headers = _signed_headers(api_key, private_key, "GET", path)
            url = KALSHI_BASE + path

            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 401:
                    logger.error("AUTH FAILED (401) — check KALSHI_API_KEY / key signature")
                    return
                if resp.status == 429:
                    logger.warning("Rate limited (429) — sleeping 10s")
                    await asyncio.sleep(10)
                    continue
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("HTTP %d — %s", resp.status, body[:300])
                    return

                data = await resp.json()

            raw_markets = data.get("markets") or []
            page += 1
            logger.info("Page %d: received %d markets (total so far: %d)",
                        page, len(raw_markets), len(all_markets) + len(raw_markets))

            # Print raw JSON for first two markets on the very first page
            if page == 1 and raw_markets:
                print("\n" + "=" * 70)
                print("RAW JSON — first 2 markets (field name reference):")
                print("=" * 70)
                for m in raw_markets[:2]:
                    print(json.dumps(m, indent=2, default=str))
                print("=" * 70 + "\n")

            all_markets.extend(raw_markets)
            cursor = data.get("cursor")
            if not cursor or not raw_markets or page >= MAX_PAGES:
                break

        logger.info("Sweep complete. Total markets fetched: %d", len(all_markets))

        # --- Sports taxonomy ---
        sports = [m for m in all_markets if _is_sports(m)]
        logger.info("Sports-related markets: %d of %d", len(sports), len(all_markets))

        # Sort by 24h volume — try common field names
        def _vol(m: dict) -> float:
            return float(m.get("volume_24h") or m.get("volume_24h_fp") or m.get("dollar_volume") or 0)

        sports.sort(key=_vol, reverse=True)

        print("\n" + "=" * 70)
        print(f"SPORTS MARKETS ON KALSHI ({len(sports)} found, sorted by 24h volume)")
        print("=" * 70)
        print(f"{'TICKER':<40} {'TITLE':<60} {'VOL_24H':>10}")
        print("-" * 115)
        for m in sports:
            ticker = m.get("ticker", "")[:38]
            title = m.get("title", "")[:58]
            vol = _vol(m)
            print(f"{ticker:<40} {title:<60} {vol:>10.0f}")

        # --- All categories present (for awareness) ---
        categories = {}
        for m in all_markets:
            cat = m.get("category") or m.get("series_ticker", "UNKNOWN")[:20]
            categories[cat] = categories.get(cat, 0) + 1
        print("\n" + "=" * 70)
        print("MARKET CATEGORIES (all markets)")
        print("=" * 70)
        for cat, count in sorted(categories.items(), key=lambda x: -x[1])[:30]:
            print(f"  {cat:<40} {count:>5}")

        # --- Price field names (from first market) ---
        if all_markets:
            first = all_markets[0]
            price_fields = [k for k in first.keys() if any(
                w in k.lower() for w in ("price", "ask", "bid", "yes", "no", "vol", "liq", "dollar")
            )]
            print("\n" + "=" * 70)
            print("PRICE / VOLUME FIELDS detected in first market:")
            print("=" * 70)
            for f in price_fields:
                print(f"  {f}: {first[f]}")


async def main() -> None:
    _load_env()

    api_key = os.environ.get("KALSHI_API_KEY", "").strip()
    key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "").strip()

    if not api_key or not key_path:
        logger.error(
            "Missing credentials. Set KALSHI_API_KEY and KALSHI_PRIVATE_KEY_PATH in .env"
        )
        return

    logger.info("Loaded API key: %s...", api_key[:8])
    private_key = _load_key(key_path)
    logger.info("Loaded RSA private key from %s", key_path)

    await scan(api_key, private_key)


if __name__ == "__main__":
    asyncio.run(main())
