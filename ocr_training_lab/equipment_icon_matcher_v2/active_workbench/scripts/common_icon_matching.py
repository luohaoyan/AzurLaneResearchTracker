#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        active_workbench 共用装备图标识别工具                 ║
║                                                              ║
║  【一句话解释】给装备页和 icon-only 测试共用图库与输出逻辑。   ║
║  【类比理解】像一套公共工具箱，避免每个测试入口重复造轮子。    ║
║  【数据流说明】data/images + reviewed → matcher → csv/json。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

try:
    import cv2
except Exception:  # pragma: no cover - 没有 OpenCV 时只禁用合成图库。
    cv2 = None

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - Pillow 缺失时仍可输出 CSV。
    Image = None
    ImageDraw = None
    ImageFont = None


# ============================================================
# 🧱 第二部分：路径解析
# ============================================================

def find_project_root(start: Path) -> Path:
    """
    从脚本位置向上寻找项目根目录。

    输入：
        当前脚本路径。
    输出：
        包含 data/equipment_library.csv 的项目根目录。
    使用示例：
        root = find_project_root(Path(__file__))
    """
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "data" / "equipment_library.csv").exists():
            return candidate
    raise RuntimeError("无法定位项目根目录：未找到 data/equipment_library.csv。")


PROJECT_ROOT = find_project_root(Path(__file__))
V2_DIR = PROJECT_ROOT / "ocr_training_lab" / "equipment_icon_matcher_v2"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.recognition.equipment_icon_matcher import EquipmentIconMatcher  # noqa: E402

EQUIPMENT_LIBRARY_CSV = PROJECT_ROOT / "data" / "equipment_library.csv"
EQUIPMENT_IMAGES_CSV = PROJECT_ROOT / "data" / "equipment_images.csv"
REVIEWED_GALLERY_CSV = V2_DIR / "reviewed_icon_gallery" / "reviewed_icon_gallery_manifest.csv"
ACCEPTED_GALLERY_CSV = V2_DIR / "accepted_icon_gallery" / "accepted_icon_gallery_manifest.csv"
FONT_PATHS = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
)


# ============================================================
# 🏗️ 第三部分：图库与 matcher
# ============================================================

def load_equipment_catalog() -> Dict[str, Dict[str, str]]:
    """
    读取装备库 CSV，供 ID → 名称转换。

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


def resolve_name(catalog: Mapping[str, Mapping[str, str]], equipment_id: str) -> str:
    """
    根据 equipment_id 读取当前装备名称。

    输入：
        catalog 和 equipment_id。
    输出：
        装备名称。
    使用示例：
        name = resolve_name(catalog, "G0106")
    """
    return str(catalog.get(equipment_id, {}).get("name", "") or "")


def build_combined_gallery_csv(output_dir: Path, catalog: Mapping[str, Mapping[str, str]], rarity_id: int = 0) -> Path:
    """
    合并 data/images、reviewed_gallery 和 accepted_gallery。

    输入：
        输出目录、装备 catalog、可选 rarity_id。
    输出：
        本轮临时图库 CSV。
    使用示例：
        gallery = build_combined_gallery_csv(output_dir, catalog, 4)
    """
    rows: List[Dict[str, str]] = []
    for csv_path, source in (
        (EQUIPMENT_IMAGES_CSV, "data_images"),
        (REVIEWED_GALLERY_CSV, "reviewed_gallery"),
        (ACCEPTED_GALLERY_CSV, "accepted_gallery"),
    ):
        if not csv_path.exists():
            continue
        with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                equipment_id = str(row.get("equipment_id", "") or "").strip()
                if not equipment_id:
                    continue
                catalog_row = catalog.get(equipment_id, {})
                if rarity_id > 0 and int(catalog_row.get("rarity_id", 0) or 0) != int(rarity_id):
                    continue
                image_path = str(row.get("image_path", "") or "").strip()
                if not image_path:
                    continue
                resolved = Path(image_path)
                if not resolved.is_absolute():
                    resolved = PROJECT_ROOT / resolved
                if resolved.exists():
                    rows.append({"equipment_id": equipment_id, "image_path": str(resolved), "source": source})

    output_dir.mkdir(parents=True, exist_ok=True)
    gallery_csv = output_dir / "combined_icon_gallery.csv"
    with gallery_csv.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["equipment_id", "image_path", "source"])
        writer.writeheader()
        writer.writerows(rows)
    return gallery_csv


def load_gallery_source_rows(catalog: Mapping[str, Mapping[str, str]], rarity_id: int = 0) -> List[Dict[str, str]]:
    """
    读取 data/images、reviewed_gallery 和 accepted_gallery 的图库源行。

    输入：
        装备 catalog 和可选 rarity_id。
    输出：
        已解析绝对路径的图库行。
    使用示例：
        rows = load_gallery_source_rows(catalog, 4)
    """
    rows: List[Dict[str, str]] = []
    for csv_path, source in (
        (EQUIPMENT_IMAGES_CSV, "data_images"),
        (REVIEWED_GALLERY_CSV, "reviewed_gallery"),
        (ACCEPTED_GALLERY_CSV, "accepted_gallery"),
    ):
        if not csv_path.exists():
            continue
        with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                equipment_id = str(row.get("equipment_id", "") or "").strip()
                if not equipment_id:
                    continue
                catalog_row = catalog.get(equipment_id, {})
                if rarity_id > 0 and int(catalog_row.get("rarity_id", 0) or 0) != int(rarity_id):
                    continue
                image_path = str(row.get("image_path", "") or "").strip()
                if not image_path:
                    continue
                resolved = Path(image_path)
                if not resolved.is_absolute():
                    resolved = PROJECT_ROOT / resolved
                if resolved.exists():
                    rows.append({"equipment_id": equipment_id, "image_path": str(resolved), "source": source})
    return rows


def build_equipment_overlay_gallery_csv(
    output_dir: Path,
    catalog: Mapping[str, Mapping[str, str]],
    rarity_id: int = 0,
) -> Path:
    """
    构造装备页专用“合成遮挡图库”。

    输入：
        标准装备图库和稀有度。
    输出：
        包含原图 + 装备页遮挡增强图的 CSV。
    使用示例：
        gallery = build_equipment_overlay_gallery_csv(out, catalog, 4)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    augmented_dir = output_dir / "equipment_overlay_augmented"
    augmented_dir.mkdir(parents=True, exist_ok=True)
    source_rows = load_gallery_source_rows(catalog, rarity_id)
    gallery_rows: List[Dict[str, str]] = []

    for row in source_rows:
        equipment_id = row["equipment_id"]
        image_path = Path(row["image_path"])
        gallery_rows.append({"equipment_id": equipment_id, "image_path": str(image_path), "source": f"{row['source']}:original"})
        if cv2 is None:
            continue
        image = cv2.imread(str(image_path), getattr(cv2, "IMREAD_COLOR", 1))
        if image is None or getattr(image, "size", 0) == 0:
            continue
        for variant_name, variant_image in make_equipment_overlay_variants(image).items():
            variant_path = augmented_dir / f"{equipment_id}_{image_path.stem}_{variant_name}.png"
            cv2.imwrite(str(variant_path), variant_image)
            gallery_rows.append(
                {
                    "equipment_id": equipment_id,
                    "image_path": str(variant_path),
                    "source": f"{row['source']}:synthetic_{variant_name}",
                }
            )

    gallery_csv = output_dir / "equipment_overlay_icon_gallery.csv"
    with gallery_csv.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["equipment_id", "image_path", "source"])
        writer.writeheader()
        writer.writerows(gallery_rows)
    return gallery_csv


def build_equipment_erased_gallery_csv(
    output_dir: Path,
    catalog: Mapping[str, Mapping[str, str]],
    rarity_id: int = 0,
) -> Path:
    """
    构造装备页专用“动态区域抹除图库”。

    输入：
        标准装备图库和稀有度。
    输出：
        每张图库图都抹掉右上/左下/右下动态区后的 CSV。
    使用示例：
        gallery = build_equipment_erased_gallery_csv(out, catalog, 4)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    erased_dir = output_dir / "equipment_erased_references"
    erased_dir.mkdir(parents=True, exist_ok=True)
    source_rows = load_gallery_source_rows(catalog, rarity_id)
    gallery_rows: List[Dict[str, str]] = []

    for row in source_rows:
        equipment_id = row["equipment_id"]
        image_path = Path(row["image_path"])
        if cv2 is None:
            gallery_rows.append({"equipment_id": equipment_id, "image_path": str(image_path), "source": f"{row['source']}:original_cv2_unavailable"})
            continue
        image = cv2.imread(str(image_path), getattr(cv2, "IMREAD_COLOR", 1))
        if image is None or getattr(image, "size", 0) == 0:
            continue
        erased = erase_equipment_dynamic_regions(image, crop_inset=True)
        erased_path = erased_dir / f"{equipment_id}_{image_path.stem}_erased.png"
        cv2.imwrite(str(erased_path), erased)
        gallery_rows.append({"equipment_id": equipment_id, "image_path": str(erased_path), "source": f"{row['source']}:dynamic_erased"})

    gallery_csv = output_dir / "equipment_erased_icon_gallery.csv"
    with gallery_csv.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["equipment_id", "image_path", "source"])
        writer.writeheader()
        writer.writerows(gallery_rows)
    return gallery_csv


def erase_equipment_dynamic_regions(image: Any, crop_inset: bool = True) -> Any:
    """
    抹除装备页 icon 的动态区域。

    输入：
        装备页裁剪 icon 或 data/images 标准图。
    输出：
        右上小人、左下强化、右下堆叠数量区域被局部均值填充后的图。
    使用示例：
        clean = erase_equipment_dynamic_regions(icon)
    """
    if image is None or getattr(image, "size", 0) == 0:
        return image
    cleaned = image.copy()
    height, width = int(cleaned.shape[0]), int(cleaned.shape[1])

    dynamic_regions = (
        # 右上角“装备中”头像区。
        (int(width * 0.76), 0, int(width * 0.24), int(height * 0.34)),
        # 左下角强化等级区。
        (0, int(height * 0.55), int(width * 0.36), int(height * 0.23)),
        # 右下角堆叠数量区；数量后续单独 OCR，这里只为 icon 匹配抹除。
        (int(width * 0.78), int(height * 0.60), int(width * 0.22), int(height * 0.32)),
    )
    for region in dynamic_regions:
        fill_region_with_local_average(cleaned, region)

    if not crop_inset:
        return cleaned
    inset_x = max(0, int(round(width * 0.015)))
    inset_y = max(0, int(round(height * 0.015)))
    inset_w = max(1, width - inset_x * 2)
    inset_h = max(1, height - inset_y * 2)
    return cleaned[inset_y:inset_y + inset_h, inset_x:inset_x + inset_w]


def fill_region_with_local_average(image: Any, roi: Sequence[int]) -> None:
    """
    用局部平均色填充指定区域。

    输入：
        OpenCV 图像和 x,y,w,h。
    输出：
        原图就地修改。
    使用示例：
        fill_region_with_local_average(icon, (100, 0, 32, 44))
    """
    if image is None or getattr(image, "size", 0) == 0:
        return
    x, y, width, height = (int(value) for value in roi)
    image_height, image_width = int(image.shape[0]), int(image.shape[1])
    x = min(max(0, x), max(0, image_width - 1))
    y = min(max(0, y), max(0, image_height - 1))
    width = max(1, min(width, image_width - x))
    height = max(1, min(height, image_height - y))
    pad = max(3, int(round(min(image_width, image_height) * 0.045)))
    sample_x0 = max(0, x - pad)
    sample_y0 = max(0, y - pad)
    sample_x1 = min(image_width, x + width + pad)
    sample_y1 = min(image_height, y + height + pad)
    sample = image[sample_y0:sample_y1, sample_x0:sample_x1]
    if sample is None or getattr(sample, "size", 0) == 0:
        return
    fill = sample.reshape(-1, sample.shape[-1]).mean(axis=0)
    image[y:y + height, x:x + width] = fill


def make_equipment_overlay_variants(image: Any) -> Dict[str, Any]:
    """
    给标准装备图标合成装备页常见动态遮挡。

    输入：
        data/images 或人工 accepted 图标。
    输出：
        多个遮挡变体。
    使用示例：
        variants = make_equipment_overlay_variants(icon)
    """
    if cv2 is None or image is None or getattr(image, "size", 0) == 0:
        return {}
    variants: Dict[str, Any] = {}
    base = image.copy()
    variants["used_avatar"] = apply_equipment_used_avatar(base.copy())
    variants["enhance_stack"] = apply_equipment_enhance_stack(base.copy())
    variants["used_enhance_stack"] = apply_equipment_enhance_stack(apply_equipment_used_avatar(base.copy()))
    variants["heavy_occlusion"] = apply_equipment_heavy_occlusion(base.copy())
    return variants


def apply_equipment_used_avatar(image: Any) -> Any:
    """
    在右上角合成“装备中”小人头像遮挡。

    输入：
        图标。
    输出：
        右上角带遮挡的图标。
    使用示例：
        out = apply_equipment_used_avatar(icon)
    """
    if cv2 is None:
        return image
    height, width = int(image.shape[0]), int(image.shape[1])
    center = (int(width * 0.86), int(height * 0.14))
    radius = max(7, int(min(width, height) * 0.16))
    cv2.circle(image, center, radius + 2, (40, 40, 40), thickness=-1)
    cv2.circle(image, center, radius, (210, 210, 210), thickness=-1)
    cv2.circle(image, (center[0] - radius // 3, center[1] - radius // 4), max(2, radius // 4), (120, 150, 210), thickness=-1)
    cv2.circle(image, (center[0] + radius // 3, center[1] - radius // 4), max(2, radius // 4), (120, 150, 210), thickness=-1)
    cv2.ellipse(image, (center[0], center[1] + radius // 4), (radius // 2, radius // 3), 0, 0, 180, (120, 150, 210), thickness=2)
    return image


def apply_equipment_enhance_stack(image: Any) -> Any:
    """
    合成左下强化等级和右下堆叠数量。

    输入：
        图标。
    输出：
        底部带数字遮挡的图标。
    使用示例：
        out = apply_equipment_enhance_stack(icon)
    """
    if cv2 is None:
        return image
    height, width = int(image.shape[0]), int(image.shape[1])
    # 左下角强化等级：黑色半透明底 + 白/黄文字，模拟 +10/+13。
    overlay = image.copy()
    cv2.rectangle(overlay, (0, int(height * 0.62)), (int(width * 0.34), int(height * 0.86)), (0, 0, 0), thickness=-1)
    image[:] = cv2.addWeighted(overlay, 0.62, image, 0.38, 0)
    cv2.putText(
        image,
        "+10",
        (max(1, int(width * 0.02)), int(height * 0.81)),
        getattr(cv2, "FONT_HERSHEY_SIMPLEX", 0),
        max(0.32, width / 220.0),
        (255, 235, 110),
        max(1, int(width / 60)),
        getattr(cv2, "LINE_AA", 16),
    )
    # 右下角堆叠数量：游戏里很常见的白字黑描边。
    text = "1"
    pos = (int(width * 0.82), int(height * 0.88))
    cv2.putText(image, text, pos, getattr(cv2, "FONT_HERSHEY_SIMPLEX", 0), max(0.52, width / 170.0), (0, 0, 0), max(2, int(width / 42)), getattr(cv2, "LINE_AA", 16))
    cv2.putText(image, text, pos, getattr(cv2, "FONT_HERSHEY_SIMPLEX", 0), max(0.52, width / 170.0), (255, 255, 255), max(1, int(width / 70)), getattr(cv2, "LINE_AA", 16))
    return image


def apply_equipment_heavy_occlusion(image: Any) -> Any:
    """
    合成更重一点的装备页遮挡，专门测试困难装备鲁棒性。

    输入：
        图标。
    输出：
        头像、强化等级、堆叠数量都更明显的图标。
    使用示例：
        out = apply_equipment_heavy_occlusion(icon)
    """
    image = apply_equipment_used_avatar(image)
    image = apply_equipment_enhance_stack(image)
    if cv2 is None:
        return image
    height, width = int(image.shape[0]), int(image.shape[1])
    cv2.rectangle(image, (int(width * 0.78), int(height * 0.74)), (width - 1, height - 1), (20, 20, 20), thickness=1)
    return image


def build_icon_matcher(gallery_csv: Path, top_n: int = 10, region_refine: bool = True) -> EquipmentIconMatcher:
    """
    构造装备 icon matcher。

    输入：
        合并图库 CSV、top_n、是否启用遮挡分块精排。
    输出：
        EquipmentIconMatcher。
    使用示例：
        matcher = build_icon_matcher(gallery, 10, True)
    """
    config: Dict[str, Any] = {
        "gallery_csv_path": str(gallery_csv),
        "threshold": 0.60,
        "ambiguous_margin": 0.012,
        "top_n": int(top_n),
        "target_size": [96, 96],
        "min_icon_size": [12, 12],
        "structure_weight": 0.42,
        "color_weight": 0.19,
        "edge_weight": 0.24,
        "hash_weight": 0.07,
        # 装备页可能有强化等级、堆叠数量、装备中头像遮挡，所以默认启用分块精排。
        "region_weight": 0.08 if region_refine else 0.0,
        "region_grid": [3, 3],
        "region_keep_ratio": 0.72,
        "region_refine_top_k": 32,
    }
    return EquipmentIconMatcher(config=config, gallery_csv_path=gallery_csv, project_root=PROJECT_ROOT)


# ============================================================
# 🎨 第四部分：输出工具
# ============================================================

def format_candidates(candidates: Sequence[Mapping[str, Any]], catalog: Mapping[str, Mapping[str, str]]) -> str:
    """
    把候选列表格式化成单行文本。

    输入：
        matcher candidates。
    输出：
        "G0106:四联装610mm鱼雷#T3:0.899 | ..."。
    使用示例：
        text = format_candidates(candidates, catalog)
    """
    chunks: List[str] = []
    for item in candidates:
        equipment_id = str(item.get("equipment_id", "") or "")
        confidence = float(item.get("confidence", 0.0) or 0.0)
        chunks.append(f"{equipment_id}:{resolve_name(catalog, equipment_id)}:{confidence:.3f}")
    return " | ".join(chunks)


def load_font(size: int) -> Any:
    """
    加载中文字体；失败时使用 Pillow 默认字体。

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


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """
    写出 UTF-8 JSON。

    输入：
        路径和 payload。
    输出：
        JSON 文件。
    使用示例：
        write_json(path, {"ok": True})
    """
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    """
    写出 UTF-8-SIG CSV，方便 Excel 直接打开。

    输入：
        路径、行、字段名。
    输出：
        CSV 文件。
    使用示例：
        write_csv(path, rows, ["filename", "status"])
    """
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def annotate_single_icon(image_path: Path, output_path: Path, row: Mapping[str, Any]) -> None:
    """
    给单个 icon 生成轻量标注图。

    输入：
        原图、输出图、识别结果行。
    输出：
        annotated png。
    使用示例：
        annotate_single_icon(path, out, row)
    """
    if Image is None or ImageDraw is None:
        return
    try:
        source = Image.open(image_path).convert("RGB")
    except Exception:
        return
    canvas_width = max(source.width, 860)
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
