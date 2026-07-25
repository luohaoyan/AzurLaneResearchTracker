#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        active_workbench 装备页整页扫描入口                   ║
║                                                              ║
║  【一句话解释】自动从装备页截图里裁剪装备 icon 并识别。        ║
║  【类比理解】像先把货架上每个小格子剪下来，再逐个对图鉴。      ║
║  【数据流说明】装备页截图 → 自动裁 icon → matcher → CSV。     ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

try:
    import cv2
except Exception:  # pragma: no cover - 缺依赖时输出友好错误。
    cv2 = None

try:
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover - 缺 Pillow 时仍可输出 CSV。
    Image = None
    ImageDraw = None

SCRIPT_DIR = Path(__file__).resolve().parent
WORKBENCH_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common_icon_matching import (  # noqa: E402
    build_equipment_erased_gallery_csv,
    build_equipment_overlay_gallery_csv,
    build_combined_gallery_csv,
    erase_equipment_dynamic_regions,
    build_icon_matcher,
    format_candidates,
    load_equipment_catalog,
    load_font,
    resolve_name,
    write_csv,
    write_json,
)

SECTION_DIR = WORKBENCH_DIR / "02_equipment_page"
DEFAULT_INPUT_DIR = SECTION_DIR / "img_input"
DEFAULT_OUTPUT_ROOT = SECTION_DIR / "img_out"
STATUS_FILE = SECTION_DIR / "STATUS.txt"
CURRENT_OUT_FILE = SECTION_DIR / "CURRENT_OUT.txt"

BASE_WIDTH = 1280
BASE_HEIGHT = 720
BASE_ICON_LEFTS = (137, 296, 455, 614, 773, 932, 1091)
BASE_ICON_TOPS = (86, 265, 444, 623)
BASE_ICON_SIZE = 132
BASE_VISIBLE_BOTTOM = 612
MATCH_ICON_INSET = (2, 2, 128, 128)
RARITY_NAME_TO_ID = {
    "common": 1,
    "rare": 2,
    "elite": 3,
    "super_rare": 4,
    "ultra_rare": 5,
}
RARITY_ID_TO_NAME = {value: key for key, value in RARITY_NAME_TO_ID.items()}

Roi = Tuple[int, int, int, int]


# ============================================================
# 🧱 第二部分：数据对象
# ============================================================

@dataclass(frozen=True)
class EquipmentPageCard:
    """
    装备页里一个候选装备格。

    输入：
        card_no、icon_roi、附属数字 ROI。
    输出：
        供裁剪、识别和 CSV 写出的结构。
    使用示例：
        card = EquipmentPageCard(1, (137, 86, 132, 132), ...)
    """

    card_no: int
    row_index: int
    column_index: int
    icon_roi: Roi
    enhance_roi: Roi
    stack_roi: Roi
    used_overlay_roi: Roi


@dataclass(frozen=True)
class EquipmentPageMeta:
    """
    装备页截图的分类状态。

    输入：
        文件名、截图 hash、筛选/排序信息。
    输出：
        后续断点续扫使用的 page_key。
    使用示例：
        meta = parse_equipment_page_meta(Path("equip_super_rare_scroll_001.png"), "abc")
    """

    filename: str
    page_type: str
    tab: str
    filter_rarity: str
    filter_rarity_id: int
    sort_mode: str
    scroll_index: int
    screenshot_sha1: str

    @property
    def page_key(self) -> str:
        """返回断点续扫使用的页面 key。"""
        return f"{self.page_type}:{self.tab}:{self.filter_rarity}:sort_{self.sort_mode}:scroll_{self.scroll_index:03d}"


# ============================================================
# 🏗️ 第三部分：参数与几何
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析装备页扫描参数。

    输入：
        命令行。
    输出：
        argparse.Namespace。
    使用示例：
        python run_equipment_page_scan.py
    """
    parser = argparse.ArgumentParser(description="active_workbench 装备页整页扫描。")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--output-name", default="")
    parser.add_argument("--pattern", default="*.png")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--rarity-id", type=int, default=0)
    parser.add_argument("--match-mode", choices=("raw", "clean", "both"), default="both", help="raw=不处理直接识别，clean=去遮挡识别，both=两者都跑用于对比。")
    parser.add_argument(
        "--gallery-style",
        choices=("normal", "equipment_overlay", "equipment_erased"),
        default="normal",
        help="normal=原始图库，equipment_overlay=合成遮挡图库，equipment_erased=图库也抹除动态区。",
    )
    parser.add_argument("--no-region-refine", action="store_true")
    return parser.parse_args()


def output_dir_for(root: Path, name: str) -> Path:
    """
    构造输出目录。

    输入：
        输出根目录和可选名称。
    输出：
        img_out/run_xxx。
    使用示例：
        out = output_dir_for(Path("img_out"), "")
    """
    final_name = name.strip() or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return root / final_name


def scale_roi(roi: Roi, width: int, height: int) -> Roi:
    """
    把 1280x720 基准 ROI 缩放到当前截图。

    输入：
        基准 ROI 和当前宽高。
    输出：
        当前截图 ROI。
    使用示例：
        scaled = scale_roi((137, 86, 132, 132), 1280, 720)
    """
    sx = width / float(BASE_WIDTH)
    sy = height / float(BASE_HEIGHT)
    x, y, w, h = roi
    return (
        int(round(x * sx)),
        int(round(y * sy)),
        max(1, int(round(w * sx))),
        max(1, int(round(h * sy))),
    )


def build_equipment_page_cards(width: int, height: int) -> List[EquipmentPageCard]:
    """
    根据装备页固定网格生成候选 icon 裁剪框。

    输入：
        截图宽高。
    输出：
        完整可见的装备 icon 候选。
    使用示例：
        cards = build_equipment_page_cards(1280, 720)
    """
    cards: List[EquipmentPageCard] = []
    card_no = 1
    visible_bottom = int(round(BASE_VISIBLE_BOTTOM * height / float(BASE_HEIGHT)))
    for row_index, base_y in enumerate(BASE_ICON_TOPS, start=1):
        for column_index, base_x in enumerate(BASE_ICON_LEFTS, start=1):
            icon_roi = scale_roi((base_x, base_y, BASE_ICON_SIZE, BASE_ICON_SIZE), width, height)
            x, y, w, h = icon_roi
            if y + h > visible_bottom:
                # 底部菜单遮住的半截卡片不识别，避免把脏 icon 写入训练集。
                continue
            enhance_roi = scale_roi((base_x + 0, base_y + 75, 44, 31), width, height)
            stack_roi = scale_roi((base_x + 105, base_y + 91, 26, 35), width, height)
            used_overlay_roi = scale_roi((base_x + 100, base_y - 14, 42, 42), width, height)
            cards.append(
                EquipmentPageCard(
                    card_no=card_no,
                    row_index=row_index,
                    column_index=column_index,
                    icon_roi=icon_roi,
                    enhance_roi=enhance_roi,
                    stack_roi=stack_roi,
                    used_overlay_roi=used_overlay_roi,
                )
            )
            card_no += 1
    return cards


def parse_equipment_page_meta(image_path: Path, screenshot_sha1: str, rarity_override: int = 0) -> EquipmentPageMeta:
    """
    从装备页文件名中解析筛选状态。

    输入：
        equip_super_rare_scroll_001.png 这类文件名。
    输出：
        page/tab/filter/sort/scroll_index。
    使用示例：
        meta = parse_equipment_page_meta(Path("equip_ultra_rare_scroll_2.png"), "sha1")
    """
    rarity = "unknown"
    scroll_index = 0
    match = re.match(r"^equip_(?P<rarity>.+)_scroll_(?P<index>\d+)\.(?:png|jpg|jpeg|bmp|webp)$", image_path.name, flags=re.IGNORECASE)
    if match:
        rarity = normalize_rarity_name(match.group("rarity"))
        scroll_index = int(match.group("index"))
    rarity_id = int(rarity_override or RARITY_NAME_TO_ID.get(rarity, 0))
    if rarity_id > 0:
        rarity = RARITY_ID_TO_NAME.get(rarity_id, rarity)
    return EquipmentPageMeta(
        filename=image_path.name,
        page_type="warehouse",
        tab="equipment",
        filter_rarity=rarity,
        filter_rarity_id=rarity_id,
        sort_mode="rarity",
        scroll_index=scroll_index,
        screenshot_sha1=screenshot_sha1,
    )


def normalize_rarity_name(raw: str) -> str:
    """
    规范化文件名中的稀有度字段。

    输入：
        super_rare / ultra_rare / gold / ur 等文本。
    输出：
        common/rare/elite/super_rare/ultra_rare/unknown。
    使用示例：
        normalize_rarity_name("super_rare") == "super_rare"
    """
    text = str(raw or "").strip().lower().replace("-", "_")
    aliases = {
        "normal": "common",
        "blue": "rare",
        "purple": "elite",
        "gold": "super_rare",
        "ssr": "super_rare",
        "rainbow": "ultra_rare",
        "ur": "ultra_rare",
    }
    return aliases.get(text, text if text in RARITY_NAME_TO_ID else "unknown")


def crop_roi(image: Any, roi: Roi) -> Any:
    """
    从 OpenCV 图像中裁剪 ROI。

    输入：
        image 和 roi。
    输出：
        crop。
    使用示例：
        crop = crop_roi(image, (137, 86, 132, 132))
    """
    x, y, w, h = roi
    return image[y:y + h, x:x + w]


def file_sha1(path: Path) -> str:
    """
    计算截图文件 SHA1，用于断点续扫判断“这张图是否处理过”。

    输入：
        文件路径。
    输出：
        SHA1 前 16 位。
    使用示例：
        digest = file_sha1(Path("equip.png"))
    """
    digest = hashlib.sha1()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def image_fingerprint(image: Any) -> str:
    """
    计算裁剪 icon 的内容指纹。

    输入：
        OpenCV 图像。
    输出：
        SHA1 前 16 位；失败时为空。
    使用示例：
        fp = image_fingerprint(crop)
    """
    if cv2 is None or image is None or getattr(image, "size", 0) == 0:
        return ""
    success, encoded = cv2.imencode(".png", image)
    if not success:
        return ""
    return hashlib.sha1(encoded.tobytes()).hexdigest()[:16]


def sanitize_equipment_icon_crop(crop: Any) -> Any:
    """
    清理装备页 icon 上的动态遮挡，再交给 matcher。

    输入：
        装备页完整 icon 格，通常包含头像、强化等级、堆叠数量。
    输出：
        更接近 data/images 图鉴风格的匹配图。
    使用示例：
        clean = sanitize_equipment_icon_crop(crop)
    """
    return erase_equipment_dynamic_regions(crop, crop_inset=True)


def fill_region_with_local_average(image: Any, roi: Roi) -> None:
    """
    用局部平均色填充动态遮挡区域。

    输入：
        OpenCV 图像和 ROI。
    输出：
        原图就地修改。
    使用示例：
        fill_region_with_local_average(icon, (100, 0, 32, 44))
    """
    x, y, w, h = roi
    height, width = int(image.shape[0]), int(image.shape[1])
    x = min(max(0, x), max(0, width - 1))
    y = min(max(0, y), max(0, height - 1))
    w = max(1, min(int(w), width - x))
    h = max(1, min(int(h), height - y))
    pad = 6
    sx0 = max(0, x - pad)
    sy0 = max(0, y - pad)
    sx1 = min(width, x + w + pad)
    sy1 = min(height, y + h + pad)
    sample = image[sy0:sy1, sx0:sx1]
    if sample is None or getattr(sample, "size", 0) == 0:
        return
    fill = sample.reshape(-1, sample.shape[-1]).mean(axis=0)
    image[y:y + h, x:x + w] = fill


def image_has_card_content(crop: Any) -> bool:
    """
    粗略判断裁剪结果是否像装备 icon，而不是空背景。

    输入：
        icon crop。
    输出：
        True 表示继续识别。
    使用示例：
        if image_has_card_content(crop): ...
    """
    if crop is None or getattr(crop, "size", 0) == 0:
        return False
    # 装备卡背景颜色/亮度变化明显；空背景整体更暗且方差更低。
    mean_value = float(crop.mean())
    std_value = float(crop.std())
    return bool(mean_value > 45.0 and std_value > 18.0)


# ============================================================
# 🎨 第四部分：标注图
# ============================================================

def annotate_page(image_path: Path, output_path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    """
    在整页装备截图上标注识别框。

    输入：
        原图路径、输出路径、卡片行。
    输出：
        annotated png。
    使用示例：
        annotate_page(path, out, rows)
    """
    if Image is None or ImageDraw is None:
        return
    try:
        image = Image.open(image_path).convert("RGB")
    except Exception:
        return
    draw = ImageDraw.Draw(image)
    font = load_font(15)
    small_font = load_font(12)
    for row in rows:
        x, y, w, h = [int(value) for value in str(row.get("icon_roi", "0,0,0,0")).split(",")]
        status = str(row.get("status", ""))
        color = "lime" if status == "success" else ("orange" if status == "ambiguous" else "red")
        draw.rectangle((x, y, x + w, y + h), outline=color, width=3)
        label = f"{row.get('card_no')}[{row.get('match_mode')}] {row.get('equipment_name') or row.get('equipment_id')} {float(row.get('confidence', 0.0) or 0.0):.2f}"
        draw.text((x, max(0, y - 18)), label, fill=color, font=font)
        stack_roi = [int(value) for value in str(row.get("stack_roi", "0,0,0,0")).split(",")]
        enhance_roi = [int(value) for value in str(row.get("enhance_roi", "0,0,0,0")).split(",")]
        sx, sy, sw, sh = stack_roi
        ex, ey, ew, eh = enhance_roi
        draw.rectangle((sx, sy, sx + sw, sy + sh), outline="cyan", width=1)
        draw.rectangle((ex, ey, ex + ew, ey + eh), outline="magenta", width=1)
        draw.text((x, y + h + 2), f"top1={row.get('equipment_id', '')}", fill=color, font=small_font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def roi_to_text(roi: Roi) -> str:
    """
    把 ROI 转成 CSV 友好的 x,y,w,h 文本。

    输入：
        ROI。
    输出：
        逗号分隔文本。
    使用示例：
        text = roi_to_text((1, 2, 3, 4))
    """
    return ",".join(str(int(value)) for value in roi)


def match_modes_from_arg(raw_mode: str) -> Tuple[str, ...]:
    """
    把 match-mode 参数转成实际执行列表。

    输入：
        raw/clean/both。
    输出：
        ("raw",) / ("clean",) / ("raw", "clean")。
    使用示例：
        modes = match_modes_from_arg("both")
    """
    if raw_mode == "both":
        return ("raw", "clean")
    return (raw_mode,)


def matcher_for_rarity(
    rarity_id: int,
    output_dir: Path,
    catalog: Mapping[str, Mapping[str, str]],
    matchers: Dict[Tuple[int, str], Any],
    top_n: int,
    region_refine: bool,
    gallery_style: str = "normal",
) -> Any:
    """
    按当前装备页稀有度构造/复用 matcher。

    输入：
        rarity_id、gallery_style 和 matcher 缓存。
    输出：
        只包含该稀有度图库的 matcher；rarity_id=0 时使用全图库。
    使用示例：
        matcher = matcher_for_rarity(4, out, catalog, cache, 10, True)
    """
    key = (int(rarity_id or 0), str(gallery_style or "normal"))
    if key not in matchers:
        rarity_key = key[0]
        gallery_dir = output_dir / f"gallery_{key[1]}_rarity_{rarity_key or 'all'}"
        if key[1] == "equipment_erased":
            gallery_csv = build_equipment_erased_gallery_csv(gallery_dir, catalog, rarity_key)
        elif key[1] == "equipment_overlay":
            gallery_csv = build_equipment_overlay_gallery_csv(gallery_dir, catalog, rarity_key)
        else:
            gallery_csv = build_combined_gallery_csv(gallery_dir, catalog, rarity_key)
        matchers[key] = build_icon_matcher(gallery_csv, top_n=int(top_n), region_refine=region_refine)
    return matchers[key]


def build_summary_by_mode(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    按 raw/clean 统计装备页识别结果。

    输入：
        equipment_page_cards.csv 写出前的所有行。
    输出：
        每种 match_mode 的卡片数、success、ambiguous 和 unknown/error。
    使用示例：
        summary = build_summary_by_mode(rows)
    """
    summary: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        mode = str(row.get("match_mode", "") or "unknown")
        status = str(row.get("status", "") or "unknown")
        bucket = summary.setdefault(
            mode,
            {
                "rows": 0,
                "success": 0,
                "ambiguous": 0,
                "unknown_or_error": 0,
                "success_rate": 0.0,
            },
        )
        bucket["rows"] += 1
        if status == "success":
            bucket["success"] += 1
        elif status == "ambiguous":
            bucket["ambiguous"] += 1
        else:
            bucket["unknown_or_error"] += 1

    for bucket in summary.values():
        total = int(bucket.get("rows", 0) or 0)
        bucket["success_rate"] = round(float(bucket.get("success", 0) or 0) / float(total), 4) if total else 0.0
    return summary


def format_summary_lines(summary_by_mode: Mapping[str, Mapping[str, Any]]) -> List[str]:
    """
    把 raw/clean 汇总变成 STATUS.txt 里的可读文本。

    输入：
        build_summary_by_mode 的返回值。
    输出：
        多行中文状态。
    使用示例：
        lines = format_summary_lines(summary)
    """
    lines: List[str] = []
    for mode in ("raw", "clean"):
        if mode not in summary_by_mode:
            continue
        item = summary_by_mode[mode]
        rows = int(item.get("rows", 0) or 0)
        success = int(item.get("success", 0) or 0)
        ambiguous = int(item.get("ambiguous", 0) or 0)
        unknown_or_error = int(item.get("unknown_or_error", 0) or 0)
        rate = float(item.get("success_rate", 0.0) or 0.0) * 100.0
        label = "raw 原始裁剪" if mode == "raw" else "clean 去遮挡裁剪"
        lines.append(f"{label}: success={success}/{rows} ({rate:.1f}%), ambiguous={ambiguous}, unknown/error={unknown_or_error}")
    for mode, item in summary_by_mode.items():
        if mode in {"raw", "clean"}:
            continue
        rows = int(item.get("rows", 0) or 0)
        success = int(item.get("success", 0) or 0)
        ambiguous = int(item.get("ambiguous", 0) or 0)
        unknown_or_error = int(item.get("unknown_or_error", 0) or 0)
        rate = float(item.get("success_rate", 0.0) or 0.0) * 100.0
        lines.append(f"{mode}: success={success}/{rows} ({rate:.1f}%), ambiguous={ambiguous}, unknown/error={unknown_or_error}")
    return lines


def classify_raw_clean_change(raw_row: Mapping[str, Any] | None, clean_row: Mapping[str, Any] | None) -> str:
    """
    判断 clean 相对 raw 是改善、退化还是不变。

    输入：
        同一个 card 的 raw 行和 clean 行。
    输出：
        result_change 文本。
    使用示例：
        change = classify_raw_clean_change(raw, clean)
    """
    if raw_row is None:
        return "clean_only"
    if clean_row is None:
        return "raw_only"
    raw_status = str(raw_row.get("status", "") or "")
    clean_status = str(clean_row.get("status", "") or "")
    raw_name = str(raw_row.get("equipment_name", "") or raw_row.get("equipment_id", "") or "")
    clean_name = str(clean_row.get("equipment_name", "") or clean_row.get("equipment_id", "") or "")
    if raw_status != "success" and clean_status == "success":
        return "clean_improved"
    if raw_status == "success" and clean_status != "success":
        return "clean_regressed"
    if raw_status == "success" and clean_status == "success" and raw_name != clean_name:
        return "both_success_different_name"
    if raw_status == clean_status:
        return "same_status"
    return f"{raw_status}_to_{clean_status}"


def choose_preferred_mode(raw_row: Mapping[str, Any] | None, clean_row: Mapping[str, Any] | None) -> str:
    """
    为同一个 card 选择更适合集成层采信的模式。

    输入：
        raw/clean 两行。
    输出：
        preferred_mode。
    使用示例：
        mode = choose_preferred_mode(raw, clean)
    """
    if clean_row is not None and str(clean_row.get("status", "") or "") == "success":
        return "clean"
    if raw_row is not None and str(raw_row.get("status", "") or "") == "success":
        return "raw"
    if clean_row is not None:
        return "clean"
    return "raw"


def write_comparison_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """
    写出 raw 与 clean 并排对比 CSV。

    输入：
        所有识别行。
    输出：
        equipment_page_raw_vs_clean.csv。
    使用示例：
        write_comparison_csv(path, rows)
    """
    grouped: Dict[Tuple[str, int], Dict[str, Mapping[str, Any]]] = {}
    for row in rows:
        filename = str(row.get("filename", "") or "")
        card_no = int(row.get("card_no", 0) or 0)
        mode = str(row.get("match_mode", "") or "")
        grouped.setdefault((filename, card_no), {})[mode] = row

    compare_rows: List[Dict[str, Any]] = []
    for (filename, card_no), mode_rows in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        raw_row = mode_rows.get("raw")
        clean_row = mode_rows.get("clean")
        base = clean_row or raw_row or {}
        preferred_mode = choose_preferred_mode(raw_row, clean_row)
        preferred_row = mode_rows.get(preferred_mode) or base
        compare_rows.append(
            {
                "filename": filename,
                "page_key": base.get("page_key", ""),
                "filter_rarity": base.get("filter_rarity", ""),
                "filter_rarity_id": base.get("filter_rarity_id", ""),
                "scroll_index": base.get("scroll_index", ""),
                "card_no": card_no,
                "row_index": base.get("row_index", ""),
                "column_index": base.get("column_index", ""),
                "icon_roi": base.get("icon_roi", ""),
                "raw_status": raw_row.get("status", "") if raw_row else "",
                "raw_equipment_id": raw_row.get("equipment_id", "") if raw_row else "",
                "raw_equipment_name": raw_row.get("equipment_name", "") if raw_row else "",
                "raw_confidence": raw_row.get("confidence", "") if raw_row else "",
                "raw_top3": raw_row.get("top3", "") if raw_row else "",
                "clean_status": clean_row.get("status", "") if clean_row else "",
                "clean_equipment_id": clean_row.get("equipment_id", "") if clean_row else "",
                "clean_equipment_name": clean_row.get("equipment_name", "") if clean_row else "",
                "clean_confidence": clean_row.get("confidence", "") if clean_row else "",
                "clean_top3": clean_row.get("top3", "") if clean_row else "",
                "result_change": classify_raw_clean_change(raw_row, clean_row),
                "preferred_mode": preferred_mode,
                "preferred_status": preferred_row.get("status", ""),
                "preferred_equipment_id": preferred_row.get("equipment_id", ""),
                "preferred_equipment_name": preferred_row.get("equipment_name", ""),
                "preferred_confidence": preferred_row.get("confidence", ""),
                "cropped_icon_path": base.get("cropped_icon_path", ""),
                "preferred_match_icon_path": preferred_row.get("cropped_match_icon_path", ""),
            }
        )

    fields = [
        "filename",
        "page_key",
        "filter_rarity",
        "filter_rarity_id",
        "scroll_index",
        "card_no",
        "row_index",
        "column_index",
        "icon_roi",
        "raw_status",
        "raw_equipment_id",
        "raw_equipment_name",
        "raw_confidence",
        "raw_top3",
        "clean_status",
        "clean_equipment_id",
        "clean_equipment_name",
        "clean_confidence",
        "clean_top3",
        "result_change",
        "preferred_mode",
        "preferred_status",
        "preferred_equipment_id",
        "preferred_equipment_name",
        "preferred_confidence",
        "cropped_icon_path",
        "preferred_match_icon_path",
    ]
    write_csv(path, compare_rows, fields)


# ============================================================
# 🚀 第五部分：入口
# ============================================================

def main() -> int:
    """
    执行装备页整页扫描。

    输入：
        02_equipment_page/img_input 中的完整装备页截图。
    输出：
        自动裁剪 icon、整页标注图、CSV/JSON 摘要。
    使用示例：
        python run_equipment_page_scan.py
    """
    args = parse_args()
    input_dir = args.input_dir.resolve()
    images = sorted(path for path in input_dir.glob(str(args.pattern)) if path.is_file())
    images = [path for path in images if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}]
    if not images:
        print(f"没有找到装备页截图: {input_dir} / {args.pattern}")
        return 1
    if cv2 is None:
        print("OpenCV(cv2) 不可用，无法扫描装备页。")
        return 1

    output_dir = output_dir_for(args.output_root.resolve(), args.output_name)
    cropped_dir = output_dir / "cropped_icons"
    match_cropped_dir = output_dir / "cropped_match_icons"
    annotated_dir = output_dir / "annotated"
    output_dir.mkdir(parents=True, exist_ok=True)
    cropped_dir.mkdir(parents=True, exist_ok=True)
    match_cropped_dir.mkdir(parents=True, exist_ok=True)
    annotated_dir.mkdir(parents=True, exist_ok=True)

    catalog = load_equipment_catalog()
    matchers: Dict[Tuple[int, str], Any] = {}
    match_modes = match_modes_from_arg(str(args.match_mode))
    all_rows: List[Dict[str, Any]] = []
    page_state_rows: List[Dict[str, Any]] = []

    for image_path in images:
        image = cv2.imread(str(image_path), getattr(cv2, "IMREAD_COLOR", 1))
        if image is None or getattr(image, "size", 0) == 0:
            print(f"{image_path.name}: 图片无法读取，跳过。")
            continue
        height, width = int(image.shape[0]), int(image.shape[1])
        page_meta = parse_equipment_page_meta(image_path, file_sha1(image_path), int(args.rarity_id))
        matcher = matcher_for_rarity(
            page_meta.filter_rarity_id,
            output_dir,
            catalog,
            matchers,
            int(args.top_n),
            not args.no_region_refine,
            str(args.gallery_style),
        )
        cards = build_equipment_page_cards(width, height)
        page_rows: List[Dict[str, Any]] = []
        page_rows_for_annotation: List[Dict[str, Any]] = []
        for card in cards:
            crop = crop_roi(image, card.icon_roi)
            if not image_has_card_content(crop):
                continue
            crop_name = f"{image_path.stem}_card{card.card_no:02d}_icon.png"
            crop_path = cropped_dir / crop_name
            cv2.imwrite(str(crop_path), crop)
            mode_rows: List[Dict[str, Any]] = []
            for match_mode in match_modes:
                if match_mode == "raw":
                    match_crop = crop
                else:
                    match_crop = sanitize_equipment_icon_crop(crop)
                mode_dir = match_cropped_dir / match_mode
                mode_dir.mkdir(parents=True, exist_ok=True)
                match_crop_path = mode_dir / crop_name
                cv2.imwrite(str(match_crop_path), match_crop)
                result = matcher.match_icon(match_crop, top_n=int(args.top_n)).to_dict()
                equipment_id = str(result.get("equipment_id", "") or "")
                candidates = list(result.get("candidates", []) or [])
                row = {
                    "filename": image_path.name,
                    "page_type": page_meta.page_type,
                    "tab": page_meta.tab,
                    "filter_rarity": page_meta.filter_rarity,
                    "filter_rarity_id": page_meta.filter_rarity_id,
                    "sort_mode": page_meta.sort_mode,
                    "scroll_index": page_meta.scroll_index,
                    "page_key": page_meta.page_key,
                    "screenshot_sha1": page_meta.screenshot_sha1,
                    "card_no": card.card_no,
                    "row_index": card.row_index,
                    "column_index": card.column_index,
                    "match_mode": match_mode,
                    "gallery_style": str(args.gallery_style),
                    "status": str(result.get("status", "") or ""),
                    "equipment_id": equipment_id,
                    "equipment_name": resolve_name(catalog, equipment_id),
                    "confidence": float(result.get("confidence", 0.0) or 0.0),
                    "icon_roi": roi_to_text(card.icon_roi),
                    "enhance_roi": roi_to_text(card.enhance_roi),
                    "stack_roi": roi_to_text(card.stack_roi),
                    "used_overlay_roi": roi_to_text(card.used_overlay_roi),
                    "card_fingerprint": image_fingerprint(match_crop),
                    "cropped_icon_path": str(crop_path),
                    "cropped_match_icon_path": str(match_crop_path),
                    "matched_image_path": str(result.get("matched_image_path", "") or ""),
                    "top3": format_candidates(candidates[:3], catalog),
                    "top_candidates": format_candidates(candidates, catalog),
                    "message": str(result.get("message", "") or ""),
                }
                page_rows.append(row)
                mode_rows.append(row)
                all_rows.append(row)
            preferred_mode = "clean" if "clean" in match_modes else match_modes[-1]
            preferred_rows = [row for row in mode_rows if row["match_mode"] == preferred_mode]
            page_rows_for_annotation.extend(preferred_rows)
        annotate_page(image_path, annotated_dir / f"{image_path.stem}_equipment_page.png", page_rows_for_annotation)
        page_state_rows.append(
            {
                "filename": page_meta.filename,
                "page_type": page_meta.page_type,
                "tab": page_meta.tab,
                "filter_rarity": page_meta.filter_rarity,
                "filter_rarity_id": page_meta.filter_rarity_id,
                "sort_mode": page_meta.sort_mode,
                "scroll_index": page_meta.scroll_index,
                "page_key": page_meta.page_key,
                "screenshot_sha1": page_meta.screenshot_sha1,
                "visible_cards": len({row["card_no"] for row in page_rows}),
                "match_modes": ",".join(match_modes),
                "gallery_style": str(args.gallery_style),
                "raw_success": sum(1 for row in page_rows if row["match_mode"] == "raw" and row["status"] == "success"),
                "clean_success": sum(1 for row in page_rows if row["match_mode"] == "clean" and row["status"] == "success"),
            }
        )
        mode_summary = " ".join(
            f"{mode}=success:{sum(1 for row in page_rows if row['match_mode'] == mode and row['status'] == 'success')}"
            for mode in match_modes
        )
        print(f"{image_path.name}: cards={len({row['card_no'] for row in page_rows})} {mode_summary}")

    fields = [
        "filename",
        "page_type",
        "tab",
        "filter_rarity",
        "filter_rarity_id",
        "sort_mode",
        "scroll_index",
        "page_key",
        "screenshot_sha1",
        "card_no",
        "row_index",
        "column_index",
        "match_mode",
        "gallery_style",
        "status",
        "equipment_id",
        "equipment_name",
        "confidence",
        "icon_roi",
        "enhance_roi",
        "stack_roi",
        "used_overlay_roi",
        "card_fingerprint",
        "cropped_icon_path",
        "cropped_match_icon_path",
        "matched_image_path",
        "top3",
        "top_candidates",
        "message",
    ]
    summary_by_mode = build_summary_by_mode(all_rows)
    summary = {
        "images": len(images),
        "cards": len(all_rows),
        "success": sum(1 for row in all_rows if row["status"] == "success"),
        "ambiguous": sum(1 for row in all_rows if row["status"] == "ambiguous"),
        "unknown_or_error": sum(1 for row in all_rows if row["status"] not in {"success", "ambiguous"}),
        "match_modes": list(match_modes),
        "gallery_style": str(args.gallery_style),
        "by_match_mode": summary_by_mode,
        "output_dir": str(output_dir),
        "gallery_mode": "按装备页文件名稀有度分桶；equipment_erased 表示图库与截图 icon 都抹除动态区域后再匹配。",
        "note": "cards 是按 match_mode 展开后的行数；真实可见卡片数请看 equipment_page_state.csv 的 visible_cards。",
    }
    hard_case_rows = [
        row for row in all_rows
        if str(row.get("status", "")) != "success"
    ]
    write_csv(output_dir / "equipment_page_cards.csv", all_rows, fields)
    write_csv(output_dir / "equipment_page_hard_cases.csv", hard_case_rows, fields)
    write_hard_case_txt(output_dir / "equipment_page_hard_cases.txt", hard_case_rows)
    write_comparison_csv(output_dir / "equipment_page_raw_vs_clean.csv", all_rows)
    state_fields = [
        "filename",
        "page_type",
        "tab",
        "filter_rarity",
        "filter_rarity_id",
        "sort_mode",
        "scroll_index",
        "page_key",
        "screenshot_sha1",
        "visible_cards",
        "match_modes",
        "gallery_style",
        "raw_success",
        "clean_success",
    ]
    write_csv(output_dir / "equipment_page_state.csv", page_state_rows, state_fields)
    write_json(output_dir / "equipment_page_summary.json", {"summary": summary, "page_state": page_state_rows, "rows": all_rows})
    CURRENT_OUT_FILE.write_text(str(output_dir) + "\n", encoding="utf-8")
    STATUS_FILE.write_text(
        "\n".join(
            [
                "02_equipment_page 当前状态",
                "========================",
                "",
                f"输出目录: {output_dir}",
                f"输入图片数量: {summary['images']}",
                f"识别行数量: {summary['cards']}（both 模式会让每个 card 有 raw/clean 两行）",
                f"图库模式: {args.gallery_style}",
                *format_summary_lines(summary_by_mode),
                "",
                f"整页标注图: {annotated_dir}",
                f"自动裁剪 icon: {cropped_dir}",
                f"匹配用去遮挡 icon: {match_cropped_dir}",
                f"CSV: {output_dir / 'equipment_page_cards.csv'}",
                f"raw_vs_clean: {output_dir / 'equipment_page_raw_vs_clean.csv'}",
                f"页面状态/断点: {output_dir / 'equipment_page_state.csv'}",
                f"困难项: {output_dir / 'equipment_page_hard_cases.txt'}",
            ]
        ),
        encoding="utf-8",
    )
    return 0


def write_hard_case_txt(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    """
    写出极简困难项清单，避免用户打开大 CSV。

    输入：
        非 success 行。
    输出：
        equipment_page_hard_cases.txt。
    使用示例：
        write_hard_case_txt(path, hard_rows)
    """
    lines = [
        "装备页困难项清单",
        "==============",
        "",
        "说明：这里只列 status != success 的卡。",
        "如果你要帮我纠错，只需要按下面格式告诉我：",
        "",
        "文件名 card_编号 正确装备名称",
        "",
        "例子：",
        "equip_ultra_rare_scroll_001.png card_04 双联装76mmRF火炮Mk27#T0",
        "",
    ]
    if not rows:
        lines.append("本轮没有困难项。")
    for row in rows:
        lines.extend(
            [
                f"{row.get('filename')} card_{int(row.get('card_no', 0)):02d}",
                f"  status: {row.get('status')}",
                f"  confidence: {float(row.get('confidence', 0.0) or 0.0):.3f}",
                f"  top3: {row.get('top3')}",
                f"  cropped_match_icon: {row.get('cropped_match_icon_path')}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
