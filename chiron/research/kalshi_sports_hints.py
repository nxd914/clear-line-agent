"""Shared heuristics for identifying Kalshi sports markets (research scripts)."""

from __future__ import annotations

SPORTS_HINTS = (
    "nfl", "nba", "mlb", "nhl", "mls", "wnba", "ncaa", "ufc", "pga", "masters",
    "wimbledon", "tennis", "golf", "f1", "formula", "soccer", "football",
    "super bowl", "world series", "stanley cup", "championship", "playoff",
    "premier league", "champions league", "bundesliga", "la liga", "serie a",
    "ligue 1", "nascar", "boxing", "europa league", "fa cup", "copa", "mls cup",
    "world cup", "olympic", " vs ", " vs.",
    "kxnba", "kxnfl", "kxmlb", "kxnhl", "kxncaa", "kxufc", "kxten", "kxgolf",
    "kxpg", "kxuefa", "kxserie", "kxepl", "kxuel", "kxmls", "kxwta", "kxatp",
    "kxgame", "kxmvp", "kxheis", "kxcfb", "kxcbb",
)


def sports_haystack(title: str, ticker: str, event_ticker: str = "") -> str:
    return f"{title} {ticker} {event_ticker}".lower()


def is_sports_raw(raw: dict) -> bool:
    h = sports_haystack(
        str(raw.get("title") or ""),
        str(raw.get("ticker") or ""),
        str(raw.get("event_ticker") or ""),
    )
    return any(s in h for s in SPORTS_HINTS)


def raw_volume_24h(raw: dict) -> float:
    return float(raw.get("volume_24h") or raw.get("volume_24h_fp") or 0)
