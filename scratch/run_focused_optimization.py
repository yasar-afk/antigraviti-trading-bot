# -*- coding: utf-8 -*-
"""
scratch/run_focused_optimization.py — Focused optimization around the top configuration neighborhood.
"""
import os
import sys
import time
import random
from pathlib import Path
import pandas as pd
import numpy as np
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
        dt = pd.to_datetime(timestamp, unit='s', utc=True)
        hour = dt.hour
        return (7 <= hour < 10) or (12 <= hour < 16)
    except Exception:
        return False

def backtest_single_pair(file_path, params):
    try:
        df = pd.read_csv(file_path)
        if len(df) < 220:
            return []
            
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
        
        sweep_window = params["sweep_window"]
        max_hold_sweep = params["max_hold_sweep"]
        target_rr = params["target_rr"]
        require_trend = params["require_trend"]
        trend_ema = params["trend_ema"]
        use_premium_discount = params["use_premium_discount"]
        atr_multiplier = params["atr_multiplier"]
        fvg_wait = params["fvg_wait"]
        use_session_filter = params["use_session_filter"]
        
        df["swing_high"] = df["high"].shift(1).rolling(window=sweep_window).max()
        df["swing_low"] = df["low"].shift(1).rolling(window=sweep_window).min()
        df["trend_ema_val"] = df["close"].ewm(span=trend_ema, adjust=False).mean()
        
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        df["atr"] = true_range.rolling(window=14).mean()
        
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        opens = df["open"].values
        swing_highs = df["swing_high"].values
        swing_lows = df["swing_low"].values
        emas = df["trend_ema_val"].values
        atrs = df["atr"].values
        
        signals = ["HOLD"] * len(df)
        entry_prices = [0.0] * len(df)
        sl_prices = [0.0] * len(df)
        tp_prices = [0.0] * len(df)
        has_fvgs = [False] * len(df)
        
        timestamps = df.index.astype(np.int64) // 10**9
        
        start_idx = int(max(sweep_window, trend_ema) + 2)
        
        last_bull_sweep_idx = -1
        last_bull_sweep_low = 0.0
        last_bear_sweep_idx = -1
        last_bear_sweep_high = 0.0
        
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
                            
        trades = []
        active_trade = None
        
        i = 0
        n = len(df)
        while i < n:
            if active_trade is not None:
                k_low = lows[i]
                k_high = highs[i]
                k_dt = df.index[i]
                
                side = active_trade["side"]
                entry_price = active_trade["entry_price"]
                sl_price = active_trade["sl_price"]
                final_tp = active_trade["final_tp"]
                risk = active_trade["risk"]
                
                if side == "BUY":
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
                else: # SELL
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
                else:
                    risk = sl_price - entry_target
                    
                if risk <= 0:
                    i += 1
                    continue
                    
                filled = False
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
                    else:
                        if check_high >= entry_target:
                            filled = True
                            fill_idx = idx_check
                            break
                            
                if filled:
                    active_trade = {
                        "side": sig,
                        "entry_price": entry_target,
                        "sl_price": sl_price,
                        "final_tp": tp_price,
                        "entry_datetime": df.index[fill_idx],
                        "stage": 0,
                        "outcome": "OPEN",
                        "pnl_r": 0.0,
                        "risk": risk
                    }
                    i = fill_idx
                else:
                    i += 1
            else:
                i += 1
                
        if active_trade is not None:
            active_trade["pnl_r"] = 0.0
            sl_pct_dist = risk / entry_price
            active_trade["fee_r"] = 0.00063 / max(sl_pct_dist, 0.001)
            trades.append(active_trade)
            
        return trades
    except Exception:
        return []

def evaluate_parameters(all_files, params):
    all_trades = []
    for f in all_files:
        trades = backtest_single_pair(f, params)
        all_trades.extend(trades)
        
    if not all_trades:
        return {"net_pnl": -9999.0, "total_trades": 0, "win_rate": 0.0, "max_dd": 999.0}
        
    all_trades = sorted(all_trades, key=lambda x: x["entry_datetime"] if x["entry_datetime"] is not None else "")
    
    total_trades = len(all_trades)
    wins = sum(1 for t in all_trades if t["outcome"] == "WIN")
    losses = sum(1 for t in all_trades if t["outcome"] == "LOSS")
    completed = wins + losses
    win_rate = wins / completed * 100 if completed > 0 else 0.0
    
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
    all_files_15m = list(DATA_DIR_15M.glob("*_15m.csv"))
    if not all_files_15m:
        return
        
    # Generate search space in the neighborhood of best config:
    # best: sweep_window: 120, max_hold_sweep: 6, atr_multiplier: 0.5, target_rr: 4.5, trend_ema: 200, require_trend: True
    configs = []
    
    # Grid search in the neighborhood
    sweep_windows = [100, 110, 120, 130, 140]
    max_hold_sweeps = [5, 6, 7]
    target_rrs = [3.5, 4.0, 4.2, 4.5, 4.8, 5.0, 5.5]
    atr_multipliers = [0.4, 0.45, 0.5, 0.55, 0.6]
    trend_emas = [150, 180, 200, 220, 250]
    use_premium_discounts = [True, False]
    use_session_filters = [True, False]
    
    for sw in sweep_windows:
        for mhs in max_hold_sweeps:
            for rr in target_rrs:
                for am in atr_multipliers:
                    for ema in trend_emas:
                        for pd_val in use_premium_discounts:
                            for sf_val in use_session_filters:
                                configs.append({
                                    "sweep_window": sw,
                                    "max_hold_sweep": mhs,
                                    "target_rr": rr,
                                    "atr_multiplier": am,
                                    "trend_ema": ema,
                                    "require_trend": True,
                                    "use_premium_discount": pd_val,
                                    "use_session_filter": sf_val,
                                    "fvg_wait": 3
                                })
                                
    # Since grid is 5 * 3 * 7 * 5 * 5 * 2 * 2 = 10,500 combinations,
    # let's run a random sample of 400 from this high-potential neighborhood.
    random.seed(99)
    configs = random.sample(configs, 400)
    
    # Include the best from last run to compare
    configs.append({
        "sweep_window": 120,
        "max_hold_sweep": 6,
        "target_rr": 4.5,
        "atr_multiplier": 0.5,
        "trend_ema": 200,
        "require_trend": True,
        "use_premium_discount": False,
        "use_session_filter": False,
        "fvg_wait": 3
    })
    
    # We will test this directly on all 100 coins! Since it's only 400 runs,
    # and 1 run on 100 coins takes ~2-3 seconds, with 12 workers it will take ~80-100 seconds total!
    print(f"Starting focused optimization grid search of {len(configs)} configs on all 100 coins directly...")
    
    jobs = [(idx, all_files_15m, cfg) for idx, cfg in enumerate(configs)]
    num_workers = min(multiprocessing.cpu_count(), 16)
    
    start_time = time.time()
    results = []
    
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        for job_id, params, metrics in executor.map(run_worker, jobs):
            results.append((job_id, params, metrics))
            if len(results) % 50 == 0:
                print(f"Processed {len(results)}/{len(configs)} configurations on 100 coins...")
                
    elapsed = time.time() - start_time
    print(f"Focused sweep completed in {elapsed:.2f} seconds.")
    
    sorted_results = sorted(results, key=lambda x: x[2]["net_pnl"], reverse=True)
    
    print("\n" + "=" * 80)
    print("🏆 TOP 10 REFINED CONFIGURATIONS (ALL 100 COINS)")
    print("=" * 80)
    for idx, (job_id, params, metrics) in enumerate(sorted_results[:10]):
        print(f"#{idx+1}: Net PnL: {metrics['net_pnl']:+.2f}R | Trades: {metrics['total_trades']} | Win Rate: {metrics['win_rate']:.2f}% | Max DD: {metrics['max_dd']:.2f}R")
        print(f"    Params: sweep_w: {params['sweep_window']}, max_sweep_h: {params['max_hold_sweep']}, atr_mult: {params['atr_multiplier']}, rr: {params['target_rr']}, trend_ema: {params['trend_ema']}, prem_disc: {params['use_premium_discount']}, session: {params['use_session_filter']}")
        print("-" * 80)

if __name__ == "__main__":
    main()
