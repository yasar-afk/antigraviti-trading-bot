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
import ta

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
    "options": {"defaultType": "future"},
})

def calculate_indicators(df):
    """Enrich df with ADX, Volume Ratio, and ATR."""
    df = df.copy()
    
    # ATR
    atr_ind = ta.volatility.AverageTrueRange(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=14,
    )
    df["atr"] = atr_ind.average_true_range()
    
    # ADX
    adx_ind = ta.trend.ADXIndicator(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=14,
    )
    df["adx"] = adx_ind.adx()
    
    # Volume Average & Ratio
    df["volume_avg"] = df["volume"].rolling(window=20).mean()
    df["volume_ratio"] = df["volume"] / df["volume_avg"]
    
    return df

def load_signals(signals_path):
    signals = []
    if not signals_path.exists():
        return signals
    with open(signals_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    sig = json.loads(line)
                    score = sig.get("weighted_score", 0.0)
                    rejs = sig.get("rejection_reasons", [])
                    if rejs:
                        if score >= 0.65:
                            sig["inferred_type"] = "BUY"
                            signals.append(sig)
                        elif score <= 0.40:
                            sig["inferred_type"] = "SELL"
                            signals.append(sig)
                except Exception:
                    pass
    return signals

def main():
    print("Binance'a bağlanılıyor...")
    exchange.load_markets()
    
    signals_path = PROJECT_ROOT / "logs_v21" / "signals.jsonl"
    signals = load_signals(signals_path)
    
    if not signals:
        print("Test edilecek filtrelenmiş sinyal bulunamadı.")
        return
        
    print(f"Toplam {len(signals)} adet filtrelenmiş (reddedilmiş) sinyal yüklendi.")
    
    pairs = set((s["symbol"], s["timeframe"]) for s in signals)
    print(f"Benzersiz Sembol-Timeframe çifti sayısı: {len(pairs)}")
    
    earliest_ts = min(datetime.fromisoformat(s["generated_at"].replace("Z", "+00:00")) for s in signals)
    since_ms = int(earliest_ts.timestamp() * 1000) - (48 * 3600 * 1000) # Subtract 2 days for indicator warming
    
    historical_data = {}
    for sym, tf in pairs:
        try:
            print(f"Veri indiriliyor: {sym} @ {tf}...")
            candles = exchange.fetch_ohlcv(sym, tf, since=since_ms, limit=1499)
            if not candles:
                continue
                
            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.set_index("datetime")
            df = calculate_indicators(df)
            historical_data[(sym, tf)] = df
            time.sleep(0.05)
        except Exception as e:
            print(f"  HATA ({sym}@{tf}): {e}")
            
    # Simulate each signal and store metric values along with simulated outcome
    simulated_signals = []
    
    for sig in signals:
        sym = sig["symbol"]
        tf = sig["timeframe"]
        itype = sig["inferred_type"]
        entry = sig["entry_price"]
        gen_at_str = sig["generated_at"]
        rejs = sig["rejection_reasons"]
        
        dt_gen = datetime.fromisoformat(gen_at_str.replace("Z", "+00:00"))
        if dt_gen.tzinfo is None:
            dt_gen = dt_gen.replace(tzinfo=timezone.utc)
        else:
            dt_gen = dt_gen.astimezone(timezone.utc)
            
        df = historical_data.get((sym, tf))
        if df is None or df.empty:
            continue
            
        matching_candles = df[df.index <= dt_gen]
        if matching_candles.empty:
            matching_candles = df[df.index >= dt_gen]
            if matching_candles.empty:
                continue
            idx_candle = matching_candles.index[0]
        else:
            idx_candle = matching_candles.index[-1]
            
        row = df.loc[idx_candle]
        atr = row["atr"]
        adx_val = row["adx"]
        volume_ratio = row["volume_ratio"]
        
        if pd.isna(atr) or atr == 0:
            atr = entry * 0.015
        if pd.isna(adx_val):
            adx_val = 15.0 # fallback
        if pd.isna(volume_ratio):
            volume_ratio = 0.5 # fallback
            
        # Calculate SL / TP
        risk = atr * 2.0
        if itype == "BUY":
            sl = entry - risk
            tp = entry + (2.0 * risk)
        else:
            sl = entry + risk
            tp = entry - (2.0 * risk)
            
        # Simulate walking forward
        sub_df = df[df.index > idx_candle]
        outcome = "OPEN"
        for idx, r in sub_df.iterrows():
            if itype == "BUY":
                if r["low"] <= sl:
                    outcome = "LOSS"
                    break
                if r["high"] >= tp:
                    outcome = "WIN"
                    break
            else:
                if r["high"] >= sl:
                    outcome = "LOSS"
                    break
                if r["low"] <= tp:
                    outcome = "WIN"
                    break
                    
        simulated_signals.append({
            "symbol": sym,
            "timeframe": tf,
            "inferred_type": itype,
            "adx": adx_val,
            "volume_ratio": volume_ratio,
            "outcome": outcome,
            "rejs": rejs
        })
        
    print(f"\nAnaliz edilmeye hazır {len(simulated_signals)} geçerli sinyal simüle edildi.")
    
    # Parameter sweep grid
    adx_thresholds = [0, 10, 12, 14, 15, 16, 18, 20] # 0 means disabled
    vol_thresholds = [0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0] # 0.0 means disabled
    
    results = []
    
    for adx_th in adx_thresholds:
        for vol_th in vol_thresholds:
            # Let's count how many trades pass these thresholds
            # and what their outcomes are.
            # Note: BTC bearish trend macro (F4) and other filters (F5 liquidity) are kept active.
            # We only sweep F1 (Volume) and F6 (ADX).
            wins = 0
            losses = 0
            opens = 0
            total_taken = 0
            
            for s in simulated_signals:
                # Keep other filters (like BTC Trend macro F4, AI block, F5 Spread) active if they blocked.
                # In signals, if the rejection reasons contain "BTC_BEARISH_TREND", "SPREAD", "INSUFFICIENT_DAILY_VOLUME", "AI_REJECTED",
                # it means the other filters blocked it, so it would still be blocked.
                other_block = False
                for r in s["rejs"]:
                    if "BTC_BEARISH_TREND" in r or "SPREAD" in r or "INSUFFICIENT_DAILY_VOLUME" in r or "AI_REJECTED" in r or "PUMP" in r:
                        other_block = True
                        break
                if other_block:
                    continue
                    
                # Now apply current candidate thresholds
                # Volume filter check
                if s["volume_ratio"] < vol_th:
                    continue # Blocked by Volume candidate
                    
                # ADX filter check
                if s["adx"] < adx_th:
                    continue # Blocked by ADX candidate
                    
                # If passed both candidates, we take the trade!
                total_taken += 1
                if s["outcome"] == "WIN":
                    wins += 1
                elif s["outcome"] == "LOSS":
                    losses += 1
                else:
                    opens += 1
                    
            completed = wins + losses
            win_rate = wins / completed * 100 if completed > 0 else 0.0
            
            # PnL in R (1 win = +2 R, 1 loss = -1 R)
            gross_pnl = (wins * 2) - losses
            # Commission fee (approx 0.25 R per trade taken)
            fees = total_taken * 0.15
            net_pnl = gross_pnl - fees
            
            results.append({
                "adx_th": adx_th,
                "vol_th": vol_th,
                "taken": total_taken,
                "wins": wins,
                "losses": losses,
                "opens": opens,
                "win_rate": win_rate,
                "gross_pnl": gross_pnl,
                "net_pnl": net_pnl
            })
            
    # Sort results by Net PnL descending
    results.sort(key=lambda x: x["net_pnl"], reverse=True)
    
    print("\n" + "=" * 100)
    print("📊 PARAMETRE SWEEP SONUÇLARI (Net PnL Sıralı)")
    print("=" * 100)
    print(f"{'ADX Eşiği':<10} | {'Vol Eşiği':<10} | {'İşlem':<7} | {'Kazanç':<7} | {'Zarar':<7} | {'Açık':<5} | {'Başarı %':<10} | {'Brüt R':<8} | {'Net R (Ücret Dahil)'}")
    print("-" * 100)
    for r in results[:20]: # Show top 20 configurations
        print(f"{r['adx_th']:<10} | {r['vol_th']:<10.1f} | {r['taken']:<7} | {r['wins']:<7} | {r['losses']:<7} | {r['opens']:<5} | {r['win_rate']:<10.2f} | {r['gross_pnl']:<+8.2f} | {r['net_pnl']:<+8.2f}")
        
    print("=" * 100)
    print("Açıklama: Net R = (Kazanç * 2) - (Zarar * 1) - (İşlem Sayısı * 0.15 R komisyon ücreti)")

if __name__ == "__main__":
    main()
