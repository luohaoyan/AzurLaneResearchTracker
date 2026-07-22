#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================
 Paddle icon classifier training entry point
 ------------------------------------------------------------
 This is a small supervised baseline for trusted 108x108 icons.
 It does not replace the OpenCV matcher: use it for low-confidence
 candidate re-ranking only after an independent test set is ready.
============================================================
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import time
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Tuple

import numpy as np
from PIL import Image

try:
    import paddle
    import paddle.nn as nn
    import paddle.nn.functional as F
    from paddle.io import DataLoader, Dataset
except Exception as exc:  # pragma: no cover - exercised on machines without Paddle.
    paddle = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    F = None  # type: ignore[assignment]
    DataLoader = None  # type: ignore[assignment]
    Dataset = object  # type: ignore[assignment,misc]
    PADDLE_IMPORT_ERROR = str(exc)
else:
    PADDLE_IMPORT_ERROR = ""


def write_json(path: Path, payload: object) -> None:
    """Write UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_manifest(path: Path) -> List[Dict[str, str]]:
    """Read dataset rows."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def image_to_tensor(path: Path, training: bool) -> np.ndarray:
    """Load RGB icon and apply conservative augmentation."""
    with Image.open(path) as image:
        image = image.convert("RGB").resize((96, 96), Image.Resampling.BILINEAR)
        data = np.asarray(image, dtype=np.float32)
    if training:
        if random.random() < 0.35:
            data = np.clip(data * random.uniform(0.88, 1.12), 0, 255)
        if random.random() < 0.2:
            noise = np.random.normal(0, 2.0, data.shape).astype(np.float32)
            data = np.clip(data + noise, 0, 255)
    return (data / 127.5 - 1.0).transpose(2, 0, 1).astype("float32")


class IconDataset(Dataset):
    """Paddle dataset backed by the generated manifest."""

    def __init__(
        self,
        rows: Sequence[Mapping[str, str]],
        root: Path,
        label_map: Mapping[str, int],
        training: bool,
        label_field: str = "equipment_name",
    ) -> None:
        super().__init__()
        self.rows = list(rows)
        self.root = root
        self.label_map = dict(label_map)
        self.training = training
        self.label_field = label_field

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> Tuple[np.ndarray, np.ndarray]:
        row = self.rows[index]
        image = image_to_tensor(self.root / row["path"], self.training)
        label = np.asarray([self.label_map[row[self.label_field]]], dtype="int64")
        return image, label


if nn is not None:
    class IconClassifier(nn.Layer):
        """Compact CNN; small enough for CPU smoke training."""

        def __init__(self, class_count: int) -> None:
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv2D(3, 32, 3, padding=1), nn.BatchNorm2D(32), nn.ReLU(), nn.MaxPool2D(2),
                nn.Conv2D(32, 64, 3, padding=1), nn.BatchNorm2D(64), nn.ReLU(), nn.MaxPool2D(2),
                nn.Conv2D(64, 128, 3, padding=1), nn.BatchNorm2D(128), nn.ReLU(), nn.MaxPool2D(2),
                nn.Conv2D(128, 192, 3, padding=1), nn.BatchNorm2D(192), nn.ReLU(), nn.AdaptiveAvgPool2D(1),
            )
            self.classifier = nn.Sequential(nn.Flatten(), nn.Dropout(0.2), nn.Linear(192, class_count))

        def forward(self, inputs: paddle.Tensor) -> paddle.Tensor:
            """Return class logits."""
            return self.classifier(self.features(inputs))
else:
    IconClassifier = None  # type: ignore[assignment,misc]


def topk_accuracy(logits: "paddle.Tensor", labels: "paddle.Tensor", k: int) -> float:
    """Compute top-k accuracy for one batch."""
    topk = paddle.topk(logits, k=min(k, logits.shape[1]), axis=1)[1]
    expected = labels.reshape([-1, 1])
    return float(paddle.any(topk == expected, axis=1).astype("float32").mean())


def evaluate(model: "IconClassifier", loader: "DataLoader") -> Dict[str, float]:
    """Evaluate validation rows and return top-1/top-3 accuracy."""
    model.eval()
    total = 0
    top1 = 0.0
    top3 = 0.0
    with paddle.no_grad():
        for images, labels in loader:
            logits = model(images)
            batch = labels.shape[0]
            top1 += topk_accuracy(logits, labels, 1) * batch
            top3 += topk_accuracy(logits, labels, 3) * batch
            total += batch
    model.train()
    return {"top1": top1 / total if total else 0.0, "top3": top3 / total if total else 0.0, "samples": total}


def select_device(requested: str) -> Tuple[str, str]:
    """Select a usable Paddle device and return ``(device, fallback_reason)``."""
    requested = requested.lower().strip()
    if requested not in {"auto", "cpu", "gpu"}:
        raise ValueError(f"Unsupported device: {requested}")
    if requested == "cpu" or not paddle.is_compiled_with_cuda():
        paddle.set_device("cpu")
        return "cpu", "" if requested == "cpu" else "CUDA is not compiled in this Paddle installation."
    try:
        paddle.set_device("gpu")
        # Some wheels report CUDA support but lack kernels for a newer GPU.
        probe = paddle.ones([2], dtype="float32")
        paddle.nn.functional.dropout(probe, p=0.1, training=True)
        return str(paddle.get_device()), ""
    except Exception as exc:  # pragma: no cover - depends on installed CUDA wheel.
        paddle.set_device("cpu")
        return "cpu", f"GPU probe failed; fell back to CPU: {exc}"


def train(
    dataset_dir: Path,
    output_dir: Path,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    seed: int,
    device: str = "auto",
) -> Dict[str, object]:
    """Train and checkpoint a baseline classifier."""
    if paddle is None or IconClassifier is None:
        return {"status": "unavailable", "reason": PADDLE_IMPORT_ERROR or "Paddle is not installed."}
    random.seed(seed)
    np.random.seed(seed)
    paddle.seed(seed)
    selected_device, device_fallback_reason = select_device(device)
    manifest = read_manifest(dataset_dir / "dataset_manifest.csv")
    label_payload = json.loads((dataset_dir / "label_map.json").read_text(encoding="utf-8"))
    label_field = str(label_payload.get("label_key", "equipment_id"))
    map_key = "name_to_index" if label_field == "equipment_name" else "id_to_index"
    if map_key not in label_payload:
        # 兼容旧数据集；新数据集始终使用名称作为模型类别。
        label_field = "equipment_id"
        map_key = "id_to_index"
    label_map = {key: int(value) for key, value in label_payload[map_key].items()}
    train_rows = [row for row in manifest if row["split"] == "train"]
    validation_rows = [row for row in manifest if row["split"] == "validation"]
    run_id = time.strftime("run_%Y%m%d_%H%M%S")
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "label_map.json", label_payload)
    model = IconClassifier(len(label_map))
    optimizer = paddle.optimizer.AdamW(learning_rate=learning_rate, parameters=model.parameters(), weight_decay=1e-4)
    train_loader = DataLoader(IconDataset(train_rows, dataset_dir, label_map, True, label_field), batch_size=batch_size, shuffle=True, drop_last=False, num_workers=0)
    # 关闭增强后再次评估训练图，诊断模型是否真正记住已标注 icon；
    # 该指标不能替代独立验证集，也不能代表真实截图准确率。
    train_eval_loader = DataLoader(IconDataset(train_rows, dataset_dir, label_map, False, label_field), batch_size=batch_size, shuffle=False, drop_last=False, num_workers=0)
    val_loader = DataLoader(IconDataset(validation_rows, dataset_dir, label_map, False, label_field), batch_size=batch_size, shuffle=False, drop_last=False, num_workers=0)
    metrics: List[Dict[str, object]] = []
    best_top1 = -1.0
    epoch_metrics_dir = run_dir / "epoch_metrics"
    epoch_metrics_dir.mkdir(parents=True, exist_ok=True)
    for epoch in range(1, epochs + 1):
        model.train()
        loss_total = 0.0
        seen = 0
        for images, labels in train_loader:
            logits = model(images)
            loss = F.cross_entropy(logits, labels.reshape([-1]))
            loss.backward()
            optimizer.step()
            optimizer.clear_grad()
            count = labels.shape[0]
            loss_total += float(loss) * count
            seen += count
        train_evaluation = evaluate(model, train_eval_loader)
        validation_evaluation = evaluate(model, val_loader)
        record = {
            "epoch": epoch,
            "train_loss": loss_total / seen if seen else 0.0,
            "train_top1": train_evaluation["top1"],
            "train_top3": train_evaluation["top3"],
            "train_eval_samples": train_evaluation["samples"],
            "top1": validation_evaluation["top1"],
            "top3": validation_evaluation["top3"],
            "samples": validation_evaluation["samples"],
        }
        metrics.append(record)
        paddle.save(model.state_dict(), str(run_dir / f"epoch_{epoch:03d}.pdparams"))
        write_json(epoch_metrics_dir / f"epoch_{epoch:03d}.json", {
            "epoch": epoch,
            "label_key": label_field,
            "train_loss": record["train_loss"],
            "train": train_evaluation,
            "validation": validation_evaluation,
            "checkpoint": str(run_dir / f"epoch_{epoch:03d}.pdparams"),
            "warning": "训练集指标只表示对已见 icon 的记忆能力；验证集指标也不是独立真实截图准确率。",
        })
        if validation_evaluation["top1"] > best_top1:
            best_top1 = validation_evaluation["top1"]
            paddle.save(model.state_dict(), str(run_dir / "best.pdparams"))
    summary = {
        "status": "completed",
        "device": str(paddle.get_device()),
        "requested_device": device,
        "device_fallback_reason": device_fallback_reason,
        "cuda_compiled": bool(paddle.is_compiled_with_cuda()),
        "classes": len(label_map),
        "label_key": label_field,
        "train_samples": len(train_rows),
        "validation_samples": len(validation_rows),
        "epochs": epochs,
        "batch_size": batch_size,
        "learning_rate": learning_rate,
        "metrics": metrics,
        "best_validation_top1": best_top1,
        "run_dir": str(run_dir),
        "warning": "This is a baseline with sparse classes. Do not interpret train/validation accuracy as real-world accuracy or a 98% guarantee.",
    }
    write_json(run_dir / "training_summary.json", summary)
    with (run_dir / "metrics.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["epoch", "train_loss", "train_top1", "train_top3", "train_eval_samples", "top1", "top3", "samples"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(metrics)
    return summary


def parse_args() -> argparse.Namespace:
    """Parse CLI options."""
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Train the equipment icon Paddle baseline.")
    parser.add_argument("--dataset", type=Path, default=root / "nn_training_lab" / "training_sets" / "equipment_icon_nn_dataset")
    parser.add_argument("--output", type=Path, default=root / "nn_training_lab" / "models" / "checkpoints")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--seed", type=int, default=20260722)
    parser.add_argument("--device", choices=("auto", "cpu", "gpu"), default="auto", help="Paddle device; auto probes GPU and falls back to CPU.")
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    summary = train(args.dataset.resolve(), args.output.resolve(), args.epochs, args.batch_size, args.learning_rate, args.seed, args.device)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("status") in {"completed", "unavailable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
