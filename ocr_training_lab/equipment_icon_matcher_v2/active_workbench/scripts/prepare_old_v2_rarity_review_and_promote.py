#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      old_v2 设计图按稀有度拆包与紫装导入准备工具              ║
║                                                              ║
║  【一句话解释】把旧 v2 全量复核包拆成蓝/紫/金/彩独立检查包。  ║
║  【类比理解】像把一大叠混在一起的试卷按颜色分册装订。          ║
║  【数据流说明】full_review_csv + reviewed_gallery → 分组预览/  ║
║                 紫装可信 exp。                               ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import csv
import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - 没有 Pillow 时仍可生成 CSV/EXP。
    Image = None
    ImageDraw = None
    ImageFont = None


# ============================================================
# 🧱 第二部分：常量与数据对象
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = PROJECT_ROOT / "ocr_training_lab" / "equipment_icon_matcher_v2"
DEFAULT_FULL_REVIEW_DIR = V2_ROOT / "review_iterations" / "iter_20260722_old_v2_full_review_pack"
DEFAULT_FULL_REVIEW_CSV = DEFAULT_FULL_REVIEW_DIR / "review_all_cards_for_user.csv"
DEFAULT_REVIEWED_GALLERY_CSV = V2_ROOT / "reviewed_icon_gallery" / "reviewed_icon_gallery_manifest.csv"
DEFAULT_HUMAN_ARCHIVE_CSV = V2_ROOT / "human_label_archive" / "master_human_labels.csv"
DEFAULT_OUTPUT_ROOT = V2_ROOT / "review_iterations" / "iter_20260722_old_v2_rarity_review_20260722"
DEFAULT_PROMOTE_DIR = V2_ROOT / "review_iterations" / "iter_20260722_old_v2_elite_promoted_20260722"
EQUIPMENT_LIBRARY_CSV = PROJECT_ROOT / "data" / "equipment_library.csv"

FONT_PATHS = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
)

RARITY_GROUPS = {
    "rare": {"rarity_id": "2", "display": "蓝装", "prefix": "v2_rare_"},
    "elite": {"rarity_id": "3", "display": "紫装", "prefix": "v2_elite_"},
    "super_rare": {"rarity_id": "4", "display": "金装", "prefix": "v2_super_rare_"},
    "ultra_rare": {"rarity_id": "5", "display": "彩装", "prefix": "v2_ultra_rare_"},
}

# 这些是人工复核过程中发现、且可以用卡面文字/属性明确纠正的旧脏标签。
# 注意：这里只放“确定修正”，不把机器猜测写成真值。
MANUAL_NAME_OVERRIDES = {
    ("v2_elite_scroll_2.png", 6): ("维修工具#T3", "卡面底部文字明确为 维修工具T3；旧图库误写为 T2。"),
    ("v2_elite_scroll_5.png", 3): ("潜艇用Mark 14鱼雷#T3", "卡面为潜艇用Mark...，属性为 伤害52x3/射速31.92，匹配 wiki 的 Mark 14 T3。"),
}


@dataclass(frozen=True)
class EquipmentInfo:
    """装备库中的最小字段。"""

    equipment_id: str
    name: str
    rarity_id: str


@dataclass(frozen=True)
class ProposedLabel:
    """一张卡片最终展示/导入使用的候选标签。"""

    equipment_name: str
    equipment_id: str
    rarity_id: str
    source: str
    note: str


# ============================================================
# 🧰 第三部分：CSV、字体和路径工具
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。

    输入：
        命令行参数。
    输出：
        argparse.Namespace。
    使用示例：
        python prepare_old_v2_rarity_review_and_promote.py
    """
    parser = argparse.ArgumentParser(description="拆分 old_v2 稀有度复核包，并生成紫装 promoted exp。")
    parser.add_argument("--full-review-csv", type=Path, default=DEFAULT_FULL_REVIEW_CSV, help="旧 v2 全量复核 CSV。")
    parser.add_argument("--reviewed-gallery-csv", type=Path, default=DEFAULT_REVIEWED_GALLERY_CSV, help="现有 reviewed 图库 manifest。")
    parser.add_argument("--human-archive-csv", type=Path, default=DEFAULT_HUMAN_ARCHIVE_CSV, help="人工标签总档案 master_human_labels.csv。")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="蓝/紫/金/彩分组预览输出根目录。")
    parser.add_argument("--promote-dir", type=Path, default=DEFAULT_PROMOTE_DIR, help="紫装 promoted exp 输出目录。")
    parser.add_argument("--clean", action="store_true", help="清理并重建本脚本的输出目录。")
    return parser.parse_args()


def read_csv(path: Path) -> List[Dict[str, str]]:
    """读取 UTF-8-SIG CSV，文件不存在时返回空列表。"""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [dict(row) for row in csv.DictReader(file)]


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    """写出 UTF-8-SIG CSV，方便直接用 Excel/WPS 查看。"""
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


def clean_dir(path: Path) -> None:
    """只清理本工具负责的输出目录，避免误删用户原始截图。"""
    root = V2_ROOT.resolve()
    target = path.resolve()
    if not str(target).lower().startswith(str(root).lower()):
        raise RuntimeError(f"拒绝清理 equipment_icon_matcher_v2 外目录: {target}")
    if target.exists():
        shutil.rmtree(target)


def load_font(size: int) -> Any:
    """加载中文字体，失败时退回默认字体。"""
    if ImageFont is None:
        return None
    for path in FONT_PATHS:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def safe_filename(value: str) -> str:
    """生成适合文件名使用的短文本。"""
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in str(value or "")).strip("_")


def infer_rarity_group(filename: str) -> str:
    """从 old_v2 文件名推断稀有度分组。"""
    for group, spec in RARITY_GROUPS.items():
        if str(filename).startswith(str(spec["prefix"])):
            return group
    return "unknown"


# ============================================================
# 🧮 第四部分：标签选择与导入过滤
# ============================================================

def load_equipment_index(path: Path) -> Dict[str, EquipmentInfo]:
    """读取正式装备库，只建立名称索引，不写正式 CSV。"""
    rows = read_csv(path)
    index: Dict[str, EquipmentInfo] = {}
    for row in rows:
        name = str(row.get("name", "") or "").strip()
        if not name:
            continue
        index[name] = EquipmentInfo(
            equipment_id=str(row.get("equipment_id", "") or "").strip(),
            name=name,
            rarity_id=str(row.get("rarity_id", "") or "").strip(),
        )
    return index


def load_gallery_index(path: Path) -> Dict[Tuple[str, int], Mapping[str, str]]:
    """把 reviewed 图库按 source_filename + card_no 建索引。"""
    index: Dict[Tuple[str, int], Mapping[str, str]] = {}
    for row in read_csv(path):
        filename = str(row.get("source_filename", "") or "").strip()
        try:
            card_no = int(str(row.get("card_no", "0") or "0"))
        except ValueError:
            continue
        if filename and card_no:
            index[(filename, card_no)] = row
    return index


def load_human_archive_index(path: Path) -> Dict[Tuple[str, int], Mapping[str, str]]:
    """把人工标签总档案按 filename + card_no 建索引。"""
    index: Dict[Tuple[str, int], Mapping[str, str]] = {}
    for row in read_csv(path):
        filename = str(row.get("filename", "") or "").strip()
        try:
            card_no = int(str(row.get("card_no", "0") or "0"))
        except ValueError:
            continue
        if filename and card_no and str(row.get("accepted_equipment_name", "") or "").strip():
            index[(filename, card_no)] = row
    return index


def normalize_name(raw_name: str) -> str:
    """去掉偶发的 ID 前缀和首尾空白。"""
    value = str(raw_name or "").strip()
    if ":" in value and (value.startswith("G") or value.startswith("S")):
        value = value.split(":", 1)[1].strip()
    return value


def resolve_name(name: str, equipment_index: Mapping[str, EquipmentInfo]) -> Optional[EquipmentInfo]:
    """按装备库正式名称精确解析。"""
    return equipment_index.get(normalize_name(name))


def choose_label(
    row: Mapping[str, str],
    equipment_index: Mapping[str, EquipmentInfo],
    gallery_index: Mapping[Tuple[str, int], Mapping[str, str]],
    human_archive_index: Mapping[Tuple[str, int], Mapping[str, str]],
) -> ProposedLabel:
    """
    选择一张卡片的候选标签。

    输入：
        old_v2 复核行、装备库、现有 reviewed 图库。
    输出：
        ProposedLabel。
    使用示例：
        label = choose_label(row, equipment_index, gallery_index)
    """
    filename = str(row.get("filename", "") or "").strip()
    card_no = int(str(row.get("card_no", "0") or "0"))
    override = MANUAL_NAME_OVERRIDES.get((filename, card_no))
    if override is not None:
        info = resolve_name(override[0], equipment_index)
        return ProposedLabel(override[0], info.equipment_id if info else "", info.rarity_id if info else "", "manual_override", override[1])

    # 人工总档案优先于 reviewed 图库，因为它会处理多轮人工标注之间的冲突。
    archive_row = human_archive_index.get((filename, card_no))
    if archive_row is not None:
        archive_name = normalize_name(str(archive_row.get("accepted_equipment_name", "") or ""))
        info = resolve_name(archive_name, equipment_index)
        return ProposedLabel(
            equipment_name=archive_name,
            equipment_id=info.equipment_id if info else "",
            rarity_id=info.rarity_id if info else "",
            source="human_label_archive",
            note=f"来自人工标签总档案；source={archive_row.get('source_path', '')}",
        )

    # 现有 reviewed 图库次优先，因为它来自前几轮人工确认；但如果它稀有度不匹配，会在后续过滤。
    gallery_row = gallery_index.get((filename, card_no))
    if gallery_row is not None:
        gallery_name = normalize_name(str(gallery_row.get("accepted_equipment_name", "") or gallery_row.get("equipment_name", "") or ""))
        info = resolve_name(gallery_name, equipment_index)
        return ProposedLabel(
            equipment_name=gallery_name,
            equipment_id=info.equipment_id if info else str(gallery_row.get("equipment_id", "") or ""),
            rarity_id=info.rarity_id if info else str(gallery_row.get("rarity_id", "") or ""),
            source="reviewed_gallery",
            note="来自现有 reviewed_icon_gallery；优先级高于旧 CSV 的机器字段。",
        )

    corrected_name = normalize_name(str(row.get("correct_equipment_name", "") or ""))
    if corrected_name:
        info = resolve_name(corrected_name, equipment_index)
        return ProposedLabel(
            equipment_name=corrected_name,
            equipment_id=info.equipment_id if info else "",
            rarity_id=info.rarity_id if info else "",
            source="correct_equipment_name",
            note="来自 review_all_cards_for_user.csv 的人工 correction 字段。",
        )

    current_name = normalize_name(str(row.get("current_equipment_name", "") or ""))
    info = resolve_name(current_name, equipment_index)
    return ProposedLabel(
        equipment_name=current_name,
        equipment_id=info.equipment_id if info else "",
        rarity_id=info.rarity_id if info else "",
        source="current_equipment_name",
        note="未填写 correction，沿用当前候选名；仍需经过稀有度/解析过滤。",
    )


def enrich_rows(
    review_rows: Sequence[Mapping[str, str]],
    equipment_index: Mapping[str, EquipmentInfo],
    gallery_index: Mapping[Tuple[str, int], Mapping[str, str]],
    human_archive_index: Mapping[Tuple[str, int], Mapping[str, str]],
) -> Dict[str, List[Dict[str, Any]]]:
    """给所有 old_v2 行追加 proposed_* 字段，并按稀有度分组。"""
    grouped: Dict[str, List[Dict[str, Any]]] = {key: [] for key in RARITY_GROUPS}
    for row in review_rows:
        group = infer_rarity_group(str(row.get("filename", "") or ""))
        if group not in grouped:
            continue
        label = choose_label(row, equipment_index, gallery_index, human_archive_index)
        expected_rarity_id = str(RARITY_GROUPS[group]["rarity_id"])
        promote_status = "ok" if label.equipment_id and label.rarity_id == expected_rarity_id else "needs_review"
        promote_note = label.note
        if not label.equipment_id:
            promote_note = f"候选名无法在 equipment_library.csv 精确解析；{label.note}"
        elif label.rarity_id != expected_rarity_id:
            promote_note = f"候选稀有度 {label.rarity_id} 与分组 {expected_rarity_id} 不一致；{label.note}"
        enriched = dict(row)
        enriched.update(
            {
                "rarity_group": group,
                "rarity_display": RARITY_GROUPS[group]["display"],
                "expected_rarity_id": expected_rarity_id,
                "proposed_equipment_name": label.equipment_name,
                "proposed_equipment_id": label.equipment_id,
                "proposed_rarity_id": label.rarity_id,
                "proposed_label_source": label.source,
                "promote_status": promote_status,
                "promote_note": promote_note,
            }
        )
        grouped[group].append(enriched)
    return grouped


# ============================================================
# 🖼️ 第五部分：预览包和紫装 promoted exp 写出
# ============================================================

def source_crop_path(row: Mapping[str, Any], full_review_csv: Path) -> Optional[Path]:
    """从 full review 行解析单卡裁剪图路径。"""
    value = str(row.get("card_crop_path", "") or "").strip()
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = (full_review_csv.parent / path).resolve()
    return path if path.exists() else None


def copy_group_crops(rows: Sequence[Mapping[str, Any]], group_dir: Path, full_review_csv: Path) -> List[Dict[str, Any]]:
    """复制分组单卡图，并把新路径写回 group_card_crop_path。"""
    crop_dir = group_dir / "card_crops_all"
    crop_dir.mkdir(parents=True, exist_ok=True)
    copied: List[Dict[str, Any]] = []
    for group_index, row in enumerate(rows, start=1):
        src = source_crop_path(row, full_review_csv)
        enriched = dict(row)
        old_index = str(row.get("review_index", "") or "unknown")
        stem = f"{group_index:03d}_old{old_index}_{safe_filename(str(row.get('filename', '')))}_card{int(str(row.get('card_no', '0') or '0')):02d}.png"
        dst = crop_dir / stem
        if src is not None:
            shutil.copy2(src, dst)
            enriched["group_card_crop_path"] = str(dst)
        else:
            enriched["group_card_crop_path"] = ""
        enriched["group_index"] = group_index
        copied.append(enriched)
    return copied


def create_contact_sheets(rows: Sequence[Mapping[str, Any]], sheet_dir: Path, group_display: str) -> int:
    """
    生成总览图。

    输入：
        分组行和输出目录。
    输出：
        页数。
    使用示例：
        pages = create_contact_sheets(rows, Path("full_contact_sheets"), "紫装")
    """
    if Image is None or ImageDraw is None:
        return 0
    sheet_dir.mkdir(parents=True, exist_ok=True)
    font_title = load_font(20)
    font_small = load_font(15)
    cards_per_page = 8
    columns = 2
    tile_width = 640
    tile_height = 410
    page_count = int(math.ceil(len(rows) / cards_per_page))
    for page_index in range(page_count):
        subset = rows[page_index * cards_per_page:(page_index + 1) * cards_per_page]
        rows_on_page = int(math.ceil(len(subset) / columns))
        canvas = Image.new("RGB", (columns * tile_width, max(1, rows_on_page) * tile_height), (245, 245, 245))
        draw = ImageDraw.Draw(canvas)
        for index, row in enumerate(subset):
            col = index % columns
            line = index // columns
            left = col * tile_width + 10
            top = line * tile_height + 10
            crop_path = Path(str(row.get("group_card_crop_path", "") or ""))
            if crop_path.exists():
                crop = Image.open(crop_path).convert("RGB")
                crop.thumbnail((600, 285))
                canvas.paste(crop, (left, top))
                text_top = top + crop.height + 8
            else:
                text_top = top
                draw.rectangle([left, top, left + 600, top + 280], outline=(200, 0, 0), width=2)
                draw.text((left + 8, top + 8), "缺少裁剪图", fill=(200, 0, 0), font=font_title)
            title = f"{group_display} #{row.get('group_index')} / old#{row.get('review_index')}  {row.get('filename')} card{int(str(row.get('card_no', '0') or '0')):02d}"
            proposal = f"候选: {row.get('proposed_equipment_name', '')}  id={row.get('proposed_equipment_id', '')}  r={row.get('proposed_rarity_id', '')}"
            source = f"来源: {row.get('proposed_label_source', '')}  状态: {row.get('promote_status', '')}"
            draw.text((left, text_top), title, fill=(0, 0, 0), font=font_small)
            draw.text((left, text_top + 22), proposal, fill=(0, 70, 160), font=font_small)
            draw.text((left, text_top + 44), source, fill=(150, 60, 0), font=font_small)
        canvas.save(sheet_dir / f"page_{page_index + 1:03d}.png")
    return page_count


def write_group_readme(group_dir: Path, group: str, rows: Sequence[Mapping[str, Any]], page_count: int) -> None:
    """写出每个稀有度包的中文说明。"""
    spec = RARITY_GROUPS[group]
    ok_count = sum(1 for row in rows if row.get("promote_status") == "ok")
    text = f"""{spec['display']} old_v2 复核预览包
==============================

这个目录只包含 {spec['display']} 文件名分组：
prefix: {spec['prefix']}
expected_rarity_id: {spec['rarity_id']}

你主要看：

1. full_contact_sheets/page_*.png
   按页查看所有卡片，图下方会显示这次机器/图库给出的候选名称。

2. review_all_cards_for_user.csv
   如果你发现候选错了，只改 correct_equipment_name。
   不要改 current_equipment_name，也不要改 proposed_* 字段。

3. card_crops_all/
   单张卡片裁剪图，文件名里 oldXXX 是旧全量包里的 review_index。

统计：
cards: {len(rows)}
promote_status=ok: {ok_count}
promote_status=needs_review: {len(rows) - ok_count}
contact_sheet_pages: {page_count}

注意：
蓝/金/彩这几个包当前只是给你检查，不会自动导入训练集。
紫装导入使用的是 promoted exp 快照，不直接覆盖这份 CSV。
"""
    (group_dir / "README_REVIEW_THIS_RARITY.txt").write_text(text, encoding="utf-8")


def write_group_package(
    group: str,
    rows: Sequence[Mapping[str, Any]],
    output_root: Path,
    full_review_csv: Path,
) -> List[Dict[str, Any]]:
    """写出单个稀有度预览包。"""
    group_dir = output_root / group
    group_dir.mkdir(parents=True, exist_ok=True)
    copied_rows = copy_group_crops(rows, group_dir, full_review_csv)
    fieldnames = list(dict.fromkeys([key for row in copied_rows for key in row.keys()]))
    write_csv(group_dir / "review_all_cards_for_user.csv", copied_rows, fieldnames)
    page_count = create_contact_sheets(copied_rows, group_dir / "full_contact_sheets", str(RARITY_GROUPS[group]["display"]))
    write_group_readme(group_dir, group, copied_rows, page_count)
    return copied_rows


def write_elite_promote_exp(rows: Sequence[Mapping[str, Any]], promote_dir: Path) -> Dict[str, Any]:
    """把紫装可信行写成训练管线可发现的 promoted exp。"""
    completed_dir = promote_dir / "completed"
    completed_dir.mkdir(parents=True, exist_ok=True)
    ok_rows = [row for row in rows if row.get("promote_status") == "ok" and row.get("proposed_rarity_id") == "3"]
    rejected_rows = [row for row in rows if row not in ok_rows]

    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    for row in ok_rows:
        grouped.setdefault(str(row.get("filename", "")), []).append(row)

    lines: List[str] = [
        "# old_v2 紫装 promoted exp",
        "# 生成来源：prepare_old_v2_rarity_review_and_promote.py",
        "# 规则：只导入 filename=v2_elite_*、装备库 rarity_id=3、名称可解析、完整卡片来源。",
        "# 如果后续发现某条不对，请优先修改本文件或重新生成本批次，不要改机器字段。",
        "",
    ]
    for filename in sorted(grouped):
        lines.append(f"[{filename}]")
        for row in sorted(grouped[filename], key=lambda item: int(str(item.get("card_no", "0") or "0"))):
            card_no = int(str(row.get("card_no", "0") or "0"))
            lines.append(f"card_{card_no:02d}.accepted_equipment_name:{row.get('proposed_equipment_name', '')}")
            lines.append(f"card_{card_no:02d}.accepted_equipment_id:{row.get('proposed_equipment_id', '')}")
            owned = str(row.get("correct_fragment_owned", "") or row.get("current_fragment_owned", "") or "").strip()
            required = str(row.get("correct_fragment_required", "") or row.get("current_fragment_required", "") or "").strip()
            if owned:
                lines.append(f"card_{card_no:02d}.accepted_fragment_owned:{owned}")
            if required:
                lines.append(f"card_{card_no:02d}.accepted_fragment_required:{required}")
            lines.append(f"card_{card_no:02d}.source_note:{row.get('promote_note', '')}")
        lines.append("")

    exp_path = completed_dir / "v2_prelabel_review_only_exp.old_v2_elite_promoted.txt"
    exp_path.write_text("\n".join(lines), encoding="utf-8")
    fieldnames = list(dict.fromkeys([key for row in rows for key in row.keys()]))
    write_csv(completed_dir / "elite_promoted_training_labels.csv", ok_rows, fieldnames)
    write_csv(completed_dir / "elite_rejected_or_needs_review.csv", rejected_rows, fieldnames)
    summary = {
        "exp_path": str(exp_path),
        "promoted_rows": len(ok_rows),
        "rejected_rows": len(rejected_rows),
        "note": "紫装 promoted 只包含 equipment_library.csv 中 rarity_id=3 的可解析名称。",
    }
    write_json(completed_dir / "elite_promote_summary.json", summary)
    return summary


# ============================================================
# 🚀 第六部分：主流程
# ============================================================

def build_all(
    full_review_csv: Path,
    reviewed_gallery_csv: Path,
    human_archive_csv: Path,
    output_root: Path,
    promote_dir: Path,
    clean: bool = False,
) -> Dict[str, Any]:
    """
    执行拆包和紫装 promoted exp 生成。

    输入：
        full_review_csv/reviewed_gallery_csv/output_root/promote_dir。
    输出：
        摘要字典。
    使用示例：
        summary = build_all(DEFAULT_FULL_REVIEW_CSV, DEFAULT_REVIEWED_GALLERY_CSV, DEFAULT_OUTPUT_ROOT, DEFAULT_PROMOTE_DIR)
    """
    if clean:
        clean_dir(output_root)
        clean_dir(promote_dir)
    review_rows = read_csv(full_review_csv)
    equipment_index = load_equipment_index(EQUIPMENT_LIBRARY_CSV)
    gallery_index = load_gallery_index(reviewed_gallery_csv)
    human_archive_index = load_human_archive_index(human_archive_csv)
    grouped = enrich_rows(review_rows, equipment_index, gallery_index, human_archive_index)

    group_summaries: Dict[str, Any] = {}
    copied_by_group: Dict[str, List[Dict[str, Any]]] = {}
    for group, rows in grouped.items():
        copied_rows = write_group_package(group, rows, output_root, full_review_csv)
        copied_by_group[group] = copied_rows
        group_summaries[group] = {
            "display": RARITY_GROUPS[group]["display"],
            "rows": len(copied_rows),
            "ok": sum(1 for row in copied_rows if row.get("promote_status") == "ok"),
            "needs_review": sum(1 for row in copied_rows if row.get("promote_status") != "ok"),
            "review_csv": str(output_root / group / "review_all_cards_for_user.csv"),
            "contact_sheets": str(output_root / group / "full_contact_sheets"),
        }

    elite_summary = write_elite_promote_exp(copied_by_group["elite"], promote_dir)
    summary = {
        "full_review_csv": str(full_review_csv),
        "reviewed_gallery_csv": str(reviewed_gallery_csv),
        "human_archive_csv": str(human_archive_csv),
        "output_root": str(output_root),
        "promote_dir": str(promote_dir),
        "groups": group_summaries,
        "elite_promote": elite_summary,
    }
    write_json(output_root / "rarity_review_summary.json", summary)
    return summary


def main() -> int:
    """命令行入口。"""
    args = parse_args()
    summary = build_all(
        full_review_csv=args.full_review_csv.resolve(),
        reviewed_gallery_csv=args.reviewed_gallery_csv.resolve(),
        human_archive_csv=args.human_archive_csv.resolve(),
        output_root=args.output_root.resolve(),
        promote_dir=args.promote_dir.resolve(),
        clean=bool(args.clean),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
