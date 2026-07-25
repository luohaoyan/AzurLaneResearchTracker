#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Train a local equipment-name classifier with PyTorch/ResNet18."""
from __future__ import annotations

import argparse
import csv
import json
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

import numpy as np
import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms

ROOT = Path(__file__).resolve().parents[3]


def write_json(path: Path, payload: object) -> None:
    """Write UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class IconDataset(Dataset):
    """Manifest-backed icon dataset with name labels."""

    def __init__(self, rows: Sequence[Mapping[str, str]], label_map: Mapping[str, int], training: bool) -> None:
        self.rows = list(rows)
        self.label_map = dict(label_map)
        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ColorJitter(brightness=0.12, contrast=0.12, saturation=0.08),
            transforms.RandomAffine(degrees=3, translate=(0.03, 0.03), scale=(0.95, 1.05)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ]) if training else transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, int]:
        row = self.rows[index]
        with Image.open(row["path"]) as image:
            tensor = self.transform(image.convert("RGB"))
        return tensor, self.label_map[row["equipment_name"]]


def accuracy(logits: torch.Tensor, labels: torch.Tensor, k: int) -> float:
    """Compute top-k accuracy for one batch."""
    indices = logits.topk(min(k, logits.shape[1]), dim=1).indices
    return float(indices.eq(labels.view(-1, 1)).any(dim=1).float().mean().item())


def evaluate(model: nn.Module, loader: DataLoader, device: torch.device) -> Dict[str, float]:
    """Evaluate a loader without augmentation."""
    model.eval()
    top1 = top3 = total = 0
    with torch.no_grad():
        for images, labels in loader:
            logits = model(images.to(device))
            count = labels.shape[0]
            top1 += accuracy(logits, labels.to(device), 1) * count
            top3 += accuracy(logits, labels.to(device), 3) * count
            total += count
    return {"samples": total, "top1": top1 / total if total else 0.0, "top3": top3 / total if total else 0.0}


def build_model(class_count: int, pretrained: bool) -> tuple[nn.Module, bool]:
    """Build ResNet18 and replace its classifier with equipment-name classes."""
    used_pretrained = False
    weights = models.ResNet18_Weights.DEFAULT if pretrained else None
    try:
        model = models.resnet18(weights=weights)
        used_pretrained = weights is not None
    except Exception:
        model = models.resnet18(weights=None)
    model.fc = nn.Linear(model.fc.in_features, class_count)
    return model, used_pretrained


def train(dataset_dir: Path, output_root: Path, epochs: int, batch_size: int, learning_rate: float, seed: int, pretrained: bool) -> Dict[str, Any]:
    """Run an isolated ResNet18 experiment and archive every epoch."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    manifest = list(csv.DictReader((dataset_dir / "manifest.csv").open("r", encoding="utf-8-sig", newline="")))
    label_payload = json.loads((dataset_dir / "label_map.json").read_text(encoding="utf-8"))
    label_map = {str(name): int(index) for name, index in label_payload["name_to_index"].items()}
    train_rows = [row for row in manifest if row["split"] == "train"]
    validation_rows = [row for row in manifest if row["split"] == "validation"]
    run_dir = output_root / time.strftime("run_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "label_map.json", label_payload)
    model, used_pretrained = build_model(len(label_map), pretrained)
    model.to(device)
    counts = np.bincount([label_map[row["equipment_name"]] for row in train_rows], minlength=len(label_map)).astype(np.float32)
    weights = np.sqrt(np.maximum(counts.sum() / np.maximum(counts, 1.0), 1.0))
    weights = torch.tensor(weights / weights.mean(), dtype=torch.float32, device=device)
    criterion = nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, epochs))
    train_loader = DataLoader(IconDataset(train_rows, label_map, True), batch_size=batch_size, shuffle=True, num_workers=0)
    train_eval_loader = DataLoader(IconDataset(train_rows, label_map, False), batch_size=batch_size, shuffle=False, num_workers=0)
    validation_loader = DataLoader(IconDataset(validation_rows, label_map, False), batch_size=batch_size, shuffle=False, num_workers=0)
    metrics: List[Dict[str, Any]] = []
    epoch_dir = run_dir / "epoch_metrics"
    best_top1 = -1.0
    for epoch in range(1, epochs + 1):
        model.train()
        total_loss = total_samples = 0
        for images, labels in train_loader:
            optimizer.zero_grad(set_to_none=True)
            logits = model(images.to(device))
            loss = criterion(logits, labels.to(device))
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item()) * labels.shape[0]
            total_samples += labels.shape[0]
        scheduler.step()
        train_eval = evaluate(model, train_eval_loader, device)
        validation_eval = evaluate(model, validation_loader, device)
        record = {
            "epoch": epoch,
            "train_loss": total_loss / total_samples if total_samples else 0.0,
            "train_top1": train_eval["top1"],
            "train_top3": train_eval["top3"],
            "validation_top1": validation_eval["top1"],
            "validation_top3": validation_eval["top3"],
            "learning_rate": optimizer.param_groups[0]["lr"],
        }
        metrics.append(record)
        checkpoint = run_dir / f"epoch_{epoch:03d}.pt"
        torch.save({"model": model.state_dict(), "label_key": "equipment_name", "class_count": len(label_map)}, checkpoint)
        write_json(epoch_dir / f"epoch_{epoch:03d}.json", {"record": record, "checkpoint": str(checkpoint), "train": train_eval, "validation": validation_eval})
        if validation_eval["top1"] > best_top1:
            best_top1 = validation_eval["top1"]
            torch.save({"model": model.state_dict(), "label_key": "equipment_name", "class_count": len(label_map)}, run_dir / "best.pt")
    summary = {
        "status": "completed",
        "device": str(device),
        "cuda_available": torch.cuda.is_available(),
        "cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
        "pretrained_requested": pretrained,
        "pretrained_used": used_pretrained,
        "label_key": "equipment_name",
        "classes": len(label_map),
        "train_samples": len(train_rows),
        "validation_samples": len(validation_rows),
        "epochs": epochs,
        "metrics": metrics,
        "best_validation_top1": best_top1,
        "run_dir": str(run_dir),
        "warning": "Training/validation metrics are diagnostic and do not establish 98% real screenshot accuracy.",
    }
    write_json(run_dir / "training_summary.json", summary)
    with (run_dir / "metrics.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = list(metrics[0].keys())
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(metrics)
    return summary


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Train the isolated PyTorch equipment-name classifier.")
    parser.add_argument("--dataset", type=Path, default=ROOT / "nn_training_lab/pytorch_icon_training/data")
    parser.add_argument("--output", type=Path, default=ROOT / "nn_training_lab/pytorch_icon_training/models")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=0.0001)
    parser.add_argument("--seed", type=int, default=20260722)
    parser.add_argument("--no-pretrained", action="store_true")
    args = parser.parse_args()
    summary = train(args.dataset.resolve(), args.output.resolve(), args.epochs, args.batch_size, args.learning_rate, args.seed, not args.no_pretrained)
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
