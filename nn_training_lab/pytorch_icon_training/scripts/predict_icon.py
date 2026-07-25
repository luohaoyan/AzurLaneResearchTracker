#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run local PyTorch icon inference and emit equipment names."""
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


def load_names(path: Path) -> Dict[str, str]:
    """Load current name-to-ID aliases; IDs remain compatibility metadata."""
    result: Dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            name = str(row.get("name", "")).strip()
            equipment_id = str(row.get("equipment_id", "")).strip()
            if name and equipment_id:
                result.setdefault(name, equipment_id)
    return result


def predict(model: torch.nn.Module, image_path: Path, index_to_name: Dict[int, str], device: torch.device, top_k: int) -> List[Dict[str, Any]]:
    """Predict top-k candidates for one complete square icon."""
    with Image.open(image_path) as image:
        if image.width != image.height or image.width < 64:
            raise ValueError("Input must be a complete square icon, not a partial card.")
        tensor = TRANSFORM(image.convert("RGB")).unsqueeze(0).to(device)
    with torch.no_grad():
        probabilities = torch.softmax(model(tensor), dim=1)[0]
        values, indices = probabilities.topk(min(max(1, top_k), probabilities.shape[0]))
    return [
        {
            "equipment_name": index_to_name[int(index)],
            "confidence": float(value),
            "rank": rank,
            "equipment_id": "",
            "resolved_equipment_id": "",
        }
        for rank, (value, index) in enumerate(zip(values.cpu(), indices.cpu()), start=1)
    ]


def main() -> int:
    """CLI entry point for one icon or a folder of icons."""
    parser = argparse.ArgumentParser(description="Predict equipment_name with the PyTorch icon model.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--model", type=Path, required=True, help="A run directory containing best.pt and label_map.json.")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()
    model_dir = args.model.resolve()
    label_map = json.loads((model_dir / "label_map.json").read_text(encoding="utf-8"))["name_to_index"]
    index_to_name = {int(index): name for name, index in label_map.items()}
    model, _ = build_model(len(label_map), pretrained=False)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    payload = torch.load(model_dir / "best.pt", map_location=device, weights_only=False)
    model.load_state_dict(payload["model"])
    model.to(device).eval()
    aliases = load_names(ROOT / "data" / "equipment_library.csv")
    paths = [args.input.resolve()] if args.input.is_file() else sorted(args.input.glob("*.png"))
    for path in paths:
        candidates = predict(model, path, index_to_name, device, args.top_k)
        for candidate in candidates:
            candidate["equipment_id"] = aliases.get(candidate["equipment_name"], "")
            candidate["resolved_equipment_id"] = candidate["equipment_id"]
        print(json.dumps({"file": str(path), "status": "success", "label_key": "equipment_name", "candidates": candidates}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
