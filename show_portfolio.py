# ============================================================
# show_portfolio.py — ANTIGRAVITI Portföy Görüntüleyici
#
# DEĞİŞİKLİK GEÇMİŞİ:
#   2026-06-04 | v2.0 | Binance anlık ticker fiyatı eklendi
#   2026-06-04 | v3.0 | SL/TP mesafe gösterimi, --watch modu,
#                        trailing stop bilgisi, ASCII bar grafik
# ============================================================

import os
import sys
import json
import time
import argparse
from datetime import datetime
from src.config.settings import get_settings

try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _fetch_live_prices(symbols: list) -> dict:
    """Binance'tan anlık ticker fiyatlarını çeker."""
    if not CCXT_AVAILABLE or not symbols:
        return {}

    try:
        params = {"enableRateLimit": True, "timeout": 10000, "options": {"defaultType": "spot"}}
        api_key    = os.environ.get("BINANCE_API_KEY", "")
        api_secret = os.environ.get("BINANCE_API_SECRET", "")
        if api_key and api_secret:
            params["apiKey"] = api_key
            params["secret"] = api_secret

        exchange = ccxt.binance(params)
        prices = {}
        try:
            tickers = exchange.fetch_tickers(symbols)
            for sym, ticker in tickers.items():
                p = ticker.get("last") or ticker.get("close")
                if p:
                    prices[sym] = float(p)
        except Exception:
            for sym in symbols:
                try:
                    ticker = exchange.fetch_ticker(sym)
                    p = ticker.get("last") or ticker.get("close")
                    if p:
                        prices[sym] = float(p)
                except Exception:
                    pass
        return prices
    except Exception:
        return {}


def _pnl_color(val: float) -> str:
    """ANSI renk kodu — pozitif yeşil, negatif kırmızı."""
    return "\033[92m" if val >= 0 else "\033[91m"


def _progress_bar(current: float, entry: float, stop: float, target: float, width: int = 18) -> str:
    """SL ─── Giriş ─── Fiyat ─── TP arasında pozisyonu gösteren ASCII bar."""
    if stop <= 0 or target <= 0 or stop >= target:
        return " " * width
    total_range = target - stop
    pos_in_range = current - stop
    ratio = max(0.0, min(1.0, pos_in_range / total_range))
    filled = int(ratio * width)
    bar = "[" + "#" * filled + "-" * (width - filled) + "]"
    return bar


def show_portfolio(watch: bool = False, interval: int = 30):
    """Portföy durumunu ekrana basar."""
    state_path = "logs/portfolio_state.json"

    if not os.path.exists(state_path):
        print("\n\033[91m[HATA] Portföy durum dosyasi (logs/portfolio_state.json) bulunamiyor.\033[0m")
        print("Botun en az bir kere calistirildiginden emin olun.\n")
        return

    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        print(f"\n\033[91m[HATA] Dosya okunurken hata: {e}\033[0m\n")
        return

    usdt_balance   = state.get("usdt_balance", 0.0)
    open_positions = state.get("open_positions", {})
    orders         = state.get("orders", [])
    last_updated   = state.get("last_updated", "")

    # Ekranı temizle (watch modunda)
    if watch:
        os.system("cls" if os.name == "nt" else "clear")

    print("\n" + "=" * 76)
    print("\033[1m\033[94m   ANTIGRAVITI TRADING BOT -- ANLIK CUZDAN & POZISYON RAPORU\033[0m")
    print("=" * 76)
    print(f" Rapor Saati   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if last_updated:
        try:
            lu = datetime.fromisoformat(last_updated)
            sn = int((datetime.utcnow() - lu).total_seconds())
            print(f" Son Guncelleme: {lu.strftime('%H:%M:%S')} UTC ({sn}sn once)")
        except Exception:
            pass
    print(f" Bostaki Nakit : \033[1m\033[93m${usdt_balance:,.2f} USDT\033[0m")
    print(f" Acik Pozisyon : \033[1m{len(open_positions)}\033[0m")
    print("=" * 76)

    if not open_positions:
        print("\n   \033[93mSu anda acikta aktif bir pozisyon bulunmuyor.\033[0m\n")
    else:
        # Anlık fiyatları çek
        print("\033[90m   Binance'tan anlik fiyatlar aliniyor...\033[0m", end="\r")
        live_prices  = _fetch_live_prices(list(open_positions.keys()))
        price_source = "\033[92m[CANLI]\033[0m" if live_prices else "\033[93m[KAYITLI]\033[0m"
        print(f"   Fiyat Kaynagi: {price_source}                    ")

        # Tablo başlığı
        print(f"\n{'Sembol':<11} {'Yon':<9} {'Giris':>9} {'Guncel':>9} {'SL':>9} {'TP':>9}   {'PnL'}")
        print("-" * 76)

        total_pnl  = 0.0
        total_cost = 0.0

        for sym, pos in open_positions.items():
            entry_price    = pos.get("entry_price", 0.0)
            amount         = pos.get("amount", 0.0)
            cost           = pos.get("cost_usdt", amount * entry_price)
            side           = pos.get("side", "LONG").upper()
            stop_loss      = pos.get("stop_loss", 0.0)
            take_profit    = pos.get("take_profit", 0.0)
            trailing_on    = pos.get("trailing_stop_active", False)
            status         = pos.get("status", "active")

            current_price = live_prices.get(sym, pos.get("current_price", entry_price))

            # Kaldıraç bilgisi
            cfg_leverage = getattr(get_settings().execution, "leverage", 1)
            is_futures = getattr(get_settings().exchange, "default_type", "spot") == "future"
            lev_str = f" {cfg_leverage}x" if is_futures else ""
            side_display = f"{side}{lev_str}"

            if status == "pending":
                print(
                    f"{sym:<11} {side_display:<9} "
                    f"${entry_price:>8,.4f} ${current_price:>8,.4f} "
                    f"\033[91m${stop_loss:>8,.4f}\033[0m "
                    f"\033[92m${take_profit:>8,.4f}\033[0m   "
                    f"\033[93m[BEKLEYEN LİMİT ALIM]\033[0m"
                )
                print(
                    f"{'':11} {'':9} "
                    f" Maliyet: ${cost:,.2f} | "
                    f"Limit Fiyat: ${entry_price:,.4f}"
                )
                total_cost += cost
                continue

            # PnL hesabı
            if side == "LONG":
                pnl_usdt = (current_price - entry_price) * amount
            else:
                pnl_usdt = (entry_price - current_price) * amount
            pnl_pct = (pnl_usdt / cost * 100) if cost > 0 else 0.0

            total_cost += cost
            total_pnl  += pnl_usdt

            # SL/TP mesafeleri
            sl_dist = f"{abs(current_price - stop_loss) / current_price * 100:.1f}%" if stop_loss > 0 and current_price > 0 else "  N/A"
            tp_dist = f"{abs(take_profit - current_price) / current_price * 100:.1f}%" if take_profit > 0 and current_price > 0 else "  N/A"

            pnl_c = _pnl_color(pnl_usdt)
            pnl_sign = "+" if pnl_usdt >= 0 else ""

            # Trailing stop etiketi
            trailing_tag = " (Trailing)" if trailing_on else ""

            print(
                f"{sym:<11} {side_display:<9} "
                f"${entry_price:>8,.4f} ${current_price:>8,.4f} "
                f"\033[91m${stop_loss:>8,.4f}\033[0m "
                f"\033[92m${take_profit:>8,.4f}\033[0m   "
                f"{pnl_c}{pnl_sign}${pnl_usdt:,.2f} ({pnl_sign}{pnl_pct:.2f}%){trailing_tag}\033[0m"
            )
            print(
                f"{'':11} {'':9} "
                f" Maliyet: ${cost:,.2f} | "
                f"SL mesafe: \033[91m{sl_dist}\033[0m | "
                f"TP mesafe: \033[92m{tp_dist}\033[0m"
            )

        print("-" * 76)

        pnl_c = _pnl_color(total_pnl)
        pnl_sign = "+" if total_pnl >= 0 else ""
        total_portfolio_value = usdt_balance + total_cost + total_pnl

        print(f" \033[1mToplam Pozisyon Maliyeti : ${total_cost:,.2f} USDT\033[0m")
        print(f" Toplam Anlik PnL          : {pnl_c}{pnl_sign}${total_pnl:,.2f} USDT ({pnl_sign}{total_pnl/total_cost*100:.2f}%)\033[0m" if total_cost > 0 else f" Toplam PnL: ${total_pnl:,.2f}")
        print(f" Toplam Portfoy Degeri     : \033[1m\033[96m${total_portfolio_value:,.2f} USDT\033[0m")

    # Son kapanan işlemler (close_reason'ı set edilmiş her filled emir)
    closed_orders_list = [o for o in orders if o.get("close_reason") is not None and o.get("status") == "filled"]
    if closed_orders_list:
        print("=" * 76)
        print("\033[1m\033[95m   SON KAPANAN ISLEMLER\033[0m")
        print("=" * 76)
        for order in reversed(closed_orders_list):
            time_str = order.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(time_str)
                t_fmt = dt.strftime("%m-%d %H:%M")
            except Exception:
                t_fmt = time_str[:16]

            pnl_o = order.get("pnl_usdt", 0.0)
            pnl_pct = order.get("pnl_pct", 0.0)
            reason = order.get("close_reason", "")
            pnl_c = _pnl_color(pnl_o)
            pnl_s = "+" if pnl_o >= 0 else ""
            reason_short = reason.replace(" TRIGGERED", "").replace("STRATEGY ", "") if reason else "KAPANDI"

            # Giriş fiyatını ve zamanını bul
            entry_price = None
            entry_time_str = ""
            try:
                # LONG kapandıysa (order side=sell) girişi buy'dır, SHORT kapandıysa (order side=buy) girişi sell'dir
                expected_entry_side = "buy" if order.get("side") == "sell" else "sell"
                order_idx = orders.index(order) if order in orders else len(orders)
                for prev_order in reversed(orders[:order_idx]):
                    if prev_order.get("symbol") == order["symbol"] and prev_order.get("side") == expected_entry_side and prev_order.get("status") == "filled":
                        entry_price = prev_order.get("price")
                        entry_time_str = prev_order.get("timestamp", "")
                        break
            except Exception:
                pass

            if entry_price is None or entry_price <= 0:
                entry_price = order["price"] / (1.0 + pnl_pct) if pnl_pct != -1.0 else order["price"]

            # Giriş zamanını formatla
            if entry_time_str:
                try:
                    dt_entry = datetime.fromisoformat(entry_time_str)
                    t_entry_fmt = dt_entry.strftime("%m-%d %H:%M")
                except Exception:
                    t_entry_fmt = entry_time_str[5:16].replace("T", " ")
            else:
                t_entry_fmt = "??-?? ??:??"

            print(
                f" [{t_entry_fmt} -> {t_fmt}] {order['symbol']:<10} | "
                f"Giris: ${entry_price:.4f} | "
                f"Cikis: ${order['price']:.4f} | "
                f"{pnl_c}{pnl_s}${pnl_o:.2f}\033[0m | "
                f"\033[90m{reason_short}\033[0m"
            )

    print("=" * 76)

    if watch:
        print(f"\n\033[90m[{interval}sn'de yenilenecek... Cıkmak için Ctrl+C]\033[0m")


def main():
    parser = argparse.ArgumentParser(description="ANTIGRAVITI Portfoy Goruntuleyici")
    parser.add_argument(
        "--watch", "-w",
        action="store_true",
        help="Otomatik yenileme modu (varsayilan: 30 saniye)"
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=30,
        help="Watch modunda yenileme suresi (saniye, varsayilan: 30)"
    )
    args = parser.parse_args()

    if args.watch:
        print("\033[92m[WATCH MODU] Baslatiliyor... Cıkmak icin Ctrl+C\033[0m")
        try:
            while True:
                show_portfolio(watch=True, interval=args.interval)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n\033[93mWatch modu durduruldu.\033[0m")
    else:
        show_portfolio(watch=False)


if __name__ == "__main__":
    main()
