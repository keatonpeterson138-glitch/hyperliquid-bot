"""Debug: try all known Hyperliquid API endpoints to find balance for unified account."""
import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

WALLET = os.getenv("WALLET_ADDRESS", "")
if not WALLET:
    raise SystemExit("Set WALLET_ADDRESS in .env")
API = "https://api.hyperliquid.xyz/info"

endpoints = [
    ("clearinghouseState", {"type": "clearinghouseState", "user": WALLET}),
    ("spotClearinghouseState", {"type": "spotClearinghouseState", "user": WALLET}),
    ("userFunding", {"type": "userFunding", "user": WALLET, "startTime": 0}),
    ("userFills", {"type": "userFills", "user": WALLET}),
    ("openOrders", {"type": "openOrders", "user": WALLET}),
    ("userTokenBalances", {"type": "userTokenBalances", "user": WALLET}),
    ("clearinghouseState (perp)", {"type": "clearinghouseState", "user": WALLET}),
]

for name, payload in endpoints:
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    try:
        resp = requests.post(API, json=payload, timeout=10)
        data = resp.json()
        out = json.dumps(data, indent=2)
        # Truncate long responses
        if len(out) > 1500:
            out = out[:1500] + "\n... (truncated)"
        print(out)
    except Exception as e:
        print(f"  Error: {e}")

# Also try the unified-specific approach: 
# check if crossMarginSummary or marginSummary has the balance
# or if we need to combine spot + perps
print(f"\n{'='*60}")
print("  Combined balance check")
print(f"{'='*60}")
try:
    # Perps
    r1 = requests.post(API, json={"type": "clearinghouseState", "user": WALLET}, timeout=10).json()
    perps_val = float(r1.get("marginSummary", r1.get("crossMarginSummary", {})).get("accountValue", 0))
    withdrawable = float(r1.get("withdrawable", 0))
    
    # Spot
    r2 = requests.post(API, json={"type": "spotClearinghouseState", "user": WALLET}, timeout=10).json()
    spot_usdc = 0
    for b in r2.get("balances", []):
        if b.get("coin") == "USDC":
            spot_usdc = float(b.get("total", 0))
    
    print(f"  Perps accountValue: ${perps_val}")
    print(f"  Perps withdrawable: ${withdrawable}")
    print(f"  Spot USDC: ${spot_usdc}")
    print(f"  Total: ${perps_val + spot_usdc}")
except Exception as e:
    print(f"  Error: {e}")
