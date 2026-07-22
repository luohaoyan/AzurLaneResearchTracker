#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║             装备 icon 多后端识别基准                         ║
║  【一句话解释】比较 OpenCV、PyTorch、ONNX 的速度和候选准确性。  ║
║  【类比理解】像让三位选手做同一套题，看谁又快又准。             ║
║  【数据流说明】manifest icon → 各后端 top-k → CSV/JSON/TXT。   ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Mapping, Sequence

import torch
from PIL import Image
from torchvision import transforms

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYTORCH_SCRIPT_DIR = PROJECT_ROOT / "nn_training_lab" / "pytorch_icon_training" / "scripts"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PYTORCH_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(PYTORCH_SCRIPT_DIR))

from core.recognition.equipment_icon_matcher import EquipmentIconMatcher  # noqa: E402
from nn_training_lab.inference.onnx_icon_classifier import OnnxEquipmentIconClassifier  # noqa: E402
from train_resnet_icon_classifier import build_model  # noqa: E402


TRANSFORM = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


# ============================================================
# 🧱 第二部分：加载器
# ============================================================

class PytorchPredictor:
    """轻量 PyTorch 推理器，用于 benchmark。"""

    def __init__(self, run_dir: Path, library_path: Path) -> None:
        """加载 PyTorch best.pt 和当前名称到 ID 映射。"""
        self.run_dir = run_dir
        label_payload = json.loads((run_dir / "label_map.json").read_text(encoding="utf-8"))
        name_to_index = label_payload["name_to_index"]
        self.index_to_name = {int(index): str(name) for name, index in name_to_index.items()}
        self.name_to_id = load_name_to_id(library_path)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model, _ = build_model(len(name_to_index), pretrained=False)
        checkpoint = torch.load(run_dir / "best.pt", map_location=self.device, weights_only=False)
        self.model.load_state_dict(checkpoint["model"])
        self.model.to(self.device).eval()

    def predict_file(self, image_path: Path, top_k: int = 3) -> List[Dict[str, Any]]:
        """返回 top-k 名称候选。"""
        with Image.open(image_path) as image:
            tensor = TRANSFORM(image.convert("RGB")).unsqueeze(0).to(self.device)
        with torch.no_grad():
            probabilities = torch.softmax(self.model(tensor), dim=1)[0]
            values, indices = probabilities.topk(min(max(1, int(top_k)), probabilities.shape[0]))
        return [
            {
                "equipment_name": self.index_to_name[int(index)],
                "equipment_id": self.name_to_id.get(self.index_to_name[int(index)], ""),
                "confidence": float(value),
                "rank": rank,
            }
            for rank, (value, index) in enumerate(zip(values.cpu(), indices.cpu()), start=1)
        ]


def read_csv(path: Path) -> List[Dict[str, str]]:
    """读取 UTF-8-SIG CSV。"""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """写出 benchmark CSV。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "backend", "image_path", "expected_name", "expected_id", "top1_name", "top1_id",
        "top1_confidence", "expected_rank", "top1_ok", "top3_ok", "elapsed_ms",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def load_name_to_id(path: Path) -> Dict[str, str]:
    """加载装备名称到当前 ID 的映射。"""
    result: Dict[str, str] = {}
    for row in read_csv(path):
        name = str(row.get("name", "")).strip()
        equipment_id = str(row.get("equipment_id", "")).strip()
        if name and equipment_id:
            result.setdefault(name, equipment_id)
    return result


def latest_pytorch_run(root: Path) -> Path:
    """选择最新完整 PyTorch 训练目录。"""
    model_root = root / "nn_training_lab" / "pytorch_icon_training" / "models"
    runs = [path for path in model_root.glob("run_*") if (path / "best.pt").is_file()]
    if not runs:
        raise FileNotFoundError(f"找不到 PyTorch 模型: {model_root}")
    return max(runs, key=lambda item: item.stat().st_mtime)


def latest_onnx_dir(root: Path, run_name: str) -> Path:
    """选择与当前 run 对应或最新的 ONNX 导出目录。"""
    model_root = root / "nn_training_lab" / "deployment" / "onnx_models"
    exact = model_root / run_name
    if (exact / "equipment_icon_resnet18_fp32.onnx").is_file():
        return exact
    runs = [path for path in model_root.glob("run_*") if (path / "equipment_icon_resnet18_fp32.onnx").is_file()]
    if not runs:
        raise FileNotFoundError(f"找不到 ONNX 模型: {model_root}")
    return max(runs, key=lambda item: item.stat().st_mtime)


# ============================================================
# 🧮 第三部分：评估核心
# ============================================================

def select_rows(rows: Sequence[Mapping[str, str]], limit: int) -> List[Mapping[str, str]]:
    """稳定抽样，避免每次 benchmark 样本变化。"""
    filtered = [row for row in rows if Path(str(row.get("path", ""))).is_file()]
    if limit <= 0 or len(filtered) <= limit:
        return filtered
    step = max(1, len(filtered) // limit)
    return filtered[::step][:limit]


def evaluate_candidates(
    backend: str,
    image_path: Path,
    expected_name: str,
    expected_id: str,
    candidates: Sequence[Mapping[str, Any]],
    elapsed_ms: float,
) -> Dict[str, Any]:
    """把候选列表压成一行可比较结果。"""
    top = candidates[0] if candidates else {}
    expected_rank = next(
        (int(item.get("rank", index)) for index, item in enumerate(candidates, start=1)
         if item.get("equipment_name") == expected_name or item.get("equipment_id") == expected_id),
        0,
    )
    return {
        "backend": backend,
        "image_path": str(image_path),
        "expected_name": expected_name,
        "expected_id": expected_id,
        "top1_name": top.get("equipment_name", ""),
        "top1_id": top.get("equipment_id", ""),
        "top1_confidence": float(top.get("confidence", 0.0) or 0.0),
        "expected_rank": expected_rank,
        "top1_ok": expected_rank == 1,
        "top3_ok": 0 < expected_rank <= 3,
        "elapsed_ms": elapsed_ms,
    }


def timed_call(function: Any, *args: Any, **kwargs: Any) -> tuple[Any, float]:
    """执行函数并返回结果与耗时毫秒。"""
    start = time.perf_counter()
    result = function(*args, **kwargs)
    return result, (time.perf_counter() - start) * 1000.0


def benchmark(args: argparse.Namespace) -> Dict[str, Any]:
    """执行 OpenCV/PyTorch/ONNX benchmark。"""
    root = PROJECT_ROOT
    dataset = args.dataset.resolve()
    library_path = root / "data" / "equipment_library.csv"
    name_to_id = load_name_to_id(library_path)
    rows = select_rows(read_csv(dataset), int(args.limit))
    run_dir = (args.pytorch_run or latest_pytorch_run(root)).resolve()
    onnx_dir = (args.onnx_dir or latest_onnx_dir(root, run_dir.name)).resolve()
    output_dir = (args.output_dir or (root / "nn_training_lab" / "deployment" / "benchmark_out" / time.strftime("run_%Y%m%d_%H%M%S"))).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    pytorch = None if args.skip_pytorch else PytorchPredictor(run_dir, library_path)
    onnx_model = None if args.skip_onnx else OnnxEquipmentIconClassifier(
        onnx_dir / args.onnx_model,
        onnx_dir / "label_map.json",
        library_path,
        providers=tuple(args.provider or ()),
    )
    opencv = None if args.skip_opencv else EquipmentIconMatcher(
        gallery_csv_paths=[
            root / "ocr_training_lab" / "equipment_icon_matcher_v2" / "reviewed_icon_gallery" / "reviewed_icon_gallery_manifest.csv",
            root / "ocr_training_lab" / "equipment_icon_matcher_v2" / "accepted_icon_gallery" / "accepted_icon_gallery_manifest.csv",
        ],
        project_root=root,
    )

    result_rows: List[Dict[str, Any]] = []
    for row in rows:
        image_path = Path(str(row["path"]))
        expected_name = str(row["equipment_name"])
        expected_id = str(row.get("equipment_id", "") or name_to_id.get(expected_name, ""))
        if opencv is not None:
            import cv2
            import numpy as np

            image = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is not None:
                output, elapsed = timed_call(opencv.match_icon, image, (0, 0, image.shape[1], image.shape[0]), 3)
                candidates = [
                    {
                        "equipment_id": item.get("equipment_id", ""),
                        "equipment_name": name_by_id(name_to_id, item.get("equipment_id", "")),
                        "confidence": item.get("confidence", 0.0),
                        "rank": item.get("rank", index),
                    }
                    for index, item in enumerate(output.to_dict().get("candidates", []), start=1)
                ]
                result_rows.append(evaluate_candidates("opencv", image_path, expected_name, expected_id, candidates, elapsed))
        if pytorch is not None:
            candidates, elapsed = timed_call(pytorch.predict_file, image_path, 3)
            result_rows.append(evaluate_candidates("pytorch", image_path, expected_name, expected_id, candidates, elapsed))
        if onnx_model is not None:
            output, elapsed = timed_call(onnx_model.predict_file, image_path, 3)
            result_rows.append(evaluate_candidates(f"onnx:{onnx_model.selected_provider or 'lazy'}", image_path, expected_name, expected_id, [item.__dict__ for item in output.candidates], elapsed))

    summary = summarize(result_rows, len(rows), run_dir, onnx_dir)
    write_csv(output_dir / "backend_benchmark_results.csv", result_rows)
    (output_dir / "backend_benchmark_results.json").write_text(json.dumps(result_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "backend_benchmark_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "backend_benchmark_report.txt").write_text(format_report(summary), encoding="utf-8")
    return {"output_dir": str(output_dir), **summary}


def name_by_id(name_to_id: Mapping[str, str], equipment_id: str) -> str:
    """按 ID 反查名称；只用于 OpenCV benchmark 展示。"""
    for name, current_id in name_to_id.items():
        if current_id == equipment_id:
            return name
    return ""


def summarize(rows: Sequence[Mapping[str, Any]], sample_count: int, run_dir: Path, onnx_dir: Path) -> Dict[str, Any]:
    """汇总 benchmark。"""
    by_backend: Dict[str, Dict[str, Any]] = {}
    for backend in sorted({str(row.get("backend", "")) for row in rows}):
        items = [row for row in rows if row.get("backend") == backend]
        by_backend[backend] = {
            "samples": len(items),
            "top1": sum(bool(row.get("top1_ok")) for row in items) / len(items) if items else 0.0,
            "top3": sum(bool(row.get("top3_ok")) for row in items) / len(items) if items else 0.0,
            "avg_ms": mean(float(row.get("elapsed_ms", 0.0) or 0.0) for row in items) if items else 0.0,
        }
    return {
        "status": "completed",
        "sample_count": sample_count,
        "pytorch_run": str(run_dir),
        "onnx_dir": str(onnx_dir),
        "backends": by_backend,
        "warning": "该 benchmark 使用现有训练/图库样本，属于工程诊断，不代表独立真实截图准确率。",
    }


def format_report(summary: Mapping[str, Any]) -> str:
    """生成给测试工程师看的纯文本报告。"""
    lines = [
        "装备 icon 多后端 benchmark 报告",
        "================================",
        "",
        f"样本数: {summary.get('sample_count', 0)}",
        f"PyTorch 模型: {summary.get('pytorch_run', '')}",
        f"ONNX 目录: {summary.get('onnx_dir', '')}",
        "",
        "后端结果:",
    ]
    for backend, item in dict(summary.get("backends", {})).items():
        lines.append(
            f"- {backend}: top1={float(item.get('top1', 0.0)):.3f}, "
            f"top3={float(item.get('top3', 0.0)):.3f}, avg_ms={float(item.get('avg_ms', 0.0)):.2f}"
        )
    lines.extend([
        "",
        "结论建议:",
        "- 正式识别优先使用 OpenCV 命中高置信样本。",
        "- OpenCV ambiguous/unknown 或低置信度时，再调用 ONNX Runtime FP32/INT8。",
        "- PyTorch 保留给训练、调试和模型对照，不建议作为普通用户默认运行依赖。",
        "",
        str(summary.get("warning", "")),
    ])
    return "\n".join(lines)


# ============================================================
# 🚀 第四部分：命令入口
# ============================================================

def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="比较装备 icon OpenCV/PyTorch/ONNX 后端。")
    parser.add_argument("--dataset", type=Path, default=PROJECT_ROOT / "nn_training_lab" / "pytorch_icon_training" / "data" / "manifest.csv")
    parser.add_argument("--pytorch-run", type=Path, default=None)
    parser.add_argument("--onnx-dir", type=Path, default=None)
    parser.add_argument("--onnx-model", default="equipment_icon_resnet18_fp32.onnx")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=120, help="0 表示全量。")
    parser.add_argument("--provider", action="append", default=[], help="ONNX Runtime provider 优先级，可重复。")
    parser.add_argument("--skip-opencv", action="store_true")
    parser.add_argument("--skip-pytorch", action="store_true")
    parser.add_argument("--skip-onnx", action="store_true")
    args = parser.parse_args()
    summary = benchmark(args)
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
