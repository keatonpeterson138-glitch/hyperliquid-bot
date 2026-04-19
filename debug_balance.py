"""Direct Hyperliquid API query to debug account balance."""
import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

WALLET = os.getenv("WALLET_ADDRESS", "")
if not WALLET:
    raise SystemExit("Set WALLET_ADDRESS in .env")
API_URL = "https://api.hyperliquid.xyz/info"

# 1. Query user state (clearinghouse)
print("=" * 60)
print("1. Clearinghouse state (user_state)")
print("=" * 60)
resp = requests.post(API_URL, json={
    "type": "clearinghouseState",
    "user": WALLET
}, timeout=10)
print(f"Status: {resp.status_code}")
data = resp.json()
print(json.dumps(data, indent=2)[:3000])

# 2. Query spot clearinghouse state
print("\n" + "=" * 60)
print("2. Spot clearinghouse state")
print("=" * 60)
resp2 = requests.post(API_URL, json={
    "type": "spotClearinghouseState",
    "user": WALLET
}, timeout=10)
print(f"Status: {resp2.status_code}")
data2 = resp2.json()
print(json.dumps(data2, indent=2)[:2000])

# 3. Check perps meta for reference
print("\n" + "=" * 60)
print("3. All mid prices (first 5)")
print("=" * 60)
resp3 = requests.post(API_URL, json={
    "type": "allMids"
}, timeout=10)
print(f"Status: {resp3.status_code}")
mids = resp3.json()
for k in list(mids.keys())[:5]:
    print(f"  {k}: ${mids[k]}")
