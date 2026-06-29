# -*- coding: utf-8 -*-
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import argparse

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Windows console output encoding fix
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.strategy.v3_pa_strategy import V3PriceActionStrategy

DATA_DIR = PROJECT_ROOT / "data" / "historical" / "1h"

def run_simulation(df, strategy):
    """Simulates trading using FVG limit orders, partial TP, and BE stop adjustments."""
    df_signals = strategy.calculate_signals(df)
    
    trades = []
    active_trade = None
    
    for i in range(len(df_signals)):
        # If there is an active trade, check its SL/TP conditions
        if active_trade is not None:
            k_low = df_signals["low"].iloc[i]
            k_high = df_signals["high"].iloc[i]
            k_close = df_signals["close"].iloc[i]
            k_dt = df_signals.index[i]
            
            side = active_trade["side"]
            entry_price = active_trade["entry_price"]
            sl_price = active_trade["sl_price"]
            partial_tp = active_trade["partial_tp"]
            final_tp = active_trade["final_tp"]
            stage = active_trade["stage"]
            
            if side == "BUY": # LONG
                if stage == 1:
                    # Check SL
                    if k_low <= sl_price:
                        # Reached SL in stage 1 -> full loss (-1.0 R)
                        active_trade["outcome"] = "LOSS"
                        active_trade["exit_price"] = sl_price
                        active_trade["exit_datetime"] = k_dt
                        active_trade["pnl_r"] = -1.0
                        trades.append(active_trade)
                        active_trade = None
                    # Check Partial TP
                    elif k_high >= partial_tp:
                        # Reached Partial TP! Scale out 50%, move stop to entry (BE)
                        active_trade["stage"] = 2
                        active_trade["sl_price"] = entry_price
                        active_trade["locked_r"] = 0.5 * strategy.partial_rr # +0.75 R
                elif stage == 2:
                    # Check SL (which is now at entry price)
                    if k_low <= entry_price:
                        active_trade["outcome"] = "BE"
                        active_trade["exit_price"] = entry_price
                        active_trade["exit_datetime"] = k_dt
                        active_trade["pnl_r"] = active_trade["locked_r"] # +0.75 R
                        trades.append(active_trade)
                        active_trade = None
                    # Check Final TP
                    elif k_high >= final_tp:
                        active_trade["outcome"] = "WIN"
                        active_trade["exit_price"] = final_tp
                        active_trade["exit_datetime"] = k_dt
                        active_trade["pnl_r"] = active_trade["locked_r"] + 0.5 * strategy.target_rr # +0.75 + 1.5 = +2.25 R
                        trades.append(active_trade)
                        active_trade = None
                        
            elif side == "SELL": # SHORT
                if stage == 1:
                    # Check SL
                    if k_high >= sl_price:
                        # Reached SL in stage 1 -> full loss (-1.0 R)
                        active_trade["outcome"] = "LOSS"
                        active_trade["exit_price"] = sl_price
                        active_trade["exit_datetime"] = k_dt
                        active_trade["pnl_r"] = -1.0
                        trades.append(active_trade)
                        active_trade = None
                    # Check Partial TP
                    elif k_low <= partial_tp:
                        # Reached Partial TP! Scale out 50%, move stop to entry (BE)
                        active_trade["stage"] = 2
                        active_trade["sl_price"] = entry_price
                        active_trade["locked_r"] = 0.5 * strategy.partial_rr # +0.75 R
                elif stage == 2:
                    # Check SL (which is now at entry price)
                    if k_high >= entry_price:
                        active_trade["outcome"] = "BE"
                        active_trade["exit_price"] = entry_price
                        active_trade["exit_datetime"] = k_dt
                        active_trade["pnl_r"] = active_trade["locked_r"] # +0.75 R
                        trades.append(active_trade)
                        active_trade = None
                    # Check Final TP
                    elif k_low <= final_tp:
                        active_trade["outcome"] = "WIN"
                        active_trade["exit_price"] = final_tp
                        active_trade["exit_datetime"] = k_dt
                        active_trade["pnl_r"] = active_trade["locked_r"] + 0.5 * strategy.target_rr # +0.75 + 1.5 = +2.25 R
                        trades.append(active_trade)
                        active_trade = None
            continue
            
        # If no active trade, check for new signals
        sig = df_signals["signal"].iloc[i]
        if sig in ("BUY", "SELL"):
            entry_target = df_signals["entry_price"].iloc[i]
            sl_price = df_signals["sl_price"].iloc[i]
            tp_price = df_signals["tp_price"].iloc[i]
            has_fvg = df_signals["has_fvg"].iloc[i]
            
            # Risk calculation
            if sig == "BUY":
                risk = entry_target - sl_price
                partial_tp = entry_target + (strategy.partial_rr * risk)
            else:
                risk = sl_price - entry_target
                partial_tp = entry_target - (strategy.partial_rr * risk)
                
            if risk <= 0:
                continue
                
            # Simulate Limit Order Fill window (next fvg_wait candles)
            filled = False
            fill_price = entry_target
            fill_dt = None
            
            for offset in range(1, strategy.fvg_wait + 1):
                idx_check = i + offset
                if idx_check >= len(df_signals):
                    break
                
                check_low = df_signals["low"].iloc[idx_check]
                check_high = df_signals["high"].iloc[idx_check]
                check_dt = df_signals.index[idx_check]
                
                if sig == "BUY":
                    # If FVG setup, check if low goes deep enough to fill limit
                    if check_low <= entry_target:
                        filled = True
                        fill_dt = check_dt
                        break
                else: # SELL
                    # Check if high goes high enough to fill limit
                    if check_high >= entry_target:
                        filled = True
                        fill_dt = check_dt
                        break
                        
            if filled:
                active_trade = {
                    "side": sig,
                    "entry_price": fill_price,
                    "sl_price": sl_price,
                    "partial_tp": partial_tp,
                    "final_tp": tp_price,
                    "entry_datetime": fill_dt,
                    "stage": 1,
                    "locked_r": 0.0,
                    "outcome": "OPEN",
                    "pnl_r": 0.0,
                    "has_fvg": has_fvg
                }
                
    # Append the last active trade if it was left open
    if active_trade is not None:
        if active_trade["stage"] == 2:
            active_trade["pnl_r"] = active_trade["locked_r"] # keep the partial PnL
        else:
            active_trade["pnl_r"] = 0.0
        trades.append(active_trade)
        
    return trades

def main():
    parser = argparse.ArgumentParser(description="V3 Price Action Strategy Backtester")
    parser.add_argument("--symbols", type=str, default=None, help="virgülle ayrılmış özel semboller (varsayılan: hepsi)")
    parser.add_argument("--window", type=int, default=120, help="Swing high/low geriye bakış penceresi")
    parser.add_argument("--no-trend", action="store_true", help="EMA 200 trend filtresini kapat")
    parser.add_argument("--target-rr", type=float, default=3.0, help="Hedef Risk/Ödül oranı")
    args = parser.parse_args()
    
    strategy = V3PriceActionStrategy(
        sweep_window=args.window, 
        target_rr=args.target_rr, 
        partial_rr=1.5,
        require_trend=not args.no_trend
    )
    
    if args.symbols:
        symbol_files = []
        for s in args.symbols.split(","):
            cleaned = s.strip().replace("/", "_").replace(":", "_") + "_1h.csv"
            path = DATA_DIR / cleaned
            if path.exists():
                symbol_files.append(path)
    else:
        symbol_files = list(DATA_DIR.glob("*_1h.csv"))
        
    if not symbol_files:
        print("Test edilecek veri dosyası bulunamadı.")
        return
        
    print(f"Toplam {len(symbol_files)} sembol dosyası yüklendi. Backtest başlıyor...")
    print("-" * 70)
    
    all_trades = []
    symbol_stats = {}
    
    for file_path in symbol_files:
        symbol_name = file_path.name.replace("_USDT_USDT_1h.csv", "/USDT").replace("_1h.csv", "").replace("_", "/")
        try:
            df = pd.read_csv(file_path)
            if len(df) < args.window + 10:
                continue
                
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
            
            trades = run_simulation(df, strategy)
            if trades:
                all_trades.extend([(symbol_name, t) for t in trades])
                
                # Calculate symbol metrics
                sym_wins = sum(1 for t in trades if t["outcome"] == "WIN")
                sym_losses = sum(1 for t in trades if t["outcome"] == "LOSS")
                sym_bes = sum(1 for t in trades if t["outcome"] == "BE")
                sym_opens = sum(1 for t in trades if t["outcome"] == "OPEN")
                sym_pnl = sum(t["pnl_r"] for t in trades)
                
                symbol_stats[symbol_name] = {
                    "trades": len(trades),
                    "wins": sym_wins,
                    "losses": sym_losses,
                    "bes": sym_bes,
                    "opens": sym_opens,
                    "pnl": sym_pnl
                }
        except Exception as e:
            print(f"HATA ({symbol_name}): {e}")
            
    if not all_trades:
        print("Backtest süresince hiçbir işlem açılmadı.")
        return
        
    # Analyze total performance
    total_trades = len(all_trades)
    wins = sum(1 for _, t in all_trades if t["outcome"] == "WIN")
    losses = sum(1 for _, t in all_trades if t["outcome"] == "LOSS")
    bes = sum(1 for _, t in all_trades if t["outcome"] == "BE")
    opens = sum(1 for _, t in all_trades if t["outcome"] == "OPEN")
    
    completed_trades = wins + losses + bes
    win_rate = (wins + bes) / completed_trades * 100 if completed_trades > 0 else 0.0
    strict_win_rate = wins / completed_trades * 100 if completed_trades > 0 else 0.0
    
    gross_pnl = sum(t["pnl_r"] for _, t in all_trades)
    # Commission per trade (0.15 R per entry)
    total_fees = total_trades * 0.15
    net_pnl = gross_pnl - total_fees
    
    # Drawdown calculation in R-units
    cumulative_pnl = []
    current_pnl = 0.0
    # Sort trades by datetime to calculate drawdowns chronologically
    sorted_trades = sorted(all_trades, key=lambda x: x[1]["entry_datetime"] if x[1]["entry_datetime"] is not None else "")
    
    for _, t in sorted_trades:
        current_pnl += t["pnl_r"] - 0.15 # subtract fee
        cumulative_pnl.append(current_pnl)
        
    cum_series = pd.Series(cumulative_pnl)
    peaks = cum_series.cummax()
    drawdowns = peaks - cum_series
    max_dd = drawdowns.max() if not drawdowns.empty else 0.0
    
    print("\n" + "=" * 80)
    print("📈 ANTIGRAVITI V3 PRICE ACTION BACKTEST RAPORU")
    print("=" * 80)
    print(f"Toplam Test Edilen Coin   : {len(symbol_stats)}")
    print(f"Toplam Açılan Pozisyon    : {total_trades} adet")
    print(f"  - Kazançla Kapananlar   : {wins} adet (Final TP)")
    print(f"  - Başa Baş Kapananlar   : {bes} adet (Kısmi TP sonrası BE)")
    print(f"  - Zararla Kapananlar    : {losses} adet (Full Stop)")
    print(f"  - Açık Kalanlar         : {opens} adet")
    print("-" * 80)
    print(f"Tamamlanan İşlem Sayısı   : {completed_trades}")
    print(f"Kısmi veya Tam Başarı %   : %{win_rate:.2f} (Zarar edilmeyen işlemler oranı)")
    print(f"Tam Hedef Başarı %        : %{strict_win_rate:.2f} (Full TP oranı)")
    print("-" * 80)
    print(f"Toplam Brüt Kazanç        : {gross_pnl:+.2f} R")
    print(f"Toplam Komisyon Maliyeti  : {total_fees:.2f} R (İşlem başı 0.15 R)")
    print(f"Toplam Net Kâr/Zarar      : {net_pnl:+.2f} R")
    print(f"Maksimum Düşüş (Max DD)   : {max_dd:.2f} R")
    
    # Sort symbols by PnL
    sorted_symbols = sorted(symbol_stats.items(), key=lambda x: x[1]["pnl"], reverse=True)
    
    print("-" * 80)
    print("🏆 EN ÇOK KAZANDIRAN 5 COIN:")
    for sym, stat in sorted_symbols[:5]:
        print(f"  • {sym:<10} | {stat['trades']:<3} işlem | Net PnL: {stat['pnl']:+.2f} R (Başarı %: {(stat['wins'] + stat['bes'])/max(1, stat['wins']+stat['losses']+stat['bes'])*100:.1f}%)")
        
    print("\n💀 EN ÇOK KAYBETTİREN 5 COIN:")
    for sym, stat in sorted_symbols[-5:]:
        print(f"  • {sym:<10} | {stat['trades']:<3} işlem | Net PnL: {stat['pnl']:+.2f} R (Başarı %: {(stat['wins'] + stat['bes'])/max(1, stat['wins']+stat['losses']+stat['bes'])*100:.1f}%)")
        
    print("=" * 80)
    print("Açıklama: 1 R = Yatırılan Risk Birimi (Örn: Hesapta %1 risk alınıyorsa 1 R = %1 kâr)")
    print("Kısmi kâr almada (1.5R'da %50 kapanma ve BE çekme), işlem +0.75 R net kazanç getirir.")
    print("Tam hedefte (3.0R'da kalan %50 kapanma), işlem +2.25 R net kazanç getirir.")

if __name__ == "__main__":
    main()
