"""Test script to verify bot setup."""
import sys

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    
    try:
        import config
        print("✓ config")
        
        from core import exchange, market_data, risk_manager
        print("✓ core.exchange")
        print("✓ core.market_data")
        print("✓ core.risk_manager")
        
        from strategies import base, ema_crossover, rsi_mean_reversion, breakout, factory
        print("✓ strategies.base")
        print("✓ strategies.ema_crossover")
        print("✓ strategies.rsi_mean_reversion")
        print("✓ strategies.breakout")
        print("✓ strategies.factory")
        
        print("\n✓ All imports successful!")
        return True
        
    except ImportError as e:
        print(f"\n✗ Import failed: {e}")
        return False


def test_strategy_creation():
    """Test creating strategy instances."""
    print("\nTesting strategy creation...")
    
    try:
        from strategies.factory import get_strategy
        
        strategies = ['ema_crossover', 'rsi_mean_reversion', 'breakout']
        for strat_name in strategies:
            strategy = get_strategy(strat_name)
            print(f"  {strategy}")
        
        print("  All strategies created successfully!")
        return True
        
    except Exception as e:
        print(f"\n  Strategy creation failed: {e}")
        return False


def test_hip3_markets():
    """Test fetching HIP-3 cash dex markets (GOLD, SILVER, stocks)."""
    print("\nTesting HIP-3 cash dex market discovery...")
    
    try:
        import requests
        r = requests.post(
            'https://api.hyperliquid.xyz/info',
            json={'type': 'meta', 'dex': 'cash'},
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
        assets = [u['name'] for u in data.get('universe', [])]
        
        print(f"  Found {len(assets)} HIP-3 cash dex assets:")
        for a in assets:
            max_lev = next(
                (u['maxLeverage'] for u in data['universe'] if u['name'] == a), '?'
            )
            print(f"    {a}  (max {max_lev}x)")
        
        # Verify gold and silver exist
        has_gold = any('GOLD' in a for a in assets)
        has_silver = any('SILVER' in a for a in assets)
        print(f"  Gold available: {has_gold}")
        print(f"  Silver available: {has_silver}")
        
        # Get current prices
        r2 = requests.post(
            'https://api.hyperliquid.xyz/info',
            json={'type': 'allMids', 'dex': 'cash'},
            timeout=10
        )
        mids = r2.json()
        print("  Current prices:")
        for sym, price in sorted(mids.items()):
            print(f"    {sym}: ${float(price):,.2f}")
        
        return True
    except Exception as e:
        print(f"  HIP-3 market test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("Hyperliquid Trading Bot - Setup Verification")
    print("=" * 60)
    
    results = []
    results.append(test_imports())
    results.append(test_strategy_creation())
    results.append(test_hip3_markets())
    
    print("\n" + "=" * 60)
    if all(results):
        print("All tests passed! Bot is ready to configure and run.")
        print("\nNext steps:")
        print("1. Copy .env.example to .env")
        print("2. Fill in your Hyperliquid credentials in .env")
        print("3. Set DEX= for crypto, or DEX=cash for gold/silver/stocks")
        print("4. Run: py bot.py")
    else:
        print("Some tests failed. Please install dependencies:")
        print("   py -m pip install -r requirements.txt")
    print("=" * 60)
    
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
