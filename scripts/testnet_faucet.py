"""Check testnet balance & open deposit page — no faucet API exists.

Usage:
    py scripts/testnet_faucet.py
"""
import json
import sys
import os
import webbrowser

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from dotenv import load_dotenv

load_dotenv()

WALLET = os.getenv("WALLET_ADDRESS", "")
API = "https://api.hyperliquid-testnet.xyz"


def check_and_fund():
    """Check testnet balance and help the user deposit."""
    if not WALLET:
        print("ERROR: WALLET_ADDRESS not set in .env")
        return

    print(f"Wallet: {WALLET}")
    print()

    # Check current balance
    balance = 0.0
    try:
        resp = requests.post(f"{API}/info", json={
            "type": "clearinghouseState",
            "user": WALLET,
        }, timeout=15)
        if resp.ok:
            data = resp.json()
            balance = float(data.get("marginSummary", {}).get("accountValue", "0"))
            withdrawable = float(data.get("withdrawable", "0"))
            positions = [p for p in data.get("assetPositions", [])
                        if float(p.get("position", {}).get("szi", "0")) != 0]
            print(f"  Account Value:  ${balance:,.2f}")
            print(f"  Withdrawable:   ${withdrawable:,.2f}")
            print(f"  Open Positions: {len(positions)}")
    except Exception as e:
        print(f"  Could not fetch balance: {e}")

    # Also check spot balance
    try:
        resp = requests.post(f"{API}/info", json={
            "type": "spotClearinghouseState",
            "user": WALLET,
        }, timeout=15)
        if resp.ok:
            data = resp.json()
            for bal in data.get("balances", []):
                token = bal.get("coin", "?")
                total = float(bal.get("total", "0"))
                if total > 0:
                    print(f"  Spot {token}: {total:,.2f}")
    except Exception:
        pass

    print()

    if balance > 0:
        print(f"✓ You already have ${balance:,.2f} on testnet. Ready to trade!")
        return

    print("=" * 60)
    print("  YOUR ACCOUNT HAS $0 — FOLLOW THESE STEPS TO FUND IT")
    print("=" * 60)
    print()
    print("  Hyperliquid testnet has NO public faucet API.")
    print("  You must deposit via the web UI bridge.")
    print()
    print("  STEP 1: Open the testnet app (opening now...)")
    print("     → https://app.hyperliquid-testnet.xyz")
    print()
    print("  STEP 2: Connect your wallet (MetaMask / Rabby)")
    print(f"     → Make sure it's address {WALLET[:10]}...")
    print()
    print("  STEP 3: Switch to Arbitrum Sepolia testnet in your wallet")
    print("     → Chain ID: 421614")
    print("     → RPC: https://sepolia-rollup.arbitrum.io/rpc")
    print()
    print("  STEP 4: Get Sepolia ETH for gas (free faucets):")
    print("     → https://www.alchemy.com/faucets/arbitrum-sepolia")
    print("     → https://faucet.quicknode.com/arbitrum/sepolia")
    print()
    print("  STEP 5: Get testnet USDC on Arbitrum Sepolia:")
    print("     → USDC contract: 0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238")
    print("     → Mint at: https://faucet.circle.com/ (select Arbitrum Sepolia)")
    print()
    print("  STEP 6: Click 'Deposit' in the testnet app and bridge USDC in")
    print()
    print("  ALTERNATIVE: If the web UI won't load in Chrome:")
    print("     → Try Edge or Brave browser")
    print("     → Try incognito/private mode")
    print("     → Disable all extensions temporarily")
    print("     → Clear cache for hyperliquid-testnet.xyz")
    print("=" * 60)

    # Open the testnet app
    try:
        webbrowser.open("https://app.hyperliquid-testnet.xyz")
    except Exception:
        pass


if __name__ == "__main__":
    check_and_fund()
