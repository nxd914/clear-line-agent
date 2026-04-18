"""
Kelly criterion implementation with fractional capping.

For binary prediction markets:
  f* = (p * b - q) / b
  where p = win probability, q = 1 - p, b = net odds (payout - 1)

On a YES-outcome contract priced at `ask`:
  - Effective cost = ask + taker fee per contract
  - Payout on win = 1 / effective_cost  (resolves to $1)
  - b = (1 / effective_cost) - 1
  - p = our model probability

Kalshi taker fee: 0.07 × P × (1-P) per contract (parabolic, max at P=0.50).
See api-docs/kalshi-fee-schedule.pdf for the authoritative schedule.

We cap at MAX_KELLY_FRACTION to account for estimation error in p,
a standard OR/quant risk control. Typical cap: 0.25× to 0.5× full Kelly.
"""

MAX_KELLY_FRACTION = 0.25  # conservative half-Kelly analog
MIN_EDGE = 0.04            # don't trade if edge < 4 percentage points (accounts for fee drag)
MIN_KELLY = 0.01           # don't trade if Kelly < 1% of bankroll

KALSHI_TAKER_FEE_RATE = 0.07  # from api-docs/kalshi-fee-schedule.pdf


def kalshi_taker_fee_per_contract(price: float) -> float:
    """Continuous approximation of per-contract Kalshi taker fee.

    Actual fee is ceil(0.07 × C × P × (1-P)) for C contracts,
    but for Kelly sizing we use the continuous per-contract rate
    since we don't know C yet.
    """
    if price <= 0 or price >= 1:
        return 0.0
    return KALSHI_TAKER_FEE_RATE * price * (1.0 - price)


def compute_kelly(model_prob: float, market_price: float) -> float:
    """
    Compute unconstrained Kelly fraction for a binary market.

    Uses fee-adjusted effective price: the true cost per contract
    is the ask price plus the Kalshi taker fee.

    Args:
        model_prob:   our estimate of the true win probability
        market_price: current ask price for the YES token (in USDC, 0–1)

    Returns:
        Unconstrained Kelly fraction f* (may be negative → don't trade)
    """
    if market_price <= 0 or market_price >= 1:
        return 0.0
    effective_price = market_price + kalshi_taker_fee_per_contract(market_price)
    if effective_price >= 1.0:
        return 0.0
    b = (1.0 / effective_price) - 1.0
    q = 1.0 - model_prob
    return (model_prob * b - q) / b


def capped_kelly(model_prob: float, market_price: float) -> float:
    """
    Kelly fraction capped at MAX_KELLY_FRACTION.
    Handles both YES-side (model > market) and NO-side (model < market).
    Returns 0.0 if the trade doesn't meet minimum thresholds.
    """
    f = compute_kelly(model_prob, market_price)
    if f > 0:
        return min(f, MAX_KELLY_FRACTION)

    f_no = compute_kelly(1.0 - model_prob, 1.0 - market_price)
    if f_no > 0:
        return min(f_no, MAX_KELLY_FRACTION)

    return 0.0


def position_size(
    model_prob: float,
    market_price: float,
    bankroll_usdc: float,
) -> float:
    """
    Compute dollar position size after Kelly capping.
    Works for both YES and NO trades.

    Note: edge filtering is done upstream in the scanner (vs implied_prob/mid).
    This function only enforces MIN_KELLY to filter trivially small positions.
    """
    fraction = capped_kelly(model_prob, market_price)
    if fraction < MIN_KELLY:
        return 0.0

    return fraction * bankroll_usdc
