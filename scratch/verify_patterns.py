# ============================================================
# scratch/test_patterns.py — ANTIGRAVITI Trading Bot
#
# AMAÇ:
#   Canlı Binance verilerini çekerek Mum ve Grafik Formasyonları
#   tespit algoritmalarını canlı veri üzerinde doğrular.
# ============================================================

import sys
import os

# Windows konsolu için UTF-8 rekonfigürasyonu
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# src klasörünü PYTHONPATH'a ekle
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data.collector import DataCollector
from src.technical.engine import TechnicalEngine
from src.utils.logger import get_logger

logger = get_logger("test_patterns_manual")

def test_symbol_patterns(collector, engine, symbol, timeframe):
    print(f"\n{symbol} çiftinin {timeframe} zaman dilimi için mum verileri çekiliyor...")
    # Formasyonlar için son 150-200 mum yeterlidir, limiti 300 yapıyoruz
    fetch_result = collector.fetch(symbol, timeframe, limit=300)
    
    if not fetch_result.success or fetch_result.data is None:
        print(f"Hata: Veri çekilemedi! {fetch_result.error_message}")
        return

    df = collector.to_dataframe(fetch_result.data)
    indicator_set = engine.get_latest_indicators(df, symbol, timeframe)

    if not indicator_set or not indicator_set.patterns:
        print("Hata: Formasyon analizleri yapılamadı!")
        return

    patterns = indicator_set.patterns
    price = indicator_set.current_price

    print(f"Mevcut Fiyat: ${price:,.4f}")
    print(f"Aktif Formasyonlar: {', '.join(patterns.active_patterns) if patterns.active_patterns else 'Yok'}")
    
    print("Detaylı Durum:")
    print(f"  - Çekiç (Hammer)            : {'Evet' if patterns.hammer else 'Hayır'}")
    print(f"  - Kayan Yıldız (Shooting Star): {'Evet' if patterns.shooting_star else 'Hayır'}")
    print(f"  - Yutan Boğa (Engulfing)    : {'Evet' if patterns.bullish_engulfing else 'Hayır'}")
    print(f"  - Yutan Ayı (Engulfing)     : {'Evet' if patterns.bearish_engulfing else 'Hayır'}")
    print(f"  - İkili Dip (Double Bottom) : {'Evet' if patterns.double_bottom else 'Hayır'}")
    print(f"  - İkili Tepe (Double Top)   : {'Evet' if patterns.double_top else 'Hayır'}")
    print("--------------------------------------------------")

def main():
    print("==================================================")
    print("         FORMASYON TESPİT DOĞRULAMA SCRIPT'İ      ")
    print("==================================================")

    # 1. Collector ve Engine'i başlat
    collector = DataCollector(is_paper_trade=True)
    engine = TechnicalEngine()

    print("Binance bağlantısı kuruluyor...")
    connected = collector.connect()
    if not connected:
        print("Hata: Binance bağlantısı kurulamadı!")
        return

    # Farklı semboller ve zaman dilimlerini test edelim
    test_symbol_patterns(collector, engine, "BTC/USDT", "1h")
    test_symbol_patterns(collector, engine, "ETH/USDT", "15m")
    test_symbol_patterns(collector, engine, "SOL/USDT", "4h")
    print("==================================================")

if __name__ == "__main__":
    main()
