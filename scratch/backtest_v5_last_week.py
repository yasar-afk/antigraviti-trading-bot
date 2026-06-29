# -*- coding: utf-8 -*-
"""
scratch/backtest_v5_last_week.py — V5 Backtest for the last 7 days.
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

# V5 Parameters
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

def backtest_v5_last_week():
    all_files = list(DATA_DIR_15M.glob("*_15m.csv"))
    if not all_files:
        print("No historical files found!")
        return

    # Filter files and date range
    start_date = pd.to_datetime("2026-06-07 23:00:00+00:00")
    end_date = pd.to_datetime("2026-06-14 23:00:00+00:00")
    
    all_trades = []
    
    for file_path in all_files:
        symbol = file_path.name.split("_USDT")[0].replace("_", "/")
        try:
            df = pd.read_csv(file_path)
            if len(df) < 220:
                continue
                
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
            
            # Run calculations
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
                
                # Apply filter to only capture entries within the last week
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
                        
                    # ONLY ENTER trades if the signal date is within the last 7 days
                    if k_dt < start_date or k_dt > end_date:
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

    # Filter out trades that were entered in the last week
    weekly_trades = [t for t in all_trades if t["entry_datetime"] >= start_date and t["entry_datetime"] <= end_date]
    
    if not weekly_trades:
        print("No trades occurred in the last week.")
        return

    weekly_trades = sorted(weekly_trades, key=lambda x: x["entry_datetime"])
    
    total_trades = len(weekly_trades)
    wins = sum(1 for t in weekly_trades if t["outcome"] == "WIN")
    losses = sum(1 for t in weekly_trades if t["outcome"] == "LOSS")
    opens = sum(1 for t in weekly_trades if t["outcome"] == "OPEN")
    
    completed = wins + losses
    win_rate = wins / completed * 100 if completed > 0 else 0.0
    
    gross_pnl_r = sum(t["pnl_r"] for t in weekly_trades)
    total_fees_r = sum(t["fee_r"] for t in weekly_trades)
    net_pnl_r = gross_pnl_r - total_fees_r
    
    print("\n" + "=" * 80)
    print(f"📊 BACKTEST RAPORU: SON 1 HAFTA (7 Haziran - 14 Haziran 2026)")
    print("=" * 80)
    print(f"Toplam İşlem Sayısı   : {total_trades}")
    print(f"  - Kazançlı (WIN)    : {wins}")
    print(f"  - Zararlı (LOSS)    : {losses}")
    print(f"  - Açık/Bekleyen    : {opens}")
    print(f"Kazanma Oranı (WR)    : {win_rate:.2f}%")
    print(f"Brüt PnL (R-birimi)   : {gross_pnl_r:+.2f} R")
    print(f"Toplam Komisyon (R)   : {total_fees_r:.2f} R")
    print(f"Net PnL (R-birimi)    : {net_pnl_r:+.2f} R")
    print("-" * 80)
    
    # Capital parameters
    init_capital = 10000.0
    risk_pct = 0.02 # 2% risk
    risk_amount = init_capital * risk_pct # $200 per trade
    
    usd_karsi = net_pnl_r * risk_amount
    yuzde_karsi = net_pnl_r * risk_pct * 100
    
    print(f"Başlangıç Bakiyesi    : ${init_capital:,.2f} USDT")
    print(f"İşlem Başı Risk (%2)  : ${risk_amount:,.2f} USDT")
    print(f"Haftalık Kâr Yüzdesi  : {yuzde_karsi:+.2f}%")
    print(f"Haftalık Net Kazanç   : {usd_karsi:+,.2f} USDT")
    print(f"Son Bakiye            : ${(init_capital + usd_karsi):,.2f} USDT")
    print("=" * 80)
    
    print("\nSon 10 İşlemin Listesi:")
    print(f"{'Tarih':<16} | {'Sembol':<10} | {'Yön':<5} | {'Giriş':>9} | {'Çıkış':>9} | {'Sonuç':<6} | {'Net R':>6}")
    print("-" * 80)
    for t in weekly_trades[-10:]:
        exit_p = t.get("exit_price", 0.0)
        exit_str = f"{exit_p:.4f}" if exit_p > 0 else "-"
        pnl_val = t["pnl_r"] - t["fee_r"]
        print(f"{t['entry_datetime'].strftime('%m-%d %H:%M'):<16} | {t['symbol']:<10} | {t['side']:<5} | {t['entry_price']:>9.4f} | {exit_str:>9} | {t['outcome']:<6} | {pnl_val:>+6.2f}R")

if __name__ == "__main__":
    backtest_v5_last_week()
