# -*- coding: utf-8 -*-
import json
import time
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import ccxt
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Windows stdout encoding fix
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Initialize CCXT Binance connection
exchange = ccxt.binance({
    "enableRateLimit": True,
    "timeout": 10000,
    "options": {"defaultType": "future"}, # Futures for futures prices, or spot if needed
})

def calculate_atr(df, period=14):
    """Calculate ATR on a DataFrame."""
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr

def load_signals(signals_path):
    signals = []
    if not signals_path.exists():
        return signals
    with open(signals_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    sig = json.loads(line)
                    # We are interested in signals with rejection reasons
                    # either BUY (score >= 0.65) or SHORT/SELL (score <= 0.40)
                    score = sig.get("weighted_score", 0.0)
                    rejs = sig.get("rejection_reasons", [])
                    if rejs:
                        if score >= 0.65:
                            sig["inferred_type"] = "BUY" # LONG
                            signals.append(sig)
                        elif score <= 0.40:
                            sig["inferred_type"] = "SELL" # SHORT
                            signals.append(sig)
                except Exception:
                    pass
    return signals

def main():
    print("Binance bağlanılıyor...")
    exchange.load_markets()
    
    signals_path = PROJECT_ROOT / "logs_v21" / "signals.jsonl"
    signals = load_signals(signals_path)
    
    if not signals:
        print("Test edilecek filtrelenmiş sinyal bulunamadı.")
        return
        
    print(f"Toplam {len(signals)} adet filtrelenmiş (reddedilmiş) sinyal yüklendi.")
    
    # Unique symbol-timeframe pairs
    pairs = set((s["symbol"], s["timeframe"]) for s in signals)
    print(f"Benzersiz Sembol-Timeframe çifti sayısı: {len(pairs)}")
    
    # Download historical OHLCV data for each unique pair
    # We will fetch up to 1000 candles to cover the signal times
    # Earliest signal timestamp:
    earliest_ts = min(datetime.fromisoformat(s["generated_at"].replace("Z", "+00:00")) for s in signals)
    since_ms = int(earliest_ts.timestamp() * 1000) - (24 * 3600 * 1000) # Subtract 1 day for ATR warming
    
    historical_data = {}
    for sym, tf in pairs:
        try:
            print(f"Veri indiriliyor: {sym} @ {tf}...")
            # Fetch futures ohlcv
            candles = exchange.fetch_ohlcv(sym, tf, since=since_ms, limit=1499)
            if not candles:
                print(f"  {sym} için veri boş döndü.")
                continue
                
            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.set_index("datetime")
            df["atr"] = calculate_atr(df, period=14)
            historical_data[(sym, tf)] = df
            time.sleep(0.1)
        except Exception as e:
            print(f"  HATA ({sym}@{tf}): {e}")
            
    # Now simulate each signal
    wins = 0
    losses = 0
    open_trades = 0
    no_data = 0
    
    filter_stats = {} # filter_name -> {wins, losses, open}
    
    print("\n=== FILTREYE TAKILAN SINYALLERIN SIMÜLASYON SONUÇLARI ===")
    print(f"{'Tarih':<16} | {'Sembol':<10} | {'Yön':<5} | {'Skor':<5} | {'Giriş':<8} | {'SL':<8} | {'TP':<8} | {'Sonuç':<6} | {'Red Nedeni'}")
    print("-" * 115)
    
    for sig in signals:
        sym = sig["symbol"]
        tf = sig["timeframe"]
        itype = sig["inferred_type"]
        entry = sig["entry_price"]
        score = sig["weighted_score"]
        rejs = sig["rejection_reasons"]
        gen_at_str = sig["generated_at"]
        
        # Convert generated_at to datetime object
        dt_gen = datetime.fromisoformat(gen_at_str.replace("Z", "+00:00"))
        if dt_gen.tzinfo is None:
            dt_gen = dt_gen.replace(tzinfo=timezone.utc)
        else:
            dt_gen = dt_gen.astimezone(timezone.utc)
        
        df = historical_data.get((sym, tf))
        if df is None or df.empty:
            no_data += 1
            continue
            
        # Find the candle at or just after gen_at
        # signals have millisecond precision, candles have round timestamps
        # We find the candle where df.index <= dt_gen, and take the closest
        matching_candles = df[df.index <= dt_gen]
        if matching_candles.empty:
            # Maybe the signal is slightly before our first candle
            matching_candles = df[df.index >= dt_gen]
            if matching_candles.empty:
                no_data += 1
                continue
            idx_candle = matching_candles.index[0]
        else:
            idx_candle = matching_candles.index[-1]
            
        # Get ATR at this candle
        row = df.loc[idx_candle]
        atr = row["atr"]
        if pd.isna(atr) or atr == 0:
            # Fallback ATR estimation (e.g. 1.5% of price)
            atr = entry * 0.015
            
        # Compute SL and TP
        risk = atr * 2.0
        if itype == "BUY": # LONG
            sl = entry - risk
            tp = entry + (2.0 * risk) # 1:2 Risk Reward Ratio
        else: # SHORT/SELL
            sl = entry + risk
            tp = entry - (2.0 * risk)
            
        # Simulate trade walking candles after idx_candle
        sub_df = df[df.index > idx_candle]
        outcome = "OPEN"
        
        for idx, r in sub_df.iterrows():
            if itype == "BUY":
                # Check SL
                if r["low"] <= sl:
                    outcome = "LOSS"
                    break
                # Check TP
                if r["high"] >= tp:
                    outcome = "WIN"
                    break
            else: # SHORT
                # Check SL
                if r["high"] >= sl:
                    outcome = "LOSS"
                    break
                # Check TP
                if r["low"] <= tp:
                    outcome = "WIN"
                    break
                    
        # Update stats
        if outcome == "WIN":
            wins += 1
        elif outcome == "LOSS":
            losses += 1
        else:
            open_trades += 1
            
        # Update filter stats
        primary_rej = rejs[0]
        # Clean up rejection reason label
        clean_rej = primary_rej
        if "BTC_BEARISH_TREND_BLOCKED" in primary_rej:
            clean_rej = "BTC Bearish Trend Block (F4)"
        elif "Hacim yetersiz" in primary_rej:
            clean_rej = "Hacim Yetersiz (F1)"
        elif "INSUFFICIENT_DAILY_VOLUME" in primary_rej:
            clean_rej = "Likidite Yetersiz (F5)"
        elif "ADX_RANGE_BLOCKED" in primary_rej:
            clean_rej = "ADX Yönsüz (F6)"
        elif "PUMP" in primary_rej:
            clean_rej = "Pump/Dump Dedektörü"
        elif "AI_REJECTED" in primary_rej:
            clean_rej = "AI Filtresi"
            
        if clean_rej not in filter_stats:
            filter_stats[clean_rej] = {"win": 0, "loss": 0, "open": 0}
        
        filter_stats[clean_rej][outcome.lower()] += 1
        
        # Print first few or interesting ones
        print(f"{dt_gen.strftime('%m-%d %H:%M'):<16} | {sym:<10} | {itype:<5} | {score:.3f} | {entry:<8.4f} | {sl:<8.4f} | {tp:<8.4f} | {outcome:<6} | {primary_rej[:40]}")
        
    print("\n" + "=" * 80)
    print("📊 GENEL SİMÜLASYON RAPORU")
    print("=" * 80)
    total_completed = wins + losses
    win_rate = wins / total_completed * 100 if total_completed > 0 else 0
    print(f"Toplam Simüle Edilen Sinyal : {wins + losses + open_trades}")
    print(f"  - Kazançla Kapanacaklar   : {wins} adet")
    print(f"  - Zararla Kapanacaklar    : {losses} adet")
    print(f"  - Hala Açık Kalanlar      : {open_trades} adet")
    print(f"  - Veri Eksikliği Nedeniyle: {no_data} adet atlandı")
    print(f"Tamamlanan İşlemlerde Başarı: %{win_rate:.2f}")
    print(f"Net Kar/Zarar Katkısı       : {wins - losses:+} R (Risk Birimi)")
    print("-" * 80)
    print("🛑 FİLTRE BAZINDA ENGELLEDİĞİ/KURTARDIĞI İŞLEMLER:")
    print("-" * 80)
    print(f"{'Filtre Adı':<35} | {'Engellenen':<10} | {'Kazanç':<8} | {'Zarar':<8} | {'Açık':<5} | {'Etki (Win-Loss)'}")
    print("-" * 80)
    for f_name, f_data in filter_stats.items():
        f_wins = f_data["win"]
        f_losses = f_data["loss"]
        f_open = f_data["open"]
        f_total = f_wins + f_losses + f_open
        f_impact = f_wins - f_losses
        # Impact represents how much we missed or saved.
        # If we blocked a LOSS, that is GOOD (+1 saved). If we blocked a WIN, that is BAD (-1 missed).
        # So Net Benefit of blocking = blocked_losses - blocked_wins
        net_benefit = f_losses - f_wins
        net_benefit_str = f"{net_benefit:+d}"
        print(f"{f_name:<35} | {f_total:<10} | {f_wins:<8} | {f_losses:<8} | {f_open:<5} | {net_benefit_str}")
    print("=" * 80)
    print("Açıklama: Net Benefit = Engellenen Zarar - Engellenen Kazanç")
    print("Pozitif (+) değerler filtrenin sizi zarardan koruduğunu gösterir (BAŞARILI).")
    print("Negatif (-) değerler filtrenin karlı işlemleri kaçırdığını gösterir.")

if __name__ == "__main__":
    main()
