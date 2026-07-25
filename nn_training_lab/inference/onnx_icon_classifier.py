#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║             ONNX 装备图标推理适配器                          ║
║  【一句话解释】用 ONNX Runtime 加载导出的装备名称分类模型。     ║
║  【类比理解】它像一把通用钥匙，让同一模型在 CPU/GPU/核显上跑。 ║
║  【数据流说明】icon PNG → 归一化张量 → ONNX logits → 名称候选。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
from PIL import Image

try:
    import onnxruntime as ort
except Exception:  # pragma: no cover - ONNX Runtime 是可选部署依赖。
    ort = None  # type: ignore[assignment]


# ============================================================
# 🧱 第二部分：数据对象与常量
# ============================================================

MEAN = np.asarray([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
STD = np.asarray([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)


@dataclass(frozen=True)
class OnnxIconCandidate:
    """一条 ONNX 推理候选。"""

    equipment_name: str
    confidence: float
    rank: int
    equipment_id: str = ""


@dataclass(frozen=True)
class OnnxIconResult:
    """ONNX 推理结果，结构兼容现有 NN fallback。"""

    status: str
    message: str
    candidates: tuple[OnnxIconCandidate, ...] = ()
    provider: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为 JSON 友好的结构。"""
        return {
            "status": self.status,
            "message": self.message,
            "provider": self.provider,
            "candidates": [
                {
                    "equipment_name": item.equipment_name,
                    "confidence": item.confidence,
                    "rank": item.rank,
                    "equipment_id": item.equipment_id,
                    "resolved_equipment_id": item.equipment_id,
                }
                for item in self.candidates
            ],
        }


# ============================================================
# 🏗️ 第三部分：ONNX 推理器
# ============================================================

class OnnxEquipmentIconClassifier:
    """延迟加载的 ONNX Runtime 装备名称分类器。"""

    def __init__(
        self,
        model_path: str | Path,
        label_map_path: str | Path,
        equipment_library_path: str | Path,
        providers: Optional[Sequence[str]] = None,
    ) -> None:
        """创建推理器；真正加载 session 延迟到第一次预测。"""
        self.model_path = Path(model_path)
        self.label_map_path = Path(label_map_path)
        self.equipment_library_path = Path(equipment_library_path)
        self.requested_providers = tuple(providers or ())
        self._session: Optional[Any] = None
        self._input_name = ""
        self._index_to_name: Dict[int, str] = {}
        self._name_to_id: Dict[str, str] = {}
        self._load_error = ""

    def check_status(self) -> Dict[str, Any]:
        """返回依赖、模型文件和 provider 可用性。"""
        available_providers = list(ort.get_available_providers()) if ort is not None else []
        return {
            "available": bool(
                ort is not None
                and self.model_path.is_file()
                and self.label_map_path.is_file()
            ),
            "onnxruntime_available": ort is not None,
            "model_path": str(self.model_path),
            "model_exists": self.model_path.is_file(),
            "label_map_path": str(self.label_map_path),
            "label_map_exists": self.label_map_path.is_file(),
            "available_providers": available_providers,
            "selected_provider": self.selected_provider,
            "load_error": self._load_error,
        }

    @property
    def selected_provider(self) -> str:
        """返回当前 session 使用的第一个 provider。"""
        if self._session is None:
            return ""
        providers = self._session.get_providers()
        return str(providers[0]) if providers else ""

    def predict_file(self, image_path: str | Path, top_k: int = 3) -> OnnxIconResult:
        """预测一张完整正方形 icon。"""
        path = Path(image_path)
        if not path.is_file():
            return OnnxIconResult("error", f"Icon file does not exist: {path}")
        try:
            tensor = preprocess_icon(path)
        except (OSError, ValueError) as exc:
            return OnnxIconResult("rejected", str(exc))
        if not self._ensure_loaded():
            return OnnxIconResult("unavailable", self._load_error or "ONNX model unavailable.")
        try:
            logits = self._session.run(None, {self._input_name: tensor})[0][0]  # type: ignore[union-attr]
            probabilities = softmax(np.asarray(logits, dtype=np.float32))
            top_count = min(max(1, int(top_k)), probabilities.shape[0])
            indices = np.argsort(probabilities)[::-1][:top_count]
            candidates = tuple(
                OnnxIconCandidate(
                    equipment_name=self._index_to_name[int(index)],
                    confidence=float(probabilities[int(index)]),
                    rank=rank,
                    equipment_id=self._name_to_id.get(self._index_to_name[int(index)], ""),
                )
                for rank, index in enumerate(indices, start=1)
            )
            return OnnxIconResult("success", "ONNX top-k candidates generated.", candidates, self.selected_provider)
        except Exception as exc:  # pragma: no cover - runtime provider specific.
            return OnnxIconResult("error", f"ONNX inference failed: {exc}", provider=self.selected_provider)

    def _ensure_loaded(self) -> bool:
        """加载 ONNX session 和标签映射；失败时只记录错误。"""
        if self._session is not None:
            return True
        if ort is None:
            self._load_error = "onnxruntime is not installed."
            return False
        if not self.model_path.is_file() or not self.label_map_path.is_file():
            self._load_error = "ONNX model or label_map.json is missing."
            return False
        try:
            payload = json.loads(self.label_map_path.read_text(encoding="utf-8"))
            name_to_index = payload.get("name_to_index", {})
            self._index_to_name = {int(index): str(name) for name, index in name_to_index.items()}
            self._name_to_id = load_name_to_id(self.equipment_library_path)
            providers = choose_providers(self.requested_providers)
            self._session = ort.InferenceSession(str(self.model_path), providers=providers or None)
            self._input_name = str(self._session.get_inputs()[0].name)
            return True
        except Exception as exc:
            self._load_error = str(exc)
            return False


# ============================================================
# 🛠️ 第四部分：辅助函数
# ============================================================

def choose_providers(requested: Sequence[str] = ()) -> List[str]:
    """按用户请求和当前环境选择 ONNX Runtime provider。"""
    if ort is None:
        return []
    available = set(ort.get_available_providers())
    preferred = list(requested) if requested else [
        "TensorrtExecutionProvider",
        "CUDAExecutionProvider",
        "DmlExecutionProvider",
        "OpenVINOExecutionProvider",
        "CPUExecutionProvider",
    ]
    providers = [provider for provider in preferred if provider in available]
    if "CPUExecutionProvider" in available and "CPUExecutionProvider" not in providers:
        providers.append("CPUExecutionProvider")
    return providers


def preprocess_icon(path: Path) -> np.ndarray:
    """把完整 icon 转为 ONNX Runtime 输入张量。"""
    with Image.open(path) as image:
        if image.width != image.height or image.width < 64:
            raise ValueError("Input must be a complete square icon, not a partial card.")
        rgb = image.convert("RGB").resize((224, 224))
    array = np.asarray(rgb, dtype=np.float32) / 255.0
    chw = array.transpose(2, 0, 1)
    normalized = (chw - MEAN) / STD
    return normalized[np.newaxis, ...].astype(np.float32)


def softmax(values: np.ndarray) -> np.ndarray:
    """稳定计算 softmax。"""
    shifted = values - np.max(values)
    exp = np.exp(shifted)
    return exp / np.sum(exp)


def load_name_to_id(path: Path) -> Dict[str, str]:
    """加载当前装备库名称到 ID 的兼容映射。"""
    result: Dict[str, str] = {}
    if not path.is_file():
        return result
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            name = str(row.get("name", "")).strip()
            equipment_id = str(row.get("equipment_id", "")).strip()
            if name and equipment_id:
                result.setdefault(name, equipment_id)
    return result
