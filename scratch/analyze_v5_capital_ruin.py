# -*- coding: utf-8 -*-
"""
scratch/analyze_v5_capital_ruin.py — Simulates account balance over the 100-day backtest of V5 strategy.
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Windows console output encoding fix
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.strategy.smc_utils import get_premium_discount_zone

DATA_DIR_15M = PROJECT_ROOT / "data" / "historical" / "15m"

params = {
    "sweep_window": 100,
    "max_hold_sweep": 7,
    "target_rr": 5.5,
    "require_trend": True,
    "trend_ema": 180,
    "use_premium_discount": True,
    "atr_multiplier": 0.6,
    "fvg_wait": 3,
    "use_session_filter": False,
    "use_partial": False
}

def load_v5_trades():
    all_files = list(DATA_DIR_15M.glob("*_15m.csv"))
    all_trades = []
    
    for file_path in all_files:
        symbol = file_path.name.split("_USDT")[0].replace("_", "/")
        try:
            df = pd.read_csv(file_path)
            if len(df) < 220:
                continue
                
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
            
            last_bull_sweep_idx = -1
            last_bull_sweep_low = 0.0
            last_bear_sweep_idx = -1
            last_bear_sweep_high = 0.0
            
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
                                
            # Simulate
            trades = []
            active_trade = None
            
            i = 0
            n = len(df)
            while i < n:
                k_dt = df.index[i]
                if active_trade is not None:
                    k_low = lows[i]
                    k_high = highs[i]
                    
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
                            "symbol": symbol,
                            "side": sig,
                            "entry_price": entry_target,
                            "sl_price": sl_price,
                            "final_tp": tp_price,
                            "entry_datetime": df.index[fill_idx],
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
                
            all_trades.extend(trades)
        except Exception:
            pass

    return sorted(all_trades, key=lambda x: x["entry_datetime"] if x["entry_datetime"] is not None else "")

def main():
    print("Extracting all V5 trades chronologically...")
    trades = load_v5_trades()
    print(f"Total V5 trades executed: {len(trades)}")
    
    initial_balance = 10000.0
    
    # 1. FIXED RISK 2% ($200 per trade)
    balance_fixed_2 = initial_balance
    min_balance_fixed_2 = initial_balance
    blew_account_fixed_2 = False
    blew_at_index_fixed_2 = -1
    
    # 2. DYNAMIC RISK 2% (2% of current balance)
    balance_dyn_2 = initial_balance
    min_balance_dyn_2 = initial_balance
    
    # 3. DYNAMIC RISK 1% (1% of current balance)
    balance_dyn_1 = initial_balance
    min_balance_dyn_1 = initial_balance
    
    # 4. DYNAMIC RISK 0.5% (0.5% of current balance)
    balance_dyn_05 = initial_balance
    min_balance_dyn_05 = initial_balance

    for idx, t in enumerate(trades):
        r_outcome = t["pnl_r"] - t["fee_r"]
        
        # 1. Fixed $200 per trade
        if not blew_account_fixed_2:
            fixed_win_loss = r_outcome * 200.0
            balance_fixed_2 += fixed_win_loss
            if balance_fixed_2 < min_balance_fixed_2:
                min_balance_fixed_2 = balance_fixed_2
            if balance_fixed_2 <= 0:
                blew_account_fixed_2 = True
                blew_at_index_fixed_2 = idx
                
        # 2. Dynamic 2% of current balance
        risk_dyn_2 = balance_dyn_2 * 0.02
        balance_dyn_2 += r_outcome * risk_dyn_2
        if balance_dyn_2 < min_balance_dyn_2:
            min_balance_dyn_2 = balance_dyn_2
            
        # 3. Dynamic 1% of current balance
        risk_dyn_1 = balance_dyn_1 * 0.01
        balance_dyn_1 += r_outcome * risk_dyn_1
        if balance_dyn_1 < min_balance_dyn_1:
            min_balance_dyn_1 = balance_dyn_1
            
        # 4. Dynamic 0.5% of current balance
        risk_dyn_05 = balance_dyn_05 * 0.005
        balance_dyn_05 += r_outcome * risk_dyn_05
        if balance_dyn_05 < min_balance_dyn_05:
            min_balance_dyn_05 = balance_dyn_05

    print("\n" + "=" * 80)
    print("📈 PORTFOLIO RUIN SIMULATION (100 DAYS - V5)")
    print("=" * 80)
    print(f"Başlangıç Bakiyesi: ${initial_balance:,.2f} USDT\n")
    
    # Scenario A
    print("A) Sabit $200 Risk (İlkin %2'si - Sabit):")
    if blew_account_fixed_2:
        print(f"  ❌ HESAP SIFIRLANDI! (İşlem #{blew_at_index_fixed_2 + 1}'de kasa 0'ın altına indi.)")
        print(f"  En Düşük Bakiye: ${min_balance_fixed_2:,.2f} USDT")
    else:
        print(f"  ✅ Hayatta kaldı.")
        print(f"  En Düşük Bakiye: ${min_balance_fixed_2:,.2f} USDT")
        print(f"  Son Bakiye: ${balance_fixed_2:,.2f} USDT")
    print("-" * 60)
        
    # Scenario B
    print("B) Dinamik %2 Risk (Mevcut Bakiyenin %2'si):")
    print(f"  ✅ Matematiksel olarak patlaması imkansız.")
    print(f"  En Düşük Bakiye: ${min_balance_dyn_2:,.2f} USDT (Maksimum Düşüşte Ulaşılan Nokta)")
    print(f"  Son Bakiye: ${balance_dyn_2:,.2f} USDT")
    print("-" * 60)
    
    # Scenario C
    print("C) Dinamik %1 Risk (Mevcut Bakiyenin %1'i):")
    print(f"  ✅ Hayatta kaldı.")
    print(f"  En Düşük Bakiye: ${min_balance_dyn_1:,.2f} USDT")
    print(f"  Son Bakiye: ${balance_dyn_1:,.2f} USDT")
    print("-" * 60)
    
    # Scenario D
    print("D) Dinamik %0.5 Risk (Mevcut Bakiyenin %0.5'i):")
    print(f"  ✅ Hayatta kaldı.")
    print(f"  En Düşük Bakiye: ${min_balance_dyn_05:,.2f} USDT")
    print(f"  Son Bakiye: ${balance_dyn_05:,.2f} USDT")
    print("=" * 80)

if __name__ == "__main__":
    main()
