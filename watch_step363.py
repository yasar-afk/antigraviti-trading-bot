"# ============================================================
# watch.py — ANTIGRAVITI Multi-Version Watch Dashboard
#
# AMAÇ:
#   V1, V2 ve V2.1 botlarının portföy durumunu aynı anda
#   tek ekranda gösterir. 1 dakikada bir otomatik yenilenir.
#
# KULLANIM:
#   python watch.py               # Dashboard başlat
#   python watch.py --refresh 30  # 30 saniyede bir yenile
#   python watch.py --once        # Bir kez göster ve çık
#
# BAĞIMLILIK:
#   pip install colorama   (zaten requirements.txt'te)
# ============================================================

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Colorama — renkli terminal çıktısı (Windows uyumlu)
try:
    import colorama
    from colorama import Fore, Back, Style
    colorama.init(autoreset=True)
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False
    class Fore:
        RED = GREEN = YELLOW = CYAN = MAGENTA = BLUE = WHITE = RESET = ""
    class Back:
        RED = GREEN = BLUE = BLACK = WHITE = RESET = ""
    class Style:
        BRIGHT = DIM = RESET_ALL = NORMAL = ""

PROJECT_ROOT = Path(__file__).parent

# ─── Her versiyon için log dizini ve portföy dosyası ─────────
VERSIONS = [
    {
        "label":     "V1   (Long-Only Klasik)",
        "short":     "V1",
        "log_dir":   PROJECT_ROOT / "logs_v1",
        "state_file": "portfolio_state.json",
        "journal_prefix": "signals_",
        "color":     Fore.CYAN,
        "accent":    "🔵",
    },
    {
        "label":     "V2   (Long-Only + Filtreler)",
        "short":     "V2",
        "log_dir":   PROJECT_ROOT / "logs",
        "state_file": "portfolio_state.json",
        "journal_prefix": "signals_",
        "color":     Fore.GREEN,
        "accent":    <truncated 10334 bytes>