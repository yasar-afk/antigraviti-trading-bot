# -*- coding: utf-8 -*-
import json
from pathlib import Path

path = Path("logs_v21/signals.jsonl")
unique_pairs = set()
count = 0
if path.exists():
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                sig = json.loads(line)
                score = sig.get("weighted_score", 0.0)
                rejs = sig.get("rejection_reasons", [])
                if rejs and score >= 0.65:
                    unique_pairs.add((sig.get("symbol"), sig.get("timeframe")))
                    count += 1

print(f"Total rejected signals (score >= 0.65): {count}")
print(f"Unique symbol-timeframe pairs: {len(unique_pairs)}")
for p in unique_pairs:
    print(p)
