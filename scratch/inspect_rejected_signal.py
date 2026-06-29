# -*- coding: utf-8 -*-
import json
from pathlib import Path

path = Path("logs_v21/signals.jsonl")
if path.exists():
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                sig = json.loads(line)
                if sig.get("weighted_score", 0.0) >= 0.65 and sig.get("rejection_reasons"):
                    print(json.dumps(sig, indent=2))
                    break
