#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run local NN top-k inference for one icon or a folder of icons."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


# Direct double-click/`python path/to/script.py` execution starts with the
# scripts directory on sys.path; add the project root so the package import
# remains usable without requiring PyCharm or `python -m`.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nn_training_lab.inference.equipment_icon_nn import EquipmentIconNN


def latest_model_dir(checkpoint_root: Path) -> Path:
    """Return the best complete local run; ignore failed/incomplete runs."""
    candidates = []
    for run in checkpoint_root.glob("run_*"):
        if not (run / "best.pdparams").is_file() or not (run / "label_map.json").is_file():
            continue
        score = -1.0
        summary = run / "training_summary.json"
        if summary.is_file():
            try:
                score = float(json.loads(summary.read_text(encoding="utf-8")).get("best_validation_top1", -1.0))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                score = -1.0
        candidates.append((score, run.stat().st_mtime, run))
    return max(candidates, key=lambda item: (item[0], item[1]))[2] if candidates else checkpoint_root / "missing_run"


def main() -> int:
    """CLI entry point."""
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Run local equipment icon NN inference.")
    parser.add_argument("input", type=Path, help="One square icon or a folder containing square icons.")
    parser.add_argument("--model", type=Path, default=None, help="Checkpoint directory; defaults to the newest run_* directory.")
    parser.add_argument("--dataset", type=Path, default=root / "nn_training_lab" / "training_sets" / "equipment_icon_nn_dataset")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()
    checkpoint_root = root / "nn_training_lab" / "models" / "checkpoints"
    model_dir = args.model.resolve() if args.model is not None else latest_model_dir(checkpoint_root)
    detector = EquipmentIconNN(model_dir, args.dataset.resolve())
    paths = [args.input.resolve()] if args.input.is_file() else sorted(args.input.glob("*.png"))
    if not paths:
        print(json.dumps({"status": "empty", "message": "No PNG icons found."}, ensure_ascii=False, indent=2))
        return 0
    for path in paths:
        result = detector.predict_file(path, args.top_k)
        print(json.dumps({"file": str(path), **result.to_dict()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
