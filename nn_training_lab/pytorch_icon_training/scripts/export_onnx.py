#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              PyTorch 装备模型导出 ONNX                       ║
║  【一句话解释】把 ResNet18 checkpoint 转成跨硬件部署格式。      ║
║  【类比理解】像把专用钥匙复制成通用钥匙胚，方便不同机器使用。   ║
║  【数据流说明】best.pt + label_map → fp32/fp16/int8 ONNX。     ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import json
import sys
import shutil
import time
from pathlib import Path
from typing import Any, Dict

import torch

from train_resnet_icon_classifier import build_model


ROOT = Path(__file__).resolve().parents[3]
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# ============================================================
# 🧰 第二部分：文件工具
# ============================================================

def write_json(path: Path, payload: object) -> None:
    """写出 UTF-8 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def latest_run(root: Path) -> Path:
    """选择最新且完整的 PyTorch 训练目录。"""
    model_root = root / "nn_training_lab" / "pytorch_icon_training" / "models"
    candidates = [
        path for path in model_root.glob("run_*")
        if (path / "best.pt").is_file() and (path / "label_map.json").is_file()
    ]
    if not candidates:
        raise FileNotFoundError(f"找不到 PyTorch 模型目录: {model_root}")
    return max(candidates, key=lambda item: item.stat().st_mtime)


def load_model(run_dir: Path) -> tuple[torch.nn.Module, Dict[str, Any]]:
    """加载 PyTorch best.pt 和 label_map。"""
    label_payload = json.loads((run_dir / "label_map.json").read_text(encoding="utf-8"))
    class_count = len(label_payload["name_to_index"])
    model, _ = build_model(class_count, pretrained=False)
    checkpoint = torch.load(run_dir / "best.pt", map_location="cpu", weights_only=False)
    model.load_state_dict(checkpoint["model"])
    model.eval()
    return model, label_payload


# ============================================================
# 🚚 第三部分：导出与量化
# ============================================================

def export_fp32(model: torch.nn.Module, output_path: Path, opset: int) -> None:
    """导出 FP32 ONNX。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dummy = torch.randn(1, 3, 224, 224, dtype=torch.float32)
    torch.onnx.export(
        model,
        dummy,
        str(output_path),
        export_params=True,
        opset_version=opset,
        do_constant_folding=True,
        input_names=["input"],
        output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
        dynamo=False,
    )


def validate_onnx(path: Path) -> str:
    """用 onnx checker 做基础校验；缺包时返回 unavailable。"""
    try:
        import onnx

        model = onnx.load(str(path))
        onnx.checker.check_model(model)
        return "ok"
    except Exception as exc:
        return f"unavailable_or_failed: {exc}"


def export_fp16(fp32_path: Path, fp16_path: Path) -> str:
    """尝试导出 FP16 ONNX；转换失败不影响 FP32。"""
    try:
        import onnx
        from onnxconverter_common import float16

        model = onnx.load(str(fp32_path))
        model_fp16 = float16.convert_float_to_float16(model, keep_io_types=True)
        onnx.save(model_fp16, str(fp16_path))
        return "ok"
    except Exception as exc:
        return f"unavailable_or_failed: {exc}"


def export_int8(fp32_path: Path, int8_path: Path) -> str:
    """尝试动态 INT8 量化；适合 CPU 体积/速度优化初筛。"""
    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic

        quantize_dynamic(str(fp32_path), str(int8_path), weight_type=QuantType.QInt8)
        return "ok"
    except Exception as exc:
        return f"unavailable_or_failed: {exc}"


def export_model(run_dir: Path, output_dir: Path, opset: int, fp16: bool, int8: bool) -> Dict[str, Any]:
    """执行完整导出流程。"""
    model, label_payload = load_model(run_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fp32_path = output_dir / "equipment_icon_resnet18_fp32.onnx"
    export_fp32(model, fp32_path, opset)
    shutil.copy2(run_dir / "label_map.json", output_dir / "label_map.json")
    variants: Dict[str, Dict[str, str]] = {
        "fp32": {"path": str(fp32_path), "status": validate_onnx(fp32_path)},
    }
    if fp16:
        fp16_path = output_dir / "equipment_icon_resnet18_fp16.onnx"
        variants["fp16"] = {"path": str(fp16_path), "status": export_fp16(fp32_path, fp16_path)}
        if fp16_path.exists():
            variants["fp16"]["status"] = validate_onnx(fp16_path)
    if int8:
        int8_path = output_dir / "equipment_icon_resnet18_int8_dynamic.onnx"
        variants["int8_dynamic"] = {"path": str(int8_path), "status": export_int8(fp32_path, int8_path)}
        if int8_path.exists():
            variants["int8_dynamic"]["status"] = validate_onnx(int8_path)
    summary = {
        "status": "completed",
        "source_run_dir": str(run_dir),
        "output_dir": str(output_dir),
        "label_key": label_payload.get("label_key", "equipment_name"),
        "classes": len(label_payload.get("name_to_index", {})),
        "opset": opset,
        "variants": variants,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "ONNX 输出 logits；推理端统一做 softmax 并返回 equipment_name。",
    }
    write_json(output_dir / "onnx_export_summary.json", summary)
    return summary


# ============================================================
# 🚀 第四部分：命令入口
# ============================================================

def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="导出 PyTorch 装备 icon 模型为 ONNX。")
    parser.add_argument("--run-dir", type=Path, default=None, help="PyTorch run_* 目录；默认选择最新完整模型。")
    parser.add_argument("--output-dir", type=Path, default=None, help="ONNX 输出目录。")
    parser.add_argument("--opset", type=int, default=17)
    parser.add_argument("--no-fp16", action="store_true", help="不尝试 FP16 导出。")
    parser.add_argument("--no-int8", action="store_true", help="不尝试 INT8 动态量化。")
    args = parser.parse_args()
    run_dir = (args.run_dir or latest_run(ROOT)).resolve()
    output_dir = (
        args.output_dir
        or (ROOT / "nn_training_lab" / "deployment" / "onnx_models" / run_dir.name)
    ).resolve()
    summary = export_model(run_dir, output_dir, args.opset, not args.no_fp16, not args.no_int8)
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
