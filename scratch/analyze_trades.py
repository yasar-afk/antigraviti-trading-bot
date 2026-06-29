# -*- coding: utf-8 -*-
import json
from pathlib import Path
from datetime import datetime

path = Path("logs_v21/portfolio_state.json")
if path.exists():
    with open(path, encoding="utf-8") as f:
        state = json.load(f)
    
    orders = state.get("orders", [])
    filled = [o for o in orders if o.get("status") == "filled"]
    # Sort by timestamp
    filled.sort(key=lambda x: x.get("timestamp", ""))
    
    # We want to pair buy and sell orders for the same symbol
    print("=== STRATEJI V2.1 DETAYLI ISLEM LISTESI ===")
    print(f"{'Tarih':<20} | {'Sembol':<10} | {'Yön':<6} | {'Fiyat':<10} | {'PnL ($)':<10} | {'PnL (%)':<8} | {'Sebep':<20}")
    print("-" * 95)
    for o in filled:
        ts = o.get("timestamp")
        sym = o.get("symbol")
        side = o.get("side").upper()
        price = o.get("price")
        pnl_u = o.get("pnl_usdt", 0)
        pnl_p = o.get("pnl_pct", 0) * 100
        reason = o.get("close_reason") or "ACILIS"
        
        # Format PnL
        pnl_u_str = f"${pnl_u:+.2f}" if pnl_u != 0 else "-"
        pnl_p_str = f"{pnl_p:+.2f}%" if pnl_p != 0 else "-"
        
        print(f"{ts[:19]:<20} | {sym:<10} | {side:<6} | {price:<10.4f} | {pnl_u_str:<10} | {pnl_p_str:<8} | {reason:<20}")
