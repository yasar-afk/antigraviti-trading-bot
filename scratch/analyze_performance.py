# -*- coding: utf-8 -*-
import json
from pathlib import Path
from datetime import datetime

logs_v1_dir = Path("logs_v1")
logs_v21_dir = Path("logs_v21")

def load_portfolio(log_dir):
    path = log_dir / "portfolio_state.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def load_signals(log_dir):
    path = log_dir / "signals.jsonl"
    signals = []
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        signals.append(json.loads(line))
                    except Exception:
                        pass
    return signals

p1 = load_portfolio(logs_v1_dir)
p21 = load_portfolio(logs_v21_dir)

print("=== STRATEJI V1 PORTOFOLYO OZET ===")
if p1:
    print(f"Bakiye: ${p1.get('usdt_balance', 0):,.2f}")
    open_pos = p1.get('open_positions', {})
    print(f"Acik Pozisyonlar ({len(open_pos)}):")
    for sym, pos in open_pos.items():
        print(f"  - {sym}: {pos.get('side')} Giriş: ${pos.get('entry_price')} PnL: ${pos.get('pnl_usdt'):+.2f} ({pos.get('pnl_pct')*100:+.2f}%)")
    orders = p1.get('orders', [])
    closed = [o for o in orders if o.get('close_reason')]
    print(f"Kapali Islemler ({len(closed)}):")
    for o in closed:
        print(f"  - {o.get('symbol')}: {o.get('side')} Giriş: ${o.get('price')} PnL: ${o.get('pnl_usdt'):+.2f} ({o.get('pnl_pct')*100:+.2f}%) Nedeni: {o.get('close_reason')}")
else:
    print("V1 portfolio bulunamadi")

print("\n=== STRATEJI V2.1 PORTOFOLYO OZET ===")
if p21:
    print(f"Bakiye: ${p21.get('usdt_balance', 0):,.2f}")
    open_pos = p21.get('open_positions', {})
    print(f"Acik Pozisyonlar ({len(open_pos)}):")
    for sym, pos in open_pos.items():
        print(f"  - {sym}: {pos.get('side')} Giriş: ${pos.get('entry_price')} PnL: ${pos.get('pnl_usdt'):+.2f} ({pos.get('pnl_pct')*100:+.2f}%)")
    orders = p21.get('orders', [])
    closed = [o for o in orders if o.get('close_reason')]
    print(f"Kapali Islemler ({len(closed)}):")
    for o in closed:
        print(f"  - {o.get('symbol')}: {o.get('side')} Giriş: ${o.get('price')} PnL: ${o.get('pnl_usdt'):+.2f} ({o.get('pnl_pct')*100:+.2f}%) Nedeni: {o.get('close_reason')}")
else:
    print("V2.1 portfolio bulunamadi")
