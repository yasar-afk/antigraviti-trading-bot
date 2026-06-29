# -*- coding: utf-8 -*-
"""
scratch/run_extensive_optimization.py — Hyperparameter optimization for ANTIGRAVITI PA/SMC Strategy.
"""
import os
import sys
import time
import random
from pathlib import Path
import pandas as pd
import numpy as np
import ta
import multiprocessing
from concurrent.futures import ProcessPoolExecutor

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Windows console output encoding fix
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.strategy.smc_utils import get_premium_discount_zone

DATA_DIR_15M = PROJECT_ROOT / "data" / "historical" / "15m"

def check_session(timestamp, use_session_filter):
    if not use_session_filter:
        return True
    if not timestamp or np.isnan(timestamp):
        return False
    if timestamp > 1e11:
        timestamp = timestamp / 1000.0
    try:
        # Convert timestamp to UTC hour
        dt = pd.to_datetime(timestamp, unit='s', utc=True)
        hour = dt.hour
        return (7 <= hour < 10) or (12 <= hour < 16)
    except Exception:
        return False

def check_ote_condition(entry_price, swing_h, swing_l, side, ote_min, ote_max):
    swing_range = swing_h - swing_l
    if swing_range <= 0:
        return False
    if side == "BUY":
        retracement = (swing_h - entry_price) / swing_range
    else: # SELL
        retracement = (entry_price - swing_l) / swing_range
    return ote_min <= retracement <= ote_max

def backtest_single_pair(file_path, params):
    """Runs backtest on a single CSV file with given parameters."""
    try:
        df = pd.read_csv(file_path)
        if len(df) < 220:
            return []
            
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
        
        # Extract parameters
        sweep_window = params["sweep_window"]
        max_hold_sweep = params["max_hold_sweep"]
        target_rr = params["target_rr"]
        partial_rr = params["partial_rr"]
        use_partial = params["use_partial"]
        require_trend = params["require_trend"]
        trend_ema = params["trend_ema"]
        use_premium_discount = params["use_premium_discount"]
        atr_multiplier = params["atr_multiplier"]
        fvg_wait = params["fvg_wait"]
        use_session_filter = params["use_session_filter"]
        use_ote_filter = params["use_ote_filter"]
        ote_min = params.get("ote_min", 0.62)
        ote_max = params.get("ote_max", 0.79)
        use_volume_filter = params["use_volume_filter"]
        volume_ratio = params.get("volume_ratio", 1.5)
        
        # Calculate indicators
        df["swing_high"] = df["high"].shift(1).rolling(window=sweep_window).max()
        df["swing_low"] = df["low"].shift(1).rolling(window=sweep_window).min()
        df["trend_ema_val"] = df["close"].ewm(span=trend_ema, adjust=False).mean()
        
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        df["atr"] = true_range.rolling(window=14).mean()
        
        if use_volume_filter:
            df["vol_sma"] = df["volume"].rolling(window=20).mean()
            
        df["signal"] = "HOLD"
        df["entry_price"] = 0.0
        df["sl_price"] = 0.0
        df["tp_price"] = 0.0
        df["has_fvg"] = False
        
        last_bull_sweep_idx = -1
        last_bull_sweep_low = 0.0
        last_bear_sweep_idx = -1
        last_bear_sweep_high = 0.0
        
        # Populate signals
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        opens = df["open"].values
        swing_highs = df["swing_high"].values
        swing_lows = df["swing_low"].values
        emas = df["trend_ema_val"].values
        atrs = df["atr"].values
        
        volumes = df["volume"].values if use_volume_filter else None
        vol_smas = df["vol_sma"].values if use_volume_filter else None
        
        signals = ["HOLD"] * len(df)
        entry_prices = [0.0] * len(df)
        sl_prices = [0.0] * len(df)
        tp_prices = [0.0] * len(df)
        has_fvgs = [False] * len(df)
        
        timestamps = df.index.astype(np.int64) // 10**9
        
        start_idx = int(max(sweep_window, trend_ema) + 2)
        
        for i in range(start_idx, len(df)):
            high_prev = swing_highs[i]
            low_prev = swing_lows[i]
            ema_val = emas[i]
            atr_val = atrs[i]
            
            h = highs[i]
            l = lows[i]
            c = closes[i]
            o = opens[i]
            
            candle_range = h - l
            if candle_range == 0:
                continue
                
            # Sweep Detection
            is_bull_sweep_now = (l < low_prev) and (c > low_prev)
            if is_bull_sweep_now:
                lower_wick = min(c, o) - l
                is_bull_rejection = (lower_wick / candle_range >= 0.35) or (c > o and closes[i-1] < opens[i-1])
                if is_bull_rejection:
                    last_bull_sweep_idx = i
                    last_bull_sweep_low = l
                    last_bear_sweep_idx = -1
                    
            is_bear_sweep_now = (h > high_prev) and (c < high_prev)
            if is_bear_sweep_now:
                upper_wick = h - max(c, o)
                is_bear_rejection = (upper_wick / candle_range >= 0.35) or (c < o and closes[i-1] > opens[i-1])
                if is_bear_rejection:
                    last_bear_sweep_idx = i
                    last_bear_sweep_high = h
                    last_bull_sweep_idx = -1
                    
            # Stateful Signal Evaluation
            # 1. BULLISH SETUP
            if last_bull_sweep_idx != -1:
                if i - last_bull_sweep_idx > max_hold_sweep:
                    last_bull_sweep_idx = -1
                else:
                    is_bullish_mss = c > max(closes[i-1], closes[i-2], closes[i-3])
                    if is_bullish_mss:
                        trend_ok = True
                        if require_trend:
                            trend_ok = (c > ema_val)
                            
                        if use_premium_discount and trend_ok:
                            s_h = swing_highs[last_bull_sweep_idx]
                            s_l = swing_lows[last_bull_sweep_idx]
                            zone = get_premium_discount_zone(c, s_h, s_l)
                            trend_ok = (zone == "DISCOUNT")
                            
                        if trend_ok:
                            if use_session_filter:
                                if not check_session(timestamps[i], True):
                                    trend_ok = False
                                    
                            if trend_ok and use_ote_filter:
                                fvg_gap = lows[i] - highs[i-2]
                                entry_price_check = (lows[i] + highs[i-2]) / 2.0 if fvg_gap > 0 else c
                                s_h = swing_highs[last_bull_sweep_idx]
                                s_l = swing_lows[last_bull_sweep_idx]
                                if not check_ote_condition(entry_price_check, s_h, s_l, "BUY", ote_min, ote_max):
                                    trend_ok = False
                                    
                            if trend_ok and use_volume_filter:
                                vol_sma_val = vol_smas[i]
                                if not pd.isna(vol_sma_val) and vol_sma_val > 0:
                                    if volumes[i] / vol_sma_val <= volume_ratio:
                                        trend_ok = False
                                        
                        if trend_ok:
                            signals[i] = "BUY"
                            sl = last_bull_sweep_low - (atr_val * atr_multiplier)
                            
                            fvg_gap = lows[i] - highs[i-2]
                            if fvg_gap > 0:
                                has_fvgs[i] = True
                                fvg_mid = (lows[i] + highs[i-2]) / 2.0
                                entry_prices[i] = fvg_mid
                            else:
                                entry_prices[i] = c
                                
                            risk = entry_prices[i] - sl
                            if risk <= 0:
                                risk = atr_val * 0.5
                                sl = entry_prices[i] - risk
                                
                            sl_prices[i] = sl
                            tp_prices[i] = entry_prices[i] + (target_rr * risk)
                            last_bull_sweep_idx = -1
                            
            # 2. BEARISH SETUP
            if last_bear_sweep_idx != -1:
                if i - last_bear_sweep_idx > max_hold_sweep:
                    last_bear_sweep_idx = -1
                else:
                    is_bearish_mss = c < min(closes[i-1], closes[i-2], closes[i-3])
                    if is_bearish_mss:
                        trend_ok = True
                        if require_trend:
                            trend_ok = (c < ema_val)
                            
                        if use_premium_discount and trend_ok:
                            s_h = swing_highs[last_bear_sweep_idx]
                            s_l = swing_lows[last_bear_sweep_idx]
                            zone = get_premium_discount_zone(c, s_h, s_l)
                            trend_ok = (zone == "PREMIUM")
                            
                        if trend_ok:
                            if use_session_filter:
                                if not check_session(timestamps[i], True):
                                    trend_ok = False
                                    
                            if trend_ok and use_ote_filter:
                                fvg_gap = lows[i-2] - highs[i]
                                entry_price_check = (highs[i] + lows[i-2]) / 2.0 if fvg_gap > 0 else c
                                s_h = swing_highs[last_bear_sweep_idx]
                                s_l = swing_lows[last_bear_sweep_idx]
                                if not check_ote_condition(entry_price_check, s_h, s_l, "SELL", ote_min, ote_max):
                                    trend_ok = False
                                    
                            if trend_ok and use_volume_filter:
                                vol_sma_val = vol_smas[i]
                                if not pd.isna(vol_sma_val) and vol_sma_val > 0:
                                    if volumes[i] / vol_sma_val <= volume_ratio:
                                        trend_ok = False
                                        
                        if trend_ok:
                            signals[i] = "SELL"
                            sl = last_bear_sweep_high + (atr_val * atr_multiplier)
                            
                            fvg_gap = lows[i-2] - highs[i]
                            if fvg_gap > 0:
                                has_fvgs[i] = True
                                fvg_mid = (highs[i] + lows[i-2]) / 2.0
                                entry_prices[i] = fvg_mid
                            else:
                                entry_prices[i] = c
                                
                            risk = sl - entry_prices[i]
                            if risk <= 0:
                                risk = atr_val * 0.5
                                sl = entry_prices[i] + risk
                                
                            sl_prices[i] = sl
                            tp_prices[i] = entry_prices[i] - (target_rr * risk)
                            last_bear_sweep_idx = -1
                            
        # Simulation
        trades = []
        active_trade = None
        
        i = 0
        n = len(df)
        while i < n:
            if active_trade is not None:
                k_low = lows[i]
                k_high = highs[i]
                k_close = closes[i]
                k_dt = df.index[i]
                
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
                            
                            sl_pct_dist = risk / entry_price
                            active_trade["fee_r"] = 0.00063 / max(sl_pct_dist, 0.001)
                            trades.append(active_trade)
                            active_trade = None
                        elif use_partial and k_high >= partial_tp:
                            active_trade["stage"] = 2
                            active_trade["sl_price"] = entry_price
                            active_trade["locked_r"] = 0.5 * partial_rr
                    elif stage == 2:
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
                    else: # No partial profits
                        if k_low <= sl_price:
                            active_trade["outcome"] = "LOSS"
                            active_trade["exit_price"] = sl_price
                            active_trade["exit_datetime"] = k_dt
                            active_trade["pnl_r"] = -1.0
                            
                            sl_pct_dist = risk / entry_price
                            active_trade["fee_r"] = 0.00063 / max(sl_pct_dist, 0.001)
                            trades.append(active_trade)
                            active_trade = None
                        elif k_high >= final_tp:
                            active_trade["outcome"] = "WIN"
                            active_trade["exit_price"] = final_tp
                            active_trade["exit_datetime"] = k_dt
                            active_trade["pnl_r"] = target_rr
                            
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
                        elif use_partial and k_low <= partial_tp:
                            active_trade["stage"] = 2
                            active_trade["sl_price"] = entry_price
                            active_trade["locked_r"] = 0.5 * partial_rr
                    elif stage == 2:
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
                    else: # No partial profits
                        if k_high >= sl_price:
                            active_trade["outcome"] = "LOSS"
                            active_trade["exit_price"] = sl_price
                            active_trade["exit_datetime"] = k_dt
                            active_trade["pnl_r"] = -1.0
                            
                            sl_pct_dist = risk / entry_price
                            active_trade["fee_r"] = 0.00063 / max(sl_pct_dist, 0.001)
                            trades.append(active_trade)
                            active_trade = None
                        elif k_low <= final_tp:
                            active_trade["outcome"] = "WIN"
                            active_trade["exit_price"] = final_tp
                            active_trade["exit_datetime"] = k_dt
                            active_trade["pnl_r"] = target_rr
                            
                            sl_pct_dist = risk / entry_price
                            active_trade["fee_r"] = 0.00036 / max(sl_pct_dist, 0.001)
                            trades.append(active_trade)
                            active_trade = None
                i += 1
                continue
                
            sig = signals[i]
            if sig in ("BUY", "SELL"):
                entry_target = entry_prices[i]
                sl_price = sl_prices[i]
                tp_price = tp_prices[i]
                has_fvg = has_fvgs[i]
                
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
                    if idx_check >= len(df):
                        break
                    
                    check_low = lows[idx_check]
                    check_high = highs[idx_check]
                    
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
                        "entry_datetime": df.index[fill_idx],
                        "stage": 1 if use_partial else 0,
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
            
            sl_pct_dist = risk / entry_price
            active_trade["fee_r"] = 0.00063 / max(sl_pct_dist, 0.001)
            trades.append(active_trade)
            
        return trades
    except Exception as e:
        return []

def evaluate_parameters(all_files, params):
    """Evaluates a single parameter dict across all files."""
    all_trades = []
    for f in all_files:
        trades = backtest_single_pair(f, params)
        all_trades.extend(trades)
        
    if not all_trades:
        return {
            "net_pnl": -9999.0,
            "total_trades": 0,
            "win_rate": 0.0,
            "fees": 0.0,
            "max_dd": 999.0
        }
        
    # Sort chronologically to get DD
    all_trades = sorted(all_trades, key=lambda x: x["entry_datetime"] if x["entry_datetime"] is not None else "")
    
    total_trades = len(all_trades)
    wins = sum(1 for t in all_trades if t["outcome"] == "WIN")
    losses = sum(1 for t in all_trades if t["outcome"] == "LOSS")
    bes = sum(1 for t in all_trades if t["outcome"] == "BE")
    completed = wins + losses + bes
    win_rate = (wins + bes) / completed * 100 if completed > 0 else 0.0
    
    gross_pnl = sum(t["pnl_r"] for t in all_trades)
    total_fees = sum(t["fee_r"] for t in all_trades)
    net_pnl = gross_pnl - total_fees
    
    cumulative_pnl = []
    current_pnl = 0.0
    for t in all_trades:
        current_pnl += (t["pnl_r"] - t["fee_r"])
        cumulative_pnl.append(current_pnl)
        
    cum_series = pd.Series(cumulative_pnl)
    peaks = cum_series.cummax()
    drawdowns = peaks - cum_series
    max_dd = drawdowns.max() if not drawdowns.empty else 0.0
    
    return {
        "net_pnl": net_pnl,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "fees": total_fees,
        "max_dd": max_dd
    }

def run_worker(job):
    job_id, all_files, params = job
    metrics = evaluate_parameters(all_files, params)
    return job_id, params, metrics

def main():
    # Load all symbol files
    all_files_15m = list(DATA_DIR_15M.glob("*_15m.csv"))
    if not all_files_15m:
        print("No historical files found!")
        return
        
    print(f"Loaded {len(all_files_15m)} 15m historical files.")
    
    # Define a subset of representative coins for rapid testing (top coins)
    major_tokens = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "LINK", "AVAX", "LTC", "ONDO", "SUI", "NEAR", "OP", "TRX"]
    subset_files = [f for f in all_files_15m if any(token in f.name for token in major_tokens)]
    if not subset_files:
        subset_files = all_files_15m[:15]
    print(f"Selected {len(subset_files)} tokens for fast search: {[f.name.split('_')[0] for f in subset_files]}")
    
    # Generate search space configurations
    configs = []
    
    # Let's seed for reproducibility
    random.seed(42)
    
    sweep_windows = [40, 60, 80, 100, 120, 150, 180, 200]
    max_hold_sweeps = [3, 4, 5, 6, 8, 10]
    target_rrs = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
    partial_rrs = [1.0, 1.2, 1.5, 1.8, 2.0]
    use_partials = [True, False]
    require_trends = [True, False]
    trend_emas = [50, 100, 200]
    use_premium_discounts = [True, False]
    atr_multipliers = [0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.2, 1.5]
    fvg_waits = [2, 3, 4, 5]
    use_session_filters = [True, False]
    use_ote_filters = [True, False]
    ote_mins = [0.5, 0.62, 0.705]
    use_volume_filters = [True, False]
    volume_ratios = [1.2, 1.5, 1.8, 2.0]
    
    # Add baseline configs to make sure we don't miss classic structures
    configs.append({
        "sweep_window": 120,
        "max_hold_sweep": 5,
        "target_rr": 3.0,
        "partial_rr": 1.5,
        "use_partial": True,
        "require_trend": True,
        "trend_ema": 200,
        "use_premium_discount": True,
        "atr_multiplier": 0.5,
        "fvg_wait": 3,
        "use_session_filter": True,
        "use_ote_filter": False,
        "use_volume_filter": False
    })
    
    # Generate 300 random configurations
    for _ in range(300):
        use_ote = random.choice(use_ote_filters)
        use_vol = random.choice(use_volume_filters)
        configs.append({
            "sweep_window": random.choice(sweep_windows),
            "max_hold_sweep": random.choice(max_hold_sweeps),
            "target_rr": random.choice(target_rrs),
            "partial_rr": random.choice(partial_rrs),
            "use_partial": random.choice(use_partials),
            "require_trend": random.choice(require_trends),
            "trend_ema": random.choice(trend_emas),
            "use_premium_discount": random.choice(use_premium_discounts),
            "atr_multiplier": random.choice(atr_multipliers),
            "fvg_wait": random.choice(fvg_waits),
            "use_session_filter": random.choice(use_session_filters),
            "use_ote_filter": use_ote,
            "ote_min": random.choice(ote_mins) if use_ote else 0.62,
            "ote_max": 0.79 if use_ote else 0.79,
            "use_volume_filter": use_vol,
            "volume_ratio": random.choice(volume_ratios) if use_vol else 1.5
        })
        
    print(f"Generated {len(configs)} configurations for search.")
    
    jobs = [(idx, subset_files, cfg) for idx, cfg in enumerate(configs)]
    
    num_workers = min(multiprocessing.cpu_count(), 16)
    print(f"Starting parameter search using {num_workers} parallel workers...")
    
    start_time = time.time()
    results = []
    
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        for job_id, params, metrics in executor.map(run_worker, jobs):
            results.append((job_id, params, metrics))
            if len(results) % 50 == 0:
                print(f"Processed {len(results)}/{len(configs)} configurations...")
                
    elapsed = time.time() - start_time
    print(f"Search completed in {elapsed:.2f} seconds.")
    
    # Sort results by net PnL descending
    valid_results = [r for r in results if r[2]["net_pnl"] != -9999.0]
    sorted_results = sorted(valid_results, key=lambda x: x[2]["net_pnl"], reverse=True)
    
    print("\n" + "=" * 80)
    print("🏆 TOP 10 CONFIGURATIONS ON 15 REPRESENTATIVE TOKENS")
    print("=" * 80)
    for idx, (job_id, params, metrics) in enumerate(sorted_results[:10]):
        print(f"#{idx+1}: Net PnL: {metrics['net_pnl']:+.2f}R | Trades: {metrics['total_trades']} | Win Rate: {metrics['win_rate']:.2f}% | Max DD: {metrics['max_dd']:.2f}R")
        print(f"    Params: sweep_w: {params['sweep_window']}, max_sweep_h: {params['max_hold_sweep']}, atr_mult: {params['atr_multiplier']}, rr: {params['target_rr']}, partial: {params['use_partial']} (prr: {params['partial_rr'] if params['use_partial'] else 'N/A'}), trend: {params['require_trend']} (ema {params['trend_ema'] if params['require_trend'] else 'N/A'}), prem_disc: {params['use_premium_discount']}, session: {params['use_session_filter']}, ote: {params['use_ote_filter']}, vol: {params['use_volume_filter']}")
        print("-" * 80)
        
    # Now, take the top 5 configurations and run them on all 100 coins!
    print("\n" + "=" * 80)
    print("🔍 VALIDATING TOP 5 CONFIGURATIONS ON ALL 100 COINS...")
    print("=" * 80)
    
    top_5 = sorted_results[:5]
    final_results = []
    for idx, (job_id, params, _) in enumerate(top_5):
        print(f"Validating Top Configuration #{idx+1} on 100 coins...")
        metrics = evaluate_parameters(all_files_15m, params)
        final_results.append((params, metrics))
        print(f"  Result on 100 coins: Net PnL: {metrics['net_pnl']:+.2f}R | Trades: {metrics['total_trades']} | Win Rate: {metrics['win_rate']:.2f}% | Max DD: {metrics['max_dd']:.2f}R")
        print("-" * 60)
        
    # Sort final results by net PnL
    final_results = sorted(final_results, key=lambda x: x[1]["net_pnl"], reverse=True)
    best_params = final_results[0][0]
    best_metrics = final_results[0][1]
    
    print("\n" + "=" * 80)
    print("👑 ULTIMATE OPTIMIZED PA/SMC STRATEGY PARAMETERS FOUND:")
    print("=" * 80)
    print(f"Net PnL: {best_metrics['net_pnl']:+.2f} R-units")
    print(f"Total Trades: {best_metrics['total_trades']}")
    print(f"Win Rate: {best_metrics['win_rate']:.2f}%")
    print(f"Max Drawdown: {best_metrics['max_dd']:.2f} R-units")
    print("-" * 80)
    for k, v in best_params.items():
        print(f"  {k:<22}: {v}")
    print("=" * 80)

if __name__ == "__main__":
    main()
