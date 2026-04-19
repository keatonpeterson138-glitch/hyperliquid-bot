"""
Quick test: open and close a 0.001 BTC position on mainnet.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv()

from config import Config
from core.exchange import HyperliquidClient

SYMBOL = "BTC"
SIZE_BTC = 0.001  # ~$68 at current prices

print("=" * 60)
print("  HYPERLIQUID TEST TRADE")
print("=" * 60)
print(f"  Wallet:  {Config.WALLET_ADDRESS[:10]}...{Config.WALLET_ADDRESS[-6:]}")
print(f"  Testnet: {Config.USE_TESTNET}")
print(f"  Symbol:  {SYMBOL}")
print(f"  Size:    {SIZE_BTC} BTC")
print("=" * 60)

# Connect
print("\n[1/6] Connecting to Hyperliquid...")
client = HyperliquidClient(
    private_key=Config.PRIVATE_KEY,
    wallet_address=Config.WALLET_ADDRESS,
    testnet=Config.USE_TESTNET,
    dex=Config.DEX,
)

# Check balance (unified account: spot + perps share same margin)
print("[2/6] Checking account balance...")
balance = client.get_balance()
print(f"  Account balance: ${balance:,.2f}")

if balance < 10:
    print("  ✗ Balance too low. Deposit USDC to your Hyperliquid account first.")
    sys.exit(1)

# Get current price
print("[3/6] Getting BTC price...")
price = client.get_market_price(SYMBOL)
print(f"  BTC price: ${price:,.2f}")
print(f"  Trade value: ${SIZE_BTC * price:,.2f}")

# Set leverage low for safety
print("[4/6] Setting leverage to 3x (cross)...")
client.update_leverage(SYMBOL, 3, is_cross=True)

# Place buy order
print("[5/6] Opening LONG 0.001 BTC...")
try:
    result = client.exchange.market_open(
        name=SYMBOL,
        is_buy=True,
        sz=SIZE_BTC,
        slippage=0.05,
    )
    print(f"  Order result: {result}")
except Exception as e:
    print(f"  ✗ Order failed: {e}")
    sys.exit(1)

# Wait for fill
print("  Waiting 3s for fill...")
time.sleep(3)

# Check position
pos = client.get_position(SYMBOL)
if pos:
    pd = pos["position"]
    size = float(pd["szi"])
    entry = float(pd["entryPx"])
    pnl = float(pd["unrealizedPnl"])
    print(f"  ✓ Position open: {size} BTC @ ${entry:,.2f}  (PnL: ${pnl:.4f})")
else:
    print("  ✗ No position found. Order may not have filled.")
    sys.exit(1)

# Close position
print("[6/6] Closing position...")
try:
    close_result = client.exchange.market_close(
        coin=SYMBOL,
        slippage=0.05,
    )
    print(f"  Order result: {close_result}")
except Exception as e:
    print(f"  ✗ Close failed: {e}")
    sys.exit(1)

time.sleep(3)

# Verify closed
pos2 = client.get_position(SYMBOL)
if pos2 and float(pos2["position"]["szi"]) != 0:
    print(f"  ⚠ Position still open: {pos2['position']['szi']}")
else:
    print("  ✓ Position closed successfully!")

# Final balance
final_bal = client.get_balance()
pnl_total = final_bal - balance
print(f"\n{'=' * 60}")
print(f"  Starting balance: ${balance:,.2f}")
print(f"  Ending balance:   ${final_bal:,.2f}")
print(f"  Test P&L:         ${pnl_total:,.4f}")
print(f"{'=' * 60}")
print("  ✓ TEST COMPLETE - Bot can open and close trades!")
