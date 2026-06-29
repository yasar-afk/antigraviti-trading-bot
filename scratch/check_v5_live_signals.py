# -*- coding: utf-8 -*-
"""
scratch/check_v5_live_signals.py — Checks Binance Futures live data for V5 signals generated today.
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import ccxt
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Windows console output encoding fix
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.strategy.v5_pa_strategy import V5PriceActionStrategy

def main():
    print("Binance Futures bağlantısı kuruluyor...")
    exchange = ccxt.binance({
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}
    })
    
    try:
        print("Binance Futures aktif USDT pariteleri hacme göre çekiliyor...")
        tickers = exchange.fetch_tickers()
        usdt_tickers = []
        for sym, ticker in tickers.items():
            is_usdt = sym.endswith("/USDT") or sym.endswith("/USDT:USDT")
            if is_usdt and ticker.get("active", True) != False:
                base_vol = ticker.get("baseVolume") or 0.0
                close_price = ticker.get("close") or 0.0
                vol = ticker.get("quoteVolume") or (base_vol * close_price)
                if vol and vol > 0:
                    clean_sym = sym.split(":")[0]
                    usdt_tickers.append((clean_sym, vol))
                    
        usdt_tickers.sort(key=lambda x: x[1], reverse=True)
        top_100 = [sym for sym, _ in usdt_tickers[:100]]
        print(f"Top 100 USDT paritesi belirlendi. Canlı mum verileri indirilip analiz ediliyor...")
    except Exception as e:
        print(f"Binance'tan parite listesi alınamadı: {e}")
        return

    # Initialize V5 strategy
    v5_strat = V5PriceActionStrategy(
        sweep_window=100,
        max_hold_sweep=7,
        target_rr=5.5,
        require_trend=True,
        trend_ema=180,
        use_premium_discount=True,
        atr_multiplier=0.6,
        use_session_filter=False
    )
    
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    signals_found = []
    
    print("-" * 80)
    print(f"Tarih: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Bugün (15 Haziran 2026) tetiklenen sinyaller taranıyor...")
    print("-" * 80)
    
    processed = 0
    for symbol in top_100:
        try:
            # Fetch 250 candles to ensure enough history for EMA 180 and Sweep Window 100
            candles = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=250)
            if len(candles) < 220:
                continue
                
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            df = df.set_index('datetime')
            
            df_signals = v5_strat.calculate_signals(df)
            
            # Filter for signals generated today
            df_today = df_signals[df_signals.index >= today_start]
            
            # Check if any row has BUY or SELL signal
            today_signals = df_today[df_today['signal'].isin(['BUY', 'SELL'])]
            
            for dt, row in today_signals.iterrows():
                signals_found.append({
                    "symbol": symbol,
                    "datetime": dt,
                    "signal": row["signal"],
                    "price": row["close"],
                    "entry": row["entry_price"],
                    "sl": row["sl_price"],
                    "tp": row["tp_price"],
                    "has_fvg": row["has_fvg"]
                })
                
            processed += 1
            if processed % 20 == 0:
                print(f"İşlenen parite sayısı: {processed}/100...")
        except Exception as e:
            pass
            
    print("\n" + "=" * 80)
    print(f"📢 BUGÜNÜN (15 HAZİRAN 2026) V5 SİNYAL SONUÇLARI")
    print("=" * 80)
    if not signals_found:
        print("Bugün V5 stratejisi kurallarına uyan hiçbir sinyal oluşmadı.")
        print("Stratejimiz çok seçicidir, bu nedenle sinyal oluşmaması son derece normaldir.")
    else:
        print(f"Bugün toplam {len(signals_found)} adet sinyal tetiklendi:\n")
        print(f"{'Zaman (UTC)':<16} | {'Sembol':<10} | {'Yön':<5} | {'Giriş Fiyat':>11} | {'Stop-Loss':>11} | {'Kar-Al (TP)':>11} | {'Tip'}")
        print("-" * 80)
        for s in signals_found:
            entry_type = "LIMIT (FVG)" if s["has_fvg"] else "MARKET (CLOSE)"
            time_str = s["datetime"].strftime("%m-%d %H:%M")
            print(f"{time_str:<16} | {s['symbol']:<10} | {s['signal']:<5} | {s['entry']:>11.4f} | {s['sl']:>11.4f} | {s['tp']:>11.4f} | {entry_type}")
            
    print("=" * 80)

if __name__ == "__main__":
    main()
