# -*- coding: utf-8 -*-
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import ta
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Windows console output encoding fix
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.strategy.smc_utils import get_premium_discount_zone, detect_order_block

DATA_DIR_15M = PROJECT_ROOT / "data" / "historical" / "15m"
DATA_DIR_1H = PROJECT_ROOT / "data" / "historical" / "1h"
PLOT_DIR = Path(r"C:\Users\52tuz\.gemini\antigravity-ide\brain\3b3ebdf4-4025-4a51-9470-bc737d8176c0")

def calculate_versioned_indicators(df, version):
    df = df.copy()
    
    # ADX (for Version 9)
    if version == 9:
        df["adx"] = ta.trend.adx(df["high"], df["low"], df["close"], window=14)
        
    # Volume SMA 20 (for Version 3, 4, 5, 6, 7, 8, 9)
    if version in (3, 4, 5, 6, 7, 8, 9):
        df["vol_sma"] = df["volume"].rolling(window=20).mean()
        
    # RSI (for Version 5, 6, 9)
    if version in (5, 6, 9):
        df["rsi"] = ta.momentum.rsi(df["close"], window=14)
        
    # Ensure funding rate and open interest columns exist
    if "funding_rate" not in df.columns:
        df["funding_rate"] = 0.0
    if "open_interest" not in df.columns:
        df["open_interest"] = 0.0
        
    return df

def check_ote_condition(entry_price, swing_h, swing_l, side):
    swing_range = swing_h - swing_l
    if swing_range <= 0:
        return False
    if side == "BUY":
        retracement = (swing_h - entry_price) / swing_range
    else: # SELL
        retracement = (entry_price - swing_l) / swing_range
    return 0.62 <= retracement <= 0.79

def calculate_signals_versioned(df, version, strategy_config):
    df = calculate_versioned_indicators(df, version)
    
    sweep_window = strategy_config.get("sweep_window", 120)
    max_hold_sweep = strategy_config.get("max_hold_sweep", 5)
    require_trend = strategy_config.get("require_trend", True)
    use_premium_discount = strategy_config.get("use_premium_discount", True)
    
    target_rr = strategy_config.get("target_rr", 3.0)
    
    df["swing_high"] = df["high"].shift(1).rolling(window=sweep_window).max()
    df["swing_low"] = df["low"].shift(1).rolling(window=sweep_window).min()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df["atr"] = true_range.rolling(window=14).mean()
    
    df["signal"] = "HOLD"
    df["entry_price"] = 0.0
    df["sl_price"] = 0.0
    df["tp_price"] = 0.0
    df["has_fvg"] = False
    
    last_bull_sweep_idx = -1
    last_bull_sweep_low = 0.0
    last_bear_sweep_idx = -1
    last_bear_sweep_high = 0.0
    
    start_idx = int(max(sweep_window, 200) + 2)
    if start_idx >= len(df):
        return df
        
    for i in range(start_idx, len(df)):
        high_prev = df["swing_high"].iloc[i]
        low_prev = df["swing_low"].iloc[i]
        ema200_val = df["ema200"].iloc[i]
        atr_val = df["atr"].iloc[i]
        
        h = df["high"].iloc[i]
        l = df["low"].iloc[i]
        c = df["close"].iloc[i]
        o = df["open"].iloc[i]
        
        candle_range = h - l
        if candle_range == 0:
            continue
            
        # A. Sweep detection
        is_bull_sweep_now = (l < low_prev) and (c > low_prev)
        if is_bull_sweep_now:
            lower_wick = min(c, o) - l
            is_bull_rejection = (lower_wick / candle_range >= 0.35) or (c > o and df["close"].iloc[i-1] < df["open"].iloc[i-1])
            if is_bull_rejection:
                last_bull_sweep_idx = i
                last_bull_sweep_low = l
                last_bear_sweep_idx = -1
                
        is_bear_sweep_now = (h > high_prev) and (c < high_prev)
        if is_bear_sweep_now:
            upper_wick = h - max(c, o)
            is_bear_rejection = (upper_wick / candle_range >= 0.35) or (c < o and df["close"].iloc[i-1] > df["open"].iloc[i-1])
            if is_bear_rejection:
                last_bear_sweep_idx = i
                last_bear_sweep_high = h
                last_bull_sweep_idx = -1
                
        # B. Stateful Signal Evaluation
        # 1. BULLISH SETUP
        if last_bull_sweep_idx != -1:
            if i - last_bull_sweep_idx > max_hold_sweep:
                last_bull_sweep_idx = -1
            else:
                is_bullish_mss = c > max(df["close"].iloc[i-1], df["close"].iloc[i-2], df["close"].iloc[i-3])
                if is_bullish_mss:
                    trend_ok = True
                    if require_trend:
                        trend_ok = (c > ema200_val)
                        
                    if use_premium_discount and trend_ok:
                        swing_h = df["swing_high"].iloc[last_bull_sweep_idx]
                        swing_l = df["swing_low"].iloc[last_bull_sweep_idx]
                        zone = get_premium_discount_zone(c, swing_h, swing_l)
                        trend_ok = (zone == "DISCOUNT")
                        
                    # Apply specific version filters
                    if trend_ok:
                        # Session Filters (V1, V2, V3, V4, V5, V6, V8, V9, V10)
                        if version in (1, 2, 3, 4, 5, 6, 8, 9, 10):
                            dt = df.index[i]
                            hour = dt.hour
                            is_kz = (7 <= hour < 10) or (12 <= hour < 16)
                            if not is_kz:
                                trend_ok = False
                                
                        # Fibonacci OTE (V2, V4, V6, V7, V9, V10)
                        if trend_ok and version in (2, 4, 6, 7, 9, 10):
                            # Check FVG midpoint or Close entry relative to swing
                            fvg_gap = df["low"].iloc[i] - df["high"].iloc[i-2]
                            entry_price_check = (df["low"].iloc[i] + df["high"].iloc[i-2]) / 2.0 if fvg_gap > 0 else c
                            swing_h = df["swing_high"].iloc[last_bull_sweep_idx]
                            swing_l = df["swing_low"].iloc[last_bull_sweep_idx]
                            if not check_ote_condition(entry_price_check, swing_h, swing_l, "BUY"):
                                trend_ok = False
                                
                        # Volume Confirmation (V3, V4, V5, V6, V7, V9)
                        if trend_ok and version in (3, 4, 5, 6, 7, 9):
                            vol_sma_val = df["vol_sma"].iloc[i]
                            if not pd.isna(vol_sma_val) and vol_sma_val > 0:
                                if df["volume"].iloc[i] / vol_sma_val <= 1.5:
                                    trend_ok = False
                                    
                        # Golden Combo Extra Filters (Funding & OI) (V5, V6, V9, V10)
                        if trend_ok and version in (5, 6, 9, 10):
                            funding_rate_val = df["funding_rate"].iloc[i]
                            if funding_rate_val > 0.0005:
                                trend_ok = False
                            if trend_ok:
                                oi_sweep = df["open_interest"].iloc[last_bull_sweep_idx]
                                oi_mss = df["open_interest"].iloc[i]
                                if oi_sweep > 0 and oi_mss > 0 and oi_mss <= oi_sweep:
                                    trend_ok = False
                                    
                    if trend_ok:
                        df.at[df.index[i], "signal"] = "BUY"
                        sl = last_bull_sweep_low - (atr_val * 0.5)
                        
                        fvg_gap = df["low"].iloc[i] - df["high"].iloc[i-2]
                        if fvg_gap > 0:
                            df.at[df.index[i], "has_fvg"] = True
                            fvg_mid = (df["low"].iloc[i] + df["high"].iloc[i-2]) / 2.0
                            df.at[df.index[i], "entry_price"] = fvg_mid
                        else:
                            df.at[df.index[i], "entry_price"] = c
                            
                        risk = df["entry_price"].iloc[i] - sl
                        if risk <= 0:
                            risk = atr_val * 0.5
                            sl = df["entry_price"].iloc[i] - risk
                            
                        df.at[df.index[i], "sl_price"] = sl
                        df.at[df.index[i], "tp_price"] = df["entry_price"].iloc[i] + (target_rr * risk)
                        last_bull_sweep_idx = -1
                        
        # 2. BEARISH SETUP
        if last_bear_sweep_idx != -1:
            if i - last_bear_sweep_idx > max_hold_sweep:
                last_bear_sweep_idx = -1
            else:
                is_bearish_mss = c < min(df["close"].iloc[i-1], df["close"].iloc[i-2], df["close"].iloc[i-3])
                if is_bearish_mss:
                    trend_ok = True
                    if require_trend:
                        trend_ok = (c < ema200_val)
                        
                    if use_premium_discount and trend_ok:
                        swing_h = df["swing_high"].iloc[last_bear_sweep_idx]
                        swing_l = df["swing_low"].iloc[last_bear_sweep_idx]
                        zone = get_premium_discount_zone(c, swing_h, swing_l)
                        trend_ok = (zone == "PREMIUM")
                        
                    # Apply specific version filters
                    if trend_ok:
                        # Session Filters (V1, V2, V3, V4, V5, V6, V8, V9, V10)
                        if version in (1, 2, 3, 4, 5, 6, 8, 9, 10):
                            dt = df.index[i]
                            hour = dt.hour
                            is_kz = (7 <= hour < 10) or (12 <= hour < 16)
                            if not is_kz:
                                trend_ok = False
                                
                        # Fibonacci OTE (V2, V4, V6, V7, V9, V10)
                        if trend_ok and version in (2, 4, 6, 7, 9, 10):
                            fvg_gap = df["low"].iloc[i-2] - df["high"].iloc[i]
                            entry_price_check = (df["high"].iloc[i] + df["low"].iloc[i-2]) / 2.0 if fvg_gap > 0 else c
                            swing_h = df["swing_high"].iloc[last_bear_sweep_idx]
                            swing_l = df["swing_low"].iloc[last_bear_sweep_idx]
                            if not check_ote_condition(entry_price_check, swing_h, swing_l, "SELL"):
                                trend_ok = False
                                
                        # Volume Confirmation (V3, V4, V5, V6, V7, V9)
                        if trend_ok and version in (3, 4, 5, 6, 7, 9):
                            vol_sma_val = df["vol_sma"].iloc[i]
                            if not pd.isna(vol_sma_val) and vol_sma_val > 0:
                                if df["volume"].iloc[i] / vol_sma_val <= 1.5:
                                    trend_ok = False
                                    
                        # Golden Combo Extra Filters (Funding & OI) (V5, V6, V9, V10)
                        if trend_ok and version in (5, 6, 9, 10):
                            funding_rate_val = df["funding_rate"].iloc[i]
                            if funding_rate_val < -0.0005:
                                trend_ok = False
                            if trend_ok:
                                oi_sweep = df["open_interest"].iloc[last_bear_sweep_idx]
                                oi_mss = df["open_interest"].iloc[i]
                                if oi_sweep > 0 and oi_mss > 0 and oi_mss <= oi_sweep:
                                    trend_ok = False
                                    
                    if trend_ok:
                        df.at[df.index[i], "signal"] = "SELL"
                        sl = last_bear_sweep_high + (atr_val * 0.5)
                        
                        fvg_gap = df["low"].iloc[i-2] - df["high"].iloc[i]
                        if fvg_gap > 0:
                            df.at[df.index[i], "has_fvg"] = True
                            fvg_mid = (df["high"].iloc[i] + df["low"].iloc[i-2]) / 2.0
                            df.at[df.index[i], "entry_price"] = fvg_mid
                        else:
                            df.at[df.index[i], "entry_price"] = c
                            
                        risk = sl - df["entry_price"].iloc[i]
                        if risk <= 0:
                            risk = atr_val * 0.5
                            sl = df["entry_price"].iloc[i] + risk
                            
                        df.at[df.index[i], "sl_price"] = sl
                        df.at[df.index[i], "tp_price"] = df["entry_price"].iloc[i] - (target_rr * risk)
                        last_bear_sweep_idx = -1
                        
    return df

def run_simulation_versioned(df_signals, version, strategy_config):
    trades = []
    active_trade = None
    
    target_rr = strategy_config.get("target_rr", 3.0)
    partial_rr = strategy_config.get("partial_rr", 1.5)
    fvg_wait = strategy_config.get("fvg_wait", 3)
    
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
            risk = active_trade["risk"]
            
            if side == "BUY": # LONG
                if stage == 1:
                    if k_low <= sl_price:
                        active_trade["outcome"] = "LOSS"
                        active_trade["exit_price"] = sl_price
                        active_trade["exit_datetime"] = k_dt
                        active_trade["pnl_r"] = -1.0
                        
                        # Dynamic Fee Calculation (BNB discounted)
                        sl_pct_dist = risk / entry_price
                        active_trade["fee_r"] = 0.00063 / max(sl_pct_dist, 0.001)
                        
                        trades.append(active_trade)
                        active_trade = None
                    elif k_high >= partial_tp:
                        active_trade["stage"] = 2
                        active_trade["sl_price"] = entry_price
                        active_trade["locked_r"] = 0.5 * partial_rr
                elif stage == 2:
                    if version == 8:
                        # Version 8: Trailing stop loss starts after 2.0 RR
                        atr_val = df_signals["atr"].iloc[i]
                        current_rr = (k_close - entry_price) / risk
                        if current_rr >= 2.0:
                            trail_level = k_close - (1.5 * atr_val)
                            sl_price = max(sl_price, trail_level)
                            active_trade["sl_price"] = sl_price
                        
                        if k_low <= sl_price:
                            active_trade["outcome"] = "TRAILED"
                            active_trade["exit_price"] = sl_price
                            active_trade["exit_datetime"] = k_dt
                            active_trade["pnl_r"] = 0.5 * partial_rr + 0.5 * ((sl_price - entry_price) / risk)
                            
                            sl_pct_dist = risk / entry_price
                            active_trade["fee_r"] = 0.00063 / max(sl_pct_dist, 0.001)
                            
                            trades.append(active_trade)
                            active_trade = None
                    else:
                        if k_low <= entry_price:
                            active_trade["outcome"] = "BE"
                            active_trade["exit_price"] = entry_price
                            active_trade["exit_datetime"] = k_dt
                            active_trade["pnl_r"] = active_trade["locked_r"]
                            
                            sl_pct_dist = risk / entry_price
                            active_trade["fee_r"] = 0.00063 / max(sl_pct_dist, 0.001)
                            
                            trades.append(active_trade)
                            active_trade = None
                        elif k_high >= final_tp:
                            active_trade["outcome"] = "WIN"
                            active_trade["exit_price"] = final_tp
                            active_trade["exit_datetime"] = k_dt
                            active_trade["pnl_r"] = active_trade["locked_r"] + 0.5 * target_rr
                            
                            sl_pct_dist = risk / entry_price
                            active_trade["fee_r"] = 0.00036 / max(sl_pct_dist, 0.001)
                            
                            trades.append(active_trade)
                            active_trade = None
                            
            elif side == "SELL": # SHORT
                if stage == 1:
                    if k_high >= sl_price:
                        active_trade["outcome"] = "LOSS"
                        active_trade["exit_price"] = sl_price
                        active_trade["exit_datetime"] = k_dt
                        active_trade["pnl_r"] = -1.0
                        
                        sl_pct_dist = risk / entry_price
                        active_trade["fee_r"] = 0.00063 / max(sl_pct_dist, 0.001)
                        
                        trades.append(active_trade)
                        active_trade = None
                    elif k_low <= partial_tp:
                        active_trade["stage"] = 2
                        active_trade["sl_price"] = entry_price
                        active_trade["locked_r"] = 0.5 * partial_rr
                elif stage == 2:
                    if version == 8:
                        # Version 8: Trailing stop loss starts after 2.0 RR
                        atr_val = df_signals["atr"].iloc[i]
                        current_rr = (entry_price - k_close) / risk
                        if current_rr >= 2.0:
                            trail_level = k_close + (1.5 * atr_val)
                            sl_price = min(sl_price, trail_level)
                            active_trade["sl_price"] = sl_price
                        
                        if k_high >= sl_price:
                            active_trade["outcome"] = "TRAILED"
                            active_trade["exit_price"] = sl_price
                            active_trade["exit_datetime"] = k_dt
                            active_trade["pnl_r"] = 0.5 * partial_rr + 0.5 * ((entry_price - sl_price) / risk)
                            
                            sl_pct_dist = risk / entry_price
                            active_trade["fee_r"] = 0.00063 / max(sl_pct_dist, 0.001)
                            
                            trades.append(active_trade)
                            active_trade = None
                    else:
                        if k_high >= entry_price:
                            active_trade["outcome"] = "BE"
                            active_trade["exit_price"] = entry_price
                            active_trade["exit_datetime"] = k_dt
                            active_trade["pnl_r"] = active_trade["locked_r"]
                            
                            sl_pct_dist = risk / entry_price
                            active_trade["fee_r"] = 0.00063 / max(sl_pct_dist, 0.001)
                            
                            trades.append(active_trade)
                            active_trade = None
                        elif k_low <= final_tp:
                            active_trade["outcome"] = "WIN"
                            active_trade["exit_price"] = final_tp
                            active_trade["exit_datetime"] = k_dt
                            active_trade["pnl_r"] = active_trade["locked_r"] + 0.5 * target_rr
                            
                            sl_pct_dist = risk / entry_price
                            active_trade["fee_r"] = 0.00036 / max(sl_pct_dist, 0.001)
                            
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
                partial_tp = entry_target + (partial_rr * risk)
            else:
                risk = sl_price - entry_target
                partial_tp = entry_target - (partial_rr * risk)
                
            if risk <= 0:
                i += 1
                continue
                
            filled = False
            fill_price = entry_target
            fill_idx = None
            
            for offset in range(1, fvg_wait + 1):
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
                    "risk": risk
                }
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
        
        # Calculate dynamic fee for open trades
        sl_pct_dist = risk / entry_price
        active_trade["fee_r"] = 0.00063 / max(sl_pct_dist, 0.001)
        
        trades.append(active_trade)
        
    return trades

def evaluate_run_versioned(symbol_files, version, strategy_config):
    all_trades = []
    
    for file_path in symbol_files:
        symbol_name = file_path.name.split("_USDT")[0].replace("_", "/")
        try:
            df = pd.read_csv(file_path)
            if len(df) < 220:
                continue
                
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
            
            df_signals = calculate_signals_versioned(df, version, strategy_config)
            trades = run_simulation_versioned(df_signals, version, strategy_config)
            if trades:
                all_trades.extend([(symbol_name, t) for t in trades])
        except Exception as e:
            pass
            
    if not all_trades:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "bes": 0,
            "trailed": 0,
            "win_rate": 0.0,
            "gross_pnl": 0.0,
            "fees": 0.0,
            "net_pnl": 0.0,
            "max_dd": 0.0
        }, []
        
    total_trades = len(all_trades)
    wins = sum(1 for _, t in all_trades if t["outcome"] == "WIN")
    losses = sum(1 for _, t in all_trades if t["outcome"] == "LOSS")
    bes = sum(1 for _, t in all_trades if t["outcome"] == "BE")
    trailed = sum(1 for _, t in all_trades if t["outcome"] == "TRAILED")
    
    completed = wins + losses + bes + trailed
    win_rate = (wins + trailed + bes) / completed * 100 if completed > 0 else 0.0
    
    gross_pnl = sum(t["pnl_r"] for _, t in all_trades)
    
    # Calculate cumulative fees and net PnL using our dynamic fees
    total_fees = sum(t["fee_r"] for _, t in all_trades)
    net_pnl = gross_pnl - total_fees
    
    # Sort trades chronologically to build equity curves
    sorted_trades = sorted(all_trades, key=lambda x: x[1]["entry_datetime"] if x[1]["entry_datetime"] is not None else "")
    
    cumulative_pnl = []
    current_pnl = 0.0
    equity_curve = []
    
    for _, t in sorted_trades:
        net_trade_pnl = t["pnl_r"] - t["fee_r"]
        current_pnl += net_trade_pnl
        cumulative_pnl.append(current_pnl)
        equity_curve.append({
            "datetime": t["entry_datetime"],
            "cum_pnl": current_pnl
        })
        
    cum_series = pd.Series(cumulative_pnl)
    peaks = cum_series.cummax()
    drawdowns = peaks - cum_series
    max_dd = drawdowns.max() if not drawdowns.empty else 0.0
    
    metrics = {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "bes": bes,
        "trailed": trailed,
        "win_rate": win_rate,
        "gross_pnl": gross_pnl,
        "fees": total_fees,
        "net_pnl": net_pnl,
        "max_dd": max_dd
    }
    
    return metrics, equity_curve

def main():
    # Load symbol files
    symbol_files_15m = list(DATA_DIR_15M.glob("*_15m.csv"))
    symbol_files_1h = list(DATA_DIR_1H.glob("*_1h.csv"))
    
    if not symbol_files_15m:
        print("Error: No 15m historical data files found.")
        return
        
    print(f"Loaded {len(symbol_files_15m)} 15m files and {len(symbol_files_1h)} 1h files.")
    print("Starting optimized comparative backtest for 10 versions with Fibonacci OTE & Dynamic Fees...")
    print("-" * 100)
    
    strategy_config = {
        "sweep_window": 120,
        "target_rr": 3.0,
        "partial_rr": 1.5,
        "require_trend": True,
        "max_hold_sweep": 5,
        "fvg_wait": 3,
        "use_premium_discount": True
    }
    
    version_names = {
        1: "V1: Baseline Session Kill Zone (London & NY UTC)",
        2: "V2: Session Kill Zone + Fibonacci OTE Filter",
        3: "V3: Session Kill Zone + Volume Confirmation (> 1.5 ratio)",
        4: "V4: Session Kill Zone + Fibonacci OTE + Vol Confirmation",
        5: "V5: Golden Combo (Session + Vol + Funding + OI)",
        6: "V6: Golden Combo + Fibonacci OTE Filter",
        7: "V7: Fibonacci OTE + Volume Confirmation (No Session)",
        8: "V8: Refined Session Kill Zone + Trailing SL (starts at 2.0 RR)",
        9: "V9: Ultimate Combo (Session + Vol + OTE + Funding + OI)",
        10: "V10: 1H Timeframe with Session Kill Zone + Fibonacci OTE"
    }
    
    results = {}
    curves = {}
    
    for v in range(1, 11):
        print(f"Simulating {version_names[v]}...")
        files = symbol_files_1h if v == 10 else symbol_files_15m
        res, curve = evaluate_run_versioned(files, v, strategy_config)
        results[v] = res
        curves[v] = curve
        print(f"  Result: Trades: {res['total_trades']}, WR: {res['win_rate']:.2f}%, Fees: {res['fees']:.2f} R, Net PnL: {res['net_pnl']:.2f} R, Max DD: {res['max_dd']:.2f} R")
        print("-" * 60)
        
    print("\n" + "=" * 100)
    print("📊 COMPILATION REPORT - 10 STRATEGY VERSIONS OPTIMIZED WITH DYNAMIC FEES")
    print("=" * 100)
    header = f"{'Version':<10} | {'Trades':<8} | {'Win Rate':<10} | {'Gross PnL':<12} | {'Fees (R)':<10} | {'Net PnL (R)':<13} | {'Max DD (R)':<10}"
    print(header)
    print("-" * 100)
    
    for v in range(1, 11):
        res = results[v]
        row = f"V{v:<8} | {res['total_trades']:<8} | {res['win_rate']:>7.2f}% | {res['gross_pnl']:+10.2f}R | {res['fees']:>8.2f} | {res['net_pnl']:+11.2f}R | {res['max_dd']:>8.2f}"
        print(row)
        
    print("=" * 100)
    print("\n[Dynamic BNB fee structure applied dynamically based on maker/taker outcomes.]")

    # Plotting Equity Curves
    print("\nGenerating equity curve visualization...")
    plt.figure(figsize=(12, 6.5))
    
    for v in range(1, 11):
        curve = curves[v]
        if not curve:
            continue
        df_curve = pd.DataFrame(curve)
        df_curve["datetime"] = pd.to_datetime(df_curve["datetime"])
        df_curve = df_curve.sort_values("datetime")
        
        plt.plot(df_curve["datetime"], df_curve["cum_pnl"], label=f"V{v} ({results[v]['net_pnl']:+.1f} R)")
        
    plt.title("ANTIGRAVITI V3 PA Strategy - 100-Day Comparative Equity Curves (Net R-Units)", fontsize=13, fontweight='bold')
    plt.xlabel("Timeline", fontsize=11)
    plt.ylabel("Cumulative Net R-Units", fontsize=11)
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend(loc="upper left")
    plt.tight_layout()
    
    plot_path = PLOT_DIR / "equity_curves.png"
    plt.savefig(plot_path, dpi=150)
    plt.close()
    print(f"Equity curves saved to: {plot_path}")

if __name__ == "__main__":
    main()
