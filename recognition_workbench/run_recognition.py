#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenCV + OCR + PyTorch equipment screenshot workbench.

The workbench accepts complete design-page screenshots, rejects partial cards,
and writes only test artifacts.  The PyTorch model predicts equipment_name;
equipment_id is resolved from the current equipment library after inference.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

try:
    import torch
    from PIL import Image
    from torchvision import transforms
except Exception:  # PyTorch is optional when ONNX Runtime is available.
    torch = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    transforms = None  # type: ignore[assignment]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nn_training_lab.inference.onnx_icon_classifier import OnnxEquipmentIconClassifier
from nn_training_lab.scripts.run_screenshot_pipeline import (
    EquipmentCardDigitReader,
    EquipmentIconMatcher,
    EquipmentNameResolver,
    OcrEngine,
    DesignFragmentDetector,
    load_equipment_names,
    load_rarity_equipment_ids,
    normalize_rarity_state,
    process_image,
    read_json,
    write_outputs,
)


TRANSFORM = (
    transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    if transforms is not None
    else None
)


@dataclass(frozen=True)
class PytorchCandidate:
    """One PyTorch candidate compatible with the existing pipeline adapter."""

    equipment_name: str
    confidence: float
    rank: int
    equipment_id: str = ""


@dataclass(frozen=True)
class PytorchResult:
    """Serializable result shape consumed by process_image()."""

    status: str
    message: str
    candidates: tuple[PytorchCandidate, ...] = ()


class PytorchIconAdapter:
    """Lazy local ResNet18 adapter used only for uncertain OpenCV icons."""

    def __init__(self, model_dir: Path, library_path: Path) -> None:
        """Create an adapter without loading weights until the first icon."""
        self.model_dir = model_dir
        self.library_path = library_path
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu") if torch is not None else None
        self._model: Optional[torch.nn.Module] = None
        self._index_to_name: Dict[int, str] = {}
        self._name_to_id: Dict[str, str] = {}
        self._load_error = ""

    def predict_file(self, image_path: Path, top_k: int = 3) -> PytorchResult:
        """Predict a complete square icon and reject partial/non-icon inputs."""
        path = Path(image_path)
        if not path.is_file():
            return PytorchResult("error", f"Icon file does not exist: {path}")
        if torch is None or Image is None or TRANSFORM is None:
            return PytorchResult("unavailable", "PyTorch/torchvision 当前不可用，已使用 ONNX fallback。")
        try:
            with Image.open(path) as image:
                if image.width != image.height or image.width < 64:
                    return PytorchResult("rejected", "Input is not a complete square icon.")
                tensor = TRANSFORM(image.convert("RGB")).unsqueeze(0).to(self.device)
        except (OSError, ValueError) as exc:
            return PytorchResult("error", f"Icon cannot be read: {exc}")
        if not self._ensure_loaded():
            return PytorchResult("unavailable", self._load_error or "PyTorch checkpoint unavailable.")
        try:
            with torch.no_grad():
                probabilities = torch.softmax(self._model(tensor), dim=1)[0]  # type: ignore[misc]
                values, indices = probabilities.topk(min(max(1, int(top_k)), probabilities.shape[0]))
            candidates = tuple(
                PytorchCandidate(
                    equipment_name=self._index_to_name[int(index)],
                    confidence=float(value),
                    rank=rank,
                    equipment_id=self._name_to_id.get(self._index_to_name[int(index)], ""),
                )
                for rank, (value, index) in enumerate(zip(values.cpu(), indices.cpu()), start=1)
            )
            return PytorchResult("success", "PyTorch top-k candidates generated.", candidates)
        except Exception as exc:  # pragma: no cover - backend-specific errors
            return PytorchResult("error", f"PyTorch inference failed: {exc}")

    def _ensure_loaded(self) -> bool:
        """Load local label map and checkpoint exactly once; never download."""
        if self._model is not None:
            return True
        label_path = self.model_dir / "label_map.json"
        checkpoint_path = self.model_dir / "best.pt"
        if not label_path.is_file() or not checkpoint_path.is_file():
            self._load_error = f"Missing best.pt or label_map.json in {self.model_dir}"
            return False
        try:
            from nn_training_lab.pytorch_icon_training.scripts.train_resnet_icon_classifier import build_model

            payload = json.loads(label_path.read_text(encoding="utf-8"))
            name_to_index = payload.get("name_to_index", {})
            self._index_to_name = {int(index): str(name) for name, index in name_to_index.items()}
            with self.library_path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    name = str(row.get("name", "")).strip()
                    equipment_id = str(row.get("equipment_id", "")).strip()
                    if name and equipment_id:
                        self._name_to_id.setdefault(name, equipment_id)
            model, _ = build_model(len(self._index_to_name), pretrained=False)
            checkpoint = torch.load(checkpoint_path, map_location=self.device, weights_only=False)
            model.load_state_dict(checkpoint["model"])
            self._model = model.to(self.device).eval()
            return True
        except Exception as exc:  # pragma: no cover - malformed checkpoint/backend
            self._load_error = str(exc)
            return False


def latest_model_dir(root: Path) -> Path:
    """Choose the newest complete PyTorch run, preferring validation score."""
    model_root = root / "nn_training_lab" / "pytorch_icon_training" / "models"
    candidates: List[tuple[float, float, Path]] = []
    for run in model_root.glob("run_*"):
        if not (run / "best.pt").is_file() or not (run / "label_map.json").is_file():
            continue
        score = -1.0
        summary = run / "training_summary.json"
        try:
            score = float(json.loads(summary.read_text(encoding="utf-8")).get("best_validation_top1", -1.0))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        candidates.append((score, run.stat().st_mtime, run))
    return max(candidates, key=lambda item: (item[0], item[1]))[2] if candidates else model_root / "missing_run"


def latest_onnx_dir(root: Path) -> Path:
    """Choose the newest complete ONNX export directory."""
    model_root = root / "nn_training_lab" / "deployment" / "onnx_models"
    candidates: List[tuple[float, Path]] = []
    for run in model_root.glob("run_*"):
        if (run / "equipment_icon_resnet18_fp32.onnx").is_file() and (run / "label_map.json").is_file():
            candidates.append((run.stat().st_mtime, run))
    return max(candidates, key=lambda item: item[0])[1] if candidates else model_root / "missing_run"


def parse_args() -> argparse.Namespace:
    """Parse workbench arguments."""
    default_input = PROJECT_ROOT / "recognition_workbench" / "test_img"
    default_output = PROJECT_ROOT / "recognition_workbench" / "test_out"
    parser = argparse.ArgumentParser(description="Run OpenCV + OCR + PyTorch screenshot recognition.")
    parser.add_argument("--input-dir", type=Path, default=default_input)
    parser.add_argument("--output-dir", type=Path, default=default_output)
    parser.add_argument("--pattern", default="*.png")
    parser.add_argument("--image-mode", choices=("viewport_full", "long_screenshot"), default="viewport_full")
    parser.add_argument("--model", type=Path, default=None, help="PyTorch run directory; defaults to best local run.")
    parser.add_argument("--onnx-dir", type=Path, default=None, help="ONNX export directory; defaults to latest local export.")
    parser.add_argument("--onnx-model", default="equipment_icon_resnet18_fp32.onnx")
    parser.add_argument("--nn-backend", choices=("auto", "onnx", "pytorch", "off"), default="auto")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--skip-icons", action="store_true")
    parser.add_argument("--disable-nn", action="store_true")
    parser.add_argument("--nn-min-confidence", type=float, default=0.55)
    parser.add_argument("--nn-min-margin", type=float, default=0.08)
    parser.add_argument("--nn-mode", choices=("fallback", "assist", "always"), default="fallback")
    parser.add_argument("--nn-trigger-threshold", type=float, default=0.82)
    parser.add_argument("--rarity-state", default="", help="当前截图稀有度，例如 ultra_rare；会限制图库和 NN 候选。")
    parser.add_argument("--enforce-rarity-filter", action="store_true", help="仅在已确认筛选状态时按 rarity_id 限制候选。")
    parser.add_argument("--no-preview", action="store_true", help="不生成 annotated 预览图，只输出 JSON/CSV。")
    return parser.parse_args()


def run_recognition_for_images(
    image_paths: Sequence[Path],
    run_dir: Path,
    *,
    image_mode: str = "viewport_full",
    model: Optional[Path] = None,
    onnx_dir: Optional[Path] = None,
    onnx_model: str = "equipment_icon_resnet18_fp32.onnx",
    nn_backend: str = "auto",
    skip_ocr: bool = False,
    skip_icons: bool = False,
    disable_nn: bool = False,
    nn_min_confidence: float = 0.55,
    nn_min_margin: float = 0.08,
    no_preview: bool = False,
    rarity_state: str = "",
    nn_mode: str = "fallback",
    nn_trigger_threshold: float = 0.82,
    enforce_rarity_filter: bool = False,
) -> Dict[str, Any]:
    """Run the checked recognition pipeline on an explicit screenshot list.

    This helper is intentionally small: the ordinary workbench and the ADB
    manifest consumer both share it, so their CSV/JSON contracts stay aligned.
    """
    config = read_json(PROJECT_ROOT / "config" / "recognition" / "roi_config.json", {})
    equipment_config = config.get("equipment_icon_matching", {}) if isinstance(config, dict) else {}
    pipeline_config = config.get("pipeline", {}) if isinstance(config, dict) else {}
    library_path = PROJECT_ROOT / "data" / "equipment_library.csv"
    names = load_equipment_names(library_path)
    rarity_sets = load_rarity_equipment_ids(library_path)
    normalized_rarity = normalize_rarity_state(rarity_state)
    allowed_equipment_ids = (
        rarity_sets.get(normalized_rarity, set())
        if enforce_rarity_filter and normalized_rarity != "unknown"
        else set()
    )
    name_catalog = {equipment_id: {"name": name} for equipment_id, name in names.items()}
    resolver = EquipmentNameResolver.from_catalog(name_catalog, min_score=float(pipeline_config.get("name_resolve_min_score", 0.66)))
    detector = DesignFragmentDetector()
    reader = None if skip_ocr else EquipmentCardDigitReader(OcrEngine(config=config.get("ocr", {})), config.get("card_digits", {}))
    ocr_status = (
        reader.ocr_engine.check_status()
        if reader is not None
        else {"available": False, "status": "disabled"}
    )
    matcher = None if skip_icons else EquipmentIconMatcher(config=equipment_config)
    model_dir = (model or latest_model_dir(PROJECT_ROOT)).resolve()
    resolved_onnx_dir = (onnx_dir or latest_onnx_dir(PROJECT_ROOT)).resolve()
    nn_adapter: Any = None
    resolved_backend = "off"
    if not disable_nn and not skip_icons and nn_backend != "off":
        if nn_backend in {"auto", "onnx"}:
            onnx_adapter = OnnxEquipmentIconClassifier(
                resolved_onnx_dir / onnx_model,
                resolved_onnx_dir / "label_map.json",
                library_path,
            )
            if onnx_adapter.check_status().get("available"):
                nn_adapter = onnx_adapter
                resolved_backend = "onnx"
        if nn_adapter is None and nn_backend in {"auto", "pytorch"}:
            nn_adapter = PytorchIconAdapter(model_dir, library_path)
            resolved_backend = "pytorch"
    threshold = float(equipment_config.get("threshold", 0.82))
    results: List[Dict[str, Any]] = []
    for image_path in image_paths:
        result = process_image(
            image_path, run_dir, detector, reader, matcher, nn_adapter, names, resolver,
            pipeline_config, threshold, nn_min_confidence, nn_min_margin,
            disable_nn, image_mode, write_preview=not bool(no_preview),
            rarity_override=normalized_rarity,
            allowed_equipment_ids=tuple(sorted(allowed_equipment_ids)),
            nn_mode=nn_mode,
            nn_trigger_threshold=float(nn_trigger_threshold),
        )
        results.append(result)
        print(f"{image_path.name}: detected={len(result['detection'].get('candidates', []))} cards")
    summary = write_outputs(run_dir, results)
    summary["pytorch_model"] = str(model_dir)
    summary["onnx_model_dir"] = str(resolved_onnx_dir)
    summary["nn_backend"] = resolved_backend
    summary["rarity_state"] = normalized_rarity
    summary["rarity_filter_enabled"] = bool(allowed_equipment_ids)
    summary["rarity_candidate_count"] = len(allowed_equipment_ids)
    summary["enforce_rarity_filter"] = bool(enforce_rarity_filter)
    summary["nn_mode"] = str(nn_mode)
    summary["nn_trigger_threshold"] = float(nn_trigger_threshold)
    summary["ocr_status"] = ocr_status
    (run_dir / "recognition_model.json").write_text(json.dumps({
        "backend": f"opencv+ocr+{resolved_backend}",
        "pytorch_model": str(model_dir),
        "onnx_model_dir": str(resolved_onnx_dir),
        "onnx_model": onnx_model,
        "label_key": "equipment_name",
        "rarity_state": normalized_rarity,
        "rarity_filter_enabled": bool(allowed_equipment_ids),
        "rarity_candidate_count": len(allowed_equipment_ids),
        "enforce_rarity_filter": bool(enforce_rarity_filter),
        "nn_mode": str(nn_mode),
        "nn_trigger_threshold": float(nn_trigger_threshold),
        "ocr_status": ocr_status,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    """Run the full offline recognition flow and write isolated artifacts."""
    args = parse_args()
    input_dir = args.input_dir.resolve()
    output_root = args.output_dir.resolve()
    run_dir = output_root / (args.run_name.strip() or time.strftime("run_%Y%m%d_%H%M%S"))
    image_paths = sorted(path for path in input_dir.glob(args.pattern) if path.is_file())
    if not image_paths:
        print(f"No input screenshots found: {input_dir / args.pattern}")
        return 1
    summary = run_recognition_for_images(
        image_paths,
        run_dir,
        image_mode=args.image_mode,
        model=args.model,
        onnx_dir=args.onnx_dir,
        onnx_model=args.onnx_model,
        nn_backend=args.nn_backend,
        skip_ocr=args.skip_ocr,
        skip_icons=args.skip_icons,
        disable_nn=args.disable_nn,
        nn_min_confidence=args.nn_min_confidence,
        nn_min_margin=args.nn_min_margin,
        no_preview=args.no_preview,
        rarity_state=args.rarity_state,
        nn_mode=args.nn_mode,
        nn_trigger_threshold=args.nn_trigger_threshold,
        enforce_rarity_filter=args.enforce_rarity_filter,
    )
    print(json.dumps({"output_dir": str(run_dir), **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
