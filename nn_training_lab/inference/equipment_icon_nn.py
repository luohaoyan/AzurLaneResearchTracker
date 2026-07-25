#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================
 Equipment icon NN inference adapter
 ------------------------------------------------------------
 Lazy-load a local Paddle checkpoint and return top-k candidates.
 The adapter accepts an already cropped square icon only. It rejects
 partial cards and never downloads weights or writes business data.
============================================================
"""
from __future__ import annotations

import json
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from PIL import Image

try:
    import paddle
except Exception:  # pragma: no cover - optional dependency
    paddle = None  # type: ignore[assignment]

from nn_training_lab.scripts.train_equipment_icon_classifier import IconClassifier, image_to_tensor


@dataclass(frozen=True)
class NNCandidate:
    """One neural-network candidate."""

    equipment_name: str
    confidence: float
    rank: int
    # 当前 data/equipment_library.csv 的运行时映射，不是模型类别身份。
    equipment_id: str = ""


@dataclass(frozen=True)
class NNInferenceResult:
    """Serializable NN inference response."""

    status: str
    message: str
    candidates: tuple[NNCandidate, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly response."""
        return {
            "status": self.status,
            "message": self.message,
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


class EquipmentIconNN:
    """Lazy local checkpoint wrapper used as an OpenCV fallback."""

    def __init__(
        self,
        model_dir: str | Path,
        dataset_dir: str | Path,
        equipment_library_path: str | Path | None = None,
    ) -> None:
        """Create an unloaded adapter for one checkpoint directory.

        ``equipment_name`` is the model's stable class identity.  The library
        path is only consulted after prediction to expose the currently known
        ``equipment_id`` alias; changing an ID therefore does not require
        retraining the classifier.
        """
        self.model_dir = Path(model_dir)
        self.dataset_dir = Path(dataset_dir)
        self._model: Optional[Any] = None
        self.equipment_library_path = (
            Path(equipment_library_path)
            if equipment_library_path is not None
            else self.dataset_dir.resolve().parents[2] / "data" / "equipment_library.csv"
        )
        self._index_to_name: Dict[int, str] = {}
        self._name_to_id: Dict[str, str] = {}
        self._load_error = ""
        self._device_warning = ""

    def check_status(self) -> Dict[str, Any]:
        """Report dependency/checkpoint availability without loading weights."""
        label_map_exists = (self.model_dir / "label_map.json").exists()
        dataset_manifest_exists = (self.dataset_dir / "dataset_manifest.csv").exists()
        label_count = 0
        label_schema_ok = False
        if label_map_exists:
            try:
                payload = json.loads((self.model_dir / "label_map.json").read_text(encoding="utf-8"))
                name_to_index = payload.get("name_to_index", {})
                index_to_name = payload.get("index_to_name", {})
                id_to_index = payload.get("id_to_index", {})
                index_to_id = payload.get("index_to_id", {})
                label_count = len(name_to_index or id_to_index)
                label_schema_ok = bool(
                    (name_to_index and len(name_to_index) == len(index_to_name))
                    or (id_to_index and len(id_to_index) == len(index_to_id))
                )
            except (OSError, TypeError, ValueError):
                label_schema_ok = False
        return {
            "available": bool(
                paddle is not None
                and (self.model_dir / "best.pdparams").exists()
                and label_map_exists
                and dataset_manifest_exists
                and label_schema_ok
            ),
            "paddle_available": paddle is not None,
            "model_dir": str(self.model_dir),
            "checkpoint_exists": (self.model_dir / "best.pdparams").exists(),
            "label_map_exists": label_map_exists,
            "label_map_entries": label_count,
            "label_map_schema_ok": label_schema_ok,
            "dataset_manifest_exists": dataset_manifest_exists,
            "load_error": self._load_error,
            "device_warning": self._device_warning,
        }

    def predict_file(self, image_path: str | Path, top_k: int = 3) -> NNInferenceResult:
        """Predict a cropped square icon; reject full/partial card images."""
        if paddle is None:
            return NNInferenceResult("unavailable", "Paddle is not installed; NN fallback is disabled.")
        path = Path(image_path)
        if not path.exists() or not path.is_file():
            return NNInferenceResult("error", f"Icon file does not exist: {path}")
        try:
            with Image.open(path) as image:
                width, height = image.size
                if width != height or width < 64 or height < 64:
                    return NNInferenceResult("rejected", "Input is not a complete square icon; partial cards are rejected.")
                image.load()
        except (OSError, ValueError) as exc:
            return NNInferenceResult("error", f"Icon cannot be read: {exc}")
        if not self._ensure_loaded():
            return NNInferenceResult("unavailable", self._load_error or "NN checkpoint is unavailable.")
        try:
            tensor = paddle.to_tensor(image_to_tensor(path, training=False)[None, ...])
            with paddle.no_grad():
                logits = self._model(tensor)
                probabilities = paddle.nn.functional.softmax(logits, axis=1)[0]
                values, indices = paddle.topk(probabilities, k=min(max(1, int(top_k)), probabilities.shape[0]))
            candidates = tuple(
                NNCandidate(
                    equipment_name=self._index_to_name[int(index)],
                    confidence=float(value),
                    rank=rank,
                    equipment_id=self._name_to_id.get(self._index_to_name[int(index)], ""),
                )
                for rank, (value, index) in enumerate(zip(values.numpy(), indices.numpy()), start=1)
            )
            return NNInferenceResult("success", "NN top-k candidates generated.", candidates)
        except Exception as exc:  # pragma: no cover - backend-specific errors
            return NNInferenceResult("error", f"NN inference failed: {exc}")

    def _ensure_loaded(self) -> bool:
        """Load the local model once; never download anything."""
        if self._model is not None:
            return True
        checkpoint = self.model_dir / "best.pdparams"
        label_map_path = self.model_dir / "label_map.json"
        if not checkpoint.exists() or not label_map_path.exists():
            self._load_error = "best.pdparams or label_map.json is missing."
            return False
        try:
            payload = json.loads(label_map_path.read_text(encoding="utf-8"))
            if payload.get("name_to_index") and payload.get("index_to_name"):
                self._index_to_name = {
                    int(index): str(name)
                    for index, name in payload["index_to_name"].items()
                }
            else:
                # 兼容旧 ID 标签 checkpoint；名称仍是对外输出字段。
                legacy_index_to_id = {
                    int(index): str(equipment_id)
                    for index, equipment_id in payload["index_to_id"].items()
                }
                manifest_names: Dict[str, str] = {}
                with (self.dataset_dir / "dataset_manifest.csv").open("r", encoding="utf-8-sig", newline="") as handle:
                    for row in csv.DictReader(handle):
                        manifest_names.setdefault(row["equipment_id"], row["equipment_name"])
                self._index_to_name = {
                    index: manifest_names.get(equipment_id, equipment_id)
                    for index, equipment_id in legacy_index_to_id.items()
                }
            if self.equipment_library_path.is_file():
                with self.equipment_library_path.open("r", encoding="utf-8-sig", newline="") as handle:
                    for row in csv.DictReader(handle):
                        name = str(row.get("name", "")).strip()
                        equipment_id = str(row.get("equipment_id", "")).strip()
                        if name and equipment_id:
                            self._name_to_id.setdefault(name, equipment_id)
            if not self._name_to_id:
                with (self.dataset_dir / "dataset_manifest.csv").open("r", encoding="utf-8-sig", newline="") as handle:
                    for row in csv.DictReader(handle):
                        self._name_to_id.setdefault(row["equipment_name"], row["equipment_id"])
            self._select_device()
            model = IconClassifier(len(self._index_to_name))
            model.set_state_dict(paddle.load(str(checkpoint)))
            model.eval()
            self._model = model
            return True
        except Exception as exc:  # pragma: no cover - backend-specific errors
            self._load_error = str(exc)
            return False

    def _select_device(self) -> None:
        """Use GPU only when a tiny kernel probe succeeds; otherwise use CPU."""
        if paddle is None or not paddle.is_compiled_with_cuda():
            paddle.set_device("cpu")
            return
        try:
            paddle.set_device("gpu")
            probe = paddle.ones([2], dtype="float32")
            paddle.nn.functional.dropout(probe, p=0.1, training=True)
        except Exception as exc:  # pragma: no cover - depends on CUDA wheel/GPU.
            paddle.set_device("cpu")
            self._device_warning = f"GPU probe failed; NN inference fell back to CPU: {exc}"


def should_use_nn_fallback(status: str, confidence: float, threshold: float = 0.82, margin: float = 0.025) -> bool:
    """Decide whether OpenCV's result warrants NN candidate assistance."""
    return status in {"unknown", "ambiguous"} or confidence < threshold or margin < 0.025
