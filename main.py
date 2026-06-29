# ============================================================
# main.py — ANTIGRAVITI Trading Bot
#
# AMAÇ:
#   Trading Botunun ana giriş noktası (CLI).
#   Varsayılan olarak BotEngine'i periyodik döngü modunda çalıştırır.
#   --test-collector parametresi ile sadece veri toplama testi yapar.
#   --single-run parametresi ile botu tek seferlik tarama modunda çalıştırır.
#
# ÇALIŞTIRMA:
#   python main.py                           # Varsayılan: Döngü modu (Paper)
#   python main.py --single-run              # Tek seferlik analiz yap ve çık
#   python main.py --symbol ETH/USDT --mode live # Canlı modda ETH/USDT
#   python main.py --test-collector          # Sadece veri çekme testi yap
# ============================================================

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Proje kökünü Python yoluna ekle
sys.path.insert(0, str(Path(__file__).parent))

from src.config.settings import get_settings
from src.data.collector import DataCollector
from src.bot.engine import BotEngine
from src.utils.logger import get_logger

logger = get_logger("antigraviti.main")


def parse_args() -> argparse.Namespace:
    """Komut satırı argümanlarını işler."""
    parser = argparse.ArgumentParser(
        description="ANTIGRAVITI Algoritmik Ticaret Motoru",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  python main.py
  python main.py --single-run
  python main.py --symbol ETH/USDT --mode paper
  python main.py --test-collector --symbol BTC/USDT --tf 1d --save-csv
        """,
    )
    # Bot Arama Modları
    parser.add_argument(
        "--test-collector",
        action="store_true",
        help="Sadece DataCollector modülünü test et (sinyal üretmez)",
    )
    parser.add_argument(
        "--single-run",
        action="store_true",
        help="Botu tek bir analiz döngüsü için çalıştırır ve kapatır",
    )

    # Parametre Eziciler (Overrides)
    parser.add_argument(
        "--top-50",
        action="store_true",
        help="Binance'taki en yüksek 24 saatlik hacme sahip 50 USDT çiftini dinamik olarak tarar",
    )
    parser.add_argument(
        "--top-100",
        action="store_true",
        help="Binance'taki en yüksek 24 saatlik hacme sahip 100 USDT çiftini dinamik olarak tarar",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        help="Binance'taki en yüksek 24 saatlik hacme sahip belirtilen sayıda USDT çiftini dinamik olarak tarar",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Birden fazla sembolü virgülle ayırarak taramak için (ör. BTC/USDT,ETH/USDT,SOL/USDT)",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="İşlem çifti (ör. BTC/USDT, ETH/USDT). Varsayılan: config.yaml'dan",
    )
    parser.add_argument(
        "--tf",
        type=str,
        default=None,
        help="Timeframe (ör. 4h, 1d). Birden fazla TF için virgülle ayırın (ör. 4h,1d)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Alınacak mum sayısı. Varsayılan: config.yaml'dan",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["paper", "live"],
        default=None,
        help="Çalışma modu: 'paper' (kağıt işlem) veya 'live' (canlı). Varsayılan: config.yaml'dan",
    )
    parser.add_argument(
        "--save-csv",
        action="store_true",
        help="Sadece --test-collector ile kullanılır: Çekilen veriyi CSV olarak kaydeder",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Kullanılacak konfigürasyon dosyası (varsayılan: config.yaml)",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        choices=["v1", "v2", "v2.1"],
        default=None,
        help="Strateji versiyonunu override et (v1, v2, v2.1)",
    )
    return parser.parse_args()


def run_data_collection_test(
    symbol: str,
    timeframes: list[str],
    limit: int | None,
    save_csv: bool,
) -> None:
    """Eski DataCollector test modunu çalıştırır."""
    logger.info("=" * 60)
    logger.info("🤖 ANTIGRAVITI — DataCollector Test Başlıyor")
    logger.info("=" * 60)
    logger.info(f"Sembol   : {symbol}")
    logger.info(f"Timeframe: {timeframes}")
    logger.info(f"Limit    : {limit}")
    logger.info("=" * 60)

    # Collector'ı başlat
    collector = DataCollector(is_paper_trade=True)

    # Bağlan
    logger.info("Binance'a bağlanılıyor...")
    if not collector.connect():
        logger.error("❌ Bağlantı başarısız. Program sonlandırılıyor.")
        sys.exit(1)

    # Sembol geçerliliğini kontrol et
    if not collector.validate_symbol(symbol):
        logger.error(f"❌ '{symbol}' Binance'ta bulunamadı.")
        collector.disconnect()
        sys.exit(1)

    # Piyasa bilgisi al
    market_info = collector.get_market_info(symbol)
    if market_info:
        logger.info(
            f"📊 Piyasa Bilgisi: {market_info.symbol} | "
            f"Base: {market_info.base} | Quote: {market_info.quote} | "
            f"Durum: {market_info.status.value}"
        )

    # Çoklu timeframe veri çekimi
    results = collector.fetch_multi_timeframe(
        symbol=symbol,
        timeframes=timeframes,
        limit=limit,
    )

    # Sonuçları raporla
    logger.info("\n" + "=" * 60)
    logger.info("📈 VERİ ÖZET RAPORU")
    logger.info("=" * 60)

    for tf, result in results.items():
        if result.success and result.data:
            df = collector.to_dataframe(result.data)
            latest = result.data.latest_candle
            oldest = result.data.oldest_candle

            logger.info(f"\n── {tf} ──────────────────────────────────")
            logger.info(f"  Toplam Mum  : {result.candle_count}")
            logger.info(f"  API Süresi  : {result.fetch_duration_ms:.0f}ms")
            logger.info(
                f"  Tarih Aralığı: "
                f"{oldest.candle_datetime.strftime('%Y-%m-%d') if oldest.candle_datetime else 'N/A'}"
                f" → "
                f"{latest.candle_datetime.strftime('%Y-%m-%d') if latest.candle_datetime else 'N/A'}"
            )
            logger.info(f"  Son Kapanış : ${latest.close:,.2f}")
            logger.info(f"  Son Hacim   : {latest.volume:,.2f}")
            logger.info(
                f"  Son Mum     : {'🟢 Yükseliş' if latest.is_bullish else '🔴 Düşüş'}"
            )

            if save_csv:
                csv_path = Path(f"data_{symbol.replace('/', '_')}_{tf}.csv")
                df.to_csv(csv_path)
                logger.info(f"  💾 Kaydedildi: {csv_path}")

        else:
            logger.error(f"\n── {tf}: ❌ BAŞARISIZ — {result.error_message}")

    # Önbellek istatistikleri
    cache_stats = collector.get_cache_stats()
    logger.info(f"\n🗄️  Önbellek: {cache_stats['active_entries']} aktif giriş")

    # Bağlantıyı kapat
    collector.disconnect()
    logger.info("\n✅ DataCollector testi tamamlandı.")


def main() -> None:
    """Ana giriş noktası."""
    args = parse_args()

    # Config dosyasını yükle
    config_file = getattr(args, 'config', 'config.yaml')
    import yaml as _yaml
    from src.config.settings import _build_settings_from_yaml as _build
    if config_file != 'config.yaml':
        try:
            with open(config_file, encoding='utf-8') as _f:
                _yaml_data = _yaml.safe_load(_f) or {}
            cfg = _build(_yaml_data)
        except Exception as _e:
            logger.error(f"❌ Config dosyası yüklenemedi ({config_file}): {_e}. Varsayılan kullanılıyor.")
            cfg = get_settings()
    else:
        cfg = get_settings()

    # 1. Konfigürasyon Ezicileri Uygula
    if args.symbol:
        cfg.exchange.symbol = args.symbol
        logger.info(f"⚙️ CLI Override: Sembol -> {args.symbol}")

    if args.tf:
        # Virgülle ayrılmış çoklu timeframeleri listeye çevir
        tfs = [t.strip() for t in args.tf.split(",")]
        cfg.data.timeframes = tfs
        logger.info(f"⚙️ CLI Override: Timeframes -> {tfs}")

    if args.limit:
        cfg.data.limit = args.limit
        logger.info(f"⚙️ CLI Override: Limit -> {args.limit}")

    if args.mode:
        cfg.trading_mode = args.mode
        logger.info(f"⚙️ CLI Override: Trading Mode -> {args.mode}")

    if args.strategy:
        cfg.strategy.version = args.strategy
        logger.info(f"⚙️ CLI Override: Strateji Versiyonu -> {args.strategy}")

    # 2. Çalışma Moduna Karar Ver
    if args.test_collector:
        # Eski veri çekme testi
        timeframes = cfg.data.timeframes
        limit = cfg.data.limit
        run_data_collection_test(
            symbol=cfg.exchange.symbol,
            timeframes=timeframes,
            limit=limit,
            save_csv=args.save_csv,
        )
    else:
        # Canlı/Paper Trading Bot Döngüsü
        # Canlı moda geçiş yaparken API key doğrulaması ve sandbox kontrolü
        if cfg.trading_mode == "live":
            logger.warning("⚠️  CANLI trading modu seçildi!")
            if not cfg.has_api_credentials:
                logger.error("❌ HATA: Canlı modda çalışmak için BINANCE_API_KEY ve BINANCE_API_SECRET gereklidir.")
                logger.error(".env dosyasını doldurun veya '--mode paper' parametresi kullanın.")
                sys.exit(1)
            
            # Canlı modda sandbox'ı kapatma uyarısı
            if cfg.exchange.sandbox:
                logger.warning("🔬 UYARI: Canlı mod seçildi ancak sandbox (testnet) aktif. Gerçek emir gönderilmez.")

        # Çoklu sembol listesi çözümleme
        symbols_list = [s.strip() for s in args.symbols.split(",")] if args.symbols else None

        # Bot motorunu başlat
        bot = BotEngine(settings=cfg)
        bot.run(
            single_run=args.single_run,
            symbols=symbols_list,
            top_50=args.top_50,
            top_100=args.top_100,
            top_n=args.top,
        )


if __name__ == "__main__":
    main()
