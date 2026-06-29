# ============================================================
# scratch/test_fibonacci.py — ANTIGRAVITI Trading Bot
#
# AMAÇ:
#   Canlı Binance verilerini çekerek Fibonacci hesaplama motorunu
#   ve swing high/low bulma mantığını canlı veriyle doğrular.
# ============================================================

import sys
import os

# src klasörünü PYTHONPATH'a ekle
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data.collector import DataCollector
from src.technical.engine import TechnicalEngine
from src.utils.logger import get_logger

logger = get_logger("test_fibonacci_manual")

def main():
    print("==================================================")
    print("         FIBONACCI HESAPLAMA DOĞRULAMA SCRIPT'İ    ")
    print("==================================================")

    # 1. Collector ve Engine'i başlat
    collector = DataCollector(is_paper_trade=True)
    engine = TechnicalEngine()

    print("Binance bağlantısı kuruluyor...")
    connected = collector.connect()
    if not connected:
        print("Hata: Binance bağlantısı kurulamadı!")
        return

    symbol = "BTC/USDT"
    timeframe = "1h"

    print(f"{symbol} çiftinin {timeframe} zaman diliminden mum verileri çekiliyor...")
    # Fibonacci için son 500 mum gerektiğinden limiti 600 çekiyoruz
    fetch_result = collector.fetch(symbol, timeframe, limit=600)
    
    if not fetch_result.success or fetch_result.data is None:
        print(f"Hata: Veri çekilemedi! {fetch_result.error_message}")
        return

    print(f"Başarılı! Çekilen mum sayısı: {len(fetch_result.data.candles)}")

    # 2. DataFrame'e dönüştür ve indikatörleri hesapla
    df = collector.to_dataframe(fetch_result.data)
    
    print("\nTeknik indikatörler ve Fibonacci seviyeleri hesaplanıyor...")
    indicator_set = engine.get_latest_indicators(df, symbol, timeframe)

    if not indicator_set or not indicator_set.fib:
        print("Hata: Fibonacci seviyeleri hesaplanamadı!")
        return

    # 3. Sonuçları yazdır
    fib = indicator_set.fib
    price = indicator_set.current_price

    print("\nHESAPLANAN FIBONACCI DETAYLARI (500 Mum Lookback):")
    print(f"--------------------------------------------------")
    print(f"Mevcut Fiyat:             ${price:,.2f}")
    print(f"Swing High (Maks Tepe):   ${fib.swing_high:,.2f}")
    print(f"Swing Low (Min Dip):      ${fib.swing_low:,.2f}")
    print(f"Fark (High - Low):        ${(fib.swing_high - fib.swing_low):,.2f}")
    print(f"--------------------------------------------------")
    print(f"%%23.6 Seviyesi:          ${fib.fib_236:,.2f}")
    print(f"%%38.2 Seviyesi:          ${fib.fib_382:,.2f}")
    print(f"%%50.0 Seviyesi:          ${fib.fib_500:,.2f}")
    print(f"%%61.8 Seviyesi (GP):     ${fib.fib_618:,.2f}")
    print(f"%%78.6 Seviyesi:          ${fib.fib_786:,.2f}")
    print(f"--------------------------------------------------")

    # Fiyatın en yakın seviyeye uzaklığı
    levels = {
        "0.236": fib.fib_236,
        "0.382": fib.fib_382,
        "0.500": fib.fib_500,
        "0.618 (Golden Pocket)": fib.fib_618,
        "0.786": fib.fib_786,
        "1.000 (Swing High)": fib.swing_high,
        "0.000 (Swing Low)": fib.swing_low
    }
    
    closest_lvl = min(levels.keys(), key=lambda k: abs(price - levels[k]))
    closest_val = levels[closest_lvl]
    dist_pct = abs(price - closest_val) / closest_val * 100
    
    print(f"En Yakın Fibonacci Seviyesi: %{closest_lvl} (${closest_val:,.2f})")
    print(f"Uzaklık Yüzdesi:             %{dist_pct:.2f}")
    print("==================================================")

if __name__ == "__main__":
    main()
