#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evaluate every PyTorch checkpoint on explicitly listed icon test cases."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List

import torch
from PIL import Image
from torchvision import transforms

from train_resnet_icon_classifier import build_model

ROOT = Path(__file__).resolve().parents[3]
TRANSFORM = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


def predict(model: torch.nn.Module, path: Path, index_to_name: Dict[int, str], device: torch.device) -> List[Dict[str, Any]]:
    """Return top-five name candidates for one icon."""
    with Image.open(path) as image:
        tensor = TRANSFORM(image.convert("RGB")).unsqueeze(0).to(device)
    with torch.no_grad():
        probabilities = torch.softmax(model(tensor), dim=1)[0]
        values, indices = probabilities.topk(min(5, probabilities.shape[0]))
    return [
        {"equipment_name": index_to_name[int(index)], "confidence": float(value), "rank": rank}
        for rank, (value, index) in enumerate(zip(values.cpu(), indices.cpu()), start=1)
    ]


def load_id_map(path: Path) -> Dict[str, str]:
    """Load current name-to-ID aliases for compatibility output only."""
    library = path / "data" / "equipment_library.csv"
    result: Dict[str, str] = {}
    if library.is_file():
        with library.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                name = str(row.get("name", "")).strip()
                equipment_id = str(row.get("equipment_id", "")).strip()
                if name and equipment_id:
                    result.setdefault(name, equipment_id)
    return result


def main() -> int:
    """Evaluate all epoch checkpoints and write one JSON per epoch."""
    parser = argparse.ArgumentParser(description="Evaluate PyTorch icon checkpoints on test_cases.json.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--test-cases", type=Path, default=ROOT / "nn_training_lab/pytorch_icon_training/test_cases.json")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    output_dir = (args.output_dir or (ROOT / "nn_training_lab/pytorch_icon_training/test_out" / run_dir.name)).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = json.loads(args.test_cases.resolve().read_text(encoding="utf-8"))
    label_map = json.loads((run_dir / "label_map.json").read_text(encoding="utf-8"))["name_to_index"]
    index_to_name = {int(index): name for name, index in label_map.items()}
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    id_map = load_id_map(ROOT)
    rows: List[Dict[str, Any]] = []
    for checkpoint in sorted(run_dir.glob("epoch_*.pt")):
        model, _ = build_model(len(label_map), pretrained=False)
        payload = torch.load(checkpoint, map_location=device, weights_only=False)
        model.load_state_dict(payload["model"])
        model.to(device).eval()
        results = []
        for case in cases:
            path = Path(str(case.get("image_path", "")))
            expected_name = str(case.get("equipment_name", ""))
            if not path.is_file():
                results.append({"equipment_name": expected_name, "status": "missing", "image_path": str(path)})
                continue
            candidates = predict(model, path, index_to_name, device)
            expected_rank = next((item["rank"] for item in candidates if item["equipment_name"] == expected_name), None)
            results.append({
                "equipment_name": expected_name,
                "equipment_id": id_map.get(expected_name, ""),
                "image_path": str(path),
                "independent": bool(case.get("independent", False)),
                "status": "evaluated",
                "expected_rank": expected_rank,
                "top_candidates": candidates,
            })
        epoch = int(checkpoint.stem.split("_")[-1])
        report = {"status": "completed", "epoch": epoch, "checkpoint": str(checkpoint), "label_key": "equipment_name", "cases": results}
        (output_dir / f"epoch_{epoch:03d}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append({
            "epoch": epoch,
            "evaluated": sum(item.get("status") == "evaluated" for item in results),
            "top1_count": sum(item.get("expected_rank") == 1 for item in results),
            "top3_count": sum((item.get("expected_rank") or 99) <= 3 for item in results),
        })
    with (output_dir / "test_summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    summary = {"status": "completed", "run_dir": str(run_dir), "output_dir": str(output_dir), "label_key": "equipment_name", "epochs": len(rows), "test_cases": len(cases), "independent_cases": sum(bool(case.get("independent", False)) for case in cases)}
    (output_dir / "evaluation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
