#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║             Recognition pipeline audit                      ║
║  检查 OpenCV 图库、OCR/NN 模型文件、标签映射与测试输出。     ║
║  只读分析输入；审计 JSON/CSV 写入指定测试 run 目录。          ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


DEFAULT_SUPPLEMENTAL_GALLERIES = (
    "nn_training_lab/archive/equipment_icon_matcher_v2/reviewed_icon_gallery/reviewed_icon_gallery_manifest.csv",
    "nn_training_lab/archive/equipment_icon_matcher_v2/accepted_icon_gallery/accepted_icon_gallery_manifest.csv",
)


# ============================================================
# 🧰 第二部分：通用读取与路径工具
# ============================================================

def find_project_root(start: Path) -> Path:
    """Locate the project root from the script or current directory."""
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / "data" / "equipment_library.csv").exists():
            return candidate
    raise RuntimeError("Cannot find project root: data/equipment_library.csv is missing.")


def read_csv(path: Path) -> List[Dict[str, str]]:
    """Read a UTF-8-SIG CSV file; missing files return an empty list."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def resolve_path(root: Path, raw_path: str | Path) -> Path:
    """Resolve a relative project path without changing the source file."""
    path = Path(raw_path)
    return path if path.is_absolute() else root / path


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write an audit payload as stable UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def latest_model_dir(root: Path) -> Path:
    """Find the best complete local NN checkpoint without downloading anything.

    A newer experiment can be worse than an older one, so validation top-1 is
    preferred; modification time is only the tie-breaker. Incomplete runs
    remain in the directory but are never selected.
    """
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


# ============================================================
# 🔍 第三部分：图库与 NN 审计
# ============================================================

def audit_gallery(root: Path, gallery_paths: Sequence[str | Path]) -> Dict[str, Any]:
    """Audit row counts, valid image paths and ID coverage for each gallery source."""
    sources: List[Dict[str, Any]] = []
    all_ids: set[str] = set()
    valid_ids: set[str] = set()
    valid_rows = 0
    for raw_path in gallery_paths:
        path = resolve_path(root, raw_path)
        rows = read_csv(path)
        valid = 0
        ids: set[str] = set()
        missing: List[Dict[str, str]] = []
        for row in rows:
            equipment_id = str(row.get("equipment_id", "") or "").strip()
            image_value = str(row.get("image_path", "") or "").strip()
            if equipment_id:
                ids.add(equipment_id)
                all_ids.add(equipment_id)
            image_path = resolve_path(root, image_value) if image_value else Path()
            if equipment_id and image_value and image_path.is_file():
                valid += 1
                valid_rows += 1
                valid_ids.add(equipment_id)
            elif equipment_id and image_value:
                missing.append({"equipment_id": equipment_id, "image_path": str(image_path)})
        sources.append({
            "path": str(path),
            "exists": path.is_file(),
            "rows": len(rows),
            "unique_equipment_ids": len(ids),
            "valid_image_rows": valid,
            "missing_image_rows": missing,
        })
    return {
        "sources": sources,
        "union_equipment_ids": len(all_ids),
        "union_valid_equipment_ids": len(valid_ids),
        "union_missing_equipment_ids": sorted(all_ids - valid_ids),
        "union_valid_image_rows": valid_rows,
    }


def audit_nn(root: Path, model_dir: Path, dataset_dir: Path, official_ids: Iterable[str]) -> Dict[str, Any]:
    """Audit checkpoint files and manifest/label-map consistency."""
    manifest_rows = read_csv(dataset_dir / "dataset_manifest.csv")
    manifest_ids = {str(row.get("equipment_id", "") or "").strip() for row in manifest_rows if row.get("equipment_id")}
    label_path = model_dir / "label_map.json"
    label_ids: set[str] = set()
    label_names: set[str] = set()
    label_payload: Dict[str, Any] = {}
    if label_path.exists():
        try:
            label_payload = json.loads(label_path.read_text(encoding="utf-8"))
            label_ids = {str(value) for value in label_payload.get("index_to_id", {}).values()}
            label_names = {str(value) for value in label_payload.get("index_to_name", {}).values()}
        except (OSError, ValueError, TypeError):
            label_payload = {}
    official = {str(item) for item in official_ids if str(item)}
    return {
        "model_dir": str(model_dir),
        "best_checkpoint_exists": (model_dir / "best.pdparams").is_file(),
        "label_map_exists": label_path.is_file(),
        "dataset_manifest_exists": (dataset_dir / "dataset_manifest.csv").is_file(),
        "dataset_rows": len(manifest_rows),
        "dataset_classes": len(manifest_ids),
        "label_classes": len(label_names or label_ids),
        "dataset_ids_without_label": sorted(manifest_ids - label_ids),
        "label_ids_without_dataset": sorted(label_ids - manifest_ids),
        "official_ids_without_nn_label": sorted(official - label_ids),
        "nn_labels_not_in_official_gallery": sorted(label_ids - official),
        "label_names_not_in_dataset": sorted(label_names - {str(row.get("equipment_name", "")).strip() for row in manifest_rows}),
        "label_map_schema_ok": bool(
            (label_payload.get("name_to_index") and label_payload.get("index_to_name"))
            or (label_payload.get("id_to_index") and label_payload.get("index_to_id"))
        ),
    }


# ============================================================
# 📊 第四部分：流水线输出与人工标注对照
# ============================================================

def audit_run(run_dir: Path, manual_csv: Optional[Path], library_csv: Path) -> Dict[str, Any]:
    """Audit one screenshot-pipeline run and optionally compare accepted names."""
    rows = read_csv(run_dir / "screenshot_pipeline_results.csv")
    manual_rows = read_csv(manual_csv) if manual_csv else []
    name_by_key = {
        (str(row.get("filename", "") or "").strip(), str(row.get("card_no", "") or "").strip()): str(row.get("accepted_equipment_name", "") or "").strip()
        for row in manual_rows
        if row.get("accepted_equipment_name")
    }
    library_names = {
        str(row.get("name", "") or "").strip()
        for row in read_csv(library_csv)
        if row.get("name")
    }
    manual_comparisons: List[Dict[str, Any]] = []
    for row in rows:
        key = (str(row.get("filename", "") or "").strip(), str(row.get("card_no", "") or "").strip())
        expected = name_by_key.get(key, "")
        if expected and row.get("visibility") == "full":
            actual = str(row.get("final_equipment_name", "") or "").strip()
            manual_comparisons.append({
                "filename": key[0],
                "card_no": key[1],
                "expected_name": expected,
                "actual_name": actual,
                "exact": expected == actual,
            })
    full_rows = [row for row in rows if row.get("visibility") == "full"]
    review_rows = [row for row in full_rows if row.get("final_status") == "unknown"]
    return {
        "run_dir": str(run_dir),
        "rows": len(rows),
        "full_cards": len(full_rows),
        "status_counts": dict(Counter(str(row.get("final_status", "")) for row in rows)),
        "opencv_status_counts": dict(Counter(str(row.get("opencv_status", "")) for row in rows)),
        "ocr_status_counts": dict(Counter(str(row.get("ocr_status", "")) for row in rows)),
        "name_ocr_status_counts": dict(Counter(str(row.get("name_ocr_status", "")) for row in rows)),
        "nn_status_counts": dict(Counter(str(row.get("nn_status", "")) for row in rows)),
        "needs_review": [
            {
                "filename": row.get("filename", ""),
                "card_no": row.get("card_no", ""),
                "opencv_top_candidates": row.get("opencv_top_candidates", ""),
                "name_ocr_text": row.get("name_ocr_text", ""),
                "name_resolve_equipment_name": row.get("name_resolve_equipment_name", ""),
                "nn_top_candidates": row.get("nn_top_candidates", ""),
                "warnings": row.get("warnings", ""),
            }
            for row in review_rows
        ],
        "manual_comparison": {
            "available": bool(manual_csv and manual_csv.is_file()),
            "path": str(manual_csv) if manual_csv else "",
            "compared": len(manual_comparisons),
            "exact": sum(1 for item in manual_comparisons if item["exact"]),
            "mismatches": [item for item in manual_comparisons if not item["exact"]],
        },
        "library_name_rows": len(library_names),
    }


def audit(root: Path, run_dir: Path, manual_csv: Optional[Path], model_dir: Path) -> Dict[str, Any]:
    """Run all read-only audits and return one serializable report."""
    config_path = root / "config" / "recognition" / "roi_config.json"
    config: Dict[str, Any] = {}
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    equipment_config = config.get("equipment_icon_matching", {})
    gallery_paths = [equipment_config.get("gallery_csv_path", "data/equipment_images.csv")]
    gallery_paths.extend(equipment_config.get("supplemental_gallery_csv_paths", DEFAULT_SUPPLEMENTAL_GALLERIES))
    gallery = audit_gallery(root, gallery_paths)
    official_ids = {
        str(row.get("equipment_id", "") or "").strip()
        for row in read_csv(root / "data" / "equipment_images.csv")
        if row.get("equipment_id")
    }
    return {
        "schema_version": "0.6.0-audit",
        "gallery": gallery,
        "nn": audit_nn(
            root,
            model_dir,
            root / "nn_training_lab" / "training_sets" / "equipment_icon_nn_dataset",
            official_ids,
        ),
        "pipeline": audit_run(
            run_dir,
            manual_csv,
            root / "data" / "equipment_library.csv",
        ),
        "warning": "Audit metrics describe these local files and screenshots only; they are not a general accuracy claim.",
    }


# ============================================================
# 🚀 第五部分：命令行入口
# ============================================================

def parse_args() -> argparse.Namespace:
    """Parse audit command-line arguments."""
    root = find_project_root(Path(__file__))
    default_run = root / "nn_training_lab" / "screenshot_pipeline" / "test_out"
    parser = argparse.ArgumentParser(description="Audit OpenCV/OCR/NN local recognition inputs and one pipeline run.")
    parser.add_argument("--run-dir", type=Path, required=True, help="screenshot_pipeline run directory")
    parser.add_argument("--manual-csv", type=Path, default=None, help="Optional accepted-name CSV for exact comparison")
    parser.add_argument("--model-dir", type=Path, default=None, help="Optional local NN checkpoint directory")
    parser.add_argument("--output", type=Path, default=None, help="Audit JSON path; defaults to run-dir/recognition_audit.json")
    parser.add_argument("--root", type=Path, default=root, help=argparse.SUPPRESS)
    parser.set_defaults(default_run=default_run)
    return parser.parse_args()


def main() -> int:
    """Run the audit and write JSON beside the selected run."""
    args = parse_args()
    root = args.root.resolve()
    run_dir = args.run_dir.resolve()
    model_dir = (
        args.model_dir.resolve()
        if args.model_dir is not None
        else latest_model_dir(root)
    )
    manual_csv = args.manual_csv.resolve() if args.manual_csv is not None else None
    report = audit(root, run_dir, manual_csv, model_dir)
    output = args.output.resolve() if args.output is not None else run_dir / "recognition_audit.json"
    write_json(output, report)
    print(json.dumps({"output": str(output), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
