# ============================================================
# watch.py -- ANTIGRAVITI Multi-Version Watch Dashboard
#
# AMAC:
#   V2.1, V3 ve V4 botlarinin portfolyo durumunu ayni anda
#   tek ekranda gosterir. 1 dakikada bir otomatik yenilenir.
#
# KULLANIM:
#   python watch.py               # Dashboard baslat
#   python watch.py --refresh 30  # 30 saniyede bir yenile
#   python watch.py --once        # Bir kez goster ve cik
# ============================================================

# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Colorama -- renkli terminal ciktisi (Windows uyumlu)
try:
    import colorama
    from colorama import Fore, Back, Style
    colorama.init(autoreset=True, strip=False)
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False
    class Fore:
        RED = GREEN = YELLOW = CYAN = MAGENTA = BLUE = WHITE = RESET = ""
    class Back:
        RED = GREEN = BLUE = BLACK = WHITE = RESET = ""
    class Style:
        BRIGHT = DIM = RESET_ALL = NORMAL = ""

# Windows stdout encoding fix
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        h_stdout = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(h_stdout, ctypes.byref(mode)):
            kernel32.SetConsoleMode(h_stdout, mode.value | 0x0004)
    except Exception:
        pass

# Custom print wrapper to clear each line (flicker-free rendering without trailing artifacts)
_orig_print = print
def print(*args, **kwargs):
    file = kwargs.get('file', sys.stdout)
    if file == sys.stdout or file is None:
        sep_char = kwargs.get('sep', ' ')
        content = sep_char.join(str(arg) for arg in args)
        content = content.replace('\n', '\033[K\n')
        end = kwargs.get('end', '\n')
        if end == '\n':
            end = '\033[K\n'
        elif end == '\r':
            end = '\033[K\r'
        _orig_print(content, end=end, file=sys.stdout, flush=kwargs.get('flush', False))
    else:
        _orig_print(*args, **kwargs)

PROJECT_ROOT = Path(__file__).parent

# --- Her versiyon icin log dizini ve portfolyo dosyasi ---
VERSIONS = [
    {
        "label":          "V2.1 (Long + SHORT)",
        "short":          "V2.1",
        "log_dir":        PROJECT_ROOT / "logs_v21",
        "state_file":     "portfolio_state.json",
        "journal_prefix": "signals_",
        "color":          Fore.MAGENTA,
        "marker":         "[V2.1]",
    },
    {
        "label":          "V3   (Price Action - SMC)",
        "short":          "V3",
        "log_dir":        PROJECT_ROOT / "logs_v3",
        "state_file":     "portfolio_state.json",
        "journal_prefix": "signals_",
        "color":          Fore.YELLOW,
        "marker":         "[V3]",
    },
    {
        "label":          "V4   (Price Action - SMC Optimized)",
        "short":          "V4",
        "log_dir":        PROJECT_ROOT / "logs_v4",
        "state_file":     "portfolio_state.json",
        "journal_prefix": "signals_",
        "color":          Fore.CYAN,
        "marker":         "[V4]",
    },
    {
        "label":          "V5   (Price Action - SMC Refined)",
        "short":          "V5",
        "log_dir":        PROJECT_ROOT / "logs_v5",
        "state_file":     "portfolio_state.json",
        "journal_prefix": "signals_",
        "color":          Fore.GREEN,
        "marker":         "[V5]",
    },
]


# --- Yardimci Fonksiyonlar ---

def clear_screen() -> None:
    # Ekranı silmek yerine imleci en başa (sol üst köşeye) taşıyoruz.
    # Böylece ekran hiç silinmez/kararmaz (no flicker) ve eski veriler silinmeden yenileri üstüne yazılır.
    sys.stdout.write("\033[H")
    sys.stdout.flush()


def load_portfolio_state(log_dir: Path, state_file: str) -> Optional[Dict]:
    path = log_dir / state_file
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_recent_signals(log_dir: Path, journal_prefix: str, max_signals: int = 5) -> List[Dict]:
    """Son N sinyali journal'dan yukler."""
    try:
        journal_files = sorted(
            [f for f in log_dir.glob(f"{journal_prefix}*.jsonl")],
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        if not journal_files:
            return []

        latest_file = journal_files[0]
        lines = []
        with open(latest_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except Exception:
                        pass

        actionable = [s for s in lines if s.get("signal_type") in ("BUY", "SELL")]
        if actionable:
            return actionable[-max_signals:]
        return lines[-max_signals:]
    except Exception:
        return []


def load_trade_history(log_dir: Path, state_file: str, max_trades: int = 15) -> List[Dict]:
    """
    portfolio_state.json'dan islem gecmisini yukler.
    Hem acilis (close_reason=None, filled) hem kapanis emirlerini dondurur.
    En yeni en uste gelecek sekilde siralar.
    """
    path = log_dir / state_file
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        return []

    orders = state.get("orders", [])
    # Sadece FILLED emirleri al (basarisiz ve iptal edilenleri gizle)
    filled = [o for o in orders if o.get("status") == "filled"]

    # Tarih sirasina gore sirala (en yeni en uste)
    try:
        filled = sorted(filled, key=lambda o: o.get("timestamp", ""), reverse=True)
    except Exception:
        pass

    return filled[:max_trades]




def pnl_raw_str(pnl: float, pct: float = 0.0) -> str:
    """PnL'i renksiz string olarak formatlar."""
    sign = "+" if pnl >= 0 else ""
    pct_part = f" ({sign}{pct*100:.2f}%)" if pct != 0 else ""
    return f"{sign}${pnl:,.2f}{pct_part}"


def pnl_str(pnl: float, pct: float = 0.0) -> str:
    """PnL'i renkli string olarak formatlar."""
    color = Fore.GREEN if pnl >= 0 else Fore.RED
    return f"{color}{pnl_raw_str(pnl, pct)}{Style.RESET_ALL}"


def time_ago(iso_str: Optional[str]) -> str:
    if not iso_str:
        return "-"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        secs = int((now - dt).total_seconds())
        if secs < 60:
            return f"{secs}sn once"
        elif secs < 3600:
            return f"{secs//60}dk once"
        elif secs < 86400:
            return f"{secs//3600}sa once"
        else:
            return f"{secs//86400}g once"
    except Exception:
        return "-"


def sep(ch: str = "=", width: int = 80) -> str:
    return ch * width


def render_version_panel(ver: dict, width: int = 80) -> None:
    """Tek bir versiyon icin panel cizer."""
    color = ver["color"]
    marker = ver["marker"]
    label = ver["label"]
    log_dir = ver["log_dir"]

    print(f"{color}{Style.BRIGHT}{sep('=', width)}")
    print(f"  {marker} {label.upper()}")
    print(f"{sep('=', width)}{Style.RESET_ALL}")

    state = load_portfolio_state(log_dir, ver["state_file"])

    if state is None:
        print(f"  {Fore.YELLOW}UYARI: Portfolyo verisi bulunamadi. Bot calisiyor mu?{Style.RESET_ALL}")
        print(f"         Beklenen dosya: {log_dir / ver['state_file']}\n")
        return

    balance   = state.get("usdt_balance", 0.0)
    positions = state.get("open_positions", {})
    orders    = state.get("orders", [])
    last_upd  = state.get("last_updated")

    total_pnl  = sum(p.get("pnl_usdt", 0.0) for p in positions.values())
    total_cost = sum(p.get("cost_usdt", 0.0) for p in positions.values())
    total_val  = balance + total_cost + total_pnl

    upd_time = time_ago(last_upd)
    print(f"  Durum          : {Fore.GREEN}{Style.BRIGHT}AKTIF (Piyasa Taraniyor){Style.RESET_ALL}   |   Son guncelleme : {upd_time}")
    print(f"  USDT Bakiye    : {Style.BRIGHT}${balance:,.2f}{Style.RESET_ALL}{' ' * (20 - len(f'${balance:,.2f}'))} |   Portfolyo Deger: {Style.BRIGHT}${total_val:,.2f}{Style.RESET_ALL}")
    
    pnl_val_str = pnl_raw_str(total_pnl)
    pnl_colored = pnl_str(total_pnl)
    pnl_padded = f"{pnl_colored}{' ' * (20 - len(pnl_val_str))}"
    
    print(f"  Anlik PnL      : {pnl_padded} |   Acik Pozisyon  : {Style.BRIGHT}{len(positions)} adet{Style.RESET_ALL}")
    
    closed = [o for o in orders if o.get("close_reason")]
    if closed:
        wins     = [o for o in closed if o.get("pnl_usdt", 0) >= 0]
        losses   = [o for o in closed if o.get("pnl_usdt", 0) < 0]
        real_pnl = sum(o.get("pnl_usdt", 0) for o in closed)
        real_pnl_str = f"${real_pnl:,.2f}"
        win_loss_str = f"{len(closed)} (Kar: {len(wins)} / Zarar: {len(losses)})"
        
        real_pnl_val_str = pnl_raw_str(real_pnl)
        real_pnl_colored = pnl_str(real_pnl)
        real_pnl_padded = f"{real_pnl_colored}{' ' * (20 - len(real_pnl_val_str))}"
        
        print(f"  Kapali Islem   : {win_loss_str}{' ' * (20 - len(win_loss_str))} |   Realize PnL    : {real_pnl_padded}")
    
    if positions:
        print(f"  {Fore.WHITE}{Style.BRIGHT}{sep('-', width - 4)}")
        print(f"  {'Sembol':<10} {'Yon':<6} {'Giris':>11} {'Guncel':>11} {'SL':>11} {'TP':>11}   PnL")
        print(f"  {sep('-', width - 4)}{Style.RESET_ALL}")
        for sym, pos in positions.items():
            side = pos.get("side", "?")
            if isinstance(side, dict): side = side.get("value", "?")
            side_up = str(side).upper()
            s_color = Fore.GREEN if "LONG" in side_up or side_up == "BUY" else Fore.RED
            entry = pos.get("entry_price", 0.0)
            current = pos.get("current_price", entry)
            sl_price  = pos.get("stop_loss", 0.0)
            tp_price  = pos.get("take_profit", 0.0)
            pnl_u = pos.get("pnl_usdt", 0.0)
            pnl_p = pos.get("pnl_pct", 0.0)
            pos_status = pos.get("status", "active")
            
            sl_warn = ""
            if current > 0 and sl_price > 0:
                dist = abs(current - sl_price) / current * 100
                if dist < 3.0:
                    sl_warn = f" {Fore.RED}!! SL YAKINI ({dist:.1f}%){Style.RESET_ALL}"
            
            pnl_colored = pnl_str(pnl_u, pnl_p)
            
            entry_str = f"${entry:,.4f}"
            current_str = f"${current:,.4f}"
            sl_str = f"${sl_price:,.4f}" if sl_price > 0 else "-"
            tp_str = f"${tp_price:,.4f}" if tp_price > 0 else "-"
            
            status_tag = f" {Fore.YELLOW}[BEKLIYOR]{Style.RESET_ALL}" if pos_status == "pending" else ""
            
            print(f"  {Fore.WHITE}{sym:<10}{Style.RESET_ALL} {s_color}{side_up:<6}{Style.RESET_ALL} {entry_str:>11} {current_str:>11} {sl_str:>11} {tp_str:>11}   {pnl_colored}{sl_warn}{status_tag}")
        print(f"  {Fore.WHITE}{sep('-', width - 4)}{Style.RESET_ALL}")
    else:
        print(f"    {Fore.WHITE}(Acik pozisyon yok){Style.RESET_ALL}")

    # ── SON İŞLEM GEÇMİŞİ ──────────────────────────────────────────────────────
    trade_history = load_trade_history(log_dir, ver["state_file"], max_trades=10)
    print()
    print(f"  {color}{Style.BRIGHT}  SON ISLEM GECMISI (Son 10 Islem){Style.RESET_ALL}")
    print(f"  {Fore.WHITE}{Style.BRIGHT}{sep('-', width - 4)}")
    if trade_history:
        # Baslik satiri
        print(
            f"  {'Tarih':<16} {'Sembol':<10} {'Yon':<5} {'Giris':>11} "
            f"{'Cikis/Anlik':>11} {'PnL $':>10} {'PnL %':>7}  Sebep"
        )
        print(f"  {sep('-', width - 4)}{Style.RESET_ALL}")
        for o in trade_history:
            o_side = o.get("side", "?").upper()
            o_sym  = o.get("symbol", "?")
            o_price = o.get("price", 0.0)
            o_pnl_u = o.get("pnl_usdt", 0.0)
            o_pnl_p = o.get("pnl_pct", 0.0)
            o_reason = o.get("close_reason") or "ACILIS"
            o_ts = o.get("timestamp", "")
            
            # Kisa tarih formatla
            try:
                dt = datetime.fromisoformat(o_ts.replace("Z", "+00:00"))
                date_str = dt.strftime("%m-%d %H:%M")
            except Exception:
                date_str = str(o_ts)[:16]
            
            # Kapanis emrinde cikis fiyati, acilis emrinde giriş fiyati goster
            is_close = bool(o.get("close_reason"))
            exit_str  = f"${o_price:,.4f}" if is_close else f"${o_price:,.4f}"
            
            # PnL rengi (sadece kapanis emirleri icin gosterilir)
            if is_close:
                pnl_u_str = pnl_raw_str(o_pnl_u, o_pnl_p)
                pnl_colored_o = pnl_str(o_pnl_u, o_pnl_p)
            else:
                pnl_u_str = "-"
                pnl_colored_o = f"{Fore.WHITE}-{Style.RESET_ALL}"
                o_pnl_p = 0.0

            # Yon rengi: BUY=yesil, SELL=kirmizi
            if o_side == "BUY":
                side_color = Fore.GREEN
            else:
                side_color = Fore.RED

            # Sebep kisalt
            short_reason = o_reason[:22] if o_reason else "-"

            pnl_pct_str = f"{o_pnl_p*100:+.2f}%" if is_close else "  -"

            print(
                f"  {Fore.WHITE}{date_str:<16}{Style.RESET_ALL} "
                f"{o_sym:<10} "
                f"{side_color}{o_side:<5}{Style.RESET_ALL} "
                f"${o_price:>10,.4f} "
                f"{exit_str:>11} "
                f"{pnl_colored_o} "
                f"{Fore.WHITE}{pnl_pct_str:>7}{Style.RESET_ALL}  "
                f"{Style.DIM}{short_reason}{Style.RESET_ALL}"
            )
        print(f"  {Fore.WHITE}{sep('-', width - 4)}{Style.RESET_ALL}")
    else:
        print(f"  {Style.DIM}(Henuz hicbir islem gerceklesmedi){Style.RESET_ALL}")
        print(f"  {Fore.WHITE}{sep('-', width - 4)}{Style.RESET_ALL}")
    print()


def render_dashboard(refresh_sec: int, filter_version: Optional[str] = None) -> None:
    """Tam dashboard'u render eder."""
    try:
        term_width = min(os.get_terminal_size(0).columns, 120)
    except (OSError, AttributeError):
        try:
            term_width = min(os.get_terminal_size().columns, 120)
        except (OSError, AttributeError):
            term_width = 100

    panel_width = max(80, term_width - 4)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n{Style.BRIGHT}{Fore.WHITE}{sep('=', panel_width)}")
    title = "ANTIGRAVITI -- MULTI-VERSION WATCH DASHBOARD"
    print(f"  {title.center(panel_width - 4)}")
    print(f"  Saat: {now_str}  |  Yenileme: {refresh_sec}sn  |  Cikis: Ctrl+C")
    print(f"{sep('=', panel_width)}{Style.RESET_ALL}\n")

    for ver in VERSIONS:
        if filter_version and ver["short"].lower() != filter_version.lower():
            continue
        render_version_panel(ver, width=panel_width)

    print(f"{Style.DIM}{Fore.WHITE}{sep('-', panel_width)}")
    print(f"  Sonraki yenileme: {refresh_sec} saniye sonra")
    print(f"{sep('-', panel_width)}{Style.RESET_ALL}")
    # Ekranın geri kalanını temizle (eğer eski çizimden kalan karakterler varsa)
    sys.stdout.write("\033[J")
    sys.stdout.flush()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ANTIGRAVITI Watch Dashboard")
    parser.add_argument("--refresh", type=int, default=60,
                        help="Yenileme araligi (saniye, varsayilan: 60)")
    parser.add_argument("--once", action="store_true",
                        help="Tek seferlik goster ve cik")
    parser.add_argument("--version", type=str, default=None, choices=["v2.1", "v3", "v4", "v5"],
                        help="Sadece belirli bir versiyonu izlemek icin (v2.1, v3, v4, v5)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    refresh_sec = max(10, args.refresh)

    if args.once:
        render_dashboard(refresh_sec, args.version)
        return

    # Başlangıçta ekranı ve geçmişi bir kez temizleyelim
    if os.name == "nt" and sys.stdout.isatty():
        os.system("cls")
    else:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()

    try:
        while True:
            try:
                clear_screen()
                render_dashboard(refresh_sec, args.version)
            except Exception as e:
                print(f"\n{Fore.RED}Gosterim hatasi: {e}{Style.RESET_ALL}")
            time.sleep(refresh_sec)
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Dashboard kapatildi.{Style.RESET_ALL}")
        sys.exit(0)


if __name__ == "__main__":
    main()
