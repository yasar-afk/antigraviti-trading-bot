# -*- coding: utf-8 -*-
import sys
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# No stdout wrapping needed here to avoid closed stream error

from scratch.backtest_v3_comparison import AdvancedV3PriceActionStrategy, run_simulation

DATA_DIR = PROJECT_ROOT / "data" / "historical" / "15m"

def run_simulation_corrected(df, strategy):
    """Corrected simulation loop using a while loop to jump index to fill candle, avoiding pre-fill evaluation."""
    df_signals = strategy.calculate_signals_with_filters(df)
    trades = []
    active_trade = None
    
    i = 0
    n = len(df_signals)
    while i < n:
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
                    if k_low <= sl_price:
                        active_trade["outcome"] = "LOSS"
                        active_trade["exit_price"] = sl_price
                        active_trade["exit_datetime"] = k_dt
                        active_trade["pnl_r"] = -1.0
                        trades.append(active_trade)
                        active_trade = None
                    elif k_high >= partial_tp:
                        active_trade["stage"] = 2
                        active_trade["sl_price"] = entry_price
                        active_trade["locked_r"] = 0.5 * strategy.partial_rr
                elif stage == 2:
                    if k_low <= entry_price:
                        active_trade["outcome"] = "BE"
                        active_trade["exit_price"] = entry_price
                        active_trade["exit_datetime"] = k_dt
                        active_trade["pnl_r"] = active_trade["locked_r"]
                        trades.append(active_trade)
                        active_trade = None
                    elif k_high >= final_tp:
                        active_trade["outcome"] = "WIN"
                        active_trade["exit_price"] = final_tp
                        active_trade["exit_datetime"] = k_dt
                        active_trade["pnl_r"] = active_trade["locked_r"] + 0.5 * strategy.target_rr
                        trades.append(active_trade)
                        active_trade = None
                        
            elif side == "SELL": # SHORT
                if stage == 1:
                    if k_high >= sl_price:
                        active_trade["outcome"] = "LOSS"
                        active_trade["exit_price"] = sl_price
                        active_trade["exit_datetime"] = k_dt
                        active_trade["pnl_r"] = -1.0
                        trades.append(active_trade)
                        active_trade = None
                    elif k_low <= partial_tp:
                        active_trade["stage"] = 2
                        active_trade["sl_price"] = entry_price
                        active_trade["locked_r"] = 0.5 * strategy.partial_rr
                elif stage == 2:
                    if k_high >= entry_price:
                        active_trade["outcome"] = "BE"
                        active_trade["exit_price"] = entry_price
                        active_trade["exit_datetime"] = k_dt
                        active_trade["pnl_r"] = active_trade["locked_r"]
                        trades.append(active_trade)
                        active_trade = None
                    elif k_low <= final_tp:
                        active_trade["outcome"] = "WIN"
                        active_trade["exit_price"] = final_tp
                        active_trade["exit_datetime"] = k_dt
                        active_trade["pnl_r"] = active_trade["locked_r"] + 0.5 * strategy.target_rr
                        trades.append(active_trade)
                        active_trade = None
            i += 1
            continue
            
        sig = df_signals["signal"].iloc[i]
        if sig in ("BUY", "SELL"):
            entry_target = df_signals["entry_price"].iloc[i]
            sl_price = df_signals["sl_price"].iloc[i]
            tp_price = df_signals["tp_price"].iloc[i]
            has_fvg = df_signals["has_fvg"].iloc[i]
            
            if sig == "BUY":
                risk = entry_target - sl_price
                partial_tp = entry_target + (strategy.partial_rr * risk)
            else:
                risk = sl_price - entry_target
                partial_tp = entry_target - (strategy.partial_rr * risk)
                
            if risk <= 0:
                i += 1
                continue
                
            filled = False
            fill_price = entry_target
            fill_idx = None
            
            for offset in range(1, strategy.fvg_wait + 1):
                idx_check = i + offset
                if idx_check >= len(df_signals):
                    break
                
                check_low = df_signals["low"].iloc[idx_check]
                check_high = df_signals["high"].iloc[idx_check]
                
                if sig == "BUY":
                    if check_low <= entry_target:
                        filled = True
                        fill_idx = idx_check
                        break
                else: # SELL
                    if check_high >= entry_target:
                        filled = True
                        fill_idx = idx_check
                        break
                        
            if filled:
                active_trade = {
                    "side": sig,
                    "entry_price": fill_price,
                    "sl_price": sl_price,
                    "partial_tp": partial_tp,
                    "final_tp": tp_price,
                    "entry_datetime": df_signals.index[fill_idx],
                    "stage": 1,
                    "locked_r": 0.0,
                    "outcome": "OPEN",
                    "pnl_r": 0.0,
                    "has_fvg": has_fvg,
                    "signal_idx": i,
                    "fill_idx": fill_idx
                }
                # Jump outer loop to the fill index so we evaluate from fill_idx onwards
                i = fill_idx
            else:
                i += 1
        else:
            i += 1
                
    if active_trade is not None:
        if active_trade["stage"] == 2:
            active_trade["pnl_r"] = active_trade["locked_r"]
        else:
            active_trade["pnl_r"] = 0.0
        trades.append(active_trade)
        
    return trades

def audit_symbol(file_path):
    df = pd.read_csv(file_path)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime")
    
    strategy = AdvancedV3PriceActionStrategy(
        use_filters=False,
        sweep_window=120,
        target_rr=3.0,
        partial_rr=1.5,
        require_trend=True
    )
    
    trades_old = run_simulation(df, strategy)
    trades_new = run_simulation_corrected(df, strategy)
    
    print(f"Auditing file: {file_path.name}")
    print(f"  • Original loop trades: {len(trades_old)}")
    print(f"  • Corrected loop trades: {len(trades_new)}")
    
    # Check if there are discrepancies
    if len(trades_old) != len(trades_new):
        print("  ⚠️ Discrepancy found in trade count!")
        
    # Detailed check of first trade in new simulation
    if trades_new:
        t = trades_new[0]
        print(f"  • Sample Trade (Corrected):")
        print(f"    Side: {t['side']} | Entry Price: {t['entry_price']} | SL: {t['sl_price']} | TP: {t['final_tp']}")
        print(f"    Signal Index: {t.get('signal_idx')} | Fill Index: {t.get('fill_idx')}")
        print(f"    Exit DateTime: {t.get('exit_datetime')} | Outcome: {t.get('outcome')} | PnL: {t.get('pnl_r')} R")
        
        # Verify fill chronology
        if t.get('fill_idx') <= t.get('signal_idx'):
            print("    ❌ ERROR: Fill occurred before or at signal candle!")
        else:
            print("    ✅ Fill occurs chronologically after signal.")

def main():
    symbol_files = list(DATA_DIR.glob("*_15m.csv"))
    if not symbol_files:
        print("No files found.")
        return
        
    # Audit a few symbols
    for path in symbol_files[:3]:
        audit_symbol(path)
        print("-" * 50)

if __name__ == "__main__":
    main()
