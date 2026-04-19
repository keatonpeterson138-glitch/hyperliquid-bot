"""HIP-4 Outcome (prediction market) client for Hyperliquid.

Provides read-only market data (works testnet + mainnet) and order
placement via SDK injection (mainnet) or raw HTTP signing (testnet).

Outcome token naming convention:
    coin  = f"#{encoding}"
    encoding = 10 * outcome_id + side   (side: 0 = Yes, 1 = No)
    asset_id = 100_000_000 + encoding   (used internally by L1)
"""
import logging
import re
import requests
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple

from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class OutcomeSide:
    """One side (Yes / No) of an outcome."""
    side: int              # 0 = Yes, 1 = No
    encoding: int          # 10 * outcome_id + side
    coin: str              # e.g. "#45680"
    asset_id: int          # 100_000_000 + encoding
    label: str             # "Yes" or "No"


@dataclass
class Outcome:
    """A single HIP-4 prediction-market outcome."""
    outcome_id: int
    question: str
    description: str
    sides: List[OutcomeSide] = field(default_factory=list)
    sz_decimals: int = 0

    # Parsed from description (populated by PriceBinaryParser)
    underlying: Optional[str] = None
    target_price: Optional[float] = None
    expiry: Optional[str] = None
    period: Optional[str] = None


@dataclass
class PriceBinaryParsed:
    """Parsed components from a price-binary outcome description."""
    underlying: str        # e.g. "BTC"
    target_price: float    # e.g. 100000.0
    direction: str         # "above" or "below"
    expiry: str            # e.g. "2025-06-30"
    period: str            # e.g. "end of June"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def outcome_to_coin(outcome_id: int, side: int) -> str:
    """Convert (outcome_id, side) → coin string like '#45680'."""
    return f"#{10 * outcome_id + side}"


def coin_to_outcome(coin: str) -> Tuple[int, int]:
    """Convert coin string like '#45680' → (outcome_id, side)."""
    encoding = int(coin.lstrip("#"))
    return encoding // 10, encoding % 10


def encoding_to_asset_id(encoding: int) -> int:
    """L1 asset id for an outcome encoding."""
    return 100_000_000 + encoding


# ---------------------------------------------------------------------------
# Price-Binary Description Parser
# ---------------------------------------------------------------------------

class PriceBinaryParser:
    """Parse HIP-4 price-binary outcome descriptions.

    Two known formats:

    1. Pipe-delimited (current API):
       "class:priceBinary|underlying:BTC|expiry:20260420-0300|targetPrice:75712|period:1d"

    2. Natural-language (possible future / custom):
       "Will BTC be above $100,000 by end of June 2025?"
    """

    # Pipe-delimited key:value pairs
    _PIPE_PATTERN = re.compile(r"class:priceBinary", re.IGNORECASE)

    # Natural-language fallback
    _NL_PATTERN = re.compile(
        r"Will\s+(\w+)\s+be\s+(above|below)\s+\$?([\d,._]+)\s+"
        r"(?:by|on|at|before)\s+(.+?)[\?\.]?\s*$",
        re.IGNORECASE,
    )

    @staticmethod
    def parse(description: str) -> Optional[PriceBinaryParsed]:
        """Try to parse a price-binary description. Returns None if not matched."""

        # --- Try pipe-delimited format first ---
        if PriceBinaryParser._PIPE_PATTERN.search(description):
            fields: Dict[str, str] = {}
            for part in description.split("|"):
                if ":" in part:
                    key, _, val = part.partition(":")
                    fields[key.strip().lower()] = val.strip()

            underlying = fields.get("underlying", "").upper()
            if not underlying:
                return None

            try:
                target_price = float(fields.get("targetprice", "0"))
            except ValueError:
                return None

            expiry = fields.get("expiry", "")
            period = fields.get("period", "")

            return PriceBinaryParsed(
                underlying=underlying,
                target_price=target_price,
                direction="above",  # priceBinary default
                expiry=expiry,
                period=period,
            )

        # --- Natural-language fallback ---
        m = PriceBinaryParser._NL_PATTERN.search(description)
        if not m:
            return None
        underlying = m.group(1).upper()
        direction = m.group(2).lower()
        price_str = m.group(3).replace(",", "").replace("_", "")
        try:
            target_price = float(price_str)
        except ValueError:
            return None
        period = m.group(4).strip().rstrip("?.")
        return PriceBinaryParsed(
            underlying=underlying,
            target_price=target_price,
            direction=direction,
            expiry=period,
            period=period,
        )


# ---------------------------------------------------------------------------
# OutcomeClient
# ---------------------------------------------------------------------------

class OutcomeClient:
    """Read market data and place orders for HIP-4 outcome tokens.

    Info layer uses raw HTTP (works on both testnet and mainnet).
    Order placement uses the SDK Exchange object with injected asset
    mappings (works on mainnet; testnet SDK has a known spot_meta bug,
    so we fall back to raw HTTP signing there).

    Usage:
        client = OutcomeClient(testnet=True)
        outcomes = client.fetch_outcomes()
        for o in outcomes:
            print(o.question, [s.coin for s in o.sides])

        book = client.fetch_l2_book("#45680")
        mids = client.fetch_outcome_mids()
    """

    TESTNET_URL = "https://api.hyperliquid-testnet.xyz"
    MAINNET_URL = "https://api.hyperliquid.xyz"

    def __init__(self, testnet: bool = True):
        self.testnet = testnet
        self.base_url = self.TESTNET_URL if testnet else self.MAINNET_URL
        self.info_url = f"{self.base_url}/info"

        # Cached outcome meta
        self._outcomes: Optional[List[Outcome]] = None
        # coin → OutcomeSide for fast lookup
        self._coin_map: Dict[str, OutcomeSide] = {}

        logger.info(f"OutcomeClient initialised (testnet={testnet})")

    # ------------------------------------------------------------------
    # Raw HTTP helper
    # ------------------------------------------------------------------

    def _post_info(self, payload: dict, timeout: int = 10) -> dict:
        """POST to /info and return parsed JSON."""
        resp = requests.post(self.info_url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Outcome meta
    # ------------------------------------------------------------------

    def fetch_outcomes(self, force: bool = False) -> List[Outcome]:
        """Fetch all HIP-4 outcomes from the API.

        Results are cached; pass force=True to refresh.
        Returns list of Outcome dataclasses.

        API response shape::

            {
              "outcomes": [
                {"outcome": 4557, "name": "...", "description": "...",
                 "sideSpecs": [{"name": "Yes"}, {"name": "No"}]},
                ...
              ],
              "questions": [
                {"question": 1, "name": "...", "description": "...",
                 "namedOutcomes": [10, 11], "fallbackOutcome": 13, ...},
                ...
              ]
            }
        """
        if self._outcomes is not None and not force:
            return self._outcomes

        data = self._post_info({"type": "outcomeMeta"})

        # Build question lookup  (question_id → question dict)
        questions_map: Dict[int, dict] = {}
        for q in data.get("questions", []):
            qid = q.get("question")
            if qid is not None:
                questions_map[int(qid)] = q

        outcomes: List[Outcome] = []

        for item in data.get("outcomes", []):
            oid = item.get("outcome")
            if oid is None:
                continue
            oid = int(oid)

            name = item.get("name", "")
            description = item.get("description", "")
            sz_decimals = int(item.get("szDecimals", 0))

            # Build sides from sideSpecs
            sides: List[OutcomeSide] = []
            for idx, spec in enumerate(item.get("sideSpecs", [])):
                encoding = 10 * oid + idx
                coin = f"#{encoding}"
                label = spec.get("name", "Yes" if idx == 0 else "No")
                os = OutcomeSide(
                    side=idx,
                    encoding=encoding,
                    coin=coin,
                    asset_id=encoding_to_asset_id(encoding),
                    label=label,
                )
                sides.append(os)
                self._coin_map[coin] = os

            # Use the question name if this outcome is part of a question group
            question_text = name

            outcome = Outcome(
                outcome_id=oid,
                question=question_text,
                description=description,
                sides=sides,
                sz_decimals=sz_decimals,
            )

            # Attempt description parse (price-binary pipe-delimited format)
            parsed = PriceBinaryParser.parse(description)
            if parsed:
                outcome.underlying = parsed.underlying
                outcome.target_price = parsed.target_price
                outcome.expiry = parsed.expiry
                outcome.period = parsed.period

            outcomes.append(outcome)

        self._outcomes = outcomes
        logger.info(f"Fetched {len(outcomes)} HIP-4 outcomes")
        return outcomes

    def get_outcome(self, outcome_id: int) -> Optional[Outcome]:
        """Get a single outcome by ID (fetches meta if needed)."""
        outcomes = self.fetch_outcomes()
        for o in outcomes:
            if o.outcome_id == outcome_id:
                return o
        return None

    def get_side(self, coin: str) -> Optional[OutcomeSide]:
        """Lookup an OutcomeSide by coin string (e.g. '#45680')."""
        if not self._coin_map:
            self.fetch_outcomes()
        return self._coin_map.get(coin)

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def fetch_outcome_mids(self) -> Dict[str, float]:
        """Fetch mid prices for all outcome tokens.

        Returns dict mapping coin → mid price (float).
        """
        data = self._post_info({"type": "allMids"})
        mids: Dict[str, float] = {}
        for coin, price in data.items():
            if coin.startswith("#"):
                try:
                    mids[coin] = float(price)
                except (ValueError, TypeError):
                    pass
        return mids

    def fetch_l2_book(self, coin: str, n_levels: int = 20) -> Dict:
        """Fetch L2 order book for an outcome token.

        Args:
            coin: Outcome coin string (e.g. '#45680')
            n_levels: Number of price levels per side.

        Returns:
            Raw API response with 'levels' key containing [bids, asks].
        """
        return self._post_info({
            "type": "l2Book",
            "coin": coin,
            "nSigFigs": 5,
        })

    def fetch_candles(
        self,
        coin: str,
        interval: str = "1h",
        limit: int = 100,
    ) -> List[Dict]:
        """Fetch OHLCV candles for an outcome token.

        Args:
            coin: Outcome coin string (e.g. '#45680')
            interval: '1m','5m','15m','1h','4h','1d'
            limit: Max number of candles.

        Returns:
            List of dicts with keys t, o, h, l, c, v.
        """
        import time
        interval_secs = {
            "1m": 60, "5m": 300, "15m": 900,
            "1h": 3600, "4h": 14400, "1d": 86400,
        }
        secs = interval_secs.get(interval, 3600)
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - secs * limit * 1000

        return self._post_info({
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
            },
        })

    def fetch_recent_trades(self, coin: str, limit: int = 100) -> List[Dict]:
        """Fetch recent trades for an outcome token.

        Returns list of trade dicts (raw API format).
        """
        return self._post_info({
            "type": "recentTrades",
            "coin": coin,
            "limit": limit,
        })

    def fetch_funding(self, coin: str) -> Optional[Dict]:
        """Fetch funding info for an outcome token (may not apply)."""
        try:
            return self._post_info({
                "type": "fundingHistory",
                "coin": coin,
                "startTime": 0,
            })
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Order placement (SDK injection)
    # ------------------------------------------------------------------

    def inject_into_sdk(
        self,
        info: Info,
        exchange: Optional[Exchange] = None,
    ) -> None:
        """Inject HIP-4 outcome tokens into an existing SDK Info/Exchange instance.

        After injection, the SDK's Exchange can place orders for outcome coins
        (e.g. '#45680') just like regular perps.

        NOTE: This only works when Info.__init__ has already succeeded (mainnet).
              On testnet the SDK crashes during init due to spot_meta bug.
        """
        outcomes = self.fetch_outcomes()
        for outcome in outcomes:
            for side in outcome.sides:
                info.coin_to_asset[side.coin] = side.asset_id
                info.name_to_coin[side.coin] = side.coin
                # Outcome token sizes are whole numbers (sz_decimals usually 0)
                info.asset_to_sz_decimals[side.asset_id] = outcome.sz_decimals

        if exchange is not None:
            exchange.info = info

        n = sum(len(o.sides) for o in outcomes)
        logger.info(f"Injected {n} outcome tokens into SDK")

    def place_order(
        self,
        exchange: Exchange,
        coin: str,
        is_buy: bool,
        sz: float,
        limit_px: float,
        reduce_only: bool = False,
        order_type: Optional[Dict] = None,
    ) -> Dict:
        """Place a limit order for an outcome token.

        Requires inject_into_sdk() to have been called first.

        Args:
            exchange: SDK Exchange instance (with injected info).
            coin: Outcome coin (e.g. '#45680').
            is_buy: True to buy, False to sell.
            sz: Size in contracts (whole numbers for outcome tokens).
            limit_px: Limit price (0.0 – 1.0 for outcome tokens).
            reduce_only: Close-only if True.
            order_type: SDK order type dict. Defaults to GTC limit.

        Returns:
            SDK response dict.
        """
        if order_type is None:
            order_type = {"limit": {"tif": "Gtc"}}

        try:
            result = exchange.order(
                coin,
                is_buy,
                sz,
                limit_px,
                order_type,
                reduce_only=reduce_only,
            )
            logger.info(
                f"Outcome order: {'BUY' if is_buy else 'SELL'} {sz} {coin} "
                f"@ {limit_px} → {result}"
            )
            return result
        except Exception as e:
            logger.error(f"Outcome order failed for {coin}: {e}", exc_info=True)
            raise

    def place_market_order(
        self,
        exchange: Exchange,
        coin: str,
        is_buy: bool,
        sz: float,
        slippage: float = 0.05,
    ) -> Dict:
        """Place a market-like order using IOC with slippage.

        Args:
            exchange: SDK Exchange instance (with injected info).
            coin: Outcome coin (e.g. '#45680').
            is_buy: True to buy, False to sell.
            sz: Size in contracts.
            slippage: Max slippage from mid price (e.g. 0.05 = 5 cents).

        Returns:
            SDK response dict.
        """
        mids = self.fetch_outcome_mids()
        mid = mids.get(coin)
        if mid is None:
            raise ValueError(f"No mid price found for {coin}")

        if is_buy:
            limit_px = min(mid + slippage, 1.0)
        else:
            limit_px = max(mid - slippage, 0.0)

        # Round to 5 significant figures (Hyperliquid requirement)
        limit_px = float(f"{limit_px:.5g}")

        order_type = {"limit": {"tif": "Ioc"}}
        return self.place_order(
            exchange, coin, is_buy, sz, limit_px,
            order_type=order_type,
        )

    def cancel_order(self, exchange: Exchange, coin: str, oid: int) -> Dict:
        """Cancel an open outcome order.

        Args:
            exchange: SDK Exchange instance.
            coin: Outcome coin.
            oid: Order ID to cancel.

        Returns:
            SDK response dict.
        """
        try:
            result = exchange.cancel(coin, oid)
            logger.info(f"Cancelled outcome order {oid} on {coin}")
            return result
        except Exception as e:
            logger.error(f"Cancel failed for {coin} oid={oid}: {e}", exc_info=True)
            raise

    def cancel_all_orders(self, exchange: Exchange, coin: str) -> List[Dict]:
        """Cancel all open orders for an outcome coin.

        Args:
            exchange: SDK Exchange instance.
            coin: Outcome coin.

        Returns:
            List of cancel results.
        """
        try:
            open_orders = exchange.info.open_orders(
                exchange.account.address
            )
            results = []
            for order in open_orders:
                if order.get("coin") == coin:
                    oid = order.get("oid")
                    if oid:
                        r = self.cancel_order(exchange, coin, oid)
                        results.append(r)
            return results
        except Exception as e:
            logger.error(f"Cancel all failed for {coin}: {e}", exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Convenience / summary
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """Human-readable summary of all outcomes and prices."""
        outcomes = self.fetch_outcomes()
        mids = self.fetch_outcome_mids()
        lines = [f"HIP-4 Outcomes ({len(outcomes)} total):"]
        for o in outcomes:
            prices = []
            for s in o.sides:
                mid = mids.get(s.coin)
                if mid is not None:
                    prices.append(f"{s.label}={mid:.4f}")
                else:
                    prices.append(f"{s.label}=N/A")
            lines.append(f"  [{o.outcome_id}] {o.question}  ({', '.join(prices)})")
        return "\n".join(lines)
