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
from src.strategy.smc_utils import get_premium_discount_zone

DATA_DIR = PROJECT_ROOT / "data" / "historical" / "15m"

class AdvancedV3PriceActionStrategy(V3PriceActionStrategy):
    """Subclass of V3 PA strategy to support custom backtest logic with Funding and OI filters."""
    
    def __init__(self, use_filters=False, max_funding=0.0005, min_funding=-0.0005, require_oi_increase=True, **kwargs):
        super().__init__(**kwargs)
        self.use_filters = use_filters
        self.max_funding = max_funding
        self.min_funding = min_funding
        self.require_oi_increase = require_oi_increase

    def calculate_signals_with_filters(self, df):
        """Calculates signals but applies filters to entry setups if use_filters is True."""
        df = df.copy()
        
        # Base signals from standard strategy
        # (swing_high, swing_low, ema200, atr, base signals)
        df["swing_high"] = df["high"].shift(1).rolling(window=self.sweep_window).max()
        df["swing_low"] = df["low"].shift(1).rolling(window=self.sweep_window).min()
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
        
        # We need historical columns if they exist, else default to 0.0
        if "funding_rate" not in df.columns:
            df["funding_rate"] = 0.0
        if "open_interest" not in df.columns:
            df["open_interest"] = 0.0
            
        last_bull_sweep_idx = -1
        last_bull_sweep_low = 0.0
        
        last_bear_sweep_idx = -1
        last_bear_sweep_high = 0.0
        
        start_idx = int(max(self.sweep_window, 200) + 2)
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
            
            funding_rate_val = df["funding_rate"].iloc[i]
            
            candle_range = h - l
            if candle_range == 0:
                continue
                
            # Sweep detection
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
                    
            # Stateful Signal Evaluation
            # 1. BULLISH SETUP
            if last_bull_sweep_idx != -1:
                if i - last_bull_sweep_idx > self.max_hold_sweep:
                    last_bull_sweep_idx = -1
                else:
                    is_bullish_mss = c > max(df["close"].iloc[i-1], df["close"].iloc[i-2], df["close"].iloc[i-3])
                    if is_bullish_mss:
                        trend_ok = True
                        if self.require_trend:
                            trend_ok = (c > ema200_val)
                            
                        if self.use_premium_discount and trend_ok:
                            swing_h = df["swing_high"].iloc[last_bull_sweep_idx]
                            swing_l = df["swing_low"].iloc[last_bull_sweep_idx]
                            zone = get_premium_discount_zone(c, swing_h, swing_l)
                            trend_ok = (zone == "DISCOUNT")
                            
                        # Apply new filters
                        if self.use_filters and trend_ok:
                            # Filter A: Funding rate too high (Long is dangerous)
                            if funding_rate_val > self.max_funding:
                                trend_ok = False
                                
                            # Filter B: Open Interest has not increased relative to the sweep candle
                            if self.require_oi_increase and trend_ok:
                                oi_sweep = df["open_interest"].iloc[last_bull_sweep_idx]
                                oi_mss = df["open_interest"].iloc[i]
                                if oi_sweep > 0 and oi_mss > 0:
                                    if oi_mss <= oi_sweep:
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
                            df.at[df.index[i], "tp_price"] = df["entry_price"].iloc[i] + (self.target_rr * risk)
                            last_bull_sweep_idx = -1
                            
            # 2. BEARISH SETUP
            if last_bear_sweep_idx != -1:
                if i - last_bear_sweep_idx > self.max_hold_sweep:
                    last_bear_sweep_idx = -1
                else:
                    is_bearish_mss = c < min(df["close"].iloc[i-1], df["close"].iloc[i-2], df["close"].iloc[i-3])
                    if is_bearish_mss:
                        trend_ok = True
                        if self.require_trend:
                            trend_ok = (c < ema200_val)
                            
                        if self.use_premium_discount and trend_ok:
                            swing_h = df["swing_high"].iloc[last_bear_sweep_idx]
                            swing_l = df["swing_low"].iloc[last_bear_sweep_idx]
                            zone = get_premium_discount_zone(c, swing_h, swing_l)
                            trend_ok = (zone == "PREMIUM")
                            
                        # Apply new filters
                        if self.use_filters and trend_ok:
                            # Filter A: Funding rate too negative (Short is dangerous)
                            if funding_rate_val < self.min_funding:
                                trend_ok = False
                                
                            # Filter B: Open Interest has not increased relative to the sweep candle
                            if self.require_oi_increase and trend_ok:
                                oi_sweep = df["open_interest"].iloc[last_bear_sweep_idx]
                                oi_mss = df["open_interest"].iloc[i]
                                if oi_sweep > 0 and oi_mss > 0:
                                    if oi_mss <= oi_sweep:
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
                            df.at[df.index[i], "tp_price"] = df["entry_price"].iloc[i] - (self.target_rr * risk)
                            last_bear_sweep_idx = -1
                            
        return df

def run_simulation(df, strategy):
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
                    "has_fvg": has_fvg
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
        trades.append(active_trade)
        
    return trades

def evaluate_run(symbol_files, strategy_cfg):
    strategy = AdvancedV3PriceActionStrategy(
        use_filters=strategy_cfg["use_filters"],
        max_funding=strategy_cfg["max_funding"],
        min_funding=strategy_cfg["min_funding"],
        require_oi_increase=strategy_cfg["require_oi_increase"],
        sweep_window=120,
        target_rr=3.0,
        partial_rr=1.5,
        require_trend=True,
        max_hold_sweep=5,
        fvg_wait=3
    )
    
    all_trades = []
    symbol_stats = {}
    
    for file_path in symbol_files:
        symbol_name = file_path.name.replace("_15m.csv", "").replace("_", "/")
        try:
            df = pd.read_csv(file_path)
            if len(df) < 220:
                continue
                
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
            
            trades = run_simulation(df, strategy)
            if trades:
                all_trades.extend([(symbol_name, t) for t in trades])
                sym_wins = sum(1 for t in trades if t["outcome"] == "WIN")
                sym_losses = sum(1 for t in trades if t["outcome"] == "LOSS")
                sym_bes = sum(1 for t in trades if t["outcome"] == "BE")
                sym_pnl = sum(t["pnl_r"] for t in trades)
                
                symbol_stats[symbol_name] = {
                    "trades": len(trades),
                    "wins": sym_wins,
                    "losses": sym_losses,
                    "bes": sym_bes,
                    "pnl": sym_pnl
                }
        except Exception as e:
            # print(f"HATA ({symbol_name}): {e}")
            pass
            
    if not all_trades:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "bes": 0,
            "win_rate": 0.0,
            "gross_pnl": 0.0,
            "fees": 0.0,
            "net_pnl": 0.0,
            "max_dd": 0.0
        }
        
    total_trades = len(all_trades)
    wins = sum(1 for _, t in all_trades if t["outcome"] == "WIN")
    losses = sum(1 for _, t in all_trades if t["outcome"] == "LOSS")
    bes = sum(1 for _, t in all_trades if t["outcome"] == "BE")
    
    completed = wins + losses + bes
    win_rate = (wins + bes) / completed * 100 if completed > 0 else 0.0
    
    gross_pnl = sum(t["pnl_r"] for _, t in all_trades)
    fees = total_trades * 0.15
    net_pnl = gross_pnl - fees
    
    # Drawdown
    cumulative_pnl = []
    current_pnl = 0.0
    sorted_trades = sorted(all_trades, key=lambda x: x[1]["entry_datetime"] if x[1]["entry_datetime"] is not None else "")
    for _, t in sorted_trades:
        current_pnl += t["pnl_r"] - 0.15
        cumulative_pnl.append(current_pnl)
    cum_series = pd.Series(cumulative_pnl)
    peaks = cum_series.cummax()
    drawdowns = peaks - cum_series
    max_dd = drawdowns.max() if not drawdowns.empty else 0.0
    
    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "bes": bes,
        "win_rate": win_rate,
        "gross_pnl": gross_pnl,
        "fees": fees,
        "net_pnl": net_pnl,
        "max_dd": max_dd
    }

def main():
    symbol_files = list(DATA_DIR.glob("*_15m.csv"))
    if not symbol_files:
        print("Test edilecek 15m verisi bulunamadı. Lütfen önce download_15m_advanced.py betiğini çalıştırın.")
        return
        
    print(f"Toplam {len(symbol_files)} sembol dosyası üzerinden karşılaştırmalı backtest başlatılıyor...")
    print("-" * 80)
    
    # Run Standard V3 (No filters)
    cfg_standard = {
        "use_filters": False,
        "max_funding": 0.0005,
        "min_funding": -0.0005,
        "require_oi_increase": False
    }
    print("Koşul 1: Standart V3 Stratejisi simüle ediliyor...")
    res_std = evaluate_run(symbol_files, cfg_standard)
    
    # Run Advanced V3 (With Funding and OI filters)
    cfg_advanced = {
        "use_filters": True,
        "max_funding": 0.0005,
        "min_funding": -0.0005,
        "require_oi_increase": True
    }
    print("Koşul 2: Gelişmiş V3 Stratejisi (Funding & OI Filtreli) simüle ediliyor...")
    res_adv = evaluate_run(symbol_files, cfg_advanced)
    
    print("\n" + "=" * 80)
    print("📊 V3 STRATEJİSİ KARŞILAŞTIRMALI BACKTEST RAPORU (15 Dakikalık, 30 Gün)")
    print("=" * 80)
    print(f"{'Metrik':<30} | {'Standart V3':<20} | {'Filtreli Gelişmiş V3':<20}")
    print("-" * 80)
    print(f"{'Toplam Açılan Pozisyon':<30} | {res_std['total_trades']:<20} | {res_adv['total_trades']:<20}")
    print(f"{'Kazançla Kapanan (WIN)':<30} | {res_std['wins']:<20} | {res_adv['wins']:<20}")
    print(f"{'Zararla Kapanan (LOSS)':<30} | {res_std['losses']:<20} | {res_adv['losses']:<20}")
    print(f"{'Başa Baş Kapanan (BE)':<30} | {res_std['bes']:<20} | {res_adv['bes']:<20}")
    print(f"{'Zarar Edilmeyen Poz. Oranı':<30} | %{res_std['win_rate']:.2f} | %{res_adv['win_rate']:.2f}")
    print(f"{'Brüt Kâr/Zarar (R)':<30} | {res_std['gross_pnl']:+.2f} R | {res_adv['gross_pnl']:+.2f} R")
    print(f"{'Komisyon Gideri (R)':<30} | {res_std['fees']:.2f} R | {res_adv['fees']:.2f} R")
    print(f"{'NET Kâr/Zarar (R)':<30} | {res_std['net_pnl']:+.2f} R | {res_adv['net_pnl']:+.2f} R")
    print(f"{'Maksimum Düşüş (Max DD)':<30} | {res_std['max_dd']:.2f} R | {res_adv['max_dd']:.2f} R")
    print("=" * 80)
    
    # Interpretation
    pnl_diff = res_adv['net_pnl'] - res_std['net_pnl']
    trade_diff = res_std['total_trades'] - res_adv['total_trades']
    
    print("📝 ANALİZ YORUMU:")
    if pnl_diff > 0:
        print(f"  • Yeni filtreler net kârı {pnl_diff:+.2f} R artırdı! Pozisyon kalitesi yükseldi.")
    else:
        print(f"  • Yeni filtreler net kârı {pnl_diff:+.2f} R etkiledi. Kâr artışı sağlanamadı ancak risk analizi için detaylar incelenmelidir.")
        
    print(f"  • Filtreler sayesinde gereksiz/hatalı {trade_diff} işlem elendi (Komisyondan {trade_diff * 0.15:.2f} R tasarruf sağlandı).")
    print(f"  • Net Başarı Oranı %{res_std['win_rate']:.2f} seviyesinden %{res_adv['win_rate']:.2f} seviyesine değişti.")
    print("=" * 80)

if __name__ == "__main__":
    main()
