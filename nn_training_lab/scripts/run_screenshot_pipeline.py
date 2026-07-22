#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================
 Full screenshot recognition pipeline
 ------------------------------------------------------------
 screenshot -> card/ROI detection -> OpenCV icon match and OCR
 -> NN fallback for uncertain icons -> annotated PNG + CSV/JSON.

 This workbench never writes formal equipment data. Partial cards are
 reported and rejected before recognition, while NN candidates are only
 accepted when they agree with a usable OpenCV result.
============================================================
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import cv2 as _cv2
except Exception:  # pragma: no cover - optional dependency fallback
    _cv2 = None

from core.recognition.design_fragment_detector import DesignFragmentCardCandidate, DesignFragmentDetector
from core.recognition.equipment_card_reader import EquipmentCardDigitReader
from core.recognition.equipment_icon_matcher import EquipmentIconMatcher
from core.recognition.equipment_name_resolver import EquipmentNameResolver
from core.recognition.ocr_engine import OcrEngine
from core.recognition.preview_renderer import TextOperation, draw_unicode_labels
from nn_training_lab.inference.equipment_icon_nn import EquipmentIconNN, should_use_nn_fallback


RoiRegion = Tuple[int, int, int, int]
RARITY_ALIASES = {
    "common": "common",
    "white": "common",
    "rare": "rare",
    "blue": "rare",
    "elite": "elite",
    "purple": "elite",
    "super_rare": "super_rare",
    "superrare": "super_rare",
    "gold": "super_rare",
    "ultra_rare": "ultra_rare",
    "ultrarare": "ultra_rare",
    "rainbow": "ultra_rare",
    "彩": "ultra_rare",
}
CSV_FIELDS = (
    "filename", "rarity", "card_no", "detected_index", "visibility", "bbox", "icon_roi", "name_roi", "quantity_roi",
    "opencv_status", "opencv_equipment_id", "opencv_equipment_name", "opencv_confidence", "opencv_top_candidates",
    "name_ocr_status", "name_ocr_text", "name_ocr_confidence", "name_resolve_status", "name_resolve_equipment_id",
    "name_resolve_equipment_name", "name_resolve_score", "name_resolve_candidates",
    "nn_invoked", "nn_status", "nn_equipment_id", "nn_equipment_name", "nn_confidence", "nn_top_candidates",
    "final_status", "final_equipment_id", "final_equipment_name", "recognition_source",
    "ocr_status", "fragment_count", "required_count", "ocr_confidence", "ocr_text", "warnings",
)

NAME_RATIO = (0.385, 0.040, 0.350, 0.235)


def read_json(path: Path, default: Mapping[str, Any]) -> Dict[str, Any]:
    """Read optional JSON configuration without turning a missing file into a crash."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return dict(default)


def load_equipment_names(path: Path) -> Dict[str, str]:
    """Load ID-to-name mapping for human-readable output."""
    names: Dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                equipment_id = str(row.get("equipment_id", "")).strip()
                name = str(row.get("name", "")).strip()
                if equipment_id and name:
                    names[equipment_id] = name
    except OSError:
        pass
    return names


def infer_rarity(filename: str) -> str:
    """Infer rarity from a filename token; unknown is allowed and never guessed."""
    lowered = filename.lower()
    tokens = re.split(r"[^a-z0-9_]+", lowered)
    for token in tokens:
        if token in RARITY_ALIASES:
            return RARITY_ALIASES[token]
    for alias, rarity in sorted(RARITY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in lowered:
            return rarity
    return "unknown"


def relative_child_roi(parent: RoiRegion, child: RoiRegion) -> RoiRegion:
    """Convert an absolute child ROI to coordinates relative to its card."""
    px, py, _, _ = parent
    cx, cy, cw, ch = child
    return cx - px, cy - py, cw, ch


def write_png(path: Path, image: Any) -> None:
    """Write PNG safely on Windows paths."""
    if _cv2 is None:
        raise RuntimeError("OpenCV is unavailable; cannot write an annotated preview.")
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = _cv2.imencode(".png", image)
    if not ok:
        raise ValueError(f"Unable to encode PNG: {path}")
    encoded.tofile(str(path))


def latest_model_dir(root: Path) -> Path:
    """Find the best complete local NN checkpoint without downloading anything."""
    checkpoint_root = root / "nn_training_lab" / "models" / "checkpoints"
    candidates: list[tuple[float, float, Path]] = []
    for run in checkpoint_root.glob("run_*"):
        if not (run / "best.pdparams").is_file() or not (run / "label_map.json").is_file():
            continue
        score = -1.0
        summary = run / "training_summary.json"
        if summary.is_file():
            try:
                score = float(json.loads(summary.read_text(encoding="utf-8")).get("best_validation_top1", -1.0))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                score = -1.0
        candidates.append((score, run.stat().st_mtime, run))
    if candidates:
        return max(candidates, key=lambda item: (item[0], item[1]))[2]
    return checkpoint_root / "missing_run"


def candidate_text(candidates: Sequence[Mapping[str, Any]]) -> str:
    """Flatten top-k candidates into a compact CSV cell."""
    return " | ".join(
        f"{item.get('equipment_id', '')}:{float(item.get('confidence', 0.0)):.3f}"
        for item in candidates
    )


def nn_text(candidates: Sequence[Any]) -> str:
    """Flatten NN dataclass candidates into a compact CSV cell."""
    return " | ".join(f"{item.equipment_id}:{item.confidence:.3f}" for item in candidates)


def name_roi_for_candidate(candidate: DesignFragmentCardCandidate) -> RoiRegion:
    """Return the card-relative equipment-name ROI used by the v2 OCR path."""
    x, y, width, height = candidate.bbox
    rel_x, rel_y, rel_width, rel_height = NAME_RATIO
    return (
        x + int(round(width * rel_x)),
        y + int(round(height * rel_y)),
        max(1, int(round(width * rel_width))),
        max(1, int(round(height * rel_height))),
    )


def format_name_candidates(candidates: Sequence[Mapping[str, Any]]) -> str:
    """Flatten resolver top-k candidates into a compact JSON-safe CSV value."""
    return " | ".join(
        f"{item.get('equipment_id', '')}:{item.get('equipment_name', '')}:{float(item.get('score', 0.0) or 0.0):.3f}"
        for item in candidates
    )


def choose_final_result(
    opencv: Mapping[str, Any],
    nn_result: Optional[Any],
    names: Mapping[str, str],
    opencv_threshold: float,
    nn_min_confidence: float,
    nn_min_margin: float,
    name_result: Optional[Mapping[str, Any]] = None,
    name_min_confidence: float = 0.55,
    name_override_icon_confidence: float = 0.90,
) -> Tuple[str, str, str, str, List[str]]:
    """Combine OpenCV, name OCR and NN without allowing weak evidence to guess."""
    warnings: List[str] = []
    opencv_status = str(opencv.get("status", ""))
    opencv_id = str(opencv.get("equipment_id", "") or "")
    opencv_confidence = float(opencv.get("confidence", 0.0) or 0.0)
    opencv_usable = opencv_status == "success" and opencv_id not in {"", "unknown"} and opencv_confidence >= opencv_threshold
    name_payload = name_result or {}
    name_id = str(name_payload.get("equipment_id", "") or "")
    name_success = bool(name_payload.get("success") is True and name_id not in {"", "unknown"})
    name_confidence = float(name_payload.get("ocr_confidence", 0.0) or 0.0)
    name_score = float(name_payload.get("score", 0.0) or 0.0)
    name_status = str(name_payload.get("status", "") or "")
    candidate_ids = {
        str(item.get("equipment_id", "") or "")
        for item in opencv.get("candidates", ())
        if str(item.get("equipment_id", "") or "")
    }
    name_exact_like = (
        "exact" in name_status
        or name_score >= 0.965
        or ("contains" in name_status and name_score >= 0.90)
    )
    name_usable = bool(
        name_success
        and name_confidence >= float(name_min_confidence)
        and (name_id in candidate_ids or name_exact_like)
    )
    nn_candidates = tuple(getattr(nn_result, "candidates", ()) if nn_result is not None else ())
    nn_top = nn_candidates[0] if nn_candidates else None
    if name_usable:
        if opencv_usable and opencv_id == name_id:
            return opencv_id, names.get(opencv_id, name_payload.get("equipment_name", "")), "opencv_name_agree", "success", warnings
        if opencv_status in {"ambiguous", "unknown", ""} or (
            opencv_usable and opencv_confidence < float(name_override_icon_confidence)
        ):
            warnings.append("High-confidence equipment-name OCR resolved the icon candidate.")
            return name_id, names.get(name_id, str(name_payload.get("equipment_name", ""))), "name_ocr", "success", warnings
    if nn_top is not None and opencv_usable and nn_top.equipment_id == opencv_id:
        return opencv_id, names.get(opencv_id, nn_top.equipment_name), "opencv_nn_agree", "success", warnings
    if opencv_usable:
        return opencv_id, names.get(opencv_id, ""), "opencv", "success", warnings
    if nn_top is not None:
        nn_margin = nn_top.confidence - (nn_candidates[1].confidence if len(nn_candidates) > 1 else 0.0)
        if nn_top.confidence < nn_min_confidence or nn_margin < nn_min_margin:
            warnings.append("NN candidate confidence or margin is too low; kept unknown.")
        elif opencv_id and opencv_id != "unknown":
            if nn_top.equipment_id == opencv_id:
                return nn_top.equipment_id, names.get(nn_top.equipment_id, nn_top.equipment_name), "opencv_nn_agree", "success", warnings
            warnings.append("OpenCV and NN disagree; kept unknown.")
        else:
            warnings.append("NN-only suggestion is not auto-accepted without an OpenCV candidate.")
    if opencv_status in {"ambiguous", "unknown"}:
        warnings.append(f"OpenCV status={opencv_status}; manual review is required.")
    return "", "", "needs_review", "unknown", warnings


def annotate_image(
    image: Any,
    detection: Any,
    rows: Sequence[Mapping[str, Any]],
) -> Any:
    """Draw card, icon, quantity and decision labels on the source screenshot."""
    if _cv2 is None:
        return image
    annotated = image.copy()
    row_by_index = {int(row.get("detected_index", -1)): row for row in rows}
    text_operations: List[TextOperation] = []
    for candidate in detection.candidates:
        row = row_by_index.get(candidate.index, {})
        x, y, width, height = candidate.bbox
        final_status = str(row.get("final_status", "partial"))
        if candidate.visibility != "full":
            color = (0, 165, 255)
        elif final_status == "success":
            color = (60, 210, 60)
        elif final_status == "unknown":
            color = (0, 0, 255)
        else:
            color = (180, 180, 180)
        _cv2.rectangle(annotated, (x, y), (x + width, y + height), color, 2)
        ix, iy, iw, ih = candidate.icon_roi
        nx, ny, nw, nh = name_roi_for_candidate(candidate)
        qx, qy, qw, qh = candidate.quantity_roi
        _cv2.rectangle(annotated, (ix, iy), (ix + iw, iy + ih), (255, 180, 0), 1)
        _cv2.rectangle(annotated, (nx, ny), (nx + nw, ny + nh), (180, 80, 220), 1)
        _cv2.rectangle(annotated, (qx, qy), (qx + qw, qy + qh), (255, 255, 0), 1)
        card_no = int(row.get("card_no", candidate.index) or candidate.index)
        final_id = str(row.get("final_equipment_id", "") or "unknown")
        final_name = str(row.get("final_equipment_name", "") or "")
        source = str(row.get("recognition_source", ""))
        label = f"card{card_no:02d} {final_name or final_id} {source}"
        stages = f"cv={row.get('opencv_status', '')} name={row.get('name_ocr_status', '')} ocr={row.get('ocr_status', '')} nn={row.get('nn_status', '')}"
        text_operations.append((label[:48], (x + 4, max(18, y + 18)), color, 15.0))
        text_operations.append((stages[:76], (x + 4, max(34, y + 34)), color, 12.0))
    text_operations.append(
        (
            f"pipeline cards={len(detection.candidates)} full={sum(c.visibility == 'full' for c in detection.candidates)}",
            (20, 90),
            (0, 255, 255),
            20.0,
        )
    )
    return draw_unicode_labels(annotated, text_operations)


def process_image(
    image_path: Path,
    output_dir: Path,
    detector: DesignFragmentDetector,
    reader: Optional[EquipmentCardDigitReader],
    matcher: Optional[EquipmentIconMatcher],
    nn_detector: Optional[EquipmentIconNN],
    names: Mapping[str, str],
    name_resolver: Optional[EquipmentNameResolver],
    name_config: Mapping[str, Any],
    opencv_threshold: float,
    nn_min_confidence: float,
    nn_min_margin: float,
    disable_nn: bool,
    image_mode: str,
    write_preview: bool = True,
) -> Dict[str, Any]:
    """Process one screenshot and return its JSON payload."""
    rarity = infer_rarity(image_path.name)
    detection = detector.detect(image_path, image_mode=image_mode)
    payload: Dict[str, Any] = {
        "filename": image_path.name,
        "screenshot_path": str(image_path),
        "rarity": rarity,
        "detection": detection.to_dict(),
        "annotated_output": "",
        "cards": [],
        "warnings": [],
    }
    if not detection.success:
        payload["warnings"] = [detection.message]
        return payload
    image = detector.load_image(image_path)
    icon_dir = output_dir / "icon_crops"
    rows: List[Dict[str, Any]] = []
    for candidate in detection.candidates:
        base: Dict[str, Any] = {
            "filename": image_path.name,
            "rarity": rarity,
            "card_no": candidate.index,
            "detected_index": candidate.index,
            "visibility": candidate.visibility,
            "bbox": list(candidate.bbox),
            "icon_roi": list(candidate.icon_roi),
            "name_roi": list(name_roi_for_candidate(candidate)),
            "quantity_roi": list(candidate.quantity_roi),
            "opencv_status": "skipped",
            "opencv_equipment_id": "",
            "opencv_equipment_name": "",
            "opencv_confidence": 0.0,
            "opencv_top_candidates": "",
            "name_ocr_status": "skipped",
            "name_ocr_text": "",
            "name_ocr_confidence": 0.0,
            "name_resolve_status": "skipped",
            "name_resolve_equipment_id": "",
            "name_resolve_equipment_name": "",
            "name_resolve_score": 0.0,
            "name_resolve_candidates": "",
            "nn_invoked": False,
            "nn_status": "skipped",
            "nn_equipment_id": "",
            "nn_equipment_name": "",
            "nn_confidence": 0.0,
            "nn_top_candidates": "",
            "final_status": "rejected_partial" if candidate.visibility != "full" else "unknown",
            "final_equipment_id": "",
            "final_equipment_name": "",
            "recognition_source": "partial_rejected" if candidate.visibility != "full" else "needs_review",
            "ocr_status": "skipped",
            "fragment_count": "",
            "required_count": "",
            "ocr_confidence": 0.0,
            "ocr_text": "",
            "warnings": [],
        }
        if candidate.visibility != "full":
            base["warnings"] = ["Partial card rejected; icon and quantities were not recognized."]
            rows.append(base)
            continue

        if reader is not None:
            quantity = reader.read_fragment_counts(
                image,
                card_roi=candidate.bbox,
                quantity_roi=relative_child_roi(candidate.bbox, candidate.quantity_roi),
            ).to_dict()
            base.update({
                "ocr_status": quantity.get("status", ""),
                "fragment_count": quantity.get("fragment_count", ""),
                "required_count": quantity.get("required_count", ""),
                "ocr_confidence": quantity.get("confidence", 0.0),
                "ocr_text": quantity.get("text", ""),
            })
        if matcher is not None:
            icon_result = matcher.match_icon(image, icon_roi=candidate.icon_roi, top_n=5).to_dict()
            opencv_id = str(icon_result.get("equipment_id", "") or "")
            base.update({
                "opencv_status": icon_result.get("status", ""),
                "opencv_equipment_id": opencv_id,
                "opencv_equipment_name": names.get(opencv_id, ""),
                "opencv_confidence": float(icon_result.get("confidence", 0.0) or 0.0),
                "opencv_top_candidates": candidate_text(icon_result.get("candidates", [])),
            })
        else:
            icon_result = {"status": "skipped", "equipment_id": "", "confidence": 0.0, "candidates": []}

        name_result: Dict[str, Any] = {
            "success": False,
            "status": "disabled",
            "equipment_id": "",
            "equipment_name": "",
            "score": 0.0,
            "ocr_confidence": 0.0,
        }
        enable_name_ocr = bool(name_config.get("name_ocr_enabled", True))
        if reader is not None and name_resolver is not None and enable_name_ocr:
            name_ocr = reader.ocr_engine.recognize_text(
                image,
                roi=name_roi_for_candidate(candidate),
                confidence_threshold=float(name_config.get("name_ocr_confidence_threshold", 0.55)),
                preprocess=False,
            )
            if not name_ocr.success:
                name_ocr = reader.ocr_engine.recognize_text(
                    image,
                    roi=name_roi_for_candidate(candidate),
                    confidence_threshold=float(name_config.get("name_ocr_confidence_threshold", 0.55)),
                    preprocess=True,
                )
            name_payload = name_ocr.to_dict()
            candidate_ids = [
                str(item.get("equipment_id", "") or "")
                for item in icon_result.get("candidates", [])
                if str(item.get("equipment_id", "") or "")
            ]
            if name_ocr.success:
                resolution = name_resolver.resolve(
                    name_ocr.text,
                    candidate_equipment_ids=candidate_ids,
                    min_score=float(name_config.get("name_resolve_min_score", 0.66)),
                ).to_dict()
                name_result = {
                    **resolution,
                    "ocr_status": name_ocr.status,
                    "ocr_text": name_ocr.text,
                    "ocr_confidence": float(name_ocr.confidence),
                    "raw_texts": list(name_ocr.raw_texts),
                }
            else:
                name_result = {
                    **name_result,
                    "status": name_ocr.status,
                    "ocr_status": name_ocr.status,
                    "ocr_text": name_ocr.text,
                    "ocr_confidence": float(name_ocr.confidence),
                }
            base.update({
                "name_ocr_status": name_result.get("ocr_status", ""),
                "name_ocr_text": name_result.get("ocr_text", ""),
                "name_ocr_confidence": float(name_result.get("ocr_confidence", 0.0) or 0.0),
                "name_resolve_status": name_result.get("status", ""),
                "name_resolve_equipment_id": name_result.get("equipment_id", ""),
                "name_resolve_equipment_name": name_result.get("equipment_name", ""),
                "name_resolve_score": float(name_result.get("score", 0.0) or 0.0),
                "name_resolve_candidates": format_name_candidates(name_result.get("candidates", [])),
            })
        nn_result = None
        if nn_detector is not None and not disable_nn and should_use_nn_fallback(
            str(base["opencv_status"]), float(base["opencv_confidence"]), threshold=opencv_threshold,
        ):
            if _cv2 is not None:
                icon_path = icon_dir / f"{image_path.stem}_card{candidate.index:02d}_icon.png"
                ix, iy, iw, ih = candidate.icon_roi
                write_png(icon_path, image[iy:iy + ih, ix:ix + iw])
                nn_result = nn_detector.predict_file(icon_path, top_k=3)
                nn_candidates = tuple(nn_result.candidates)
                top = nn_candidates[0] if nn_candidates else None
                base.update({
                    "nn_invoked": True,
                    "nn_status": nn_result.status,
                    "nn_equipment_id": top.equipment_id if top else "",
                    "nn_equipment_name": names.get(top.equipment_id, top.equipment_name) if top else "",
                    "nn_confidence": float(top.confidence) if top else 0.0,
                    "nn_top_candidates": nn_text(nn_candidates),
                })
        final_id, final_name, source, final_status, decision_warnings = choose_final_result(
            {
                **icon_result,
                "status": base["opencv_status"],
                "equipment_id": base["opencv_equipment_id"],
                "confidence": base["opencv_confidence"],
            }, nn_result, names, opencv_threshold, nn_min_confidence, nn_min_margin,
            name_result=name_result,
            name_min_confidence=float(name_config.get("name_ocr_confidence_threshold", 0.55)),
            name_override_icon_confidence=float(name_config.get("name_override_icon_confidence", 0.90)),
        )
        base.update({
            "final_equipment_id": final_id,
            "final_equipment_name": final_name,
            "recognition_source": source,
            "final_status": final_status,
            "warnings": decision_warnings,
        })
        rows.append(base)

    if write_preview:
        annotated = annotate_image(image, detection, rows)
        annotated_path = output_dir / "annotated" / f"{image_path.stem}_pipeline.png"
        write_png(annotated_path, annotated)
        payload["annotated_output"] = str(annotated_path)
    payload["cards"] = rows
    payload["warnings"] = [warning for row in rows for warning in row.get("warnings", [])]
    return payload


def flatten_csv_rows(results: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten per-image JSON cards to CSV rows."""
    rows: List[Dict[str, Any]] = []
    for result in results:
        rows.extend(dict(row) for row in result.get("cards", []))
    return rows


def write_outputs(output_dir: Path, results: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Write aggregate JSON, CSV and summary."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "screenshot_pipeline_results.json").write_text(json.dumps(list(results), ensure_ascii=False, indent=2), encoding="utf-8")
    rows = flatten_csv_rows(results)
    with (output_dir / "screenshot_pipeline_results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: json.dumps(row.get(field), ensure_ascii=False) if isinstance(row.get(field), (list, dict)) else row.get(field, "") for field in CSV_FIELDS})
    summary = {
        "images": len(results),
        "detected_cards": len(rows),
        "full_cards": sum(row.get("visibility") == "full" for row in rows),
        "partial_rejected": sum(row.get("final_status") == "rejected_partial" for row in rows),
        "opencv_checked": sum(row.get("opencv_status") not in {"", "skipped"} for row in rows),
        "opencv_success": sum(row.get("opencv_status") == "success" for row in rows),
        "name_ocr_checked": sum(row.get("name_ocr_status") not in {"", "skipped", "disabled"} for row in rows),
        "name_ocr_success": sum(row.get("name_ocr_status") == "success" for row in rows),
        "name_ocr_assisted": sum(row.get("recognition_source") == "name_ocr" for row in rows),
        "nn_invoked": sum(bool(row.get("nn_invoked")) for row in rows),
        "final_success": sum(row.get("final_status") == "success" for row in rows),
        "needs_review": sum(row.get("final_status") == "unknown" for row in rows),
        "rarity_counts": dict(Counter(row.get("rarity", "unknown") for row in rows)),
        "warning": "This is an offline screenshot sample report, not a general accuracy claim.",
    }
    (output_dir / "screenshot_pipeline_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    """Parse pipeline options."""
    default_input = PROJECT_ROOT / "nn_training_lab" / "screenshot_pipeline" / "test_img"
    default_output = PROJECT_ROOT / "nn_training_lab" / "screenshot_pipeline" / "test_out"
    parser = argparse.ArgumentParser(description="Run full screenshot OpenCV/OCR/NN fallback pipeline.")
    parser.add_argument("--input-dir", type=Path, default=default_input)
    parser.add_argument("--output-dir", type=Path, default=default_output)
    parser.add_argument("--pattern", default="*.png", help="Input glob pattern.")
    parser.add_argument("--image-mode", default="viewport_full", choices=("viewport_full", "long_screenshot"))
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--skip-icons", action="store_true")
    parser.add_argument("--disable-nn", action="store_true")
    parser.add_argument("--nn-min-confidence", type=float, default=0.55)
    parser.add_argument("--nn-min-margin", type=float, default=0.08)
    parser.add_argument("--no-preview", action="store_true", help="Do not write annotated PNG previews.")
    parser.add_argument("--run-name", default="", help="Optional output run directory name.")
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    input_dir = args.input_dir.resolve()
    output_root = args.output_dir.resolve()
    run_name = args.run_name.strip() or time.strftime("run_%Y%m%d_%H%M%S")
    output_dir = output_root / run_name
    input_dir.mkdir(parents=True, exist_ok=True)
    image_paths = sorted(path for path in input_dir.glob(args.pattern) if path.is_file())
    if not image_paths:
        print(f"No input screenshots found: {input_dir / args.pattern}")
        write_outputs(output_dir, [])
        return 1

    config = read_json(PROJECT_ROOT / "config" / "recognition" / "roi_config.json", {})
    equipment_config = config.get("equipment_icon_matching", {}) if isinstance(config, dict) else {}
    name_config = config.get("pipeline", {}) if isinstance(config, dict) else {}
    names = load_equipment_names(PROJECT_ROOT / "data" / "equipment_library.csv")
    name_catalog = {equipment_id: {"name": name} for equipment_id, name in names.items()}
    name_resolver = EquipmentNameResolver.from_catalog(
        name_catalog,
        min_score=float(name_config.get("name_resolve_min_score", 0.66)),
    )
    detector = DesignFragmentDetector()
    reader = None if args.skip_ocr else EquipmentCardDigitReader(OcrEngine(config=config.get("ocr", {}) if isinstance(config, dict) else {}), config.get("card_digits", {}) if isinstance(config, dict) else {})
    matcher = None if args.skip_icons else EquipmentIconMatcher(config=equipment_config)
    nn_detector = None
    if not args.disable_nn and not args.skip_icons:
        nn_detector = EquipmentIconNN(latest_model_dir(PROJECT_ROOT), PROJECT_ROOT / "nn_training_lab" / "training_sets" / "equipment_icon_nn_dataset")
    threshold = float(equipment_config.get("threshold", 0.82)) if isinstance(equipment_config, dict) else 0.82
    results: List[Dict[str, Any]] = []
    for image_path in image_paths:
        result = process_image(
            image_path, output_dir, detector, reader, matcher, nn_detector, names,
            name_resolver, name_config,
            threshold, args.nn_min_confidence, args.nn_min_margin, args.disable_nn, args.image_mode,
            write_preview=not bool(args.no_preview),
        )
        results.append(result)
        print(f"{image_path.name}: detected={len(result['detection'].get('candidates', []))} cards, output={result.get('annotated_output', '')}")
    summary = write_outputs(output_dir, results)
    print(json.dumps({"output_dir": str(output_dir), **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
