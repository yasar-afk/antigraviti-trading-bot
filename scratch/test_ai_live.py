import os
import sys

# Windows konsolu için UTF-8 rekonfigürasyonu
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# src dizinini ekle
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config.settings import get_settings
from src.utils.ai_analyzer import verify_signal_with_ai

def main():
    print("==================================================")
    print("      YAPAY ZEKA (OPENROUTER) CANLI BAĞLANTI TESTİ")
    print("==================================================")
    
    settings = get_settings()
    print(f"Konfigüre Edilen Model: {settings.openrouter_model}")
    print(f"API Anahtarı Yüklendi mi?: {'EVET' if settings.openrouter_api_key else 'HAYIR'}")
    print(f"AI Doğrulama Aktif mi?: {'EVET' if settings.use_ai_signal_verification else 'HAYIR'}")
    print("--------------------------------------------------")
    
    if not settings.openrouter_api_key:
        print("Hata: .env dosyasında OPENROUTER_API_KEY tanımlanmamış!")
        return

    # Örnek test verisi
    symbol = "BTC/USDT"
    signal_type = "BUY"
    entry_price = 65000.0
    stop_loss = 64000.0
    take_profit = 68000.0
    
    indicator_summary = {
        "rsi": 32.5,
        "macd_hist": 0.004,
        "ema_alignment": "partial_bull",
        "fib_high": 70000.0,
        "fib_low": 60000.0,
        "fib_618": 63820.0
    }
    
    reasons = [
        "RSI aşırı satım bölgesine yakın",
        "MACD histogramında bullish cross sinyali",
        "Fiyat 61.8 Fibonacci desteğine çok yakın ($63,820)"
    ]

    print("Yapay Zekaya sinyal gönderiliyor ve canlı yanıt bekleniyor...")
    print("Lütfen bekleyin (10 saniye kadar sürebilir)...")
    
    try:
        approved, reason = verify_signal_with_ai(
            symbol=symbol,
            signal_type=signal_type,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            indicator_summary=indicator_summary,
            reasons=reasons
        )
        
        print("\n---------------- TEST SONUCU ----------------")
        decision = "ONAYLANDI" if approved else "REDDEDİLDİ"
        print(f"AI Kararı:      {decision}")
        print(f"AI Gerekçesi:   {reason}")
        print("---------------------------------------------")
        print("Başarılı! Yapay zeka entegrasyonu tamamen aktif ve çalışıyor.")
    except Exception as e:
        print(f"\nHata oluştu: {e}")

if __name__ == "__main__":
    main()
