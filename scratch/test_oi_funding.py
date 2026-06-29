import ccxt
import pandas as pd
import datetime

exchange = ccxt.binance({
    "enableRateLimit": True,
    "options": {"defaultType": "future"}
})

print("Testing Binance Futures data fetching...")

# 1. Fetch OHLCV
symbol = "BTC/USDT"
timeframe = "15m"
since = exchange.parse8601((datetime.datetime.utcnow() - datetime.timedelta(days=2)).isoformat())

try:
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=10)
    print(f"OHLCV Success! Fetched {len(ohlcv)} candles. Sample: {ohlcv[0]}")
except Exception as e:
    print(f"OHLCV Error: {e}")

# 2. Fetch Funding Rate History
try:
    funding = exchange.fetch_funding_rate_history(symbol, since=since, limit=10)
    print(f"Funding Success! Fetched {len(funding)} items. Sample: {funding[0]}")
except Exception as e:
    print(f"Funding Error: {e}")

# 3. Fetch Open Interest History
try:
    oi_hist = exchange.fetch_open_interest_history(symbol, timeframe, since=since, limit=10)
    print(f"OI Success! Fetched {len(oi_hist)} items. Sample: {oi_hist[0]}")
except Exception as e:
    print(f"OI Error: {e}")
