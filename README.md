# 🚀 Trading Bot

Otonom kripto trading botu - Binance Futures üzerinde otomatik alım-satım yapan Python tabanlı sistem.

[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Binance](https://img.shields.io/badge/Binance-F0B90B?style=for-the-badge&logo=binance&logoColor=black)](https://www.binance.com/)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

## ✨ Özellikler

| Modül | Açıklama | Durum |
|-------|----------|-------|
| 📊 **V5 Strategy** | RSI + Bollinger Bands stratejisi | ✅ |
| 📈 **V7 Strategy** | Price Action + SMC stratejisi | ✅ |
| 🤖 **AI Verification** | MiMo v2.5 ile grafik doğrulama | ✅ |
| 🧠 **Adaptive Learning** | Otomatik parametre optimizasyonu | ✅ |
| 🎯 **Risk Management** | Drawdown, trailing stop, pozisyon yönetimi | ✅ |
| 📱 **Telegram Bot** | Bildirimler ve komutlar | ✅ |
| 📊 **Backtest** | Geçmiş verilerle strateji testi | ✅ |

## 🎯 Hızlı Başlangıç

### Kurulum

```bash
# 1. Depoyu klonla
git clone https://github.com/yasar-afk/trading-bot.git
cd trading-bot

# 2. Sanal ortam oluştur
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# 3. Bağımlılıkları yükle
pip install -r requirements.txt

# 4. Konfigürasyon
cp .env.example .env
# .env dosyasını düzenle
```

### .env Dosyası

```env
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### Çalıştırma

```bash
# V5 + V7 paralel çalıştır
python run_all_bots.py

# Sadece V7
python live_v7.py

# Paper trading (varsayılan)
python live_v7.py --paper

# Canlı borsa
python live_v7.py --live
```

## 📊 Stratejiler

### V5 - RSI + Bollinger Bands
- RSI aşırı alım/satım tespiti
- Bollinger Bands kırılma sinyalleri
- EMA trend filtresi

### V7 - Price Action + SMC
- 100 mum swing high/low tarama
- EMA(180) trend filtresi
- ATR bazlı Stop-Loss (0.6x ATR)
- Dinamik Risk/Reward (ADX bazlı)
- Multi-timeframe konfirmasyon (15m + 1h + 4h)

## 🤖 AI Entegrasyonu (MiMo v2.5)

```
Mum grafiği oluştur → İndikatörleri hesapla → MiMo'ya gönder
                                                ↓
                                    TRADE / SKIP / HOLD / CLOSE
```

- **Giriş doğrulama**: Grafik + indikatör analizi
- **Pozisyon inceleme**: Saatlik HOLD/CLOSE kontrolü
- **Hata yönetimi**: FAIL-CLOSE (AI hata verince sinyal reddedilir)

## 🛡️ Risk Yönetimi

| Parametre | Değer |
|-----------|-------|
| Max pozisyon | 10 |
| Pozisyon başına risk | %2 |
| Günlük max drawdown | %5 |
| Kaldıraç | 5x izole |
| Komisyon | %0.063 |
| Cooldown | Stop-loss sonrası 24 saat |

## 📱 Telegram Komutları

```
/durum    - Bot durumu
/status   - Açık pozisyonlar
/portfoy  - Portföy özeti
/pozisyon - Detaylı pozisyon bilgisi
/acik     - Açık pozisyon listesi
```

## 📁 Proje Yapısı

```
trading-bot/
├── main.py                 # Ana bot (V5)
├── main_v5.py              # V5 varyantı
├── main_v7.py              # V7 varyantı
├── run_all.py              # Tümünü paralel çalıştır
├── config.yaml             # Ana konfigürasyon
├── config_v5.yaml          # V5 ayarları
├── config_v7.yaml          # V7 ayarları
├── requirements.txt        # Bağımlılıklar
├── setup.py                # pip kurulum
├── .env.example            # Örnek konfigürasyon
│
├── src/                    # Kaynak kodları
│   ├── strategy/           # Strateji modülleri
│   ├── risk/               # Risk yönetimi
│   ├── data/               # Veri çekme
│   └── utils/              # Yardımcı fonksiyonlar
│
├── data/                   # Fiyat verileri (CSV)
├── logs/                   # İşlem logları
└── tests/                  # Test dosyaları
```

## 🔧 Konfigürasyon

```yaml
# config_v7.yaml
strategy:
  sweep_window: 100        # Swing high/low tarama penceresi
  trend_ema: 180           # Trend EMA periyodu
  atr_multiplier: 0.6      # SL hesaplama çarpanı

risk:
  max_position_pct: 0.02   # Pozisyon başına risk
  max_daily_drawdown_pct: 0.05  # Günlük max drawdown

execution:
  leverage: 5
  margin_mode: ISOLATED
```

## 🧪 Backtest

```bash
# V7 backtest
python backtest_v7.py

# Kapsamlı analiz
python analyze_v7_comprehensive.py
```

## 📊 Performans

| Metrik | Değer |
|--------|-------|
| Başlangıç | $10,000 |
| Güncel | $16,323 |
| Kâr | %+63.2 |
| Durum | Aktif (Paper Trading) |

## 🛠️ Teknoloji Stack

| Kategori | Teknoloji |
|----------|-----------|
| **Dil** | Python 3.9+ |
| **Borsa** | Binance Futures (ccxt) |
| **AI** | MiMo v2.5 (Xiaomi) |
| **Bildirim** | Telegram Bot |
| **Veri** | Pandas, NumPy |
| **Grafik** | Matplotlib |

## ⚠️ Uyarı

Bu bot yatırım tavsiyesi değildir. Kripto para birimleri yüksek risk taşır. Paper trading ile test edin.

## 📝 Lisans

MIT License - Detaylı bilgi için [LICENSE](LICENSE) dosyasına bakın.

---

**Trading Bot** — MiMoCode tarafından geliştirildi 🚀
