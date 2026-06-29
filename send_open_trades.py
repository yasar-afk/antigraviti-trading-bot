# ============================================================
# send_open_trades.py — Send Open Positions Summary to Telegram
# ============================================================

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add project root to python path
sys.path.insert(0, str(Path(__file__).parent))

# Windows console encoding fix for emojis
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.config.settings import get_settings
from src.utils.telegram_notifier import send_telegram_notification

# Log directories and version labels
VERSIONS = [
    {
        "label": "V1 (Classic)",
        "log_dir": Path("logs_v1"),
        "state_file": "portfolio_state.json",
    },
    {
        "label": "V2 (Filtered)",
        "log_dir": Path("logs"),
        "state_file": "portfolio_state.json",
    },
    {
        "label": "V2.1 (Long/Short)",
        "log_dir": Path("logs_v21"),
        "state_file": "portfolio_state.json",
    },
    {
        "label": "V3 (Price Action)",
        "log_dir": Path("logs_v3"),
        "state_file": "portfolio_state.json",
    },
]

def load_portfolio_state(log_dir: Path, state_file: str) -> dict:
    path = log_dir / state_file
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def build_telegram_message() -> str:
    msg_lines = []
    msg_lines.append("📊 <b>Mevcut Açık İşlemler Durum Raporu</b>\n")
    
    total_active_positions = 0
    total_cost_all = 0.0
    total_pnl_all = 0.0
    
    any_version_found = False

    for ver in VERSIONS:
        state = load_portfolio_state(ver["log_dir"], ver["state_file"])
        if state is None:
            continue
        
        any_version_found = True
        positions = state.get("open_positions", {})
        
        active_positions = {k: v for k, v in positions.items() if v.get("status", "active") == "active"}
        pending_positions = {k: v for k, v in positions.items() if v.get("status") == "pending"}
        
        if active_positions or pending_positions:
            msg_lines.append(f"🤖 <b>{ver['label']}</b>")
            
            for sym, pos in active_positions.items():
                total_active_positions += 1
                side = pos.get("side", "LONG").upper()
                if isinstance(side, dict):
                    side = side.get("value", "LONG").upper()
                entry = pos.get("entry_price", 0.0)
                current = pos.get("current_price", entry)
                sl = pos.get("stop_loss", 0.0)
                tp = pos.get("take_profit", 0.0)
                cost = pos.get("cost_usdt", 0.0)
                amount = pos.get("amount", 0.0)
                
                # Calculate pnl
                if side == "LONG":
                    pnl_usdt = (current - entry) * amount
                else:
                    pnl_usdt = (entry - current) * amount
                pnl_pct = (pnl_usdt / cost * 100) if cost > 0 else 0.0
                
                total_cost_all += cost
                total_pnl_all += pnl_usdt
                
                pnl_emoji = "🟢" if pnl_usdt >= 0 else "🔴"
                side_emoji = "🟢" if side == "LONG" else "🔴"
                
                msg_lines.append(
                    f"• <b>{sym}</b> ({side_emoji} {side})\n"
                    f"  Giriş: ${entry:,.4f} | Güncel: ${current:,.4f}\n"
                    f"  SL: ${sl:,.4f} | TP: ${tp:,.4f}\n"
                    f"  Maliyet: ${cost:,.2f} USDT\n"
                    f"  PnL: {pnl_emoji} ${pnl_usdt:+.2f} ({pnl_pct:+.2f}%)\n"
                )
                
            for sym, pos in pending_positions.items():
                side = pos.get("side", "LONG").upper()
                if isinstance(side, dict):
                    side = side.get("value", "LONG").upper()
                entry = pos.get("entry_price", 0.0)
                cost = pos.get("cost_usdt", 0.0)
                msg_lines.append(
                    f"• <b>{sym}</b> (⏳ BEKLEYEN LİMİT {side})\n"
                    f"  Limit Fiyatı: ${entry:,.4f} | Maliyet: ${cost:,.2f} USDT\n"
                )
                
            msg_lines.append("")

    if not any_version_found:
        return "⚠️ Portföy durum dosyaları bulunamadı. Botların en az bir kere çalıştırıldığından emin olun."

    if total_active_positions == 0:
        msg_lines.append("<i>Şu anda aktif açık pozisyon bulunmuyor.</i>")
    else:
        msg_lines.append("--------------------------------------")
        msg_lines.append(f"<b>Toplam Açık Pozisyon Sayısı:</b> {total_active_positions} adet")
        msg_lines.append(f"<b>Toplam Pozisyon Maliyeti:</b> ${total_cost_all:,.2f} USDT")
        pnl_total_emoji = "🟢" if total_pnl_all >= 0 else "🔴"
        pnl_total_pct = (total_pnl_all / total_cost_all * 100) if total_cost_all > 0 else 0.0
        msg_lines.append(f"<b>Toplam Anlık PnL:</b> {pnl_total_emoji} ${total_pnl_all:+.2f} ({pnl_total_pct:+.2f}%)")

    return "\n".join(msg_lines)

def main():
    print("Mevcut açık işlemler analiz ediliyor...")
    message = build_telegram_message()
    print("Telegram mesajı hazırlanıyor:")
    print(message)
    
    # Send notification
    send_telegram_notification(message)
    print("Telegram bildirimi gönderildi.")

if __name__ == "__main__":
    main()
