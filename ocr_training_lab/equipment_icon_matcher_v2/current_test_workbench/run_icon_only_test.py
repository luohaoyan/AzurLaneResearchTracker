#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      equipment_icon_matcher_v2 独立图标测试入口              ║
║                                                              ║
║  【一句话解释】只测试装备 icon 本体，不经过碎片卡片检测。      ║
║  【类比理解】像把装备小头像单独拿出来，对着图鉴逐张认。        ║
║  【数据流说明】icon_input → EquipmentIconMatcher → icon_out。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

try:
    import cv2
except Exception:  # pragma: no cover - 本地缺 OpenCV 时由状态文件提示。
    cv2 = None

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - Pillow 缺失时仍输出 CSV/JSON。
    Image = None
    ImageDraw = None
    ImageFont = None

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# ============================================================
# 🧱 第二部分：路径常量
# ============================================================

THIS_DIR = Path(__file__).resolve().parent
V2_DIR = THIS_DIR.parent
PROJECT_ROOT = V2_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.recognition.equipment_icon_matcher import EquipmentIconMatcher  # noqa: E402

DEFAULT_INPUT_DIR = THIS_DIR / "icon_input"
DEFAULT_OUTPUT_ROOT = THIS_DIR / "icon_out"
DEFAULT_REVIEWED_GALLERY_CSV = V2_DIR / "reviewed_icon_gallery" / "reviewed_icon_gallery_manifest.csv"
DEFAULT_ACCEPTED_GALLERY_CSV = V2_DIR / "accepted_icon_gallery" / "accepted_icon_gallery_manifest.csv"
EQUIPMENT_LIBRARY_CSV = PROJECT_ROOT / "data" / "equipment_library.csv"
EQUIPMENT_IMAGES_CSV = PROJECT_ROOT / "data" / "equipment_images.csv"
ICON_ONLY_CURRENT_OUT = THIS_DIR / "ICON_ONLY_CURRENT_OUT.txt"
ICON_ONLY_CURRENT_STATUS = THIS_DIR / "ICON_ONLY_CURRENT_STATUS.txt"
ICON_ONLY_UPDATE_LOG = THIS_DIR / "ICON_ONLY_UPDATE_LOG.txt"
FONT_PATHS = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
)


# ============================================================
# 🏗️ 第三部分：参数与数据加载
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析独立 icon 测试参数。

    输入：
        命令行参数。
    输出：
        argparse.Namespace。
    使用示例：
        python run_icon_only_test.py --rarity-id 4
    """
    parser = argparse.ArgumentParser(description="独立装备 icon 识别测试；输入应为裁剪好的单个装备图标。")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR, help="裁剪 icon 输入目录。")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="输出根目录。")
    parser.add_argument("--output-name", default="", help="输出目录名；默认 run_yyyyMMdd_HHmmss。")
    parser.add_argument("--pattern", default="*.png", help="图片匹配模式，默认 *.png。")
    parser.add_argument("--top-n", type=int, default=10, help="每张 icon 输出 top-N 候选。")
    parser.add_argument("--rarity-id", type=int, default=0, help="可选稀有度过滤：3紫/4金/5彩；0 表示不过滤。")
    parser.add_argument("--threshold", type=float, default=0.60, help="图标成功阈值。")
    parser.add_argument("--ambiguous-margin", type=float, default=0.012, help="不同装备 top 分差小于该值时标 ambiguous。")
    parser.add_argument("--enable-region-refine", action="store_true", help="启用分块精排；装备页遮挡图标建议打开。")
    return parser.parse_args()


def build_output_dir(output_root: Path, output_name: str) -> Path:
    """
    构造本轮输出目录。

    输入：
        output_root 和可选 output_name。
    输出：
        icon_out/run_xxx。
    使用示例：
        output_dir = build_output_dir(Path("icon_out"), "")
    """
    name = output_name.strip() or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return output_root / name


def load_equipment_catalog() -> Dict[str, Dict[str, str]]:
    """
    读取 equipment_library.csv，给候选 ID 补装备名和稀有度。

    输入：
        data/equipment_library.csv。
    输出：
        equipment_id → row。
    使用示例：
        catalog = load_equipment_catalog()
    """
    catalog: Dict[str, Dict[str, str]] = {}
    with EQUIPMENT_LIBRARY_CSV.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            equipment_id = str(row.get("equipment_id", "") or "").strip()
            if equipment_id:
                catalog[equipment_id] = dict(row)
    return catalog


def build_combined_gallery_csv(output_dir: Path, catalog: Mapping[str, Mapping[str, str]], rarity_id: int) -> Path:
    """
    合并 data/images、人工 reviewed 图库和 accepted 图库，供独立 icon 匹配使用。

    输入：
        输出目录、装备 catalog、可选 rarity_id。
    输出：
        本轮临时 gallery CSV。
    使用示例：
        gallery_csv = build_combined_gallery_csv(output_dir, catalog, 4)
    """
    rows: List[Dict[str, str]] = []
    source_csvs = (
        (EQUIPMENT_IMAGES_CSV, "data_images"),
        (DEFAULT_REVIEWED_GALLERY_CSV, "reviewed_gallery"),
        (DEFAULT_ACCEPTED_GALLERY_CSV, "accepted_gallery"),
    )
    for csv_path, source in source_csvs:
        if not csv_path.exists():
            continue
        with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                equipment_id = str(row.get("equipment_id", "") or "").strip()
                if not equipment_id:
                    continue
                catalog_row = catalog.get(equipment_id, {})
                if rarity_id > 0 and int(catalog_row.get("rarity_id", 0) or 0) != rarity_id:
                    continue
                image_path = str(row.get("image_path", "") or "").strip()
                if not image_path:
                    continue
                resolved = Path(image_path)
                if not resolved.is_absolute():
                    resolved = PROJECT_ROOT / resolved
                if resolved.exists():
                    rows.append({"equipment_id": equipment_id, "image_path": str(resolved), "source": source})

    gallery_csv = output_dir / "icon_only_combined_gallery.csv"
    with gallery_csv.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["equipment_id", "image_path", "source"])
        writer.writeheader()
        writer.writerows(rows)
    return gallery_csv


def build_matcher(gallery_csv: Path, args: argparse.Namespace) -> EquipmentIconMatcher:
    """
    构造独立 icon matcher。

    输入：
        合并图库 CSV 和参数。
    输出：
        EquipmentIconMatcher。
    使用示例：
        matcher = build_matcher(gallery_csv, args)
    """
    config: Dict[str, Any] = {
        "gallery_csv_path": str(gallery_csv),
        "threshold": float(args.threshold),
        "ambiguous_margin": float(args.ambiguous_margin),
        "top_n": int(args.top_n),
        "target_size": [96, 96],
        "min_icon_size": [12, 12],
        "structure_weight": 0.42,
        "color_weight": 0.19,
        "edge_weight": 0.24,
        "hash_weight": 0.07,
        "region_weight": 0.08 if args.enable_region_refine else 0.0,
        "region_grid": [3, 3],
        "region_keep_ratio": 0.72,
        "region_refine_top_k": 32,
    }
    return EquipmentIconMatcher(config=config, gallery_csv_path=gallery_csv, project_root=PROJECT_ROOT)


# ============================================================
# 🎨 第四部分：输出与标注图
# ============================================================

def resolve_name(catalog: Mapping[str, Mapping[str, str]], equipment_id: str) -> str:
    """
    通过 equipment_id 找当前装备名。

    输入：
        catalog 和 equipment_id。
    输出：
        装备名，找不到时为空。
    使用示例：
        name = resolve_name(catalog, "G0106")
    """
    return str(catalog.get(equipment_id, {}).get("name", "") or "")


def candidate_text(candidates: Sequence[Mapping[str, Any]], catalog: Mapping[str, Mapping[str, str]]) -> str:
    """
    格式化 top 候选，方便 CSV 和状态文件查看。

    输入：
        matcher candidates。
    输出：
        "G0106:四联装610mm鱼雷#T3:0.899 | ..."。
    使用示例：
        text = candidate_text(result["candidates"], catalog)
    """
    chunks: List[str] = []
    for item in candidates:
        equipment_id = str(item.get("equipment_id", "") or "")
        confidence = float(item.get("confidence", 0.0) or 0.0)
        name = resolve_name(catalog, equipment_id)
        chunks.append(f"{equipment_id}:{name}:{confidence:.3f}")
    return " | ".join(chunks)


def annotate_icon(image_path: Path, output_path: Path, row: Mapping[str, Any]) -> None:
    """
    给单张 icon 输出一个轻量标注图。

    输入：
        原图路径、输出路径、识别行。
    输出：
        annotated/*.png。
    使用示例：
        annotate_icon(path, out, row)
    """
    if Image is None or ImageDraw is None:
        return
    try:
        source = Image.open(image_path).convert("RGB")
    except Exception:
        return

    canvas_width = max(source.width, 820)
    canvas_height = source.height + 150
    canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
    canvas.paste(source, (0, 0))
    draw = ImageDraw.Draw(canvas)
    font = load_font(18)
    small_font = load_font(15)
    status = str(row.get("status", ""))
    color = "green" if status == "success" else ("orange" if status == "ambiguous" else "red")
    draw.rectangle((0, 0, source.width - 1, source.height - 1), outline=color, width=4)
    draw.text((8, source.height + 8), f"status={status} conf={float(row.get('confidence', 0.0) or 0.0):.3f}", fill=color, font=font)
    draw.text((8, source.height + 36), f"id={row.get('equipment_id', '')} name={row.get('equipment_name', '')}", fill="black", font=font)
    draw.text((8, source.height + 66), f"top3={row.get('top3', '')}", fill="black", font=small_font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)


def load_font(size: int) -> Any:
    """
    加载 Windows 中文字体；失败时退回 Pillow 默认字体。

    输入：
        字号。
    输出：
        ImageFont。
    使用示例：
        font = load_font(18)
    """
    if ImageFont is None:
        return None
    for path in FONT_PATHS:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def write_outputs(output_dir: Path, rows: Sequence[Mapping[str, Any]], summary: Mapping[str, Any]) -> None:
    """
    写出 CSV、JSON 和状态文件。

    输入：
        输出目录、识别行、摘要。
    输出：
        icon_only_results.csv/json、ICON_ONLY_CURRENT_STATUS.txt。
    使用示例：
        write_outputs(output_dir, rows, summary)
    """
    fieldnames = [
        "filename",
        "status",
        "equipment_id",
        "equipment_name",
        "confidence",
        "matched_image_path",
        "top3",
        "top_candidates",
        "message",
    ]
    with (output_dir / "icon_only_results.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    (output_dir / "icon_only_results.json").write_text(
        json.dumps({"summary": dict(summary), "rows": list(rows)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "equipment_icon_matcher_v2 icon-only 当前状态",
        "==========================================",
        "",
        f"更新时间: {summary.get('updated_at', '')}",
        f"输入图片数量: {summary.get('images', 0)}",
        f"success: {summary.get('success', 0)}",
        f"ambiguous: {summary.get('ambiguous', 0)}",
        f"unknown/error: {summary.get('unknown_or_error', 0)}",
        f"输出目录: {output_dir}",
        "",
        "重点查看:",
        f"  标注图: {output_dir / 'annotated'}",
        f"  结果CSV: {output_dir / 'icon_only_results.csv'}",
        f"  结果JSON: {output_dir / 'icon_only_results.json'}",
        "",
        "说明:",
        "  icon-only 只识别裁剪好的装备 icon，不检测碎片框/装备框。",
        "  如果这里识别正确，而整页截图识别错误，问题在页面卡片定位，不在 icon matcher。",
    ]
    ICON_ONLY_CURRENT_OUT.write_text(str(output_dir) + "\n", encoding="utf-8")
    ICON_ONLY_CURRENT_STATUS.write_text("\n".join(lines), encoding="utf-8")
    with ICON_ONLY_UPDATE_LOG.open("a", encoding="utf-8") as file:
        file.write(f"[{summary.get('updated_at', '')}] output={output_dir} images={summary.get('images', 0)} success={summary.get('success', 0)} ambiguous={summary.get('ambiguous', 0)} unknown_or_error={summary.get('unknown_or_error', 0)}\n")


# ============================================================
# 🚀 第五部分：命令入口
# ============================================================

def iter_images(input_dir: Path, pattern: str) -> Iterable[Path]:
    """
    遍历输入 icon 图片。

    输入：
        input_dir 和 glob pattern。
    输出：
        图片路径迭代器。
    使用示例：
        for path in iter_images(Path("icon_input"), "*.png"): ...
    """
    suffixes = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    for path in sorted(input_dir.glob(pattern)):
        if path.is_file() and path.suffix.lower() in suffixes:
            yield path


def main() -> int:
    """
    执行独立 icon 测试。

    输入：
        icon_input 里的裁剪图标。
    输出：
        icon_out/run_xxx 和 ICON_ONLY_CURRENT_STATUS.txt。
    使用示例：
        python run_icon_only_test.py
    """
    args = parse_args()
    input_dir = args.input_dir.resolve()
    if not input_dir.exists():
        print(f"输入目录不存在: {input_dir}")
        return 1
    images = list(iter_images(input_dir, str(args.pattern)))
    if not images:
        print(f"没有找到 icon 图片: {input_dir} / {args.pattern}")
        print("请把裁剪好的单个装备 icon 放进 current_test_workbench/icon_input。")
        return 1

    output_dir = build_output_dir(args.output_root.resolve(), args.output_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "annotated").mkdir(parents=True, exist_ok=True)
    catalog = load_equipment_catalog()
    gallery_csv = build_combined_gallery_csv(output_dir, catalog, int(args.rarity_id))
    matcher = build_matcher(gallery_csv, args)

    rows: List[Dict[str, Any]] = []
    for image_path in images:
        if cv2 is None:
            result = {"status": "unavailable", "message": "OpenCV(cv2) 不可用。", "equipment_id": "", "confidence": 0.0, "candidates": []}
        else:
            image = cv2.imread(str(image_path), getattr(cv2, "IMREAD_COLOR", 1))
            if image is None or getattr(image, "size", 0) == 0:
                result = {"status": "error", "message": "图片无法读取或已损坏。", "equipment_id": "", "confidence": 0.0, "candidates": []}
            else:
                result = matcher.match_icon(image, top_n=int(args.top_n)).to_dict()
        equipment_id = str(result.get("equipment_id", "") or "")
        candidates = list(result.get("candidates", []) or [])
        row = {
            "filename": image_path.name,
            "status": str(result.get("status", "") or ""),
            "equipment_id": equipment_id,
            "equipment_name": resolve_name(catalog, equipment_id),
            "confidence": float(result.get("confidence", 0.0) or 0.0),
            "matched_image_path": str(result.get("matched_image_path", "") or ""),
            "top3": candidate_text(candidates[:3], catalog),
            "top_candidates": candidate_text(candidates, catalog),
            "message": str(result.get("message", "") or ""),
        }
        rows.append(row)
        annotate_icon(image_path, output_dir / "annotated" / f"{image_path.stem}_icon_only.png", row)
        print(f"{image_path.name}: {row['status']} {row['equipment_id']} {row['equipment_name']} {row['confidence']:.3f}")

    summary = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "images": len(rows),
        "success": sum(1 for row in rows if row["status"] == "success"),
        "ambiguous": sum(1 for row in rows if row["status"] == "ambiguous"),
        "unknown_or_error": sum(1 for row in rows if row["status"] not in {"success", "ambiguous"}),
        "rarity_id": int(args.rarity_id),
        "gallery_csv": str(gallery_csv),
    }
    write_outputs(output_dir, rows, summary)
    print("icon-only 测试完成。请查看：")
    print(f"- 状态: {ICON_ONLY_CURRENT_STATUS}")
    print(f"- 标注图: {output_dir / 'annotated'}")
    print(f"- CSV: {output_dir / 'icon_only_results.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
