# -*- coding: utf-8 -*-
import json
from pathlib import Path

path = Path("logs_v21/signals.jsonl")
rejections = []
if path.exists():
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    sig = json.loads(line)
                    score = sig.get("weighted_score", 0.0)
                    rejs = sig.get("rejection_reasons", [])
                    stype = sig.get("signal_type")
                    # If it has rejection reasons, it means some filter blocked it
                    if rejs and score >= 0.65:
                        rejections.append(sig)
                except Exception as e:
                    pass

print(f"Toplam {len(rejections)} adet filtrelere takilan sinyal bulundu (skor >= 0.65):")
for r in rejections[:20]:
    print(f"Zaman: {r.get('generated_at')} | Sembol: {r.get('symbol')} | Skor: {r.get('weighted_score'):.3f} | Nedenler: {r.get('rejection_reasons')}")
