import os
import sys
import time
import datetime
from pathlib import Path
import pandas as pd
import ccxt

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data" / "historical" / "15m"
DATA_DIR.mkdir(parents=True, exist_ok=True)

exchange = ccxt.binance({
    "enableRateLimit": True,
    "options": {"defaultType": "future"}
})

def get_top_100_symbols():
    print("Binance Futures pazarları yükleniyor...")
    exchange.load_markets()
    tickers = exchange.fetch_tickers()
    
    usdt_tickers = []
    for sym, ticker in tickers.items():
        is_usdt = (sym.endswith("/USDT") or sym.endswith("/USDT:USDT"))
        if is_usdt and ticker.get("active", True) != False:
            base_vol = ticker.get("baseVolume") or 0.0
            close_price = ticker.get("close") or 0.0
            vol = ticker.get("quoteVolume") or (base_vol * close_price)
            if vol and vol > 0:
                usdt_tickers.append((sym, vol))
                
    usdt_tickers.sort(key=lambda x: x[1], reverse=True)
    return [x[0] for x in usdt_tickers[:100]]

def clean_filename(symbol):
    return symbol.replace("/", "_").replace(":", "_")

def download_data_for_symbol(symbol, days=30):
    file_name = clean_filename(symbol) + "_15m.csv"
    file_path = DATA_DIR / file_name
    
    # Calculate start time
    now = datetime.datetime.utcnow()
    since_dt = now - datetime.timedelta(days=days)
    since_ms = int(since_dt.timestamp() * 1000)
    
    print(f"[{symbol}] Veriler indiriliyor ({days} gün)...")
    
    # 1. Fetch OHLCV in loops (since limit is 1000 per call, we need ~3 calls for 30 days of 15m)
    ohlcv_list = []
    current_since = since_ms
    while True:
        try:
            candles = exchange.fetch_ohlcv(symbol, "15m", since=current_since, limit=1000)
            if not candles:
                break
            ohlcv_list.extend(candles)
            # Check if we reached near the end
            last_ts = candles[-1][0]
            if last_ts == current_since or len(candles) < 1000 or last_ts >= int(now.timestamp() * 1000) - (15 * 60 * 1000):
                break
            current_since = last_ts + (15 * 60 * 1000)
            time.sleep(0.1)
        except Exception as e:
            print(f"  OHLCV indirme hatası: {e}")
            break
            
    if not ohlcv_list:
        print(f"  [{symbol}] Mum verisi alınamadı.")
        return False
        
    df_ohlcv = pd.DataFrame(ohlcv_list, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df_ohlcv = df_ohlcv.drop_duplicates(subset=["timestamp"]).reset_index(drop=True)
    df_ohlcv["datetime"] = pd.to_datetime(df_ohlcv["timestamp"], unit="ms", utc=True)
    df_ohlcv = df_ohlcv.set_index("datetime")
    
    # 2. Fetch Open Interest History (Binance limits historical Open Interest to the last 30 days)
    oi_list = []
    oi_since_dt = now - datetime.timedelta(days=min(30, days))
    current_since = int(oi_since_dt.timestamp() * 1000)
    while True:
        try:
            oi_hist = exchange.fetch_open_interest_history(symbol, "15m", since=current_since, limit=500)
            if not oi_hist:
                break
            oi_list.extend(oi_hist)
            last_ts = oi_hist[-1]["timestamp"]
            if last_ts == current_since or len(oi_hist) < 500 or last_ts >= int(now.timestamp() * 1000) - (15 * 60 * 1000):
                break
            current_since = last_ts + (15 * 60 * 1000)
            time.sleep(0.1)
        except Exception as e:
            # Some symbols might not support OI history or fail, we'll continue
            print(f"  OI indirme hatası: {e}")
            break
            
    # 3. Fetch Funding Rate History (~300 items for 100 days, limit = 500 is enough)
    funding_list = []
    try:
        funding = exchange.fetch_funding_rate_history(symbol, since=since_ms, limit=500)
        funding_list.extend(funding)
    except Exception as e:
        print(f"  Funding indirme hatası: {e}")
        
    # Process and Align
    # Open Interest alignment
    if oi_list:
        oi_records = []
        for entry in oi_list:
            oi_records.append({
                "timestamp": entry["timestamp"],
                "open_interest": entry["openInterestAmount"]
            })
        df_oi = pd.DataFrame(oi_records)
        df_oi = df_oi.drop_duplicates(subset=["timestamp"])
        df_oi["datetime"] = pd.to_datetime(df_oi["timestamp"], unit="ms", utc=True)
        df_oi = df_oi.set_index("datetime").drop(columns=["timestamp"])
        df_ohlcv = df_ohlcv.join(df_oi, how="left")
    else:
        df_ohlcv["open_interest"] = None
        
    # Funding Rate alignment
    if funding_list:
        funding_records = []
        for entry in funding_list:
            funding_records.append({
                "timestamp": entry["timestamp"],
                "funding_rate": entry["fundingRate"]
            })
        df_funding = pd.DataFrame(funding_records)
        df_funding = df_funding.drop_duplicates(subset=["timestamp"])
        df_funding["datetime"] = pd.to_datetime(df_funding["timestamp"], unit="ms", utc=True)
        df_funding = df_funding.set_index("datetime").drop(columns=["timestamp"])
        df_ohlcv = df_ohlcv.join(df_funding, how="left")
        # Forward fill the funding rate (as funding rate is updated every 8 hours)
        df_ohlcv["funding_rate"] = df_ohlcv["funding_rate"].ffill().bfill()
    else:
        df_ohlcv["funding_rate"] = 0.0
        
    # If OI is missing, we fill with 0.0
    df_ohlcv["open_interest"] = df_ohlcv["open_interest"].ffill().bfill().fillna(0.0)
    
    # Save combined
    df_ohlcv.to_csv(file_path)
    print(f"  [{symbol}] Başarılı! Toplam mum: {len(df_ohlcv)} | Son mum: {df_ohlcv.index[-1]}")
    return True

def main():
    symbols = get_top_100_symbols()
    print(f"Toplam {len(symbols)} sembol için 100 günlük 15m verisi indiriliyor...")
    print(f"Veri klasörü: {DATA_DIR}")
    print("-" * 50)
    
    success_count = 0
    for i, symbol in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] ", end="")
        try:
            ok = download_data_for_symbol(symbol, days=100)
            if ok:
                success_count += 1
            # Rate limit respect sleep
            time.sleep(0.2)
        except Exception as e:
            print(f"HATA: {e}")
            
    print("-" * 50)
    print(f"Tamamlandı! {success_count}/{len(symbols)} sembol başarıyla güncellendi.")

if __name__ == "__main__":
    main()
