# ============================================================
# src/technical/indicators.py — ANTIGRAVITI Trading Bot
#
# AMAÇ:
#   Her teknik indikatörün hesaplama sonucunu taşıyan veri nesneleri
#   ve sinyal yorumlama mantığı bu dosyada tanımlanır.
#   TechnicalEngine bu sınıfları üretir; SignalGenerator tüketir.
#
# MİMARİ NOT:
#   Her indikatör için iki şey burada birleşir:
#     1. Ham sayısal değer (ör. RSI = 68.4)
#     2. Yorumlama (ör. RSIZone.OVERBOUGHT, signal_strength = 0.85)
#   Bu ayrım sayesinde SignalGenerator sadece yorumları okur,
#   tekrar hesaplama yapmaz. "Hesaplama" ve "Karar" katmanları ayrı.
#
# DEĞİŞİKLİK GEÇMİŞİ:
#   2026-06-04 | v1.0 | İlk indikatör veri modelleri
# ============================================================

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


# ─── Sinyal Enum'ları ─────────────────────────────────────────

class SignalDirection(str, Enum):
    """Bir indikatörün ürettiği yön sinyali."""
    STRONG_BUY  = "strong_buy"    # Güçlü alış
    BUY         = "buy"           # Alış
    NEUTRAL     = "neutral"       # Tarafsız
    SELL        = "sell"          # Satış
    STRONG_SELL = "strong_sell"   # Güçlü satış

    @property
    def score(self) -> float:
        """Sinyali 0.0–1.0 arası puana çevirir (ALIŞ = 1.0, SATIŞ = 0.0)."""
        mapping = {
            "strong_buy":  1.00,
            "buy":         0.75,
            "neutral":     0.50,
            "sell":        0.25,
            "strong_sell": 0.00,
        }
        return mapping[self.value]


class RSIZone(str, Enum):
    """RSI değerinin bulunduğu bölge."""
    OVERSOLD        = "oversold"        # < 30 → Aşırı satım (potansiyel alış)
    NEAR_OVERSOLD   = "near_oversold"   # 30–40
    NEUTRAL         = "neutral"         # 40–60
    NEAR_OVERBOUGHT = "near_overbought" # 60–70
    OVERBOUGHT      = "overbought"      # > 70 → Aşırı alım (potansiyel satış)


class MACDCrossType(str, Enum):
    """MACD kesişim türü."""
    BULLISH_CROSS = "bullish_cross"   # MACD sinyal çizgisini yukarı kesti
    BEARISH_CROSS = "bearish_cross"   # MACD sinyal çizgisini aşağı kesti
    NO_CROSS      = "no_cross"        # Kesişim yok


class BBPosition(str, Enum):
    """Fiyatın Bollinger Bantlarına göre konumu."""
    ABOVE_UPPER = "above_upper"   # Üst bandın üstünde → Aşırılık
    NEAR_UPPER  = "near_upper"    # Üst banda yakın
    MIDDLE      = "middle"        # Orta bölgede
    NEAR_LOWER  = "near_lower"    # Alt banda yakın
    BELOW_LOWER = "below_lower"   # Alt bandın altında → Aşırılık


class EMAAlignment(str, Enum):
    """EMA 20/50/200 hizalaması."""
    FULL_BULLISH  = "full_bullish"   # EMA20 > EMA50 > EMA200 → Tam boğa
    PARTIAL_BULL  = "partial_bull"   # Kısmi boğa hizalaması
    NEUTRAL       = "neutral"        # Karışık sıralama
    PARTIAL_BEAR  = "partial_bear"   # Kısmi ayı hizalaması
    FULL_BEARISH  = "full_bearish"   # EMA20 < EMA50 < EMA200 → Tam ayı


# ─── İndikatör Sonuç Nesneleri ────────────────────────────────

@dataclass
class RSIResult:
    """RSI hesaplama sonucu ve yorumu.

    Attributes:
        value: Mevcut RSI değeri (0–100).
        zone: RSI'nın bulunduğu bölge.
        signal: Üretilen sinyal yönü.
        signal_strength: Bu sinyalin gücü (0.0–1.0).
        is_bullish_divergence: Fiyat yeni dip yaparken RSI yapmıyor mu?
        is_bearish_divergence: Fiyat yeni zirve yaparken RSI yapmıyor mu?
        divergence_note: Uyumsuzluk açıklaması.
    """
    value: float
    zone: RSIZone
    signal: SignalDirection
    signal_strength: float               # 0.0 – 1.0
    is_bullish_divergence: bool = False
    is_bearish_divergence: bool = False
    divergence_note: str = ""

    @property
    def has_divergence(self) -> bool:
        """Herhangi bir divergence var mı?"""
        return self.is_bullish_divergence or self.is_bearish_divergence

    @property
    def effective_weight(self) -> float:
        """feature_weights.py ile entegre efektif ağırlık.

        Divergence varsa conditional_weight (0.85) döner,
        yoksa normal ağırlık (0.70) döner.
        """
        from src.strategy.feature_weights import get_effective_weight
        return get_effective_weight("rsi", condition_met=self.has_divergence)


@dataclass
class MACDResult:
    """MACD hesaplama sonucu ve yorumu.

    Attributes:
        macd_line: MACD çizgisi değeri.
        signal_line: Sinyal çizgisi değeri.
        histogram: Histogram değeri (macd - signal).
        cross_type: Son kesişim türü.
        signal: Üretilen sinyal yönü.
        signal_strength: Bu sinyalin gücü (0.0–1.0).
        histogram_trend: Histogram artıyor mu? (True = momentum kazanıyor)
    """
    macd_line: float
    signal_line: float
    histogram: float
    cross_type: MACDCrossType
    signal: SignalDirection
    signal_strength: float
    histogram_trend: bool = False        # True = histogram büyüyor (momentum güçleniyor)

    @property
    def is_bullish(self) -> bool:
        """MACD sinyali yükselişçi mi?"""
        return self.macd_line > self.signal_line

    @property
    def effective_weight(self) -> float:
        from src.strategy.feature_weights import get_effective_weight
        return get_effective_weight("macd")


@dataclass
class EMAResult:
    """EMA 20/50/200 hesaplama sonucu ve yorumu.

    Attributes:
        ema20: 20 periyotluk EMA değeri.
        ema50: 50 periyotluk EMA değeri.
        ema200: 200 periyotluk EMA değeri.
        current_price: Anlık fiyat.
        alignment: EMA hizalaması (boğa/ayı dizilimi).
        signal: Üretilen sinyal yönü.
        signal_strength: Bu sinyalin gücü (0.0–1.0).
        golden_cross: EMA50 son dönemde EMA200'ü yukarı kesti mi?
        death_cross: EMA50 son dönemde EMA200'ü aşağı kesti mi?
    """
    ema20: float
    ema50: float
    ema200: float
    current_price: float
    alignment: EMAAlignment
    signal: SignalDirection
    signal_strength: float
    golden_cross: bool = False
    death_cross: bool = False

    @property
    def price_vs_ema200(self) -> str:
        """Fiyatın EMA200'e göre konumu."""
        if self.current_price > self.ema200:
            pct = (self.current_price - self.ema200) / self.ema200 * 100
            return f"EMA200 üstünde (+{pct:.1f}%)"
        else:
            pct = (self.ema200 - self.current_price) / self.ema200 * 100
            return f"EMA200 altında (-{pct:.1f}%)"

    @property
    def effective_weight(self) -> float:
        from src.strategy.feature_weights import get_effective_weight
        return get_effective_weight("ema")


@dataclass
class ATRResult:
    """ATR (Average True Range) hesaplama sonucu.

    ATR sinyal üretmez; stop-loss ve pozisyon boyutlandırma için kullanılır.

    Attributes:
        value: Mevcut ATR değeri (fiyat cinsinden).
        current_price: Anlık fiyat.
        atr_pct: ATR'nin fiyata oranı (%) — normalize volatilite.
        stop_loss_long: Long pozisyon için ATR tabanlı stop seviyesi.
        stop_loss_short: Short pozisyon için ATR tabanlı stop seviyesi.
        take_profit_long: Long için minimum hedef (Risk/Ödül = 2.0).
        take_profit_short: Short için minimum hedef.
        volatility_label: Volatilite seviyesi etiketi.
    """
    value: float
    current_price: float
    atr_pct: float                       # ATR / Fiyat * 100
    stop_loss_long: float
    stop_loss_short: float
    take_profit_long: float
    take_profit_short: float
    volatility_label: str = ""           # "Düşük" / "Normal" / "Yüksek"

    @property
    def effective_weight(self) -> float:
        from src.strategy.feature_weights import get_effective_weight
        return get_effective_weight("atr")


@dataclass
class BollingerResult:
    """Bollinger Bantları hesaplama sonucu ve yorumu.

    Attributes:
        upper: Üst bant değeri.
        middle: Orta bant (SMA20) değeri.
        lower: Alt bant değeri.
        current_price: Anlık fiyat.
        bandwidth: Bant genişliği = (Üst - Alt) / Orta.
        percent_b: %B göstergesi = (Fiyat - Alt) / (Üst - Alt).
        position: Fiyatın bantlara göre konumu.
        is_squeeze: Bantlar daralıyor mu? (sert hareket uyarısı)
        signal: Üretilen sinyal yönü.
        signal_strength: Bu sinyalin gücü (0.0–1.0).
    """
    upper: float
    middle: float
    lower: float
    current_price: float
    bandwidth: float
    percent_b: float
    position: BBPosition
    is_squeeze: bool
    signal: SignalDirection
    signal_strength: float

    @property
    def effective_weight(self) -> float:
        from src.strategy.feature_weights import get_effective_weight
        return get_effective_weight("bollinger_bands")


@dataclass
class ADXResult:
    """ADX hesaplama sonucu ve yorumu."""
    value: float
    di_plus: float
    di_minus: float
    signal: SignalDirection
    signal_strength: float

    @property
    def effective_weight(self) -> float:
        from src.strategy.feature_weights import get_effective_weight
        return get_effective_weight("adx", condition_met=(self.value > 40))


@dataclass
class VolumeResult:
    """Hacim analizi sonucu.

    Attributes:
        current_volume: Mevcut bar hacmi.
        avg_volume: 20 periyot ortalama hacim.
        volume_ratio: current / avg (1.5 üstü = güçlü onay).
        is_above_average: Ortalama üstünde mi?
        signal: Üretilen sinyal yönü.
        signal_strength: Bu sinyalin gücü (0.0–1.0).
    """
    current_volume: float
    avg_volume: float
    volume_ratio: float
    is_above_average: bool
    signal: SignalDirection
    signal_strength: float

    @property
    def effective_weight(self) -> float:
        from src.strategy.feature_weights import get_effective_weight
        return get_effective_weight("volume")


@dataclass
class FibonacciResult:
    """Fibonacci Düzeltme Seviyeleri (Retracement) sonucu.

    Attributes:
        swing_high: Son 500 mumun en yüksek tepe fiyatı.
        swing_low: Son 500 mumun en düşük dip fiyatı.
        fib_236: %23.6 geri çekilme seviyesi.
        fib_382: %38.2 geri çekilme seviyesi.
        fib_500: %50.0 geri çekilme seviyesi.
        fib_618: %61.8 geri çekilme seviyesi.
        fib_786: %78.6 geri çekilme seviyesi.
    """
    swing_high: float
    swing_low: float
    fib_236: float
    fib_382: float
    fib_500: float
    fib_618: float
    fib_786: float

    @property
    def effective_weight(self) -> float:
        # Fibonacci weighted score'a doğrudan katılmayacak, destek/direnç olarak kullanılacaktır.
        return 0.0


@dataclass
class PatternResult:
    """Tespit edilen mum ve grafik formasyonlarının sonucu.

    Attributes:
        hammer: Çekiç mum formasyonu var mı?
        shooting_star: Kayan yıldız mum formasyonu var mı?
        bullish_engulfing: Yutan boğa mum formasyonu var mı?
        bearish_engulfing: Yutan ayı mum formasyonu var mı?
        double_bottom: İkili dip grafik formasyonu onaylandı mı?
        double_top: İkili tepe grafik formasyonu onaylandı mı?
        active_patterns: Aktif olan formasyonların Türkçe açıklamaları listesi.
    """
    hammer: bool = False
    shooting_star: bool = False
    bullish_engulfing: bool = False
    bearish_engulfing: bool = False
    double_bottom: bool = False
    double_top: bool = False
    active_patterns: List[str] = field(default_factory=list)

    @property
    def effective_weight(self) -> float:
        # Formasyonlar doğrudan ağırlıklı skora katılmaz, güven skoru ve AI için kullanılır.
        return 0.0


# ─── Bütünleşik İndikatör Seti ────────────────────────────────

@dataclass
class IndicatorSet:
    """Tek bir bar için tüm indikatörlerin toplu sonucu.

    TechnicalEngine her hesaplama sonunda bu nesneyi üretir.
    SignalGenerator yalnızca bu nesneyi tüketir.

    Attributes:
        symbol: İşlem çifti.
        timeframe: Zaman dilimi.
        timestamp: Bu bar'ın zaman damgası (Unix ms).
        current_price: Anlık kapanış fiyatı.
        rsi: RSI sonucu.
        macd: MACD sonucu.
        ema: EMA sonucu.
        atr: ATR sonucu.
        bollinger: Bollinger Bantları sonucu.
        volume: Hacim analizi sonucu.
        adx: ADX sonucu.
        fib: Fibonacci sonucu.
        patterns: Formasyon tespiti sonucu.
        weighted_score: Ağırlıklı toplam puan (0.0–1.0).
        score_breakdown: Her indikatörün katkısı.
    """
    symbol: str
    timeframe: str
    timestamp: int
    current_price: float

    rsi: Optional[RSIResult] = None
    macd: Optional[MACDResult] = None
    ema: Optional[EMAResult] = None
    atr: Optional[ATRResult] = None
    bollinger: Optional[BollingerResult] = None
    volume: Optional[VolumeResult] = None
    adx: Optional[ADXResult] = None
    fib: Optional[FibonacciResult] = None
    patterns: Optional[PatternResult] = None


    weighted_score: float = 0.0
    score_breakdown: dict = field(default_factory=dict)

    pa_signal: str = "HOLD"
    pa_entry_price: float = 0.0
    pa_sl_price: float = 0.0
    pa_tp_price: float = 0.0
    pa_has_fvg: bool = False

    def calculate_weighted_score(self) -> float:
        """Tüm aktif indikatörlerin ağırlıklı puanını hesaplar.

        Her indikatörün signal_strength değeri kendi efektif
        ağırlığı ile çarpılır; toplamı maksimum puana bölünür.

        Returns:
            0.0–1.0 arası normalize edilmiş toplam puan.
        """
        total_weight = 0.0
        weighted_sum = 0.0
        breakdown = {}

        components = [
            ("rsi",            self.rsi),
            ("macd",           self.macd),
            ("ema",            self.ema),
            ("bollinger_bands", self.bollinger),
            ("volume",         self.volume),
            ("adx",            self.adx),
        ]

        for name, indicator in components:
            if indicator is None:
                continue
            w = indicator.effective_weight
            
            # Yönlü skoru hesapla (Nötr = 0.5, Güçlü Alış -> 1.0'e yakın, Güçlü Satış -> 0.0'a yakın)
            directional_score = 0.5 + (indicator.signal.score - 0.5) * indicator.signal_strength
            contribution = w * directional_score
            
            breakdown[name] = {
                "weight": w,
                "signal_strength": indicator.signal_strength,
                "signal_direction": indicator.signal.value,
                "directional_score": round(directional_score, 4),
                "contribution": round(contribution, 4),
            }
            weighted_sum += contribution
            total_weight  += w

        if total_weight == 0:
            self.weighted_score = 0.0
        else:
            self.weighted_score = round(weighted_sum / total_weight, 4)

        self.score_breakdown = breakdown
        return self.weighted_score

    def summary(self) -> str:
        """Konsol çıktısı için kısa özet."""
        lines = [
            f"{'─'*55}",
            f" {self.symbol} @ {self.timeframe} | "
            f"Fiyat: {self.current_price:,.2f} | "
            f"Skor: {self.weighted_score:.3f}",
            f"{'─'*55}",
        ]
        if self.rsi:
            div = " [DIV!]" if self.rsi.has_divergence else ""
            lines.append(
                f"  RSI        : {self.rsi.value:.1f} "
                f"({self.rsi.zone.value}){div} → {self.rsi.signal.value}"
            )
        if self.macd:
            lines.append(
                f"  MACD       : {self.macd.macd_line:.4f} | "
                f"Hist: {self.macd.histogram:.4f} → {self.macd.signal.value}"
            )
        if self.ema:
            lines.append(
                f"  EMA        : 20={self.ema.ema20:.1f} | "
                f"50={self.ema.ema50:.1f} | 200={self.ema.ema200:.1f} "
                f"({self.ema.alignment.value})"
            )
        if self.atr:
            lines.append(
                f"  ATR        : {self.atr.value:.2f} "
                f"({self.atr.atr_pct:.2f}%) | "
                f"SL-Long: {self.atr.stop_loss_long:.2f}"
            )
        if self.bollinger:
            sq = " [SQUEEZE]" if self.bollinger.is_squeeze else ""
            lines.append(
                f"  Bollinger  : %B={self.bollinger.percent_b:.2f} "
                f"| BW={self.bollinger.bandwidth:.4f}{sq}"
            )
        if self.volume:
            lines.append(
                f"  Volume     : {self.volume.volume_ratio:.2f}x ort. "
                f"→ {self.volume.signal.value}"
            )
        if self.adx:
            lines.append(
                f"  ADX        : {self.adx.value:.1f} (di+={self.adx.di_plus:.1f}, di-={self.adx.di_minus:.1f}) "
                f"→ {self.adx.signal.value}"
            )
        lines.append(f"{'─'*55}")
        return "\n".join(lines)
