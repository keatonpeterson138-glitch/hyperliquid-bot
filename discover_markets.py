"""Discover all HIP-3 builder-deployed perp dexes and their assets."""
import requests
import json

r = requests.post('https://api.hyperliquid.xyz/info', json={'type': 'perpDexs'})
data = r.json()

print(f"Total HIP-3 builder-deployed perp dexes: {len(data)}")
print("=" * 60)
# Print raw structure first
for i, dex in enumerate(data):
    if dex is None:
        print(f"\nDex #{i}: (null/undeployed)")
        continue
    if isinstance(dex, dict):
        name = dex.get("name", "unknown")
        deployer = dex.get("deployer", "unknown")
        oi_caps = dex.get("openInterestCaps", [])
        assets = [a[0] for a in oi_caps]
        print(f"\nDex #{i}: {name}")
        print(f"  Deployer: {deployer}")
        print(f"  Assets ({len(assets)}):")
        for asset in assets:
            print(f"    - {asset}")
    else:
        print(f"\nDex #{i}: {type(dex)} = {json.dumps(dex)[:200]}")

# Now get metadata for the 'cash' dex specifically
print("\n" + "=" * 60)
print("CASH DEX - detailed metadata:")
r2 = requests.post('https://api.hyperliquid.xyz/info', json={'type': 'meta', 'dex': 'cash'})
cash_meta = r2.json()
print(json.dumps(cash_meta, indent=2))

# Get current prices for cash dex
print("\n" + "=" * 60)
print("CASH DEX - current prices:")
r3 = requests.post('https://api.hyperliquid.xyz/info', json={'type': 'allMids', 'dex': 'cash'})
cash_mids = r3.json()
print(json.dumps(cash_mids, indent=2))
