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

from src.config.settings import get_settings
from src.technical.engine import TechnicalEngine
from src.signal.generator import SignalGenerator
from src.signal.models import SignalType
from src.technical.indicators import IndicatorSet

DATA_DIR = PROJECT_ROOT / "data" / "historical" / "1h"

def run_simulation(df, symbol, tech_engine, signal_gen):
    """Simulates trading using V2.1 entry scoring and ATR/Fibonacci stop-loss/take-profit."""
    # Pre-compute all technical indicator columns once (vectorized)
    df_signals = tech_engine.enrich_dataframe(df)
    
    trades = []
    active_trade = None
    
    # We need at least 200 bars for EMA 200 calculation to be fully stable
    start_idx = 200
    if len(df_signals) <= start_idx:
        return []
        
    for i in range(start_idx, len(df_signals)):
        k_close = df_signals["close"].iloc[i]
        k_low = df_signals["low"].iloc[i]
        k_high = df_signals["high"].iloc[i]
        k_dt = df_signals.index[i]
        
        # 1. If trade is active, check exit conditions (SL / TP)
        if active_trade is not None:
            side = active_trade["side"]
            sl_price = active_trade["sl_price"]
            tp_price = active_trade["final_tp"]
            rr_val = active_trade["rr"]
            
            if side == "BUY":  # LONG
                # Check SL
                if k_low <= sl_price:
                    active_trade["outcome"] = "LOSS"
                    active_trade["exit_price"] = sl_price
                    active_trade["exit_datetime"] = k_dt
                    active_trade["pnl_r"] = -1.0
                    trades.append(active_trade)
                    active_trade = None
                # Check TP
                elif k_high >= tp_price:
                    active_trade["outcome"] = "WIN"
                    active_trade["exit_price"] = tp_price
                    active_trade["exit_datetime"] = k_dt
                    # V2.1 targets the actual calculated risk reward ratio
                    active_trade["pnl_r"] = rr_val
                    trades.append(active_trade)
                    active_trade = None
            else:  # SHORT
                # Check SL
                if k_high >= sl_price:
                    active_trade["outcome"] = "LOSS"
                    active_trade["exit_price"] = sl_price
                    active_trade["exit_datetime"] = k_dt
                    active_trade["pnl_r"] = -1.0
                    trades.append(active_trade)
                    active_trade = None
                # Check TP
                elif k_low <= tp_price:
                    active_trade["outcome"] = "WIN"
                    active_trade["exit_price"] = tp_price
                    active_trade["exit_datetime"] = k_dt
                    active_trade["pnl_r"] = rr_val
                    trades.append(active_trade)
                    active_trade = None
        
        # 2. Check for entry signal if no position is active
        # Slices up to current index (inclusive) to prevent look-ahead bias
        if active_trade is None:
            slice_df = df_signals.iloc[:i+1]
            
            # Extract and interpret last bar indicators using engine private methods
            current_price = float(k_close)
            timestamp = int(slice_df["timestamp"].iloc[-1]) if "timestamp" in slice_df.columns else 0
            
            rsi_result      = tech_engine._interpret_rsi(slice_df)
            macd_result     = tech_engine._interpret_macd(slice_df)
            ema_result      = tech_engine._interpret_ema(slice_df, current_price)
            atr_result      = tech_engine._interpret_atr(slice_df, current_price)
            bb_result       = tech_engine._interpret_bollinger(slice_df, current_price)
            volume_result   = tech_engine._interpret_volume(slice_df)
            adx_result      = tech_engine._interpret_adx(slice_df)
            fib_result      = tech_engine._interpret_fibonacci(slice_df)
            patterns_result = tech_engine._detect_patterns(slice_df)
            
            ind_set = IndicatorSet(
                symbol=symbol,
                timeframe="1h",
                timestamp=timestamp,
                current_price=current_price,
                rsi=rsi_result,
                macd=macd_result,
                ema=ema_result,
                atr=atr_result,
                bollinger=bb_result,
                volume=volume_result,
                adx=adx_result,
                fib=fib_result,
                patterns=patterns_result,
            )
            ind_set.calculate_weighted_score()
            
            # Evaluate using signal generator rules
            signal = signal_gen.evaluate(ind_set, btc_trend_bearish=False)
            
            if signal.signal_type in (SignalType.BUY, SignalType.SELL):
                active_trade = {
                    "side": "BUY" if signal.signal_type == SignalType.BUY else "SELL",
                    "entry_price": current_price,
                    "sl_price": signal.stop_loss,
                    "final_tp": signal.take_profit,
                    "rr": signal.risk_reward_ratio if signal.risk_reward_ratio > 0 else 2.0,
                    "entry_datetime": k_dt,
                    "outcome": "OPEN",
                    "pnl_r": 0.0
                }
                
    # Append the last active trade if it was left open
    if active_trade is not None:
        active_trade["pnl_r"] = 0.0
        trades.append(active_trade)
        
    return trades

def main():
    import logging
    logging.disable(logging.CRITICAL)
    
    parser = argparse.ArgumentParser(description="V2.1 Long+Short Strategy Backtester")
    parser.add_argument("--symbols", type=str, default=None, help="virgülle ayrılmış özel semboller (varsayılan: hepsi)")
    parser.add_argument("--adx", type=float, default=18.0, help="ADX filtresi eşik değeri")
    parser.add_argument("--volume", type=float, default=0.7, help="Minimum volume ratio eşiği")
    args = parser.parse_args()
    
    # Load settings from config_v21.yaml to align parameters
    cfg = get_settings("config_v21.yaml")
    
    tech_engine = TechnicalEngine(
        atr_multiplier=cfg.risk.atr_stop_multiplier,
        rr_ratio=cfg.risk.min_risk_reward_ratio,
        adx_period=cfg.technical.adx_period,
        adx_threshold=args.adx,
    )
    
    signal_gen = SignalGenerator(
        entry_threshold=cfg.strategy.entry_threshold,
        exit_threshold=cfg.strategy.exit_threshold,
        min_rr_ratio=cfg.risk.min_risk_reward_ratio,
        min_volume_ratio=args.volume,
        adx_threshold=args.adx,
        is_paper_trade=True,
    )
    # Force strategy version to v2.1 (long + short)
    signal_gen._strategy_version = "v2.1"
    
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
        
    print(f"Toplam {len(symbol_files)} sembol dosyası yüklendi. V2.1 Backtest başlıyor...")
    print("-" * 70)
    
    all_trades = []
    symbol_stats = {}
    
    for file_path in symbol_files:
        symbol_name = file_path.name.replace("_USDT_USDT_1h.csv", "/USDT").replace("_1h.csv", "").replace("_", "/")
        try:
            df = pd.read_csv(file_path)
            if len(df) < 220:
                continue
                
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
            
            trades = run_simulation(df, symbol_name, tech_engine, signal_gen)
            if trades:
                all_trades.extend([(symbol_name, t) for t in trades])
                
                # Calculate symbol metrics
                sym_wins = sum(1 for t in trades if t["outcome"] == "WIN")
                sym_losses = sum(1 for t in trades if t["outcome"] == "LOSS")
                sym_opens = sum(1 for t in trades if t["outcome"] == "OPEN")
                sym_pnl = sum(t["pnl_r"] for t in trades)
                
                symbol_stats[symbol_name] = {
                    "trades": len(trades),
                    "wins": sym_wins,
                    "losses": sym_losses,
                    "bes": 0,
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
    opens = sum(1 for _, t in all_trades if t["outcome"] == "OPEN")
    
    completed_trades = wins + losses
    win_rate = wins / completed_trades * 100 if completed_trades > 0 else 0.0
    
    gross_pnl = sum(t["pnl_r"] for _, t in all_trades)
    # Commission per trade (0.15 R per entry)
    total_fees = total_trades * 0.15
    net_pnl = gross_pnl - total_fees
    
    # Drawdown calculation in R-units
    cumulative_pnl = []
    current_pnl = 0.0
    sorted_trades = sorted(all_trades, key=lambda x: x[1]["entry_datetime"] if x[1]["entry_datetime"] is not None else "")
    
    for _, t in sorted_trades:
        current_pnl += t["pnl_r"] - 0.15 # subtract fee
        cumulative_pnl.append(current_pnl)
        
    cum_series = pd.Series(cumulative_pnl)
    peaks = cum_series.cummax()
    drawdowns = peaks - cum_series
    max_dd = drawdowns.max() if not drawdowns.empty else 0.0
    
    print("\n" + "=" * 80)
    print("📈 ANTIGRAVITI V2.1 STRATEJİSİ (LONG + SHORT) BACKTEST RAPORU")
    print("=" * 80)
    print(f"Toplam Test Edilen Coin   : {len(symbol_stats)}")
    print(f"Toplam Açılan Pozisyon    : {total_trades} adet")
    print(f"  - Kazançla Kapananlar   : {wins} adet (Take Profit)")
    print(f"  - Zararla Kapananlar    : {losses} adet (Stop Loss)")
    print(f"  - Açık Kalanlar         : {opens} adet")
    print("-" * 80)
    print(f"Tamamlanan İşlem Sayısı   : {completed_trades}")
    print(f"Başarı Oranı (Win Rate)   : %{win_rate:.2f}")
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
        print(f"  • {sym:<10} | {stat['trades']:<3} işlem | Net PnL: {stat['pnl']:+.2f} R (Başarı %: {stat['wins']/max(1, stat['wins']+stat['losses'])*100:.1f}%)")
        
    print("\n💀 EN ÇOK KAYBETTİREN 5 COIN:")
    for sym, stat in sorted_symbols[-5:]:
        print(f"  • {sym:<10} | {stat['trades']:<3} işlem | Net PnL: {stat['pnl']:+.2f} R (Başarı %: {stat['wins']/max(1, stat['wins']+stat['losses'])*100:.1f}%)")
        
    print("=" * 80)
    print("Açıklama: 1 R = Yatırılan Risk Birimi (Örn: Hesapta %1 risk alınıyorsa 1 R = %1 kâr)")
    print("V2.1 stratejisinde işlemler hedeflenen Fibonacci/ATR risk ödül oranına göre kapanır.")

if __name__ == "__main__":
    main()
