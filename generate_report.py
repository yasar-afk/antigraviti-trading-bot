# ============================================================
# generate_report.py — ANTIGRAVITI Rapor Üretici
#
# KULLANIM:
#   python generate_report.py
#   python generate_report.py --output logs/rapor.xlsx
#
# AÇIKLAMA:
#   logs/portfolio_state.json dosyasından mevcut portföy durumunu okuyarak
#   Excel formatında detaylı işlem analiz raporu üretir.
#   Açık pozisyonlar ve kapanan işlemler için AI post-mortem analizi dahildir.
# ============================================================

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.utils.generate_excel import create_analysis_excel
from src.utils.logger import get_logger

logger = get_logger("trading-bot.report")


def main():
    parser = argparse.ArgumentParser(
        description="ANTIGRAVITI — Excel İşlem Analiz Raporu Oluşturucu",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  python generate_report.py
  python generate_report.py --output logs/haftalik_rapor.xlsx
        """
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="logs/islem_analiz_raporu.xlsx",
        help="Excel dosyasının çıktı yolu (varsayılan: logs/islem_analiz_raporu.xlsx)"
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("[RAPOR] ANTIGRAVITI — Excel Raporu Olusturuluyor")
    logger.info("=" * 60)
    logger.info(f"Cikti dosyasi: {args.output}")

    try:
        create_analysis_excel(output_path=args.output)
        logger.info(f"[BASARILI] Rapor basariyla olusturuldu: {args.output}")
        print(f"\n[BASARILI] Rapor olusturuldu: {args.output}")
        print(f"   Excel'i acmak icin: start {args.output}")
    except Exception as e:
        logger.error(f"[HATA] Rapor olusturulurken hata: {e}", exc_info=True)
        print(f"\n[HATA] Hata: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
