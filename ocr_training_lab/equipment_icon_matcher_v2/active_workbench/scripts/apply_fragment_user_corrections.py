#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        设计图人工修正合并脚本                                ║
║                                                              ║
║  【一句话解释】把 review_all_cards_for_user.csv 里的人工修正   ║
║  合并成一份新的可训练结果，但保留原始文件不动。              ║
║  【类比理解】像把老师批改痕迹誊到一份干净的答案册。          ║
║  【数据流说明】review CSV + final CSV + equipment_library →  |
║  corrected CSV / exp / summary。                              ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import csv
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


# ============================================================
# 🧱 第二部分：路径与字段
# ============================================================

REVIEW_FIELDNAMES = [
    "review_index",
    "filename",
    "card_no",
    "current_equipment_name",
    "correct_equipment_name",
    "current_fragment_owned",
    "correct_fragment_owned",
    "current_fragment_required",
    "correct_fragment_required",
    "label_source",
    "needs_user_review",
    "machine_suggested_equipment_name",
    "icon_confidence",
    "name_ocr_text",
    "attribute_ocr_text",
    "review_reason",
    "card_crop_path",
    "annotated_source_path",
    "notes",
]

CORRECTED_FIELDNAMES = [
    "review_index",
    "filename",
    "card_no",
    "final_equipment_name",
    "final_equipment_id",
    "final_fragment_owned",
    "final_fragment_required",
    "final_label_source",
    "label_source_origin",
    "original_equipment_name",
    "user_corrected_equipment_name",
    "original_fragment_owned",
    "user_corrected_fragment_owned",
    "original_fragment_required",
    "user_corrected_fragment_required",
    "needs_user_review",
    "machine_suggested_equipment_name",
    "icon_confidence",
    "name_ocr_text",
    "attribute_ocr_text",
    "review_reason",
    "correction_applied",
    "correction_note",
]


# ============================================================
# 🧰 第三部分：基础工具
# ============================================================

def find_project_root(start: Path) -> Path:
    """
    从脚本位置向上寻找项目根目录。
    """
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "data" / "equipment_library.csv").exists():
            return candidate
    raise RuntimeError("无法定位项目根目录：未找到 data/equipment_library.csv。")


def read_csv(path: Path) -> List[Dict[str, str]]:
    """读取 UTF-8-SIG CSV。"""
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [dict(row) for row in csv.DictReader(file)]


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    """写出 UTF-8-SIG CSV。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """写出 UTF-8 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_name(value: str) -> str:
    """把名字压成更稳的匹配文本。"""
    text = str(value or "").strip().lower()
    text = text.replace("＃", "#").replace("（", "(").replace("）", ")")
    return re.sub(r"[\s\"'“”‘’，,。.:：;；/\\_\-]+", "", text)


def build_library_lookup(library_csv: Path) -> Dict[str, Dict[str, str]]:
    """建立 name -> equipment row 的索引。"""
    lookup: Dict[str, Dict[str, str]] = {}
    with library_csv.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            name = str(row.get("name", "") or "").strip()
            if not name:
                continue
            lookup[normalize_name(name)] = dict(row)
    return lookup


def resolve_equipment_id(library_lookup: Mapping[str, Mapping[str, str]], equipment_name: str) -> Tuple[str, str]:
    """
    通过装备名解析 current equipment_id。

    返回：
        (equipment_id, matched_name)
    """
    name = str(equipment_name or "").strip()
    row = library_lookup.get(normalize_name(name))
    if row is None:
        return "", ""
    return str(row.get("equipment_id", "") or "").strip(), str(row.get("name", "") or "").strip()


def parse_bool(value: Any) -> bool:
    """解析 CSV 布尔文本。"""
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def ensure_safe_output_dir(output_dir: Path, project_root: Path) -> None:
    """确保清理目录只发生在实验区。"""
    resolved = output_dir.resolve()
    allowed_roots = [
        (project_root / "ocr_training_lab").resolve(),
        (project_root / "ocr_preview_lab").resolve(),
    ]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise ValueError(f"拒绝清理非实验目录输出路径: {resolved}")


# ============================================================
# 🧾 第四部分：合并逻辑
# ============================================================

def build_corrected_rows(
    review_rows: Sequence[Mapping[str, str]],
    final_rows: Sequence[Mapping[str, str]],
    library_lookup: Mapping[str, Mapping[str, str]],
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """
    把人工修正合并进最终结果。

    输出：
        (corrected_rows, correction_rows)
    """
    final_by_key = {(str(row.get("filename", "")).strip(), str(row.get("card_no", "")).strip()): dict(row) for row in final_rows}
    review_by_key = {(str(row.get("filename", "")).strip(), str(row.get("card_no", "")).strip()): dict(row) for row in review_rows}

    corrected_rows: List[Dict[str, str]] = []
    correction_rows: List[Dict[str, str]] = []

    for key, final_row in final_by_key.items():
        review_row = review_by_key.get(key, {})
        original_name = str(final_row.get("final_equipment_name", "") or "").strip()
        original_owned = str(final_row.get("fragment_owned", "") or "").strip()
        original_required = str(final_row.get("fragment_required", "") or "").strip()

        corrected_name = str(review_row.get("correct_equipment_name", "") or "").strip()
        corrected_owned = str(review_row.get("correct_fragment_owned", "") or "").strip()
        corrected_required = str(review_row.get("correct_fragment_required", "") or "").strip()

        final_name = corrected_name or original_name
        final_owned = corrected_owned or original_owned
        final_required = corrected_required or original_required
        final_id, resolved_name = resolve_equipment_id(library_lookup, final_name)
        correction_applied = bool(corrected_name or corrected_owned or corrected_required)
        label_source_origin = str(final_row.get("final_label_source", "") or "").strip()
        if correction_applied:
            final_label_source = "user_full_review_correction"
            correction_note = "review_all_cards_for_user.csv 已合并"
        else:
            final_label_source = label_source_origin
            correction_note = ""

        corrected_rows.append(
            {
                "review_index": str(review_row.get("review_index", final_row.get("review_index", "")) or ""),
                "filename": key[0],
                "card_no": key[1],
                "final_equipment_name": final_name,
                "final_equipment_id": final_id,
                "final_fragment_owned": final_owned,
                "final_fragment_required": final_required,
                "final_label_source": final_label_source,
                "label_source_origin": label_source_origin,
                "original_equipment_name": original_name,
                "user_corrected_equipment_name": corrected_name,
                "original_fragment_owned": original_owned,
                "user_corrected_fragment_owned": corrected_owned,
                "original_fragment_required": original_required,
                "user_corrected_fragment_required": corrected_required,
                "needs_user_review": str(final_row.get("needs_user_review", review_row.get("needs_user_review", "")) or ""),
                "machine_suggested_equipment_name": str(final_row.get("machine_suggested_equipment_name", "") or "").strip(),
                "icon_confidence": str(final_row.get("icon_confidence", "") or "").strip(),
                "name_ocr_text": str(final_row.get("name_ocr_text", "") or "").strip(),
                "attribute_ocr_text": str(review_row.get("attribute_ocr_text", "") or "").strip(),
                "review_reason": str(final_row.get("review_reason", review_row.get("review_reason", "")) or "").strip(),
                "correction_applied": str(correction_applied),
                "correction_note": correction_note or (f"resolved_name={resolved_name}" if final_id else "名称未在装备库精确匹配"),
            }
        )

        if correction_applied:
            correction_rows.append(
                {
                    "review_index": str(review_row.get("review_index", final_row.get("review_index", "")) or ""),
                    "filename": key[0],
                    "card_no": key[1],
                    "original_equipment_name": original_name,
                    "user_corrected_equipment_name": corrected_name,
                    "original_fragment_owned": original_owned,
                    "user_corrected_fragment_owned": corrected_owned,
                    "original_fragment_required": original_required,
                    "user_corrected_fragment_required": corrected_required,
                    "final_equipment_id": final_id,
                    "final_equipment_name": final_name,
                    "correction_applied": "True",
                }
            )

    return corrected_rows, correction_rows


def write_corrected_exp(path: Path, corrected_rows: Sequence[Mapping[str, str]]) -> None:
    """写出一份可继续回填的 exp。"""
    lines: List[str] = [
        "design fragment user-corrected exp",
        "===================================",
        "",
        "说明：",
        "1. 这是把 review_all_cards_for_user.csv 合并后的结果。",
        "2. 只保留最终结果，方便后续训练/检查。",
        "3. 这里不是全局人类档案，不会自动覆盖旧历史。",
        "",
    ]
    current_filename = ""
    for row in corrected_rows:
        filename = str(row.get("filename", "") or "").strip()
        card_no = str(row.get("card_no", "") or "").strip()
        if filename != current_filename:
            if current_filename:
                lines.append("")
            current_filename = filename
            lines.append(f"[{filename}]")
        lines.extend(
            [
                f"card_{int(card_no):02d}.accepted_equipment_name: {row.get('final_equipment_name', '')}",
                f"card_{int(card_no):02d}.accepted_equipment_id: {row.get('final_equipment_id', '')}",
                f"card_{int(card_no):02d}.accepted_fragment_owned: {row.get('final_fragment_owned', '')}",
                f"card_{int(card_no):02d}.accepted_fragment_required: {row.get('final_fragment_required', '')}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


# ============================================================
# 🚀 第五部分：命令入口
# ============================================================

def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    project_root = find_project_root(Path(__file__))
    workbench = project_root / "ocr_training_lab" / "equipment_icon_matcher_v2" / "active_workbench" / "01_fragment_page"
    default_review_dir = workbench / "review" / "self_label_new_account_design_frag_20260722_0001_clean"
    parser = argparse.ArgumentParser(description="合并设计图全量复核人工修正。")
    parser.add_argument("--review-csv", type=Path, default=default_review_dir / "full_review_pack" / "review_all_cards_for_user.csv")
    parser.add_argument("--final-csv", type=Path, default=default_review_dir / "new_account_collection_final_cards.csv")
    parser.add_argument("--library-csv", type=Path, default=project_root / "data" / "equipment_library.csv")
    parser.add_argument("--output-dir", type=Path, default=default_review_dir / "applied_user_corrections")
    parser.add_argument("--copy-source-review-pack", action="store_true", help="把原始 review_all_cards_for_user.csv 也复制进输出目录。")
    return parser.parse_args()


def main() -> int:
    """合并人工修正并写出新结果。"""
    args = parse_args()
    project_root = find_project_root(Path(__file__))
    ensure_safe_output_dir(args.output_dir, project_root)

    review_rows = read_csv(args.review_csv.resolve())
    final_rows = read_csv(args.final_csv.resolve())
    library_lookup = build_library_lookup(args.library_csv.resolve())
    corrected_rows, correction_rows = build_corrected_rows(review_rows, final_rows, library_lookup)

    if args.output_dir.exists():
        shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    corrected_csv = args.output_dir / "new_account_collection_final_cards_applied.csv"
    corrections_csv = args.output_dir / "user_corrections_only.csv"
    review_snapshot_csv = args.output_dir / "review_all_cards_for_user_snapshot.csv"
    exp_path = args.output_dir / "user_confirmed_fragment_labels.exp.txt"

    write_csv(corrected_csv, corrected_rows, CORRECTED_FIELDNAMES)
    write_csv(corrections_csv, correction_rows, [field for field in CORRECTED_FIELDNAMES if field not in {"label_source_origin", "needs_user_review", "machine_suggested_equipment_name", "icon_confidence", "name_ocr_text", "attribute_ocr_text", "review_reason"}])
    write_csv(review_snapshot_csv, review_rows, REVIEW_FIELDNAMES)
    write_corrected_exp(exp_path, corrected_rows)
    write_json(
        args.output_dir / "user_corrections_summary.json",
        {
            "review_rows": len(review_rows),
            "final_rows": len(final_rows),
            "corrected_rows": len(corrected_rows),
            "correction_rows": len(correction_rows),
            "corrected_csv": str(corrected_csv),
            "corrections_csv": str(corrections_csv),
            "exp_path": str(exp_path),
            "note": "这份结果只用于当前设计图复核包的合并，不写入全局 human_label_archive。",
        },
    )
    if args.copy_source_review_pack:
        src = args.review_csv.resolve().parent
        copy_root = args.output_dir / "source_review_pack"
        copy_root.mkdir(parents=True, exist_ok=True)
        for child in src.iterdir():
            target = copy_root / child.name
            if child.is_file():
                shutil.copy2(child, target)
    print(json.dumps({"output_dir": str(args.output_dir), "corrected_rows": len(corrected_rows), "correction_rows": len(correction_rows)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
