from dotenv import load_dotenv
load_dotenv()
from config import Config
from core.exchange import HyperliquidClient

c = HyperliquidClient(Config.PRIVATE_KEY, Config.WALLET_ADDRESS, Config.USE_TESTNET, Config.DEX)
pos = c.get_position("BTC")
if pos and float(pos["position"]["szi"]) != 0:
    print("Position OPEN:", pos["position"]["szi"], "BTC")
else:
    print("No open position - trade closed successfully!")
bal = c.get_balance()
print(f"Balance: ${bal:,.2f}")
