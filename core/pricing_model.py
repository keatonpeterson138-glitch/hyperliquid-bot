"""Price-binary pricing model for HIP-4 outcome tokens.

Uses Black-Scholes digital (cash-or-nothing) option framework to calculate
theoretical fair-value probabilities given:
    - spot price of the underlying
    - strike / target price
    - time to expiry
    - annualised volatility

Also provides:
    - implied-volatility solver  (market price -> vol)
    - historical-volatility calculator (from candle data)
    - Greeks (delta, gamma, vega, theta)
    - convenience wrappers that pull live data from OutcomeClient
"""
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SECONDS_PER_YEAR = 365.25 * 24 * 3600
MIN_T = 1e-10          # floor for time-to-expiry (avoid /0)
MIN_VOL = 1e-6         # floor for volatility
MAX_VOL = 50.0         # ceiling for implied-vol search
NEWTON_ITERS = 50      # max Newton-Raphson iterations
NEWTON_TOL = 1e-8      # convergence tolerance
BISECT_ITERS = 100     # max bisection iterations


# ---------------------------------------------------------------------------
# Normal CDF / PDF  (Abramowitz & Stegun 26.2.17, |error| < 7.5e-8)
# ---------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    """Standard-normal cumulative distribution function."""
    if x > 10.0:
        return 1.0
    if x < -10.0:
        return 0.0
    a1, a2, a3, a4, a5 = (
        0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    )
    p = 0.3275911
    sign = 1.0 if x >= 0 else -1.0
    x_abs = abs(x)
    t = 1.0 / (1.0 + p * x_abs)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(
        -x_abs * x_abs / 2.0
    )
    return 0.5 * (1.0 + sign * y)


def _norm_pdf(x: float) -> float:
    """Standard-normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


# ---------------------------------------------------------------------------
# Expiry parsing
# ---------------------------------------------------------------------------

def parse_expiry(expiry_str: str) -> datetime:
    """Parse HIP-4 expiry string into a timezone-aware UTC datetime.

    Accepted formats:
        '20260420-0300'  ->  2026-04-20 03:00 UTC
        '2026-04-20'     ->  2026-04-20 00:00 UTC
    """
    expiry_str = expiry_str.strip()
    if "-" in expiry_str and len(expiry_str) == 13:
        # Format: YYYYMMDD-HHMM
        dt = datetime.strptime(expiry_str, "%Y%m%d-%H%M")
    elif len(expiry_str) == 13:
        dt = datetime.strptime(expiry_str, "%Y%m%d-%H%M")
    elif len(expiry_str) == 10:
        dt = datetime.strptime(expiry_str, "%Y-%m-%d")
    elif len(expiry_str) == 8:
        dt = datetime.strptime(expiry_str, "%Y%m%d")
    else:
        raise ValueError(f"Cannot parse expiry: {expiry_str!r}")
    return dt.replace(tzinfo=timezone.utc)


def time_to_expiry_years(
    expiry_str: str,
    now: Optional[datetime] = None,
) -> float:
    """Seconds until expiry, expressed in years.

    Returns 0.0 if already expired.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    expiry_dt = parse_expiry(expiry_str)
    delta_s = (expiry_dt - now).total_seconds()
    if delta_s <= 0:
        return 0.0
    return delta_s / SECONDS_PER_YEAR


# ---------------------------------------------------------------------------
# Core pricer: digital (cash-or-nothing) option
# ---------------------------------------------------------------------------

@dataclass
class BinaryPrice:
    """Result of a binary option pricing calculation."""
    fair_yes: float        # probability / fair value of Yes token (0-1)
    fair_no: float         # probability / fair value of No  token (0-1)
    d2: float              # Black-Scholes d2 term
    spot: float
    strike: float
    t_years: float
    vol: float

    # Greeks (per Yes token)
    delta: float = 0.0     # dPrice/dSpot
    gamma: float = 0.0     # d2Price/dSpot2
    vega: float = 0.0      # dPrice/dVol  (per 1% vol move)
    theta: float = 0.0     # dPrice/dTime (per day)


def price_binary(
    spot: float,
    strike: float,
    t_years: float,
    vol: float,
    direction: str = "above",
    r: float = 0.0,
) -> BinaryPrice:
    """Price a binary (digital cash-or-nothing) option.

    For HIP-4 price-binary markets, Yes pays 1 if the underlying
    finishes *above* the target price at expiry (digital call).
    No is the complement.

    Args:
        spot: Current price of the underlying.
        strike: Target / strike price.
        t_years: Time to expiry in years.
        vol: Annualised volatility (e.g. 0.80 = 80%).
        direction: 'above' (digital call) or 'below' (digital put).
        r: Risk-free rate (annualised, default 0 for crypto).

    Returns:
        BinaryPrice with fair values and Greeks.
    """
    t = max(t_years, MIN_T)
    sigma = max(vol, MIN_VOL)

    ln_ratio = math.log(spot / strike) if spot > 0 and strike > 0 else 0.0
    sqrt_t = math.sqrt(t)

    d1 = (ln_ratio + (r + 0.5 * sigma * sigma) * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t

    discount = math.exp(-r * t)
    call_prob = discount * _norm_cdf(d2)
    put_prob = 1.0 - call_prob

    if direction == "above":
        fair_yes = call_prob
        fair_no = put_prob
    else:
        fair_yes = put_prob
        fair_no = call_prob

    # --- Greeks (for the Yes side) ---
    pdf_d2 = _norm_pdf(d2)

    # Delta: dP/dSpot
    delta = discount * pdf_d2 / (spot * sigma * sqrt_t) if spot > 0 else 0.0
    if direction == "below":
        delta = -delta

    # Gamma: d2P/dSpot2
    gamma_val = (
        -discount * pdf_d2 * d1 / (spot * spot * sigma * sigma * t)
        if spot > 0 else 0.0
    )
    if direction == "below":
        gamma_val = -gamma_val

    # Vega: dPrice/dVol (scaled to per 1% vol move)
    vega = -discount * pdf_d2 * d1 / sigma * 0.01
    if direction == "below":
        vega = -vega

    # Theta: dPrice/dTime (per calendar day)
    if t > MIN_T and spot > 0:
        theta_yr = discount * pdf_d2 * (
            ln_ratio / (sigma * t * sqrt_t * 2.0)
            + (r + 0.5 * sigma * sigma) / (2.0 * sigma * sqrt_t)
        )
        if r != 0.0:
            theta_yr -= r * discount * _norm_cdf(d2)
    else:
        theta_yr = 0.0
    theta_per_day = theta_yr / 365.25
    if direction == "below":
        theta_per_day = -theta_per_day

    return BinaryPrice(
        fair_yes=max(0.0, min(1.0, fair_yes)),
        fair_no=max(0.0, min(1.0, fair_no)),
        d2=d2,
        spot=spot,
        strike=strike,
        t_years=t,
        vol=sigma,
        delta=delta,
        gamma=gamma_val,
        vega=vega,
        theta=theta_per_day,
    )


# ---------------------------------------------------------------------------
# Implied-volatility solver
# ---------------------------------------------------------------------------

def implied_vol(
    market_price: float,
    spot: float,
    strike: float,
    t_years: float,
    direction: str = "above",
    r: float = 0.0,
    initial_guess: float = 0.8,
) -> Optional[float]:
    """Solve for the implied volatility of a binary outcome token.

    Uses Newton-Raphson with bisection fallback.

    Args:
        market_price: Observed market price of the Yes token (0-1).
        spot: Underlying spot price.
        strike: Target / strike price.
        t_years: Time to expiry in years.
        direction: 'above' or 'below'.
        r: Risk-free rate.
        initial_guess: Starting vol for Newton search.

    Returns:
        Annualised implied vol, or None if solver fails.
    """
    if market_price <= 0.0 or market_price >= 1.0:
        return None
    if t_years <= 0.0:
        return None

    # --- Newton-Raphson ---
    sigma = initial_guess
    for _ in range(NEWTON_ITERS):
        bp = price_binary(spot, strike, t_years, sigma, direction, r)
        diff = bp.fair_yes - market_price
        # Vega is per 1% move, convert to per-unit
        vega_unit = bp.vega * 100.0
        if abs(vega_unit) < 1e-12:
            break
        sigma -= diff / vega_unit
        sigma = max(MIN_VOL, min(MAX_VOL, sigma))
        if abs(diff) < NEWTON_TOL:
            return sigma

    # --- Bisection fallback ---
    lo, hi = MIN_VOL, MAX_VOL
    for _ in range(BISECT_ITERS):
        mid = (lo + hi) / 2.0
        bp = price_binary(spot, strike, t_years, mid, direction, r)
        diff = bp.fair_yes - market_price
        if abs(diff) < NEWTON_TOL:
            return mid
        if diff > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


# ---------------------------------------------------------------------------
# Historical volatility from candle data
# ---------------------------------------------------------------------------

def historical_vol(
    closes: List[float],
    period_seconds: float = 3600.0,
) -> float:
    """Calculate annualised historical volatility from close prices.

    Uses log-returns with Bessel correction.

    Args:
        closes: List of close prices (oldest first).
        period_seconds: Time between each close in seconds
                        (3600 for 1h candles, 86400 for 1d).

    Returns:
        Annualised volatility (e.g. 0.80 = 80%).
    """
    if len(closes) < 3:
        return 0.0

    log_returns = []
    for i in range(1, len(closes)):
        if closes[i] > 0 and closes[i - 1] > 0:
            log_returns.append(math.log(closes[i] / closes[i - 1]))

    n = len(log_returns)
    if n < 2:
        return 0.0

    mean = sum(log_returns) / n
    var = sum((r - mean) ** 2 for r in log_returns) / (n - 1)
    std = math.sqrt(var)

    # Annualise: multiply by sqrt(periods_per_year)
    periods_per_year = SECONDS_PER_YEAR / period_seconds
    return std * math.sqrt(periods_per_year)


def historical_vol_from_candles(
    candles: List[Dict],
    interval: str = "1h",
) -> float:
    """Calculate historical vol from raw candle dicts (API format).

    Args:
        candles: List of dicts with 'c' (close) key.
        interval: Candle interval string for period mapping.

    Returns:
        Annualised volatility.
    """
    interval_secs = {
        "1m": 60, "5m": 300, "15m": 900,
        "1h": 3600, "4h": 14400, "1d": 86400,
    }
    period = interval_secs.get(interval, 3600)
    closes = []
    for c in candles:
        try:
            closes.append(float(c["c"]))
        except (KeyError, ValueError, TypeError):
            continue
    return historical_vol(closes, period)


# ---------------------------------------------------------------------------
# PriceBinaryModel  -  high-level wrapper
# ---------------------------------------------------------------------------

class PriceBinaryModel:
    """High-level pricing model for HIP-4 price-binary outcomes.

    Combines the core pricer with live data from OutcomeClient to produce
    theoretical prices, implied vols, and edge estimates.

    Usage::

        from core.outcome_client import OutcomeClient
        from core.pricing_model import PriceBinaryModel

        oc = OutcomeClient(testnet=True)
        model = PriceBinaryModel(oc)

        # Analyse all price-binary outcomes
        for r in model.analyse_all(default_vol=0.80):
            print(r)

        # Single outcome
        result = model.analyse(outcome_id=4557, vol=0.80)
    """

    def __init__(self, outcome_client):
        """
        Args:
            outcome_client: An OutcomeClient instance (or None for offline use).
        """
        self.oc = outcome_client

    # ------------------------------------------------------------------
    # Expiry helpers
    # ------------------------------------------------------------------

    @staticmethod
    def parse_expiry(expiry_str: str) -> datetime:
        """Parse an HIP-4 expiry string into UTC datetime."""
        return parse_expiry(expiry_str)

    @staticmethod
    def time_to_expiry(expiry_str: str, now: Optional[datetime] = None) -> float:
        """Time to expiry in years."""
        return time_to_expiry_years(expiry_str, now)

    # ------------------------------------------------------------------
    # Spot price fetching
    # ------------------------------------------------------------------

    def _fetch_spot(self, underlying: str) -> Optional[float]:
        """Fetch the spot price for an underlying from allMids.

        Looks for the perp mid (e.g. 'BTC') in the full allMids response.
        """
        if self.oc is None:
            return None
        try:
            data = self.oc._post_info({"type": "allMids"})
            price = data.get(underlying)
            if price is not None:
                return float(price)
            # Try with @-suffix variants
            for key, val in data.items():
                if key.upper() == underlying.upper():
                    return float(val)
        except Exception as e:
            logger.warning(f"Could not fetch spot for {underlying}: {e}")
        return None

    def _fetch_historical_vol(
        self,
        underlying: str,
        interval: str = "1h",
        limit: int = 168,
    ) -> float:
        """Fetch candles for the underlying and compute historical vol.

        Default: 168 x 1h candles = 1 week of data.
        """
        if self.oc is None:
            return 0.0
        try:
            candles = self.oc.fetch_candles(underlying, interval, limit)
            if candles:
                return historical_vol_from_candles(candles, interval)
        except Exception as e:
            logger.warning(f"Could not fetch hist vol for {underlying}: {e}")
        return 0.0

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    @dataclass
    class AnalysisResult:
        """Result of analysing a single price-binary outcome."""
        outcome_id: int
        underlying: str
        target_price: float
        expiry: str
        period: str
        spot: float
        t_years: float
        vol_used: float
        vol_source: str        # 'provided', 'historical', 'default'

        # Theoretical values
        theory: BinaryPrice

        # Market values
        market_yes: Optional[float] = None
        market_no: Optional[float] = None

        # Edge = theory - market  (positive = market is cheap)
        edge_yes: Optional[float] = None
        edge_no: Optional[float] = None

        # Implied vol from market price
        implied_vol: Optional[float] = None

        @property
        def is_expired(self) -> bool:
            return self.t_years <= 0.0

        def __str__(self) -> str:
            mv = f"mkt={self.market_yes:.4f}" if self.market_yes else "mkt=N/A"
            ev = f"edge={self.edge_yes:+.4f}" if self.edge_yes is not None else "edge=N/A"
            iv = f"iv={self.implied_vol:.1%}" if self.implied_vol else "iv=N/A"
            return (
                f"[{self.outcome_id}] {self.underlying} "
                f"target={self.target_price:,.0f} "
                f"T={self.t_years:.6f}y ({self.period}) "
                f"theo={self.theory.fair_yes:.4f} {mv} {ev} "
                f"vol={self.vol_used:.1%} {iv}"
            )

    def analyse(
        self,
        outcome_id: int,
        vol: Optional[float] = None,
        spot: Optional[float] = None,
        default_vol: float = 0.80,
    ) -> Optional["PriceBinaryModel.AnalysisResult"]:
        """Analyse a single price-binary outcome.

        Args:
            outcome_id: The HIP-4 outcome ID.
            vol: Override volatility. If None, tries historical then default.
            spot: Override spot price. If None, fetches live.
            default_vol: Fallback vol if historical is unavailable.

        Returns:
            AnalysisResult or None if outcome not found / not price-binary.
        """
        outcome = self.oc.get_outcome(outcome_id) if self.oc else None
        if outcome is None or outcome.underlying is None:
            return None

        # Spot
        if spot is None:
            spot = self._fetch_spot(outcome.underlying)
        if spot is None or spot <= 0:
            logger.warning(f"No spot price for {outcome.underlying}")
            return None

        # Time to expiry
        t_years = time_to_expiry_years(outcome.expiry) if outcome.expiry else 0.0

        # Volatility
        vol_source = "default"
        vol_used = default_vol
        if vol is not None:
            vol_used = vol
            vol_source = "provided"
        else:
            hv = self._fetch_historical_vol(outcome.underlying)
            if hv > 0.01:
                vol_used = hv
                vol_source = "historical"

        # Price
        direction = "above"  # HIP-4 priceBinary default
        theory = price_binary(spot, outcome.target_price, t_years, vol_used, direction)

        # Market prices
        market_yes = None
        market_no = None
        edge_yes = None
        edge_no = None
        iv = None

        if self.oc is not None:
            mids = self.oc.fetch_outcome_mids()
            if outcome.sides:
                yes_coin = outcome.sides[0].coin
                no_coin = outcome.sides[1].coin if len(outcome.sides) > 1 else None
                market_yes = mids.get(yes_coin)
                if no_coin:
                    market_no = mids.get(no_coin)

            if market_yes is not None:
                edge_yes = theory.fair_yes - market_yes
                iv = implied_vol(market_yes, spot, outcome.target_price, t_years, direction)
            if market_no is not None:
                edge_no = theory.fair_no - market_no

        return PriceBinaryModel.AnalysisResult(
            outcome_id=outcome.outcome_id,
            underlying=outcome.underlying,
            target_price=outcome.target_price,
            expiry=outcome.expiry or "",
            period=outcome.period or "",
            spot=spot,
            t_years=t_years,
            vol_used=vol_used,
            vol_source=vol_source,
            theory=theory,
            market_yes=market_yes,
            market_no=market_no,
            edge_yes=edge_yes,
            edge_no=edge_no,
            implied_vol=iv,
        )

    def analyse_all(
        self,
        vol: Optional[float] = None,
        default_vol: float = 0.80,
    ) -> List["PriceBinaryModel.AnalysisResult"]:
        """Analyse all price-binary outcomes.

        Args:
            vol: Override vol for all (None = auto per underlying).
            default_vol: Fallback vol.

        Returns:
            List of AnalysisResult for every price-binary outcome.
        """
        if self.oc is None:
            return []

        outcomes = self.oc.fetch_outcomes()
        results = []
        for o in outcomes:
            if o.underlying is None:
                continue
            r = self.analyse(o.outcome_id, vol=vol, default_vol=default_vol)
            if r is not None:
                results.append(r)
        return results

    def edge_table(
        self,
        vol: Optional[float] = None,
        default_vol: float = 0.80,
        min_edge: float = 0.0,
    ) -> str:
        """Human-readable edge table for all price-binary outcomes.

        Args:
            vol: Override vol.
            default_vol: Fallback vol.
            min_edge: Only show outcomes with |edge| >= this.

        Returns:
            Formatted string table.
        """
        results = self.analyse_all(vol=vol, default_vol=default_vol)
        if not results:
            return "No price-binary outcomes found."

        lines = [
            f"{'ID':>6} {'Under':>6} {'Strike':>10} {'Period':>6} "
            f"{'Spot':>10} {'T(yr)':>10} {'Theo':>6} {'Mkt':>6} "
            f"{'Edge':>7} {'IV':>7} {'Vol':>7} {'Src':>5}",
            "-" * 100,
        ]
        for r in results:
            if min_edge > 0 and r.edge_yes is not None and abs(r.edge_yes) < min_edge:
                continue
            mkt = f"{r.market_yes:.4f}" if r.market_yes is not None else "  N/A "
            edge = f"{r.edge_yes:+.4f}" if r.edge_yes is not None else "  N/A "
            iv = f"{r.implied_vol:.1%}" if r.implied_vol is not None else "  N/A "
            lines.append(
                f"{r.outcome_id:>6} {r.underlying:>6} "
                f"{r.target_price:>10,.0f} {r.period:>6} "
                f"{r.spot:>10,.2f} {r.t_years:>10.6f} "
                f"{r.theory.fair_yes:>6.4f} {mkt:>6} "
                f"{edge:>7} {iv:>7} {r.vol_used:>6.1%} {r.vol_source:>5}"
            )
        return "\n".join(lines)
