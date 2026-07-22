#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║   old_v2 稀有度复核包验收版生成器                           ║
║                                                              ║
║  【一句话解释】把 current_* / correct_* 合成最终验收包。      ║
║  【类比理解】像把“机器答案”和“人工改正”合并成期末定稿。      ║
║  【数据流说明】旧稀有度 CSV + 裁剪图 → applied CSV + 总览图。   ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - Pillow 不可用时，仍允许 CSV/归档继续。
    Image = None
    ImageDraw = None
    ImageFont = None


FONT_PATHS = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
)

RARITY_LABELS = {
    "rare": "蓝装",
    "super_rare": "金装",
}


def find_project_root(start: Path) -> Path:
    """从脚本位置向上找项目根目录。"""
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


def safe_stem(value: str) -> str:
    """把文件名压成适合落盘的短字符串。"""
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(value or "")).strip("_")


def load_font(size: int) -> Any:
    """加载可显示中文的字体。"""
    if ImageFont is None:
        return None
    for font_path in FONT_PATHS:
        if font_path.exists():
            try:
                return ImageFont.truetype(str(font_path), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def normalize_equipment_name(name: str) -> str:
    """尽量抹平空格、全角符号和 tier 噪声。"""
    text = str(name or "").strip()
    text = re.sub(r"^[GS]\d{1,4}\s*[:：]\s*", "", text)
    replacements = {
        "（": "(",
        "）": ")",
        "　": "",
        " ": "",
        "\t": "",
        "\r": "",
        "\n": "",
        "＃": "#",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.lower()
    text = re.sub(r"(#t\d+)[a-z]+$", r"\1", text)
    return text


def build_equipment_lookup(library_csv: Path) -> Tuple[Dict[str, str], Dict[str, str]]:
    """建立 equipment_library.csv 的名称→ID 索引。"""
    exact_to_id: Dict[str, str] = {}
    normalized_to_id: Dict[str, str] = {}
    for row in read_csv(library_csv):
        equipment_id = str(row.get("equipment_id", "") or "").strip()
        name = str(row.get("name", "") or "").strip()
        if not equipment_id or not name:
            continue
        exact_to_id[name] = equipment_id
        normalized_to_id[normalize_equipment_name(name)] = equipment_id
    return exact_to_id, normalized_to_id


def resolve_equipment_id(name: str, exact_to_id: Mapping[str, str], normalized_to_id: Mapping[str, str]) -> str:
    """把装备名落到当前装备库 ID。"""
    cleaned = str(name or "").strip()
    if not cleaned:
        return ""
    if cleaned in exact_to_id:
        return exact_to_id[cleaned]
    normalized = normalize_equipment_name(cleaned)
    return normalized_to_id.get(normalized, "")


def choose_final_name(row: Mapping[str, str]) -> str:
    """优先使用 correct_*，没有再退回 current_*。"""
    corrected = str(row.get("correct_equipment_name", "") or "").strip()
    current = str(row.get("current_equipment_name", "") or "").strip()
    return corrected or current


def choose_final_value(row: Mapping[str, str], current_key: str, correct_key: str) -> str:
    """同一套规则处理碎片 owned / required。"""
    corrected = str(row.get(correct_key, "") or "").strip()
    current = str(row.get(current_key, "") or "").strip()
    return corrected or current


def pick_crop_path(row: Mapping[str, str]) -> Optional[Path]:
    """优先使用已经存在的 card_crop_path，其次回退 group_card_crop_path。"""
    for key in ("card_crop_path", "group_card_crop_path"):
        value = str(row.get(key, "") or "").strip()
        if not value:
            continue
        path = Path(value)
        if path.exists():
            return path
    return None


def copy_crop_files(rows: Sequence[Mapping[str, str]], output_dir: Path) -> List[Dict[str, str]]:
    """把单卡裁剪图复制到输出目录。"""
    crop_dir = output_dir / "card_crops_all"
    crop_dir.mkdir(parents=True, exist_ok=True)
    copied_rows: List[Dict[str, str]] = []
    for row in rows:
        source = pick_crop_path(row)
        copied = dict(row)
        if source is not None and source.exists():
            target = crop_dir / source.name
            if target.resolve() != source.resolve():
                shutil.copy2(source, target)
            copied["applied_card_crop_path"] = str(target)
        else:
            copied["applied_card_crop_path"] = ""
        copied_rows.append(copied)
    return copied_rows


def render_contact_sheets(rows: Sequence[Mapping[str, str]], output_dir: Path, rarity_label: str) -> int:
    """把验收版卡片渲染成更容易看的总览图。"""
    if Image is None or ImageDraw is None:
        return 0

    sheet_dir = output_dir / "full_contact_sheets"
    sheet_dir.mkdir(parents=True, exist_ok=True)
    title_font = load_font(24)
    body_font = load_font(18)
    small_font = load_font(15)

    columns = 2
    cards_per_page = 6
    thumb_max = (820, 250)
    tile_width = 860
    tile_height = 420
    gap = 20
    header_height = 56
    page_width = columns * tile_width + (columns + 1) * gap
    page_height = header_height + 3 * tile_height + 4 * gap

    page_count = 0
    for start in range(0, len(rows), cards_per_page):
        subset = rows[start:start + cards_per_page]
        page_count += 1
        canvas = Image.new("RGB", (page_width, page_height), (248, 248, 248))
        draw = ImageDraw.Draw(canvas)
        draw.text(
            (gap, 14),
            f"{rarity_label}最终验收版 page {page_count} / {((len(rows) - 1) // cards_per_page) + 1}",
            fill="black",
            font=title_font,
        )
        for index, row in enumerate(subset):
            col = index % columns
            line = index // columns
            left = gap + col * (tile_width + gap)
            top = header_height + gap + line * (tile_height + gap)
            draw.rounded_rectangle((left, top, left + tile_width, top + tile_height), radius=16, fill="white", outline=(210, 210, 210), width=2)

            crop_value = str(row.get("applied_card_crop_path", "") or "").strip()
            crop_path = Path(crop_value) if crop_value else None
            if crop_path is not None and crop_path.exists():
                crop = Image.open(crop_path).convert("RGB")
                crop.thumbnail(thumb_max)
                canvas.paste(crop, (left + 16, top + 16))
                img_bottom = top + 16 + crop.height
            else:
                draw.rectangle((left + 16, top + 16, left + 16 + thumb_max[0], top + 16 + thumb_max[1]), outline=(200, 0, 0), width=2)
                draw.text((left + 28, top + 28), "缺少裁剪图", fill=(200, 0, 0), font=body_font)
                img_bottom = top + 16 + thumb_max[1]

            lines = [
                f"#{row.get('review_index', '')}  {row.get('filename', '')}  card{int(str(row.get('card_no', '0') or '0')):02d}",
                f"final: {row.get('final_equipment_name', '')}  id={row.get('final_equipment_id', '')}",
                f"owned/required: {row.get('final_fragment_owned', '')}/{row.get('final_fragment_required', '')}",
                f"source: {row.get('final_label_source', '')}  correction={row.get('correction_applied', '')}",
            ]
            text_y = min(img_bottom + 12, top + tile_height - 110)
            for line_text in lines:
                draw.text((left + 20, text_y), line_text, fill=(25, 25, 25), font=body_font if line_text.startswith("final:") else small_font)
                text_y += 26

        canvas.save(sheet_dir / f"page_{page_count:03d}.png")
    return page_count


def build_applied_rows(rows: Sequence[Mapping[str, str]], exact_to_id: Mapping[str, str], normalized_to_id: Mapping[str, str]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """把 current_* / correct_* 合成最终验收版，并收集改动行。"""
    applied_rows: List[Dict[str, str]] = []
    corrections: List[Dict[str, str]] = []
    for row in rows:
        final_name = choose_final_name(row)
        final_owned = choose_final_value(row, "current_fragment_owned", "correct_fragment_owned")
        final_required = choose_final_value(row, "current_fragment_required", "correct_fragment_required")
        final_equipment_id = resolve_equipment_id(final_name, exact_to_id, normalized_to_id)
        correction_applied = any(
            str(row.get(key, "") or "").strip()
            for key in ("correct_equipment_name", "correct_fragment_owned", "correct_fragment_required")
        )
        final_label_source = "user_full_review_correction" if correction_applied else str(row.get("label_source", "") or "").strip()
        applied = {
            "review_index": str(row.get("review_index", "") or "").strip(),
            "filename": str(row.get("filename", "") or "").strip(),
            "card_no": str(row.get("card_no", "") or "").strip(),
            "card_crop_path": str(row.get("card_crop_path", "") or "").strip(),
            "group_card_crop_path": str(row.get("group_card_crop_path", "") or "").strip(),
            "annotated_source_path": str(row.get("annotated_source_path", "") or "").strip(),
            "final_equipment_name": final_name,
            "final_equipment_id": final_equipment_id,
            "final_fragment_owned": final_owned,
            "final_fragment_required": final_required,
            "final_label_source": final_label_source,
            "label_source_origin": str(row.get("label_source", "") or "").strip(),
            "original_equipment_name": str(row.get("current_equipment_name", "") or "").strip(),
            "user_corrected_equipment_name": str(row.get("correct_equipment_name", "") or "").strip(),
            "original_fragment_owned": str(row.get("current_fragment_owned", "") or "").strip(),
            "user_corrected_fragment_owned": str(row.get("correct_fragment_owned", "") or "").strip(),
            "original_fragment_required": str(row.get("current_fragment_required", "") or "").strip(),
            "user_corrected_fragment_required": str(row.get("correct_fragment_required", "") or "").strip(),
            "needs_user_review": str(row.get("needs_user_review", "") or "").strip(),
            "machine_suggested_equipment_name": str(row.get("machine_suggested_equipment_name", "") or "").strip(),
            "icon_confidence": str(row.get("icon_confidence", "") or "").strip(),
            "name_ocr_text": str(row.get("name_ocr_text", "") or "").strip(),
            "attribute_ocr_text": str(row.get("attribute_ocr_text", "") or "").strip(),
            "review_reason": str(row.get("review_reason", "") or "").strip(),
            "correction_applied": str(bool(correction_applied)),
            "correction_note": "merged from correct_*" if correction_applied else "",
            "applied_card_crop_path": "",
        }
        applied_rows.append(applied)
        if correction_applied:
            corrections.append(applied)
    return applied_rows, corrections


def write_readme(path: Path, rarity_label: str, output_dir: Path, row_count: int, correction_count: int, page_count: int) -> None:
    """写出给人看的使用说明。"""
    text = f"""{rarity_label}最终验收版
================

先看：
{output_dir / "full_contact_sheets"}

1. 打开 page_001.png、page_002.png ...
2. 每张图下方都有 final 名称、ID、碎片数、来源。
3. 如果想查单条，打开：
{output_dir / "review_all_cards_for_user.applied.csv"}

说明：
- final_* 是把 current_* 和 correct_* 合并后的最终版。
- correction=True 表示这一行确实被人工修过。
- 这份包只用于验收/复核，不写正式业务数据。

统计：
- rows: {row_count}
- corrections: {correction_count}
- contact_sheet_pages: {page_count}
"""
    path.write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    project_root = find_project_root(Path(__file__))
    default_source_root = project_root / "ocr_training_lab" / "equipment_icon_matcher_v2" / "review_iterations" / "iter_20260722_old_v2_rarity_review_20260722"
    default_archive_root = project_root / "nn_training_lab" / "archive" / "equipment_icon_matcher_v2" / "review_iterations" / "iter_20260722_old_v2_rarity_review_20260722"
    parser = argparse.ArgumentParser(description="生成 old_v2 稀有度复核包的最终验收版。")
    parser.add_argument("--source-root", type=Path, default=default_source_root, help="旧 v2 rarity review 根目录。")
    parser.add_argument("--archive-root", type=Path, default=default_archive_root, help="新的归档输出根目录。")
    parser.add_argument("--rarity", choices=sorted(RARITY_LABELS), help="只生成某个稀有度；不填则生成 rare 和 super_rare。")
    return parser.parse_args()


def build_one_group(source_group_dir: Path, output_group_dir: Path, rarity_label: str, library_csv: Path) -> Dict[str, Any]:
    """生成单个稀有度的 applied 包。"""
    source_csv = source_group_dir / "review_all_cards_for_user.csv"
    rows = read_csv(source_csv)
    exact_to_id, normalized_to_id = build_equipment_lookup(library_csv)
    applied_rows, correction_rows = build_applied_rows(rows, exact_to_id, normalized_to_id)

    if output_group_dir.exists():
        shutil.rmtree(output_group_dir)
    output_group_dir.mkdir(parents=True, exist_ok=True)

    copied_rows = copy_crop_files(applied_rows, output_group_dir)
    page_count = render_contact_sheets(copied_rows, output_group_dir, rarity_label)

    fieldnames = [
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
        "applied_card_crop_path",
    ]
    write_csv(output_group_dir / "review_all_cards_for_user.applied.csv", copied_rows, fieldnames)
    write_csv(output_group_dir / "corrections_only.csv", correction_rows, fieldnames)
    write_readme(
        output_group_dir / "README_FINAL_REVIEW_APPLIED.txt",
        rarity_label,
        output_group_dir,
        len(copied_rows),
        len(correction_rows),
        page_count,
    )
    summary = {
        "rarity_label": rarity_label,
        "source_csv": str(source_csv),
        "output_dir": str(output_group_dir),
        "rows": len(copied_rows),
        "corrections": len(correction_rows),
        "contact_sheet_pages": page_count,
        "applied_csv": str(output_group_dir / "review_all_cards_for_user.applied.csv"),
        "corrections_only_csv": str(output_group_dir / "corrections_only.csv"),
    }
    write_json(output_group_dir / "final_review_summary.json", summary)
    return summary


def main() -> int:
    """生成蓝装/金装的最终验收版。"""
    args = parse_args()
    project_root = find_project_root(Path(__file__))
    source_root = args.source_root.resolve()
    archive_root = args.archive_root.resolve()

    groups = [args.rarity] if args.rarity else ["rare", "super_rare"]
    summaries: List[Dict[str, Any]] = []
    for group in groups:
        source_group_dir = source_root / group
        output_group_dir = archive_root / group / "final_review_pack_applied"
        summary = build_one_group(source_group_dir, output_group_dir, RARITY_LABELS[group], project_root / "data" / "equipment_library.csv")
        summaries.append(summary)

    write_json(archive_root / "final_review_pack_applied_summary.json", {"groups": summaries})
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
