#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================
 Neural-network checkpoint evaluation
 ------------------------------------------------------------
 Evaluate every epoch checkpoint from one training run without changing
 the dataset, equipment library, or user records.  The report separates
 train/validation accuracy and can rank manually confirmed icon files.
============================================================
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np
from PIL import Image

try:
    import paddle
except Exception as exc:  # pragma: no cover - optional dependency
    paddle = None  # type: ignore[assignment]
    PADDLE_IMPORT_ERROR = str(exc)
else:
    PADDLE_IMPORT_ERROR = ""

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nn_training_lab.scripts.train_equipment_icon_classifier import IconClassifier, image_to_tensor, read_manifest


def write_json(path: Path, payload: object) -> None:
    """Write a UTF-8 JSON report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_label_map(dataset_dir: Path) -> Tuple[str, Dict[str, int], Dict[int, str]]:
    """Load the model label schema and reject an ID-only new dataset."""
    payload = json.loads((dataset_dir / "label_map.json").read_text(encoding="utf-8"))
    label_key = str(payload.get("label_key", "equipment_id"))
    map_key = "name_to_index" if label_key == "equipment_name" else "id_to_index"
    if map_key not in payload:
        raise ValueError(f"Label map does not contain {map_key}: {dataset_dir}")
    label_map = {str(key): int(value) for key, value in payload[map_key].items()}
    index_to_label = {index: label for label, index in label_map.items()}
    return label_key, label_map, index_to_label


def topk_for_image(model: Any, path: Path, index_to_label: Mapping[int, str], top_k: int = 3) -> List[Dict[str, Any]]:
    """Return top-k labels for one square icon using a local checkpoint."""
    tensor = paddle.to_tensor(image_to_tensor(path, training=False)[None, ...])
    with paddle.no_grad():
        probabilities = paddle.nn.functional.softmax(model(tensor), axis=1)[0]
        values, indices = paddle.topk(probabilities, k=min(max(1, top_k), probabilities.shape[0]))
    return [
        {
            "label": index_to_label[int(index)],
            "confidence": float(value),
            "rank": rank,
        }
        for rank, (value, index) in enumerate(zip(values.numpy(), indices.numpy()), start=1)
    ]


def evaluate_manifest(
    model: Any,
    rows: Sequence[Mapping[str, str]],
    dataset_dir: Path,
    label_map: Mapping[str, int],
    batch_size: int = 64,
) -> Dict[str, Any]:
    """Evaluate manifest rows in batches, without augmentation or data writes."""
    index_to_label = {index: label for label, index in label_map.items()}
    top1 = 0
    top3 = 0
    for start in range(0, len(rows), max(1, batch_size)):
        batch_rows = rows[start:start + max(1, batch_size)]
        tensors = [image_to_tensor(dataset_dir / row["path"], training=False) for row in batch_rows]
        logits = model(paddle.to_tensor(np.stack(tensors, axis=0)))
        indices = paddle.topk(logits, k=min(3, logits.shape[1]), axis=1)[1].numpy()
        for row, row_indices in zip(batch_rows, indices):
            labels = [index_to_label[int(index)] for index in row_indices]
            expected = row["equipment_name"] if "equipment_name" in row else row["equipment_id"]
            top1 += int(labels and labels[0] == expected)
            top3 += int(expected in labels)
    total = len(rows)
    return {
        "samples": total,
        "top1": top1 / total if total else 0.0,
        "top3": top3 / total if total else 0.0,
    }


def evaluate_run(run_dir: Path, dataset_dir: Path, targets: Sequence[Tuple[str, Path]], output_dir: Path) -> Dict[str, Any]:
    """Evaluate all epoch weights and archive one JSON per epoch."""
    if paddle is None or IconClassifier is None:
        return {"status": "unavailable", "reason": PADDLE_IMPORT_ERROR or "Paddle is not installed."}
    label_key, label_map, index_to_label = load_label_map(dataset_dir)
    manifest = read_manifest(dataset_dir / "dataset_manifest.csv")
    train_rows = [row for row in manifest if row["split"] == "train"]
    validation_rows = [row for row in manifest if row["split"] == "validation"]
    checkpoints = sorted(run_dir.glob("epoch_*.pdparams"))
    if not checkpoints:
        return {"status": "error", "reason": f"No epoch checkpoints found: {run_dir}"}
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    for checkpoint in checkpoints:
        model = IconClassifier(len(label_map))
        model.set_state_dict(paddle.load(str(checkpoint)))
        model.eval()
        train = evaluate_manifest(model, train_rows, dataset_dir, label_map)
        validation = evaluate_manifest(model, validation_rows, dataset_dir, label_map)
        target_results = []
        for expected_name, target_path in targets:
            if not target_path.is_file():
                target_results.append({"expected_name": expected_name, "path": str(target_path), "status": "missing"})
                continue
            predictions = topk_for_image(model, target_path, index_to_label, 5)
            rank = next((item["rank"] for item in predictions if item["label"] == expected_name), None)
            target_results.append({
                "expected_name": expected_name,
                "path": str(target_path),
                "status": "evaluated",
                "expected_rank": rank,
                "top_candidates": predictions,
            })
        payload = {
            "status": "completed",
            "epoch": int(checkpoint.stem.split("_")[-1]),
            "checkpoint": str(checkpoint),
            "label_key": label_key,
            "train": train,
            "validation": validation,
            "targets": target_results,
            "warning": "训练/验证集和已确认 icon 只用于实验比较，不代表真实截图 98% 准确率。",
        }
        write_json(output_dir / f"{checkpoint.stem}.json", payload)
        rows.append({
            "epoch": payload["epoch"],
            "checkpoint": str(checkpoint),
            "train_top1": train["top1"],
            "train_top3": train["top3"],
            "validation_top1": validation["top1"],
            "validation_top3": validation["top3"],
            "target_top1_count": sum(item.get("expected_rank") == 1 for item in target_results),
            "target_evaluated": sum(item.get("status") == "evaluated" for item in target_results),
        })
    fields = list(rows[0].keys())
    with (output_dir / "checkpoint_evaluation.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "status": "completed",
        "run_dir": str(run_dir),
        "output_dir": str(output_dir),
        "label_key": label_key,
        "epochs_evaluated": len(rows),
        "best_validation_top1": max(row["validation_top1"] for row in rows),
        "best_validation_top3": max(row["validation_top3"] for row in rows),
        "target_count": len(targets),
    }
    write_json(output_dir / "evaluation_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    """Parse the checkpoint evaluation CLI."""
    parser = argparse.ArgumentParser(description="Evaluate every local NN checkpoint and archive per-epoch results.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=PROJECT_ROOT / "nn_training_lab" / "training_sets" / "equipment_icon_nn_dataset")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target", nargs=2, action="append", metavar=("EQUIPMENT_NAME", "ICON_PATH"), default=[])
    return parser.parse_args()


def main() -> int:
    """Run checkpoint evaluation without network or business-data writes."""
    args = parse_args()
    targets = [(str(name), Path(path).resolve()) for name, path in args.target]
    summary = evaluate_run(args.run_dir.resolve(), args.dataset.resolve(), targets, args.output_dir.resolve())
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0 if summary.get("status") in {"completed", "unavailable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
