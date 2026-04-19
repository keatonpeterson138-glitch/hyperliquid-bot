"""Hyperliquid exchange client wrapper."""
import logging
from typing import Optional, Dict, List
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
from eth_account.signers.local import LocalAccount
import eth_account

logger = logging.getLogger(__name__)


class HyperliquidClient:
    """Wrapper for Hyperliquid SDK with convenience methods."""
    
    def __init__(self, private_key: str, wallet_address: str, testnet: bool = True, dex: str = ""):
        """
        Initialize Hyperliquid client.
        
        Args:
            private_key: Ethereum private key (hex string without 0x)
            wallet_address: Ethereum wallet address
            testnet: Use testnet if True, mainnet if False
            dex: HIP-3 builder-deployed dex name ('' for native perps)
        """
        self.wallet_address = wallet_address
        self.testnet = testnet
        self.dex = dex  # '' = native, 'cash' = HIP-3 commodities/stocks
        
        # Initialize account from private key
        if private_key.startswith('0x'):
            private_key = private_key[2:]
        
        self.account: LocalAccount = eth_account.Account.from_key(private_key)
        
        # Initialize Exchange and Info clients
        base_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL

        # Pass perp_dexs so both Exchange and Info resolve HIP-3 asset IDs
        perp_dexs = [dex] if dex else None

        # Pre-load spot_meta with fallback to empty if testnet has bad data.
        # The bot trades perps/outcomes, not spot, so an empty spot_meta is safe.
        try:
            _info_tmp = Info(base_url, skip_ws=True)
            _spot = _info_tmp.spot_meta()
            # Validate: make sure token indices don't exceed list length
            for pair in _spot.get("universe", []):
                for idx in pair.get("tokens", []):
                    if idx >= len(_spot.get("tokens", [])):
                        raise IndexError("bad token index in spot_meta")
        except Exception:
            _spot = {"universe": [], "tokens": []}

        self.exchange = Exchange(self.account, base_url, spot_meta=_spot,
                                 perp_dexs=perp_dexs)
        self.info = Info(base_url, skip_ws=True, spot_meta=_spot,
                         perp_dexs=perp_dexs)
        
        logger.info(f"Initialized Hyperliquid client (testnet={testnet}, dex='{dex}')")
    
    def get_account_state(self) -> Dict:
        """Get current account state (balances, positions, etc)."""
        try:
            if self.dex:
                state = self.info.user_state(self.wallet_address, dex=self.dex)
            else:
                state = self.info.user_state(self.wallet_address)
            return state
        except Exception as e:
            logger.error(f"Failed to get account state: {e}")
            return {}
    
    def get_positions(self) -> List[Dict]:
        """Get all open positions."""
        state = self.get_account_state()
        return state.get('assetPositions', [])
    
    def get_position(self, symbol: str) -> Optional[Dict]:
        """Get position for a specific symbol."""
        positions = self.get_positions()
        for pos in positions:
            if pos['position']['coin'] == symbol:
                return pos
        return None
    
    def get_market_price(self, symbol: str) -> Optional[float]:
        """Get current market price for a symbol."""
        try:
            if self.dex:
                all_mids = self.info.all_mids(dex=self.dex)
            else:
                all_mids = self.info.all_mids()
            return float(all_mids.get(symbol, 0))
        except Exception as e:
            logger.error(f"Failed to get market price for {symbol}: {e}")
            return None

    def get_asset_context(self, symbol: str) -> Optional[Dict]:
        """
        Return live market context for *symbol* (volume, funding, OI, etc.).

        Returns dict with keys:
            dayNtlVlm, funding, openInterest, prevDayPx, markPx, midPx, oraclePx,
            premium, maxLeverage
        or None on failure.
        """
        try:
            result = self.info.post("/info", {
                "type": "metaAndAssetCtxs",
                **({"dex": self.dex} if self.dex else {}),
            })
            meta_universe = result[0]["universe"]
            asset_ctxs = result[1]

            # In cash-dex responses the names include the prefix (e.g. "cash:SILVER")
            lookup = symbol if self.dex else symbol
            for i, u in enumerate(meta_universe):
                if u["name"] == lookup:
                    ctx = dict(asset_ctxs[i])
                    ctx["maxLeverage"] = u.get("maxLeverage", 0)
                    return ctx
            logger.warning(f"Asset context not found for {symbol}")
            return None
        except Exception as e:
            logger.error(f"Failed to get asset context for {symbol}: {e}")
            return None

    def get_balance(self) -> float:
        """Get account value from on-chain margin summary.

        `accountValue` from marginSummary already includes all margin,
        unrealized PnL, and available balance.  Do NOT add spot balance
        on top — that double-counts on unified accounts.
        """
        state = self.get_account_state()
        try:
            margin_summary = (
                state.get('marginSummary')
                or state.get('crossMarginSummary')
                or {}
            )
            return float(margin_summary.get('accountValue', 0))
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return 0.0

    def get_spot_balance(self) -> float:
        """Get USDC balance on the spot (deposit) side."""
        try:
            import requests
            base_url = constants.TESTNET_API_URL if self.testnet else constants.MAINNET_API_URL
            resp = requests.post(f"{base_url}/info", json={
                "type": "spotClearinghouseState",
                "user": self.wallet_address,
            }, timeout=10)
            data = resp.json()
            for bal in data.get("balances", []):
                if bal.get("coin") == "USDC":
                    return float(bal.get("total", 0))
            return 0.0
        except Exception as e:
            logger.error(f"Failed to get spot balance: {e}")
            return 0.0

    def transfer_spot_to_perps(self, amount_usd: float) -> bool:
        """
        Transfer USDC from spot wallet to perps margin account.
        This is required before the bot can trade.
        """
        try:
            result = self.exchange.usd_class_transfer(
                amount=amount_usd,
                toPerp=True,
            )
            logger.info(f"Transferred ${amount_usd:.2f} from spot to perps: {result}")
            return True
        except Exception as e:
            logger.error(f"Spot→Perps transfer failed: {e}")
            return False
    
    def place_market_order(
        self,
        symbol: str,
        is_buy: bool,
        size_usd: float,
        leverage: int = 1,
        reduce_only: bool = False
    ) -> Optional[Dict]:
        """
        Place a market order.
        
        Args:
            symbol: Trading symbol (e.g. 'ETH')
            is_buy: True for long, False for short
            size_usd: Position size in USD
            leverage: Leverage to use (1-50)
            reduce_only: If True, only reduce existing position
        
        Returns:
            Order response dict or None if failed
        """
        try:
            # Get current price to calculate size in coins
            price = self.get_market_price(symbol)
            if not price:
                logger.error(f"Cannot place order: failed to get price for {symbol}")
                return None
            
            # Calculate size in base currency
            size = size_usd / price
            
            # Round to appropriate sz decimals
            meta = self.info.meta(dex=self.dex)
            sz_decimals = 4  # default
            for asset_info in meta.get('universe', []):
                if asset_info['name'] == symbol:
                    sz_decimals = asset_info['szDecimals']
                    break
            
            size = round(size, sz_decimals)
            
            logger.info(f"Placing {'LONG' if is_buy else 'SHORT'} market order: "
                       f"{symbol} size={size} (~${size_usd}), leverage={leverage}x")
            
            # Place order
            order_result = self.exchange.market_open(
                name=symbol,
                is_buy=is_buy,
                sz=size,
                slippage=0.05,
            )

            # Validate response
            if isinstance(order_result, dict) and order_result.get("status") == "err":
                err_msg = order_result.get("response", "unknown error")
                logger.error(f"Market order REJECTED for {symbol}: {err_msg}")
                return None

            # Check nested per-order errors
            if isinstance(order_result, dict):
                statuses = (order_result.get("response", {}).get("data", {})
                            .get("statuses", []))
                if statuses and isinstance(statuses[0], dict) and "error" in statuses[0]:
                    err_msg = statuses[0]["error"]
                    logger.error(f"Market order ERROR for {symbol}: {err_msg}")
                    return None
            
            logger.info(f"Order result: {order_result}")
            return order_result
            
        except Exception as e:
            logger.error(f"Failed to place market order: {e}", exc_info=True)
            return None
    
    def close_position(self, symbol: str) -> Optional[Dict]:
        """Close an open position for a symbol."""
        position = self.get_position(symbol)
        if not position:
            logger.warning(f"No position to close for {symbol}")
            return None
        
        try:
            pos_data = position['position']
            size = abs(float(pos_data['szi']))
            is_long = float(pos_data['szi']) > 0
            
            # To close: buy if short, sell if long
            is_buy = not is_long
            
            logger.info(f"Closing position for {symbol}: "
                       f"{'LONG' if is_long else 'SHORT'} size={size}")
            
            order_result = self.exchange.market_close(
                coin=symbol,
                slippage=0.05,
            )
            
            logger.info(f"Close order result: {order_result}")
            return order_result
            
        except Exception as e:
            logger.error(f"Failed to close position: {e}", exc_info=True)
            return None
    
    @staticmethod
    def _round_trigger_price(price: float, max_sigfigs: int = 5) -> float:
        """Round a trigger price to at most *max_sigfigs* significant figures.

        Hyperliquid rejects trigger prices with too many significant figures.
        """
        if price == 0:
            return 0.0
        from math import log10, floor
        d = floor(log10(abs(price)))
        decimals = max(0, max_sigfigs - 1 - d)
        return round(price, decimals)

    def place_trigger_order(
        self,
        symbol: str,
        is_buy: bool,
        size: float,
        trigger_price: float,
        tpsl: str = "sl",
    ) -> Optional[Dict]:
        """
        Place a trigger (stop-loss or take-profit) order on-chain.

        Args:
            symbol: Trading symbol (e.g. 'BTC')
            is_buy: True to buy (close a short), False to sell (close a long)
            size: Position size in base currency (coins)
            trigger_price: Price at which the order triggers
            tpsl: 'sl' for stop-loss, 'tp' for take-profit

        Returns:
            Order response dict or None if failed
        """
        try:
            # Round size to szDecimals for this asset
            meta = self.info.meta(dex=self.dex)
            sz_decimals = 4  # default
            for asset_info in meta.get('universe', []):
                if asset_info['name'] == symbol:
                    sz_decimals = asset_info['szDecimals']
                    break
            size = round(size, sz_decimals)

            # Round trigger price to ≤5 significant figures (API requirement)
            trigger_price = self._round_trigger_price(trigger_price)

            order_type = {
                "trigger": {
                    "triggerPx": trigger_price,
                    "isMarket": True,
                    "tpsl": tpsl,
                }
            }
            result = self.exchange.order(
                name=symbol,
                is_buy=is_buy,
                sz=size,
                limit_px=trigger_price,
                order_type=order_type,
                reduce_only=True,
            )

            # Validate API response – top-level and per-order status
            label = "TP" if tpsl == "tp" else "SL"
            if not isinstance(result, dict):
                logger.error(f"{label} trigger order got unexpected response: {result}")
                return None

            if result.get("status") == "err":
                err_msg = result.get("response", "unknown error")
                logger.error(f"{label} trigger order REJECTED for {symbol}: {err_msg}")
                return None

            # Check inside statuses array for per-order errors
            statuses = (result.get("response", {}).get("data", {})
                        .get("statuses", []))
            if statuses and isinstance(statuses[0], dict) and "error" in statuses[0]:
                err_msg = statuses[0]["error"]
                logger.error(f"{label} trigger order ERROR for {symbol}: {err_msg}")
                return None

            logger.info(f"Placed {label} trigger order for {symbol}: "
                        f"trigger@{trigger_price}, size={size}, is_buy={is_buy} → {result}")
            return result
        except Exception as e:
            logger.error(f"Failed to place trigger order ({tpsl}): {e}", exc_info=True)
            return None

    @staticmethod
    def extract_oid(order_result: Optional[Dict]) -> Optional[int]:
        """Extract the resting order ID from a trigger order response."""
        if not order_result or not isinstance(order_result, dict):
            return None
        try:
            statuses = (order_result.get("response", {})
                        .get("data", {}).get("statuses", []))
            if statuses and isinstance(statuses[0], dict):
                resting = statuses[0].get("resting", {})
                if isinstance(resting, dict):
                    return int(resting.get("oid", 0)) or None
        except (ValueError, TypeError, KeyError):
            pass
        return None

    def cancel_order_by_id(self, symbol: str, oid: int) -> bool:
        """Cancel a single order by its order ID. Returns True on success."""
        try:
            self.exchange.cancel(symbol, oid)
            logger.info(f"Cancelled order {oid} for {symbol}")
            return True
        except Exception as e:
            logger.warning(f"Failed to cancel order {oid} for {symbol}: {e}")
            return False

    def place_sl_tp_orders(
        self,
        symbol: str,
        is_long: bool,
        entry_price: float,
        size: float,
        sl_pct: float,
        tp_pct: float,
    ) -> Dict[str, Optional[Dict]]:
        """
        Place both SL and TP trigger orders for a new position.

        Args:
            symbol: Trading symbol
            is_long: True if position is long
            entry_price: Entry price of the position
            size: Position size in base currency (coins)
            sl_pct: Stop-loss percentage from entry
            tp_pct: Take-profit percentage from entry

        Returns:
            {'sl': result, 'tp': result} dict
        """
        if is_long:
            sl_price = self._round_trigger_price(entry_price * (1 - sl_pct / 100))
            tp_price = self._round_trigger_price(entry_price * (1 + tp_pct / 100))
            # To close a long we SELL
            sl_buy = False
            tp_buy = False
        else:
            sl_price = self._round_trigger_price(entry_price * (1 + sl_pct / 100))
            tp_price = self._round_trigger_price(entry_price * (1 - tp_pct / 100))
            # To close a short we BUY
            sl_buy = True
            tp_buy = True

        logger.info(f"Placing SL@{sl_price} & TP@{tp_price} for "
                     f"{'LONG' if is_long else 'SHORT'} {symbol} "
                     f"(entry={entry_price}, size={size})")

        sl_result = self.place_trigger_order(symbol, sl_buy, size, sl_price, "sl")
        tp_result = self.place_trigger_order(symbol, tp_buy, size, tp_price, "tp")

        return {
            "sl": sl_result,
            "tp": tp_result,
            "sl_oid": self.extract_oid(sl_result),
            "tp_oid": self.extract_oid(tp_result),
        }

    def cancel_open_orders(self, symbol: str) -> bool:
        """
        Cancel all open orders (including trigger/SL/TP) for a symbol.

        Returns:
            True if all cancellations succeeded (or none to cancel)
        """
        try:
            if self.dex:
                orders = self.info.frontend_open_orders(self.wallet_address, dex=self.dex)
            else:
                orders = self.info.frontend_open_orders(self.wallet_address)

            to_cancel = [o for o in orders if o.get("coin") == symbol]
            if not to_cancel:
                logger.debug(f"No open orders to cancel for {symbol}")
                return True

            for o in to_cancel:
                oid = o.get("oid")
                if oid is not None:
                    self.exchange.cancel(symbol, int(oid))
                    logger.info(f"Cancelled order {oid} for {symbol}")

            return True
        except Exception as e:
            logger.error(f"Failed to cancel open orders for {symbol}: {e}", exc_info=True)
            return False

    def get_open_order_oids(self, symbol: str) -> set:
        """Return set of oids for all open/trigger orders on *symbol*."""
        try:
            if self.dex:
                orders = self.info.frontend_open_orders(self.wallet_address, dex=self.dex)
            else:
                orders = self.info.frontend_open_orders(self.wallet_address)
            return {int(o["oid"]) for o in orders
                    if o.get("coin") == symbol and o.get("oid") is not None}
        except Exception as e:
            logger.error(f"Failed to get open order oids for {symbol}: {e}")
            return set()

    def close_partial_position(self, symbol: str, size: float, is_long: bool) -> Optional[Dict]:
        """Close a partial position by placing an opposite-side market order.

        Args:
            symbol: Trading symbol
            size: Number of coins to close
            is_long: True if the position being closed is long (we sell to close)

        Returns:
            Order response dict or None on failure.
        """
        try:
            is_buy = not is_long  # buy to close short, sell to close long
            result = self.exchange.market_open(
                name=symbol,
                is_buy=is_buy,
                sz=size,
                slippage=0.05,
            )
            logger.info(f"Partial close {symbol} size={size} is_long={is_long}: {result}")
            return result
        except Exception as e:
            logger.error(f"Failed partial close {symbol}: {e}", exc_info=True)
            return None

    def get_position_size(self, symbol: str) -> float:
        """Get the absolute size (in coins) of the current position for a symbol."""
        pos = self.get_position(symbol)
        if not pos:
            return 0.0
        return abs(float(pos['position']['szi']))

    def update_leverage(self, symbol: str, leverage: int, is_cross: bool = True) -> bool:
        """
        Update leverage for a symbol.
        
        Args:
            symbol: Trading symbol
            leverage: Desired leverage (1-50)
            is_cross: Use cross margin (False = isolated, required for HIP-3)
        
        Returns:
            True if successful
        """
        try:
            result = self.exchange.update_leverage(leverage, symbol, is_cross=is_cross)
            mode = 'cross' if is_cross else 'isolated'
            logger.info(f"Updated leverage for {symbol} to {leverage}x ({mode}): {result}")
            return True
        except Exception as e:
            logger.error(f"Failed to update leverage: {e}")
            return False
