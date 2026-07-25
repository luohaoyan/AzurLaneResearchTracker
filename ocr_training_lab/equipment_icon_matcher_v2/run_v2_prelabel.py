#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      装备图标 v2 截图预标注脚本                              ║
║                                                              ║
║  【一句话解释】批量处理 v2_scroll 截图，生成可人工修正的标注。 ║
║  【类比理解】它像先用机器把作业写一遍，再把不确定题圈出来。  ║
║  【数据流说明】img_input → img_out/prelabel 标注图/CSV/草稿。 ║
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
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - Pillow 缺失时退回 OpenCV 英文绘字。
    Image = None
    ImageDraw = None
    ImageFont = None

try:
    import numpy as np
except Exception:  # pragma: no cover - 无 NumPy 时 draw fallback 会接管。
    np = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
FRAGMENT_SCAN_DIR = PROJECT_ROOT / "ocr_training_lab" / "fragment_filter_scan"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(FRAGMENT_SCAN_DIR) not in sys.path:
    sys.path.insert(0, str(FRAGMENT_SCAN_DIR))

from core.recognition.design_fragment_detector import (  # noqa: E402
    DesignFragmentCardCandidate,
    DesignFragmentDetectionResult,
    DesignFragmentDetector,
)
from core.recognition.equipment_card_reader import EquipmentCardDigitReader  # noqa: E402
from core.recognition.equipment_attribute_reranker import (  # noqa: E402
    EquipmentAttributeReranker,
    format_attribute_candidates,
)
from core.recognition.equipment_icon_matcher import EquipmentIconMatcher  # noqa: E402
from core.recognition.equipment_name_resolver import EquipmentNameResolver, normalize_equipment_base_name  # noqa: E402
from core.recognition.ocr_engine import OcrEngine  # noqa: E402
from core.recognition.preview_renderer import draw_unicode_labels as render_unicode_labels  # noqa: E402
from run_rarity_bucket_detection import (  # noqa: E402
    RARITY_TO_ID,
    _relative_child_roi,
    load_equipment_catalog,
    load_recognition_config,
    normalize_rarity,
)


warnings.filterwarnings("ignore", message="No ccache found.*", category=UserWarning)


# ============================================================
# 🧱 第二部分：数据对象与常量
# ============================================================

RoiRegion = Tuple[int, int, int, int]

DEFAULT_INPUT_DIR = SCRIPT_DIR / "img_input"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "img_out" / "prelabel"
DEFAULT_ACCEPTED_GALLERY_CSV = SCRIPT_DIR / "accepted_icon_gallery" / "accepted_icon_gallery_manifest.csv"
DEFAULT_REVIEWED_GALLERY_CSV = SCRIPT_DIR / "reviewed_icon_gallery" / "reviewed_icon_gallery_manifest.csv"
DEFAULT_FONT_PATHS = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
)
NAME_RATIO: Tuple[float, float, float, float] = (0.385, 0.040, 0.350, 0.235)
DEFAULT_HIGH_VALUE_RARITY_ID = 4
DEFAULT_HIGH_VALUE_REVIEW_CONFIDENCE = 0.90
DEFAULT_HIGH_VALUE_STRONG_NAME_SCORE = 0.94
DEFAULT_ATTRIBUTE_MODEL_JSON = (
    PROJECT_ROOT
    / "ocr_training_lab"
    / "equipment_attribute_scan"
    / "wiki_attribute_training_set"
    / "model"
    / "wiki_attribute_signature_model.json"
)
COLLECTION_PAGE_PREFIXES = ("frag", "fragment", "equip", "equipment")
COLLECTION_SORT_TOKENS = ("rarity", "buildable", "quantity", "number")


@dataclass(frozen=True)
class V2ImageMeta:
    """
    单张 v2 截图的文件名元信息。
    输入：
        v2_<rarity>_scroll_<index>.png。
        测试图也允许 v2_test_<rarity>_scroll_<index>.png。
    输出：
        rarity/page_index/scroll_position。
    使用示例：
        meta = parse_v2_filename(Path("v2_super_rare_scroll_3.png"))
    """

    filename: str
    rarity: str
    rarity_id: int
    page_index: int
    scroll_position: str = "unknown"


# ============================================================
# 🏗️ 第三部分：参数、元信息和图库
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。
    输入：
        终端命令行。
    输出：
        argparse.Namespace。
    使用示例：
        python run_v2_prelabel.py
    """
    parser = argparse.ArgumentParser(description="为 equipment_icon_matcher_v2/img_input 生成预标注。")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR, help="v2 截图输入目录。")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="预标注输出目录。")
    parser.add_argument("--accepted-gallery-csv", type=Path, default=DEFAULT_ACCEPTED_GALLERY_CSV, help="accepted 图库 manifest CSV。")
    parser.add_argument("--reviewed-gallery-csv", type=Path, default=DEFAULT_REVIEWED_GALLERY_CSV, help="人工 reviewed 图库 manifest CSV。")
    parser.add_argument("--pattern", default="*.png", help="输入图片匹配模式。")
    parser.add_argument("--skip-ocr", action="store_true", help="跳过碎片数量 OCR，只生成卡片和图标预标注。")
    parser.add_argument("--enable-name-ocr", action="store_true", help="额外识别卡片顶部装备名称；较慢，但可辅助同图标装备判别。")
    parser.add_argument("--skip-icons", action="store_true", help="跳过装备图标匹配，只生成卡片和数量预标注。")
    parser.add_argument("--top-n", type=int, default=10, help="每张卡片保留 top-n 图标候选；名称 OCR 需要更宽候选集消歧。")
    parser.add_argument("--review-confidence", type=float, default=0.72, help="低于该图标置信度的 success 也进入人工复核清单。")
    parser.add_argument("--auto-accept-confidence", type=float, default=0.90, help="达到该阈值才标记为机器高可信 auto_accept。")
    parser.add_argument("--name-ocr-confidence", type=float, default=0.55, help="名称 OCR 文本最低置信度。")
    parser.add_argument("--name-fuzzy-threshold", type=float, default=0.66, help="名称 OCR 与装备库的最低相似度。")
    parser.add_argument("--name-assist-icon-confidence", type=float, default=0.60, help="名称辅助接管图标 ambiguous/unknown 的最低图标分。")
    parser.add_argument("--name-override-icon-confidence", type=float, default=0.86, help="名称 OCR 可接管图标结果的最高图标置信度。")
    parser.add_argument("--name-global-assist-score", type=float, default=0.90, help="名称 OCR 不在图标 top-N 时，允许辅助的最低名称相似度。")
    parser.add_argument("--enable-region-refine", action="store_true", help="启用遮挡容忍分块精排；设计图默认关闭，后续装备页遮挡测试时再打开。")
    parser.add_argument("--high-value-rarity-id", type=int, default=DEFAULT_HIGH_VALUE_RARITY_ID, help="达到该稀有度后启用保守复核阈值；默认金装和彩装。")
    parser.add_argument("--high-value-review-confidence", type=float, default=DEFAULT_HIGH_VALUE_REVIEW_CONFIDENCE, help="金/彩装备低于该图标置信度时，必须有强名称 OCR 才能机器预填。")
    parser.add_argument("--high-value-strong-name-score", type=float, default=DEFAULT_HIGH_VALUE_STRONG_NAME_SCORE, help="金/彩装备允许名称辅助放行的最低名称相似度。")
    parser.add_argument("--enable-attribute-rerank", action="store_true", help="启用 Wiki 属性签名对图标候选进行保守重排。")
    parser.add_argument("--enable-attribute-ocr", action="store_true", help="识别设计图卡片右侧属性文字；通常与 --enable-attribute-rerank 一起使用。")
    parser.add_argument("--attribute-model-json", type=Path, default=DEFAULT_ATTRIBUTE_MODEL_JSON, help="Wiki 属性签名模型 JSON。")
    parser.add_argument("--attribute-ocr-confidence", type=float, default=0.42, help="属性 OCR 文本最低置信度。")
    parser.add_argument("--attribute-rerank-icon-weight", type=float, default=0.70, help="属性重排时图标分权重。")
    parser.add_argument("--attribute-rerank-attribute-weight", type=float, default=0.30, help="属性重排时属性分权重。")
    parser.add_argument("--attribute-rerank-min-score", type=float, default=0.18, help="属性重排接管所需最低属性匹配分。")
    parser.add_argument("--attribute-rerank-min-margin", type=float, default=0.02, help="属性重排接管所需 combined 分差。")
    parser.add_argument("--high-confidence", type=float, default=None, help="兼容旧参数；等价于 --auto-accept-confidence。")
    parser.add_argument("--pattern-prefix", default="v2_prelabel", help="输出文件名前缀。")
    parser.add_argument("--no-preview", action="store_true", help="不生成 annotated 预览图，只输出 JSON/CSV/复核文本。")
    return parser.parse_args()


def parse_v2_filename(image_path: Path) -> V2ImageMeta:
    """
    从 v2 文件名中解析稀有度和滚动序号。
    输入：
        图片路径。
    输出：
        V2ImageMeta。
    使用示例：
        parse_v2_filename(Path("v2_rare_scroll_12.png"))
    """
    collection_meta = parse_collection_filename(image_path)
    if collection_meta is not None:
        return collection_meta

    match = re.match(r"^v2_(?:test_)?(?P<rarity>.+)_scroll_(?P<index>\d+)\.png$", image_path.name, flags=re.IGNORECASE)
    if not match:
        return V2ImageMeta(image_path.name, "unknown", 0, 0)
    rarity = normalize_rarity(match.group("rarity"))
    return V2ImageMeta(
        filename=image_path.name,
        rarity=rarity,
        rarity_id=RARITY_TO_ID.get(rarity, 0),
        page_index=int(match.group("index")),
    )


def parse_collection_filename(image_path: Path) -> Optional[V2ImageMeta]:
    """
    解析 collection_next 使用的更清晰截图命名。
    输入：
        frag_super_rare_buildable_scroll_001.png /
        equip_ultra_rare_scroll_001.png 等截图名。
    输出：
        能解析则返回 V2ImageMeta；否则返回 None。
    使用示例：
        parse_collection_filename(Path("frag_super_rare_number_scroll_1.png"))
    """
    stem = image_path.stem.lower()
    suffix = image_path.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg"}:
        return None

    parts = stem.split("_")
    if not parts or parts[0] not in COLLECTION_PAGE_PREFIXES:
        return None

    # 机器识别真正需要的是稀有度桶。sort/page 只是给人看，不能让它污染 rarity。
    scroll_index = next((index for index, part in enumerate(parts) if part == "scroll"), -1)
    if scroll_index <= 1 or scroll_index + 1 >= len(parts):
        return None

    try:
        page_index = int(parts[scroll_index + 1])
    except ValueError:
        return None

    rarity_parts = parts[1:scroll_index]
    if rarity_parts and rarity_parts[-1] in COLLECTION_SORT_TOKENS:
        rarity_parts = rarity_parts[:-1]
    rarity = normalize_rarity("_".join(rarity_parts))
    return V2ImageMeta(
        filename=image_path.name,
        rarity=rarity,
        rarity_id=RARITY_TO_ID.get(rarity, 0),
        page_index=page_index,
    )


def collect_images(input_dir: Path, pattern: str) -> List[Tuple[Path, V2ImageMeta]]:
    """
    收集并按稀有度、滚动序号排序图片。
    输入：
        input_dir/pattern。
    输出：
        [(path, meta)]。
    使用示例：
        images = collect_images(Path("img_input"), "*.png")
    """
    items: List[Tuple[Path, V2ImageMeta]] = []
    for image_path in input_dir.glob(pattern):
        if not image_path.is_file():
            continue
        meta = parse_v2_filename(image_path)
        items.append((image_path, meta))

    items.sort(key=lambda item: (item[1].rarity, item[1].page_index, item[0].name))
    grouped: Dict[str, List[Tuple[Path, V2ImageMeta]]] = {}
    for image_path, meta in items:
        grouped.setdefault(meta.rarity, []).append((image_path, meta))

    enriched: List[Tuple[Path, V2ImageMeta]] = []
    for rarity, group in grouped.items():
        for index, (image_path, meta) in enumerate(sorted(group, key=lambda item: item[1].page_index), start=1):
            if len(group) == 1:
                scroll_position = "single"
            elif index == 1:
                scroll_position = "start"
            elif index == len(group):
                scroll_position = "end"
            else:
                scroll_position = "middle"
            enriched.append(
                (
                    image_path,
                    V2ImageMeta(meta.filename, rarity, meta.rarity_id, meta.page_index, scroll_position),
                )
            )
    return enriched


def filter_catalog_by_rarity(
    catalog: Mapping[str, Mapping[str, Any]],
    rarity_id: int,
) -> Dict[str, Dict[str, Any]]:
    """
    按当前筛选稀有度缩小装备名称解析范围。

    输入：
        全量装备 catalog 和 filter_rarity_id。
    输出：
        仅包含当前稀有度的装备 catalog。
    使用示例：
        rare_catalog = filter_catalog_by_rarity(catalog, 2)
    """
    filtered: Dict[str, Dict[str, Any]] = {}
    for equipment_id, item in catalog.items():
        try:
            item_rarity_id = int(item.get("rarity_id", 0) or 0)
        except (TypeError, ValueError):
            item_rarity_id = 0
        if item_rarity_id == int(rarity_id):
            filtered[str(equipment_id)] = dict(item)
    return filtered


def build_combined_gallery_csv(
    output_dir: Path,
    rarity: str,
    catalog: Mapping[str, Mapping[str, Any]],
    gallery_csv_paths: Sequence[Path],
) -> Optional[Path]:
    """
    为某个稀有度构建 data/images + accepted_gallery 的临时合并图库。
    输入：
        output_dir/rarity/catalog/accepted_gallery_csv。
    输出：
        合并 CSV 路径；稀有度未知时返回 None。
    使用示例：
        csv_path = build_combined_gallery_csv(out, "super_rare", catalog, manifest)
    """
    rarity_id = RARITY_TO_ID.get(rarity, 0)
    if rarity_id <= 0:
        return None

    rows: List[Dict[str, str]] = []
    for equipment_id, item in catalog.items():
        if int(item.get("rarity_id", 0) or 0) != rarity_id:
            continue
        image_path = str(item.get("image_path", "") or "").strip()
        if not image_path:
            continue
        resolved = Path(image_path)
        if not resolved.is_absolute():
            resolved = PROJECT_ROOT / resolved
        if resolved.exists():
            rows.append({"equipment_id": equipment_id, "image_path": str(resolved), "source": "data_images"})

    for gallery_csv_path in gallery_csv_paths:
        if not gallery_csv_path.exists():
            continue
        gallery_source = gallery_csv_path.parent.name
        with gallery_csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                equipment_id = str(row.get("equipment_id", "") or "").strip()
                if not equipment_id:
                    continue
                item = catalog.get(equipment_id, {})
                if int(item.get("rarity_id", 0) or 0) != rarity_id:
                    continue
                image_path = str(row.get("image_path", "") or "").strip()
                if image_path and Path(image_path).exists():
                    rows.append({"equipment_id": equipment_id, "image_path": image_path, "source": gallery_source})

    if not rows:
        return None

    gallery_dir = output_dir / "_combined_gallery"
    gallery_dir.mkdir(parents=True, exist_ok=True)
    csv_path = gallery_dir / f"{rarity}_combined_gallery.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["equipment_id", "image_path", "source"])
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def build_matcher_for_rarity(
    rarity: str,
    config: Mapping[str, Any],
    combined_gallery_csv: Optional[Path],
    enable_region_refine: bool = False,
) -> Optional[EquipmentIconMatcher]:
    """
    构建某个稀有度的 v2 图标匹配器。
    输入：
        rarity/config/combined_gallery_csv。
    输出：
        EquipmentIconMatcher 或 None。
    使用示例：
        matcher = build_matcher_for_rarity("rare", config, csv_path)
    """
    if combined_gallery_csv is None or not combined_gallery_csv.exists():
        return None
    matcher_config = dict(config.get("equipment_icon_matching", {}))
    matcher_config["gallery_csv_path"] = str(combined_gallery_csv)
    if not enable_region_refine:
        matcher_config["region_weight"] = 0.0
    return EquipmentIconMatcher(config=matcher_config, gallery_csv_path=combined_gallery_csv, project_root=PROJECT_ROOT)


# ============================================================
# 🧮 第四部分：预标注核心逻辑
# ============================================================

def process_one(
    image_path: Path,
    meta: V2ImageMeta,
    output_dir: Path,
    detector: DesignFragmentDetector,
    reader: Optional[EquipmentCardDigitReader],
    matcher: Optional[EquipmentIconMatcher],
    name_resolver: Optional[EquipmentNameResolver],
    attribute_reranker: Optional[EquipmentAttributeReranker],
    catalog: Mapping[str, Mapping[str, Any]],
    top_n: int,
    review_confidence: float,
    auto_accept_confidence: float,
    read_quantity_ocr: bool,
    enable_name_ocr: bool,
    name_ocr_confidence: float,
    name_fuzzy_threshold: float,
    name_assist_icon_confidence: float,
    name_override_icon_confidence: float,
    name_global_assist_score: float,
    enable_attribute_ocr: bool,
    attribute_ocr_confidence: float,
    high_value_rarity_id: int,
    high_value_review_confidence: float,
    high_value_strong_name_score: float,
    pattern_prefix: str,
    write_preview: bool = True,
) -> Dict[str, Any]:
    """
    处理单张 v2 截图。
    输入：
        image_path/meta/output_dir/detector/reader/matcher/catalog/top_n。
    输出：
        单图预标注 payload。
    使用示例：
        payload = process_one(path, meta, out, detector, reader, matcher, catalog, 5, 0.9, "v2")
    """
    detection = detector.detect(image_path, image_mode="viewport_full")
    payload: Dict[str, Any] = {
        "filename": image_path.name,
        "screenshot_path": str(image_path),
        "meta": meta.__dict__,
        "detection": detection.to_dict(),
        "cards": [],
        "annotated_output": "",
        "warnings": [],
    }
    if not detection.success:
        return payload

    image = detector.load_image(image_path)
    card_rows: List[Dict[str, Any]] = []
    for card_no, candidate in enumerate(sorted(detection.candidates, key=lambda item: (item.bbox[1], item.bbox[0])), start=1):
        card_rows.append(
            build_card_row(
                image,
                image_path.name,
                meta,
                card_no,
                candidate,
                reader,
                matcher,
                name_resolver,
                catalog,
                top_n,
                review_confidence,
                auto_accept_confidence,
                read_quantity_ocr,
                enable_name_ocr,
                name_ocr_confidence,
                name_fuzzy_threshold,
                name_assist_icon_confidence,
                name_override_icon_confidence,
                name_global_assist_score,
                high_value_rarity_id,
                high_value_review_confidence,
                high_value_strong_name_score,
                attribute_reranker=attribute_reranker,
                enable_attribute_ocr=enable_attribute_ocr,
                attribute_ocr_confidence=attribute_ocr_confidence,
            )
        )

    payload["cards"] = card_rows
    if write_preview:
        annotated = draw_prelabel_annotations(detector, image, detection, card_rows, meta)
        annotated_dir = output_dir / "annotated"
        output_path = annotated_dir / f"{pattern_prefix}_{image_path.stem}.png"
        detector.write_image(output_path, annotated)
        payload["annotated_output"] = str(output_path)
    return payload


def build_card_row(
    image: Any,
    filename: str,
    meta: V2ImageMeta,
    card_no: int,
    candidate: DesignFragmentCardCandidate,
    reader: Optional[EquipmentCardDigitReader],
    matcher: Optional[EquipmentIconMatcher],
    name_resolver: Optional[EquipmentNameResolver],
    catalog: Mapping[str, Mapping[str, Any]],
    top_n: int,
    review_confidence: float,
    auto_accept_confidence: float,
    read_quantity_ocr: bool,
    enable_name_ocr: bool,
    name_ocr_confidence: float,
    name_fuzzy_threshold: float,
    name_assist_icon_confidence: float,
    name_override_icon_confidence: float,
    name_global_assist_score: float,
    high_value_rarity_id: int = DEFAULT_HIGH_VALUE_RARITY_ID,
    high_value_review_confidence: float = DEFAULT_HIGH_VALUE_REVIEW_CONFIDENCE,
    high_value_strong_name_score: float = DEFAULT_HIGH_VALUE_STRONG_NAME_SCORE,
    attribute_reranker: Optional[EquipmentAttributeReranker] = None,
    enable_attribute_ocr: bool = False,
    attribute_ocr_confidence: float = 0.42,
) -> Dict[str, Any]:
    """构造单张卡片的预标注行。"""
    full_card = candidate.visibility == "full"
    quantity_selected = full_card
    icon_selected = full_card

    name_roi = _name_roi_for_candidate(candidate)
    attribute_roi = _attribute_roi_for_candidate(candidate)
    if reader is not None and quantity_selected and read_quantity_ocr:
        fragment_result = reader.read_fragment_counts(
            image,
            card_roi=candidate.bbox,
            quantity_roi=_relative_child_roi(candidate.bbox, candidate.quantity_roi),
        ).to_dict()
    elif quantity_selected:
        fragment_result = _empty_fragment_result("skipped", "碎片数量 OCR 按参数跳过。")
    else:
        fragment_result = _empty_fragment_result("not_selected", "卡片被裁切，跳过数量 OCR。")

    if matcher is not None and icon_selected:
        icon_result = matcher.match_icon(image, icon_roi=candidate.icon_roi, top_n=top_n).to_dict()
    elif icon_selected:
        icon_result = _empty_icon_result("skipped", "装备图标匹配按参数跳过。")
    else:
        icon_result = _empty_icon_result("not_selected", "卡片被裁切，跳过图标匹配。")

    if reader is not None and enable_name_ocr and full_card:
        name_ocr_result = reader.ocr_engine.recognize_text(
            image,
            roi=name_roi,
            confidence_threshold=name_ocr_confidence,
            preprocess=False,
        ).to_dict()
        if not name_ocr_result.get("success"):
            name_ocr_result = reader.ocr_engine.recognize_text(
                image,
                roi=name_roi,
                confidence_threshold=name_ocr_confidence,
                preprocess=True,
            ).to_dict()
    elif enable_name_ocr and full_card:
        name_ocr_result = _empty_text_result("skipped", "名称 OCR 按参数跳过。")
    else:
        name_ocr_result = _empty_text_result("not_selected", "名称 OCR 未启用或卡片被裁切。")

    if reader is not None and enable_attribute_ocr and full_card:
        attribute_ocr_result = reader.ocr_engine.recognize_text(
            image,
            roi=attribute_roi,
            confidence_threshold=attribute_ocr_confidence,
            preprocess=False,
        ).to_dict()
        if not attribute_ocr_result.get("success"):
            attribute_ocr_result = reader.ocr_engine.recognize_text(
                image,
                roi=attribute_roi,
                confidence_threshold=attribute_ocr_confidence,
                preprocess=True,
            ).to_dict()
    elif enable_attribute_ocr and full_card:
        attribute_ocr_result = _empty_text_result("skipped", "属性 OCR 按参数跳过。")
    else:
        attribute_ocr_result = _empty_text_result("not_selected", "属性 OCR 未启用或卡片被裁切。")

    icon_id = str(icon_result.get("equipment_id", "unknown") or "unknown")
    catalog_item = catalog.get(icon_id, {})
    top_candidates = list(icon_result.get("candidates", []) or [])
    top_candidate_id = str(top_candidates[0].get("equipment_id", "")) if top_candidates else ""
    top_candidate_name = catalog.get(top_candidate_id, {}).get("name", "") if top_candidate_id else ""
    confidence = float(icon_result.get("confidence", 0.0) or 0.0)
    icon_status = str(icon_result.get("status", ""))
    ocr_status = str(fragment_result.get("status", ""))
    name_resolution = resolve_name_ocr(
        name_ocr_result,
        top_candidates,
        name_resolver,
        name_fuzzy_threshold,
    )
    name_resolution_id = str(name_resolution.get("equipment_id", "") or "")
    name_resolution_name = str(name_resolution.get("equipment_name", "") or "")
    name_resolution_score = float(name_resolution.get("score", 0.0) or 0.0)
    name_resolution_status = str(name_resolution.get("status", "") or "")
    name_ocr_confidence_value = float(name_ocr_result.get("confidence", 0.0) or 0.0)
    top_candidate_ids = tuple(str(item.get("equipment_id", "") or "") for item in top_candidates)
    name_in_icon_candidates = bool(name_resolution_id and name_resolution_id in top_candidate_ids)
    name_text_strong = bool(
        full_card
        and name_resolution.get("success") is True
        and name_resolution_id
        and name_ocr_confidence_value >= name_ocr_confidence
        and name_resolution_score >= name_fuzzy_threshold
    )
    name_exact_like = _name_resolution_is_exact_like(name_resolution_status, name_resolution_score)
    name_global_strong = bool(
        name_text_strong
        and not name_in_icon_candidates
        and name_resolution_score >= name_global_assist_score
        and name_exact_like
    )
    name_tierless_base_ambiguous = _tierless_base_has_multiple_variants(
        str(name_ocr_result.get("text", "") or ""),
        name_resolution_name,
        catalog,
    )
    name_tier_safe = not name_tierless_base_ambiguous
    name_can_recover_weak_icon = bool(
        name_global_strong
        and name_tier_safe
        and icon_status != "success"
        and confidence >= name_assist_icon_confidence
    )
    name_override_allowed = bool(
        name_text_strong
        and icon_status == "success"
        and confidence < name_override_icon_confidence
        and name_tier_safe
        and (name_in_icon_candidates or name_global_strong)
    )
    name_icon_conflict = bool(
        full_card
        and name_resolution.get("success") is True
        and icon_status == "success"
        and icon_id not in {"", "unknown"}
        and name_resolution_id
        and name_resolution_id != icon_id
        and not name_override_allowed
    )
    name_assisted = bool(
        full_card
        and name_resolution.get("success") is True
        and name_tier_safe
        and (name_in_icon_candidates or name_override_allowed or name_can_recover_weak_icon)
        and not name_icon_conflict
        and (
            name_in_icon_candidates
            or name_override_allowed
            or name_can_recover_weak_icon
            or icon_status != "success"
            or confidence < max(review_confidence, name_assist_icon_confidence)
        )
    )
    suggested_equipment_id = icon_id if icon_status == "success" else top_candidate_id
    suggested_name = catalog_item.get("name", "") if icon_status == "success" else top_candidate_name
    if name_assisted:
        suggested_equipment_id = name_resolution_id
        suggested_name = name_resolution_name

    attribute_observed_text = _attribute_observed_text(attribute_ocr_result)
    if attribute_reranker is not None and full_card and attribute_observed_text:
        attribute_rerank_result = attribute_reranker.rerank(attribute_observed_text, top_candidates, top_n=top_n).to_dict()
    elif attribute_reranker is not None and full_card:
        attribute_rerank_result = {
            "success": False,
            "status": "empty",
            "message": "属性 OCR 文本为空，跳过属性重排。",
            "candidates": [],
            "observed_text": attribute_observed_text,
        }
    else:
        attribute_rerank_result = {
            "success": False,
            "status": "disabled",
            "message": "属性重排未启用。",
            "candidates": [],
            "observed_text": attribute_observed_text,
        }
    attribute_rerank_success = bool(attribute_rerank_result.get("success") is True)
    attribute_rerank_id = str(attribute_rerank_result.get("selected_equipment_id", "") or "")
    attribute_rerank_name = str(attribute_rerank_result.get("selected_equipment_name", "") or "")
    attribute_rerank_score = float(attribute_rerank_result.get("attribute_score", 0.0) or 0.0)
    attribute_rerank_margin = float(attribute_rerank_result.get("margin", 0.0) or 0.0)
    attribute_rerank_attribute_margin = float(attribute_rerank_result.get("attribute_margin", 0.0) or 0.0)
    attribute_in_icon_candidates = bool(attribute_rerank_id and attribute_rerank_id in top_candidate_ids)
    attribute_assisted = bool(attribute_rerank_success and attribute_in_icon_candidates)
    attribute_name_conflict = bool(
        attribute_assisted
        and name_assisted
        and name_resolution_id
        and attribute_rerank_id
        and attribute_rerank_id != name_resolution_id
    )
    if attribute_assisted and not name_icon_conflict and not attribute_name_conflict:
        suggested_equipment_id = attribute_rerank_id
        suggested_name = attribute_rerank_name

    raw_name_text = str(name_ocr_result.get("text", "") or "")
    name_partial_conflict = bool(
        full_card
        and raw_name_text.strip()
        and name_ocr_confidence_value >= name_ocr_confidence
        and icon_status == "success"
        and suggested_name
        and not name_assisted
        and not attribute_assisted
        and _name_text_has_distinctive_conflict(raw_name_text, suggested_name)
    )
    high_value_card = bool(full_card and int(meta.rarity_id or 0) >= int(high_value_rarity_id))
    high_value_confident_icon = bool(icon_status == "success" and confidence >= high_value_review_confidence)
    high_value_name_weak = bool(
        high_value_card
        and raw_name_text.strip()
        and not high_value_confident_icon
        and _name_text_is_weak_for_high_value(
            raw_name_text,
            name_resolution_name or suggested_name,
            name_resolution_score,
            high_value_strong_name_score,
        )
    )
    high_value_distinctive_name = bool(
        high_value_card
        and name_assisted
        and name_resolution_score >= 0.70
        and _name_text_has_distinctive_model_overlap(raw_name_text, name_resolution_name or suggested_name)
    )
    high_value_strong_name = bool(
        high_value_card
        and (name_assisted or attribute_assisted)
        and not high_value_name_weak
        and (
            name_resolution_score >= high_value_strong_name_score
            or attribute_rerank_score >= 0.22
            or (
                high_value_distinctive_name
                and confidence >= max(0.0, high_value_review_confidence - 0.025)
            )
        )
    )
    high_value_guard_active = bool(
        high_value_card
        and not high_value_confident_icon
        and not high_value_strong_name
    )
    empty_false_positive = _is_probable_empty_false_positive(
        full_card=full_card,
        high_value_card=high_value_card,
        raw_name_text=raw_name_text,
        icon_status=icon_status,
        icon_confidence=confidence,
        ocr_status=ocr_status,
    )
    if empty_false_positive:
        suggested_equipment_id = ""
        suggested_name = ""
        high_value_guard_active = False
    machine_prefill = bool(
        full_card
        and not empty_false_positive
        and not high_value_guard_active
        and not name_icon_conflict
        and not name_partial_conflict
        and not attribute_name_conflict
        and (
            (icon_status == "success" and confidence >= review_confidence)
            or name_assisted
            or attribute_assisted
        )
    )
    auto_accept = bool(
        full_card
        and not empty_false_positive
        and icon_status == "success"
        and confidence >= auto_accept_confidence
        and not high_value_guard_active
        and not name_icon_conflict
        and not name_partial_conflict
        and not attribute_name_conflict
    )
    icon_needs_review = bool(
        full_card
        and not empty_false_positive
        and (
            high_value_guard_active
            or name_partial_conflict
            or attribute_name_conflict
            or (
                not name_assisted
                and not attribute_assisted
                and (icon_status != "success" or confidence < review_confidence or name_icon_conflict)
            )
        )
    )
    ocr_needs_review = bool(read_quantity_ocr and reader is not None and quantity_selected and ocr_status != "success")
    needs_review = bool(icon_needs_review or ocr_needs_review)
    reason = review_reason(
        full_card,
        icon_status,
        confidence,
        review_confidence,
        ocr_status,
        ocr_enabled=bool(read_quantity_ocr and reader is not None),
    )
    if name_icon_conflict:
        reason = ";".join(item for item in (reason, "name_icon_conflict") if item)
    if name_partial_conflict:
        reason = ";".join(item for item in (reason, "name_partial_conflict") if item)
    if attribute_assisted:
        reason = ";".join(item for item in (reason, "attribute_rerank") if item)
    if attribute_name_conflict:
        reason = ";".join(item for item in (reason, "attribute_name_conflict") if item)
    if name_tierless_base_ambiguous and icon_status != "success":
        reason = ";".join(item for item in (reason, "name_tier_ambiguous") if item)
    if high_value_guard_active:
        high_value_reason = f"high_value_confidence<{high_value_review_confidence:.2f}"
        if high_value_name_weak:
            high_value_reason = f"{high_value_reason};high_value_weak_name"
        elif not high_value_strong_name:
            high_value_reason = f"{high_value_reason};high_value_no_strong_name"
        reason = ";".join(item for item in (reason, high_value_reason) if item)
    if empty_false_positive:
        reason = "skip_empty_false_positive"
    if name_assisted and not high_value_guard_active and reason.startswith("icon_"):
        reason = ""
    return {
        "filename": filename,
        "filter_rarity": meta.rarity,
        "filter_rarity_id": meta.rarity_id,
        "scroll_position": meta.scroll_position,
        "page_index": meta.page_index,
        "card_no": card_no,
        "selected": full_card,
        "quantity_selected": quantity_selected,
        "icon_selected": icon_selected,
        "detected_index": candidate.index,
        "bbox": list(candidate.bbox),
        "icon_roi": list(candidate.icon_roi),
        "name_roi": list(name_roi),
        "attribute_roi": list(attribute_roi),
        "quantity_roi": list(candidate.quantity_roi),
        "visibility": candidate.visibility,
        "name_ocr_status": name_ocr_result.get("status", ""),
        "name_ocr_text": name_ocr_result.get("text", ""),
        "name_ocr_confidence": name_ocr_confidence_value,
        "name_resolve_status": name_resolution.get("status", ""),
        "name_resolve_equipment_id": name_resolution_id,
        "name_resolve_equipment_name": name_resolution_name,
        "name_resolve_score": name_resolution_score,
        "name_resolve_candidates": format_name_candidates(name_resolution.get("candidates", [])),
        "name_in_icon_candidates": name_in_icon_candidates,
        "name_global_strong": name_global_strong,
        "name_can_recover_weak_icon": name_can_recover_weak_icon,
        "name_tierless_base_ambiguous": name_tierless_base_ambiguous,
        "name_override_allowed": name_override_allowed,
        "name_assisted": name_assisted,
        "name_icon_conflict": name_icon_conflict,
        "name_partial_conflict": name_partial_conflict,
        "attribute_ocr_status": attribute_ocr_result.get("status", ""),
        "attribute_ocr_text": attribute_ocr_result.get("text", ""),
        "attribute_ocr_confidence": float(attribute_ocr_result.get("confidence", 0.0) or 0.0),
        "attribute_rerank_status": attribute_rerank_result.get("status", ""),
        "attribute_rerank_equipment_id": attribute_rerank_id,
        "attribute_rerank_equipment_name": attribute_rerank_name,
        "attribute_rerank_score": attribute_rerank_score,
        "attribute_rerank_margin": attribute_rerank_margin,
        "attribute_rerank_attribute_margin": attribute_rerank_attribute_margin,
        "attribute_in_icon_candidates": attribute_in_icon_candidates,
        "attribute_assisted": attribute_assisted,
        "attribute_name_conflict": attribute_name_conflict,
        "attribute_rerank_candidates": format_attribute_candidates(attribute_rerank_result.get("candidates", [])),
        "high_value_card": high_value_card,
        "high_value_confident_icon": high_value_confident_icon,
        "high_value_name_weak": high_value_name_weak,
        "high_value_strong_name": high_value_strong_name,
        "high_value_guard_active": high_value_guard_active,
        "empty_false_positive": empty_false_positive,
        "ocr_status": ocr_status,
        "ocr_fragment_count": fragment_result.get("fragment_count"),
        "ocr_required_count": fragment_result.get("required_count"),
        "ocr_confidence": fragment_result.get("confidence", 0.0),
        "ocr_text": fragment_result.get("text", ""),
        "icon_status": icon_status,
        "icon_equipment_id": icon_id,
        "icon_equipment_name": catalog_item.get("name", ""),
        "icon_confidence": confidence,
        "icon_top_candidates": format_top_candidates(top_candidates, catalog),
        "suggested_equipment_id": suggested_equipment_id,
        "suggested_equipment_name": suggested_name,
        "current_resolved_equipment_id": suggested_equipment_id,
        "machine_prefill": machine_prefill,
        "auto_accept": auto_accept,
        "icon_needs_review": icon_needs_review,
        "ocr_needs_review": ocr_needs_review,
        "needs_review": needs_review,
        "review_reason": reason,
        "accepted_equipment_name": suggested_name if machine_prefill else "",
        "accepted_equipment_id": suggested_equipment_id if machine_prefill else "",
        "accepted_fragment_owned": fragment_result.get("fragment_count") if machine_prefill and ocr_status == "success" else "",
        "accepted_fragment_required": fragment_result.get("required_count") if machine_prefill and ocr_status == "success" else "",
        "fragment_ocr": fragment_result,
        "name_ocr": name_ocr_result,
        "attribute_ocr": attribute_ocr_result,
        "attribute_rerank": attribute_rerank_result,
        "icon_match_result": icon_result,
    }


def _is_probable_empty_false_positive(
    full_card: bool,
    high_value_card: bool,
    raw_name_text: str,
    icon_status: str,
    icon_confidence: float,
    ocr_status: str,
) -> bool:
    """
    判断设计图检测出的“完整卡”是否实际是空白误检。

    输入：
        卡片完整性、稀有度、名称 OCR 文本、图标状态/分数和数量 OCR 状态。
    输出：
        True 表示跳过人工复核，不训练这张卡。
    使用示例：
        顶部空白区域被误检为 UR 卡，图标分很低且名称为空时返回 True。
    """
    return bool(
        full_card
        and high_value_card
        and not str(raw_name_text or "").strip()
        and float(icon_confidence or 0.0) < 0.70
        and str(icon_status or "") in {"success", "unknown", "ambiguous"}
        and str(ocr_status or "") != "success"
    )


def review_reason(
    full_card: bool,
    icon_status: str,
    confidence: float,
    review_confidence: float,
    ocr_status: str,
    ocr_enabled: bool = True,
) -> str:
    """生成人工复核原因。"""
    if not full_card:
        return "skip_partial_card"
    reasons: List[str] = []
    if icon_status != "success":
        reasons.append(f"icon_{icon_status or 'unknown'}")
    elif confidence < review_confidence:
        reasons.append(f"icon_confidence<{review_confidence:.2f}")
    if ocr_enabled and ocr_status != "success":
        reasons.append(f"ocr_{ocr_status or 'unknown'}")
    return ";".join(reasons) if reasons else ""


def format_top_candidates(candidates: Sequence[Mapping[str, Any]], catalog: Mapping[str, Mapping[str, Any]]) -> str:
    """把 top candidates 格式化成适合 CSV 查看的一行文本。"""
    chunks: List[str] = []
    for item in candidates:
        equipment_id = str(item.get("equipment_id", "") or "")
        name = str(catalog.get(equipment_id, {}).get("name", "") or "")
        confidence = float(item.get("confidence", 0.0) or 0.0)
        chunks.append(f"{equipment_id}:{name}:{confidence:.3f}")
    return " | ".join(chunks)


def format_name_candidates(candidates: Sequence[Mapping[str, Any]]) -> str:
    """把名称 OCR 解析候选格式化成适合 CSV/人工复核查看的一行文本。"""
    chunks: List[str] = []
    for item in candidates:
        equipment_id = str(item.get("equipment_id", "") or "")
        name = str(item.get("equipment_name", "") or "")
        score = float(item.get("score", 0.0) or 0.0)
        reason = str(item.get("reason", "") or "")
        chunks.append(f"{equipment_id}:{name}:{score:.3f}:{reason}")
    return " | ".join(chunks)


def _empty_fragment_result(status: str, message: str) -> Dict[str, Any]:
    """构造空碎片 OCR 结果。"""
    return {
        "success": False,
        "status": status,
        "message": message,
        "fragment_count": None,
        "required_count": None,
        "confidence": 0.0,
        "text": "",
        "raw_texts": [],
        "roi": None,
        "warnings": [message],
    }


def _empty_icon_result(status: str, message: str) -> Dict[str, Any]:
    """构造空图标匹配结果。"""
    return {
        "success": True,
        "status": status,
        "message": message,
        "equipment_id": "unknown",
        "confidence": 0.0,
        "icon_roi": None,
        "matched_image_path": "",
        "candidates": [],
        "warnings": [message],
    }


def _empty_text_result(status: str, message: str) -> Dict[str, Any]:
    """构造空文本 OCR 结果。"""
    return {
        "success": False,
        "status": status,
        "message": message,
        "text": "",
        "value": None,
        "confidence": 0.0,
        "raw_texts": [],
        "roi": None,
        "warnings": [message],
    }


def resolve_name_ocr(
    name_ocr_result: Mapping[str, Any],
    top_candidates: Sequence[Mapping[str, Any]],
    name_resolver: Optional[EquipmentNameResolver],
    name_fuzzy_threshold: float,
) -> Dict[str, Any]:
    """
    用 OCR 名称辅助解析装备。

    输入：
        name_ocr_result/top_candidates/name_resolver。
    输出：
        EquipmentNameResolveResult 的字典形式。
    使用示例：
        payload = resolve_name_ocr(name_ocr, icon_candidates, resolver, 0.66)
    """
    if name_resolver is None:
        return _empty_name_resolution("disabled", "名称解析器未启用。")
    if name_ocr_result.get("success") is not True:
        return _empty_name_resolution(str(name_ocr_result.get("status", "not_ready")), "名称 OCR 未成功，跳过名称解析。")

    text = str(name_ocr_result.get("text", "") or "").strip()
    candidate_ids = [str(item.get("equipment_id", "") or "") for item in top_candidates]
    try:
        result = name_resolver.resolve(
            text,
            candidate_equipment_ids=candidate_ids,
            min_score=float(name_fuzzy_threshold),
        )
        return result.to_dict()
    except Exception as exc:
        return _empty_name_resolution("error", f"名称解析失败: {exc}")


def _empty_name_resolution(status: str, message: str) -> Dict[str, Any]:
    """构造空名称解析结果。"""
    return {
        "success": False,
        "status": status,
        "message": message,
        "equipment_id": "",
        "equipment_name": "",
        "score": 0.0,
        "normalized_text": "",
        "candidates": [],
    }


def _name_resolution_is_exact_like(status: str, score: float) -> bool:
    """
    判断名称 OCR 是否足够强，可以脱离图标 top-N 辅助判断。

    输入：
        resolver status 和相似度分数。
    输出：
        True 表示接近精确/包含式命中；False 表示仍应人工复核。
    使用示例：
        _name_resolution_is_exact_like("outside_icon_candidates", 0.965)
    """
    status_text = str(status or "")
    if "exact" in status_text:
        return True
    if "contains" in status_text and score >= 0.90:
        return True
    return score >= 0.965


def _tierless_base_has_multiple_variants(
    raw_text: str,
    resolved_name: str,
    catalog: Mapping[str, Mapping[str, Any]],
) -> bool:
    """
    检查“只读到基础名”时是否存在同名多 T 等级风险。

    输入：
        OCR 原文、当前解析出的装备名、全量装备 catalog。
    输出：
        True 表示应保守复核，不能仅凭文字自动接管。
    使用示例：
        _tierless_base_has_multiple_variants("维修工具", "维修工具#T3", catalog)
    """
    text = str(raw_text or "").strip()
    if re.search(r"#?\s*[tT]\s*\d+", text):
        return False
    resolved_base = normalize_equipment_base_name(resolved_name)
    text_base = normalize_equipment_base_name(text)
    if not resolved_base or not text_base or text_base != resolved_base:
        return False
    variants = {
        str(item.get("name", "") or "").strip()
        for item in catalog.values()
        if normalize_equipment_base_name(str(item.get("name", "") or "")) == resolved_base
    }
    return len(variants) > 1


def _name_text_is_weak_for_high_value(
    raw_text: str,
    resolved_name: str,
    score: float,
    strong_score: float,
) -> bool:
    """
    判断金/彩装备的名称 OCR 是否只是“泛化片段”。

    输入：
        OCR 原文、解析后的装备名、名称分数和强名称阈值。
    输出：
        True 表示文字不足以放行机器结果，应进入人工复核。
    使用示例：
        _name_text_is_weak_for_high_value("试作型四联装", "试作型四联装152mm主炮#T0", 0.90, 0.94)
    """
    text_base = normalize_equipment_base_name(raw_text)
    resolved_base = normalize_equipment_base_name(resolved_name)
    if not text_base or not resolved_base:
        return True
    if text_base == resolved_base:
        return False
    meaningful = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", text_base)
    resolved_meaningful = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", resolved_base)
    has_distinctive_model_token = _name_text_has_distinctive_model_overlap(text_base, resolved_base)
    if score < strong_score and not (score >= 0.70 and has_distinctive_model_token):
        return True
    if len(meaningful) < 6:
        return True
    if (
        len(resolved_meaningful)
        and len(meaningful) / float(len(resolved_meaningful)) < 0.72
        and not has_distinctive_model_token
    ):
        return True
    # 试作型/联装/舰载型是科研装备的高频前缀，只读到这些词无法区分 152mm、234mm、305mm 等同脸装备。
    generic_fragments = ("试作型三联装", "试作型四联装", "试作舰载型", "试作型", "三联装", "四联装")
    if any(meaningful == fragment for fragment in generic_fragments):
        return True
    return False


def _name_text_has_distinctive_model_overlap(raw_text: str, resolved_name: str) -> bool:
    """
    判断 OCR 短名称是否含有足够区分装备的型号/口径 token。

    输入：
        OCR 基础名和已解析装备基础名。
    输出：
        True 表示如 610mm、SKC41、Mk7 这类 token 与解析装备一致。
    使用示例：
        _name_text_has_distinctive_model_overlap("四联装610mm", "四联装610mm鱼雷") == True
    """
    text_tokens = _extract_distinctive_model_tokens(raw_text)
    resolved_tokens = _extract_distinctive_model_tokens(resolved_name)
    if not text_tokens or not resolved_tokens:
        return False
    # 只要 OCR 读到的所有“数字/型号”都能在解析装备里找到，就说明这不是泛化前缀。
    return text_tokens.issubset(resolved_tokens)


def _extract_distinctive_model_tokens(text: str) -> set[str]:
    """
    抽取装备名中最能区分同脸装备的口径/型号 token。

    输入：
        规范化前后的装备名均可。
    输出：
        token 集合，例如 {"610mm", "skc41"}。
    使用示例：
        _extract_distinctive_model_tokens("双联装128mmSKC41高平两用炮") == {"128mm", "skc41"}
    """
    normalized = normalize_equipment_base_name(text)
    # PaddleOCR 在小字号装备名里常把 mm 看成 mn/nm；这里仅在数字后单位位置修正，避免影响普通英文型号。
    normalized = re.sub(r"(?<=\d)(?:mn|nm)(?![a-z0-9])", "mm", normalized, flags=re.IGNORECASE)
    tokens = set(re.findall(r"\d+(?:\.\d+)?mm", normalized, flags=re.IGNORECASE))
    tokens.update(re.findall(r"skc\d+", normalized, flags=re.IGNORECASE))
    tokens.update(re.findall(r"mk\.?[a-z0-9]+", normalized, flags=re.IGNORECASE))
    tokens.update(re.findall(r"mle\d+", normalized, flags=re.IGNORECASE))
    tokens.update(re.findall(r"model\d+", normalized, flags=re.IGNORECASE))
    tokens.update(re.findall(r"mark\d+", normalized, flags=re.IGNORECASE))
    tokens.update(re.findall(r"[a-z]{1,5}-?\d+[a-z0-9]*", normalized, flags=re.IGNORECASE))
    return {token.replace(".", "").lower() for token in tokens if any(ch.isdigit() for ch in token)}


def _name_text_has_distinctive_conflict(raw_text: str, suggested_name: str) -> bool:
    """
    判断名称 OCR 读到的“口径/型号数字”是否和图标建议名称冲突。

    输入：
        OCR 名称文本和当前图标/重排建议名称。
    输出：
        True 表示不能自动预填，必须人工复核。
    使用示例：
        _name_text_has_distinctive_conflict("双联装203mm", "双联装406mm主炮Mk5#T3") == True
    """
    text_base = normalize_equipment_base_name(raw_text)
    suggested_base = normalize_equipment_base_name(suggested_name)
    if not text_base or not suggested_base:
        return False

    # 口径、型号、Mark 数字是区分同脸炮/鱼雷/飞机的关键；只要 OCR 高置信读到而建议名不含它，就转人工。
    distinctive_tokens = re.findall(r"\d+(?:\.\d+)?(?:mm|cm|inch|in|v|型|式)?", text_base, flags=re.IGNORECASE)
    distinctive_tokens = [token for token in distinctive_tokens if len(re.sub(r"\D", "", token)) >= 2]
    if not distinctive_tokens:
        return False

    suggested_compact = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", suggested_base).lower()
    for token in distinctive_tokens:
        token_compact = re.sub(r"[^0-9a-zA-Z]+", "", token).lower()
        if token_compact and token_compact not in suggested_compact:
            return True
    return False


def _name_roi_for_candidate(candidate: DesignFragmentCardCandidate) -> RoiRegion:
    """根据卡片几何计算装备名称 ROI。"""
    x, y, width, height = candidate.bbox
    rel_x, rel_y, rel_width, rel_height = NAME_RATIO
    return (
        x + int(round(width * rel_x)),
        y + int(round(height * rel_y)),
        max(1, int(round(width * rel_width))),
        max(1, int(round(height * rel_height))),
    )


def _attribute_roi_for_candidate(candidate: DesignFragmentCardCandidate) -> RoiRegion:
    """
    根据卡片几何计算右侧属性文字 ROI。

    输入：
        设计图卡片候选。
    输出：
        属性文字绝对 ROI。
    使用示例：
        roi = _attribute_roi_for_candidate(candidate)
    """
    x, y, width, height = candidate.bbox
    icon_x, _icon_y, icon_width, _icon_height = candidate.icon_roi
    quantity_x, _quantity_y, _quantity_width, _quantity_height = candidate.quantity_roi
    left = icon_x + icon_width + 14
    top = y + int(round(height * 0.30))
    right = max(left + 1, quantity_x - 8)
    bottom = y + height - 8
    return (left, top, max(1, right - left), max(1, bottom - top))


def _attribute_observed_text(attribute_ocr_result: Mapping[str, Any]) -> str:
    """
    合并属性 OCR 主文本和 raw_texts，给属性重排使用。

    输入：
        OCR result dict。
    输出：
        去重后的文本。
    使用示例：
        text = _attribute_observed_text(result)
    """
    chunks: List[str] = []
    text = str(attribute_ocr_result.get("text", "") or "").strip()
    if text:
        chunks.append(text)
    for raw in attribute_ocr_result.get("raw_texts", []) or []:
        raw_text = str(raw or "").strip()
        if raw_text and raw_text not in chunks:
            chunks.append(raw_text)
    return " ".join(chunks)


# ============================================================
# 🎨 第五部分：绘图与输出
# ============================================================

def draw_prelabel_annotations(
    detector: DesignFragmentDetector,
    image: Any,
    detection: DesignFragmentDetectionResult,
    rows: Sequence[Mapping[str, Any]],
    meta: V2ImageMeta,
) -> Any:
    """
    绘制 v2 预标注图。
    输入：
        detector/image/detection/rows/meta。
    输出：
        OpenCV BGR 图。
    使用示例：
        annotated = draw_prelabel_annotations(detector, image, detection, rows, meta)
    """
    cv2_module = detector._require_cv2()  # noqa: SLF001 - lab 绘图复用检测器依赖。
    annotated = image.copy()
    row_by_index = {int(row.get("detected_index", -1)): row for row in rows}
    text_draw_ops: List[Tuple[str, Tuple[int, int], Tuple[int, int, int], float]] = []
    for candidate in detection.candidates:
        row = row_by_index.get(candidate.index, {})
        full_card = row.get("selected") is True
        needs_review = row.get("needs_review") is True
        auto_accept = row.get("auto_accept") is True
        if not full_card:
            color = (120, 120, 120)
        elif auto_accept:
            color = (60, 220, 60)
        elif needs_review:
            color = (0, 210, 255)
        else:
            color = (255, 160, 0)

        x, y, width, height = candidate.bbox
        ix, iy, iw, ih = candidate.icon_roi
        nx, ny, nw, nh = _name_roi_for_candidate(candidate)
        ax, ay, aw, ah = _attribute_roi_for_candidate(candidate)
        qx, qy, qw, qh = candidate.quantity_roi
        cv2_module.rectangle(annotated, (x, y), (x + width, y + height), color, 2 if full_card else 1)
        cv2_module.rectangle(annotated, (ix, iy), (ix + iw, iy + ih), (255, 180, 0), 1)
        cv2_module.rectangle(annotated, (nx, ny), (nx + nw, ny + nh), (220, 120, 255), 1)
        cv2_module.rectangle(annotated, (ax, ay), (ax + aw, ay + ah), (0, 165, 255), 1)
        cv2_module.rectangle(annotated, (qx, qy), (qx + qw, qy + qh), (255, 255, 0), 1)

        equipment_name = row.get("accepted_equipment_name") or row.get("suggested_equipment_name") or row.get("icon_equipment_name") or row.get("suggested_equipment_id") or ""
        count_text = ""
        if row.get("ocr_fragment_count") not in (None, ""):
            count_text = f"{row.get('ocr_fragment_count')}/{row.get('ocr_required_count') or '?'}"
        label = (
            f"card{int(row.get('card_no', candidate.index)):02d} {equipment_name} {count_text} "
            f"{row.get('icon_status', '')}:{float(row.get('icon_confidence', 0.0) or 0.0):.2f}"
        )
        if row.get("name_assisted") is True:
            label = f"name+ {label}"
        if row.get("attribute_assisted") is True:
            label = f"attr+ {label}"
        if row.get("name_override_allowed") is True:
            label = f"text> {label}"
        if row.get("name_icon_conflict") is True:
            label = f"conflict {label}"
        if needs_review:
            label = f"REVIEW {label}"
        if not full_card:
            label = f"skip card{int(row.get('card_no', candidate.index)):02d} {candidate.visibility}"
        text_draw_ops.append((label[:42], (x + 4, max(18, y + 18)), color, 15.0))

    summary = f"{meta.filename} rarity={meta.rarity} page={meta.page_index} pos={meta.scroll_position}"
    text_draw_ops.append((summary[:90], (20, 88), (0, 255, 255), 20.0))
    annotated = render_unicode_labels(annotated, text_draw_ops)
    return annotated


def write_outputs(output_dir: Path, results: Sequence[Mapping[str, Any]]) -> None:
    """
    写出预标注 JSON/CSV/复核清单/草稿 exp。
    输入：
        output_dir/results。
    输出：
        多个预标注文件。
    使用示例：
        write_outputs(Path("img_out/prelabel"), results)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    backup_existing_outputs(
        output_dir,
        (
            "v2_prelabel_draft_exp.txt",
            "v2_prelabel_review_only_exp.txt",
            "v2_prelabel_review_guide.txt",
            "v2_prelabel_review.csv",
        ),
    )
    (output_dir / "v2_prelabel_results.json").write_text(json.dumps(list(results), ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "v2_prelabel_summary.json").write_text(json.dumps(summarize_results(results), ensure_ascii=False, indent=2), encoding="utf-8")
    write_cards_csv(output_dir / "v2_prelabel_results.csv", iter_card_rows(results))
    write_cards_csv(output_dir / "v2_prelabel_review.csv", (row for row in iter_card_rows(results) if row.get("needs_review") is True))
    (output_dir / "v2_prelabel_draft_exp.txt").write_text(build_draft_exp(results), encoding="utf-8")
    (output_dir / "v2_prelabel_review_only_exp.txt").write_text(build_draft_exp(results, only_review=True), encoding="utf-8")
    (output_dir / "v2_prelabel_review_guide.txt").write_text(build_review_guide(results), encoding="utf-8")


def backup_existing_outputs(output_dir: Path, filenames: Sequence[str]) -> None:
    """
    覆盖预标注文件前备份，避免人工修正被下一轮脚本覆盖。
    输入：
        output_dir/filenames。
    输出：
        backups/ 下的 .bak 文件。
    使用示例：
        backup_existing_outputs(Path("prelabel"), ("v2_prelabel_review_only_exp.txt",))
    """
    backup_dir = output_dir / "backups"
    for filename in filenames:
        source = output_dir / filename
        if not source.exists() or not source.is_file():
            continue
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = source.stat().st_mtime_ns
        label = ".human_review" if _has_non_empty_accepted_names(source) else ""
        target = backup_dir / f"{source.stem}{label}.{stamp}.bak{source.suffix}"
        if not target.exists():
            target.write_bytes(source.read_bytes())


def _has_non_empty_accepted_names(path: Path) -> bool:
    """
    判断 exp 文件是否包含人工填写过的 accepted_equipment_name。

    输入：
        exp 文本路径。
    输出：
        True 表示至少有一行 accepted_equipment_name 非空。
    使用示例：
        _has_non_empty_accepted_names(Path("v2_prelabel_review_only_exp.txt"))
    """
    if path.suffix.lower() != ".txt":
        return False
    try:
        text = path.read_text(encoding="utf-8-sig")
    except Exception:
        return False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if ".accepted_equipment_name:" not in line and not line.startswith("accepted_equipment_name:"):
            continue
        _, value = line.split(":", 1)
        if value.strip():
            return True
    return False


def iter_card_rows(results: Sequence[Mapping[str, Any]]) -> Iterable[Dict[str, Any]]:
    """逐行产出卡片结果。"""
    for result in results:
        for row in result.get("cards", []):
            yield dict(row)


def write_cards_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    """写出卡片 CSV。"""
    fieldnames = [
        "filename",
        "filter_rarity",
        "filter_rarity_id",
        "scroll_position",
        "page_index",
        "card_no",
        "selected",
        "quantity_selected",
        "icon_selected",
        "detected_index",
        "bbox",
        "name_roi",
        "attribute_roi",
        "visibility",
        "name_ocr_status",
        "name_ocr_text",
        "name_ocr_confidence",
        "name_resolve_status",
        "name_resolve_equipment_id",
        "name_resolve_equipment_name",
        "name_resolve_score",
        "name_resolve_candidates",
        "name_in_icon_candidates",
        "name_global_strong",
        "name_can_recover_weak_icon",
        "name_tierless_base_ambiguous",
        "name_override_allowed",
        "name_assisted",
        "name_icon_conflict",
        "name_partial_conflict",
        "attribute_ocr_status",
        "attribute_ocr_text",
        "attribute_ocr_confidence",
        "attribute_rerank_status",
        "attribute_rerank_equipment_id",
        "attribute_rerank_equipment_name",
        "attribute_rerank_score",
        "attribute_rerank_margin",
        "attribute_rerank_attribute_margin",
        "attribute_in_icon_candidates",
        "attribute_assisted",
        "attribute_name_conflict",
        "attribute_rerank_candidates",
        "high_value_card",
        "high_value_confident_icon",
        "high_value_name_weak",
        "high_value_strong_name",
        "high_value_guard_active",
        "ocr_status",
        "ocr_fragment_count",
        "ocr_required_count",
        "ocr_confidence",
        "ocr_text",
        "icon_status",
        "icon_equipment_id",
        "icon_equipment_name",
        "icon_confidence",
        "suggested_equipment_id",
        "suggested_equipment_name",
        "current_resolved_equipment_id",
        "icon_top_candidates",
        "machine_prefill",
        "auto_accept",
        "icon_needs_review",
        "ocr_needs_review",
        "needs_review",
        "review_reason",
        "accepted_equipment_name",
        "accepted_equipment_id",
        "accepted_fragment_owned",
        "accepted_fragment_required",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def build_draft_exp(results: Sequence[Mapping[str, Any]], only_review: bool = False) -> str:
    """
    构建给用户人工修改的 draft exp。
    输入：
        results。
    输出：
        文本文档。
    使用示例：
        text = build_draft_exp(results)
    """
    lines: List[str] = [
        "# equipment_icon_matcher_v2 自动预标注草稿",
        "# 该文件展示机器候选，不再把机器猜测写入 accepted_equipment_name。",
        "# 正式人工入口请使用 review_iterations/<iter>/to_label/v2_review_todo_exp.txt。",
        "# 你主要需要检查 needs_review=true 的卡片；后续以 accepted_equipment_name 作为稳定标注主键。",
        "# machine_prefill=true 表示脚本内部认为可机器接管；这里只作为注释提示，不作为人工答案。",
        "# auto_accept=true 表示机器高可信，但仍建议抽查。",
        "# accepted_equipment_id/current_resolved_equipment_id 只是当前 equipment_library.csv 下的解析结果，ID 以后可能随 wiki 同步变化。",
        "# 如果机器建议名称正确，请在 review_iterations 的待标注文件里填写 accepted_equipment_name。",
        "# 顶部/底部被裁剪的 skip_partial_card 默认不要填 accepted_equipment_name。",
        f"# only_review:{only_review}",
        "",
    ]
    for result in results:
        meta = result.get("meta", {})
        cards = list(result.get("cards", []))
        full_cards = [row for row in cards if row.get("selected") is True]
        if only_review:
            full_cards = [row for row in full_cards if row.get("needs_review") is True]
            if not full_cards:
                continue
        icon_cards = [row for row in cards if row.get("icon_selected") is True]
        quantity_cards = [row for row in cards if row.get("quantity_selected") is True]
        lines.extend(
            [
                f"[{result.get('filename', '')}]",
                "image_mode:viewport_full",
                "source_crop:full_screen",
                "page:fragment",
                "tab:design",
                f"filter_rarity:{meta.get('rarity', 'unknown')}",
                f"filter_rarity_id:{meta.get('rarity_id', 0)}",
                "sort:buildable",
                f"scroll_position:{meta.get('scroll_position', 'unknown')}",
                f"page_index:{meta.get('page_index', 'unknown')}",
                f"candidate_cards:{len(cards)}",
                f"usable_quantity_cards:{len(quantity_cards)}",
                f"usable_icon_cards:{len(icon_cards)}",
                "note:v2自动生成; 只建议确认 visibility=full 的卡; 裁切卡在相邻截图中处理",
            ]
        )
        for row in full_cards:
            card_no = int(row.get("card_no", 0) or 0)
            prefix = f"card_{card_no:02d}"
            suggestion = row.get("suggested_equipment_id") or ""
            name = row.get("suggested_equipment_name") or ""
            status = row.get("icon_status") or ""
            confidence = float(row.get("icon_confidence", 0.0) or 0.0)
            reason = row.get("review_reason") or "ok"
            name_assist_note = ""
            if row.get("name_assisted") is True:
                name_assist_note = f" name_assisted={row.get('name_resolve_equipment_name')} score={float(row.get('name_resolve_score', 0.0) or 0.0):.3f}"
            elif row.get("name_icon_conflict") is True:
                name_assist_note = f" name_icon_conflict={row.get('name_resolve_equipment_name')}"
            lines.append(
                f"# {prefix}.suggested:{suggestion} {name} status={status} "
                f"conf={confidence:.3f} machine_prefill={row.get('machine_prefill')} "
                f"auto_accept={row.get('auto_accept')} reason={reason}{name_assist_note}"
            )
            lines.append(f"# {prefix}.image_top3:{format_human_top3(row.get('icon_top_candidates', ''))}")
            lines.append(f"# {prefix}.name_top3:{format_human_name_top3(row)}")
            if row.get("attribute_rerank_status") not in ("", "disabled"):
                lines.append(f"# {prefix}.attribute_top3:{format_human_attribute_top3(row)}")
            lines.append(f"{prefix}.accepted_equipment_name:")
            lines.append(f"{prefix}.current_resolved_equipment_id:{row.get('current_resolved_equipment_id') or ''}")
            lines.append(f"{prefix}.accepted_equipment_id:")
            lines.append(f"{prefix}.accepted_fragment_owned:")
            lines.append(f"{prefix}.accepted_fragment_required:")
        lines.append("")
    return "\n".join(lines)


def format_human_top3(candidates_text: Any) -> str:
    """把 `ID:名称:分数 | ...` 压成适合人工标注阅读的 Top3。"""
    chunks: List[str] = []
    for index, raw_part in enumerate(str(candidates_text or "").split("|")[:3], start=1):
        part = raw_part.strip()
        if not part:
            continue
        pieces = part.rsplit(":", 2)
        if len(pieces) == 3:
            equipment_id, name, score = pieces
            chunks.append(f"{index}) {equipment_id.strip()} {name.strip()} {score.strip()}")
        else:
            chunks.append(f"{index}) {part}")
    return " | ".join(chunks) if chunks else "无"


def format_human_name_top3(row: Mapping[str, Any]) -> str:
    """把名称 OCR 文本和解析候选压成适合人工标注阅读的 Top3。"""
    ocr_text = str(row.get("name_ocr_text", "") or "")
    ocr_confidence = float(row.get("name_ocr_confidence", 0.0) or 0.0)
    prefix = f'OCR="{ocr_text}" conf={ocr_confidence:.3f}'
    candidates = str(row.get("name_resolve_candidates", "") or "")
    candidate_text = format_human_top3(candidates)
    if candidate_text != "无":
        return f"{prefix} | {candidate_text}"
    resolved_name = str(row.get("name_resolve_equipment_name", "") or "")
    resolved_id = str(row.get("name_resolve_equipment_id", "") or "")
    score = float(row.get("name_resolve_score", 0.0) or 0.0)
    if resolved_name or resolved_id:
        return f"{prefix} | 1) {resolved_id} {resolved_name} {score:.3f}"
    return prefix


def format_human_attribute_top3(row: Mapping[str, Any]) -> str:
    """把属性 OCR 和属性重排候选压成适合人工阅读的 Top3。"""
    ocr_text = str(row.get("attribute_ocr_text", "") or "")
    ocr_confidence = float(row.get("attribute_ocr_confidence", 0.0) or 0.0)
    prefix = f'OCR="{ocr_text}" conf={ocr_confidence:.3f}'
    candidates = str(row.get("attribute_rerank_candidates", "") or "")
    chunks: List[str] = []
    for index, raw_part in enumerate(candidates.split("|")[:3], start=1):
        part = raw_part.strip()
        if not part:
            continue
        chunks.append(f"{index}) {part}")
    if chunks:
        return f"{prefix} | {' | '.join(chunks)}"
    return prefix


def draw_unicode_labels(
    image: Any,
    operations: Sequence[Tuple[str, Tuple[int, int], Tuple[int, int, int], float]],
) -> Any:
    """
    用 Pillow 绘制中文标签；缺 Pillow/字体时退回 OpenCV。
    输入：
        OpenCV BGR 图像和文字操作。
    输出：
        带中文标签的 BGR 图像。
    使用示例：
        annotated = draw_unicode_labels(annotated, [("液压弹射装置", (10, 10), (0, 255, 0), 16)])
    """
    try:
        if Image is None or ImageDraw is None:
            raise RuntimeError("Pillow unavailable")
        import cv2

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb)
        draw = ImageDraw.Draw(pil_image)
        font_cache: Dict[int, Any] = {}
        for text, position, color, font_size in operations:
            size = int(round(font_size))
            if size not in font_cache:
                font_cache[size] = load_chinese_font(size)
            bgr = tuple(int(item) for item in color)
            rgb_color = (bgr[2], bgr[1], bgr[0])
            draw.text(position, text, fill=rgb_color, font=font_cache[size])
        return cv2.cvtColor(np.asarray(pil_image), cv2.COLOR_RGB2BGR)
    except Exception:
        cv2_module = DesignFragmentDetector()._require_cv2()  # noqa: SLF001 - lab fallback。
        fallback = image.copy()
        for text, position, color, font_size in operations:
            safe_text = re.sub(r"[^\x00-\x7F]+", "?", text)
            cv2_module.putText(
                fallback,
                safe_text,
                position,
                cv2_module.FONT_HERSHEY_SIMPLEX,
                max(0.35, font_size / 34.0),
                color,
                1,
                cv2_module.LINE_AA,
            )
        return fallback


def load_chinese_font(font_size: int) -> Any:
    """加载 Windows 中文字体；失败时使用 Pillow 默认字体。"""
    if ImageFont is None:
        return None
    for font_path in DEFAULT_FONT_PATHS:
        if font_path.exists():
            return ImageFont.truetype(str(font_path), font_size)
    return ImageFont.load_default()


def build_review_guide(results: Sequence[Mapping[str, Any]]) -> str:
    """
    构建给用户验图的中文清单。
    输入：
        results。
    输出：
        按图片分组的复核说明。
    使用示例：
        guide = build_review_guide(results)
    """
    summary = summarize_results(results)
    lines: List[str] = [
        "equipment_icon_matcher_v2 预标注复核指南",
        "========================================",
        "",
        "你优先需要看的文件：",
        "",
        "1. annotated/ 下的标注图：看 card 编号和机器猜测是否对。",
        "2. v2_prelabel_review.csv：只包含 needs_review=true 的卡。",
        "3. v2_prelabel_draft_exp.txt：你最终修改 accepted_equipment_name 的地方。",
        "",
        "颜色含义：",
        "",
        "- 绿色：机器高可信或已预填，建议抽查。",
        "- 黄色：需要重点复核，通常是 ambiguous 或低于 review_confidence。",
        "- 蓝/青色 text>：名称 OCR 直接接管图标结果。",
        "- 紫框 name_roi：名称 OCR 区域；name_assisted=true 表示名称 OCR 帮图标候选完成消歧。",
        "- name_icon_conflict=true：名称 OCR 和图标 top1 冲突，必须人工确认。",
        "- name_partial_conflict=true：名称 OCR 读到的口径/型号数字与图标建议不一致，必须人工确认。",
        "- attribute_name_conflict=true：名称 OCR 和 Wiki 属性重排互相冲突，属性结果不会自动覆盖名称结果。",
        "- 灰色：顶部/底部被裁切，默认不要标，下一张截图会出现完整卡。",
        "",
        "总览：",
        "",
        f"- 输入截图：{summary['images']} 张",
        f"- 完整卡片：{summary['full_cards']} 张",
        f"- 机器预填名称：{summary['machine_prefill_cards']} 张",
        f"- 高可信 auto_accept：{summary['auto_accept_cards']} 张",
        f"- 名称 OCR 直接接管：{summary['name_override_cards']} 张",
        f"- 名称 OCR 辅助消歧：{summary['name_assisted_cards']} 张",
        f"- Wiki 属性辅助消歧：{summary['attribute_assisted_cards']} 张",
        f"- 属性 OCR 可用：{summary['attribute_ocr_success_cards']} 张",
        f"- 名称 OCR 救回图标漏召回：{summary['name_recovered_cards']} 张",
        f"- 同名多 T 等级保守复核：{summary['name_tier_ambiguous_cards']} 张",
        f"- 金/彩保守复核拦截：{summary['high_value_guard_cards']} 张",
        f"- 名称/图标冲突：{summary['name_conflict_cards']} 张",
        f"- 名称局部口径冲突：{summary['name_partial_conflict_cards']} 张",
        f"- 名称/属性重排冲突：{summary['attribute_name_conflict_cards']} 张",
        f"- 需要你重点复核：{summary['needs_review_cards']} 张",
        "",
        "复核原则：",
        "",
        "- 优先改 accepted_equipment_name，不要只改 ID。",
        "- 如果机器建议名称正确，可以把 accepted_equipment_name 填成 suggested 名称。",
        "- 如果看不清、被遮挡、不确定，保持空白，不要强行标。",
        "- current_resolved_equipment_id 只是当前装备库解析出的参考 ID，以后可能变化。",
        "",
        "逐图复核清单：",
        "",
    ]

    for result in results:
        rows = [row for row in result.get("cards", []) if row.get("needs_review") is True]
        if not rows:
            continue
        meta = result.get("meta", {})
        lines.append(f"[{result.get('filename', '')}] rarity={meta.get('rarity', '')} page={meta.get('page_index', '')}")
        for row in rows:
            card_no = int(row.get("card_no", 0) or 0)
            suggestion = row.get("suggested_equipment_name") or row.get("suggested_equipment_id") or "unknown"
            confidence = float(row.get("icon_confidence", 0.0) or 0.0)
            reason = row.get("review_reason") or "unknown"
            if row.get("name_icon_conflict") is True:
                reason = f"{reason};name_icon_conflict"
            candidates = str(row.get("icon_top_candidates", "") or "")
            short_candidates = candidates[:180] + ("..." if len(candidates) > 180 else "")
            name_hint = ""
            if row.get("name_resolve_equipment_name"):
                name_hint = f", 名称OCR={row.get('name_resolve_equipment_name')}({float(row.get('name_resolve_score', 0.0) or 0.0):.3f})"
            if row.get("attribute_assisted") is True:
                name_hint = f"{name_hint}, 属性重排={row.get('attribute_rerank_equipment_name')}({float(row.get('attribute_rerank_score', 0.0) or 0.0):.3f})"
            lines.append(
                f"  - card_{card_no:02d}: 建议={suggestion}, conf={confidence:.3f}, "
                f"原因={reason}{name_hint}, top={short_candidates}"
            )
        lines.append("")
    return "\n".join(lines)


def summarize_results(results: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """汇总预标注结果。"""
    cards = list(iter_card_rows(results))
    full_cards = [row for row in cards if row.get("selected") is True]
    partial_cards = [row for row in cards if row.get("selected") is not True]
    review_cards = [row for row in full_cards if row.get("needs_review") is True]
    icon_review_cards = [row for row in full_cards if row.get("icon_needs_review") is True]
    ocr_review_cards = [row for row in full_cards if row.get("ocr_needs_review") is True]
    machine_prefill_cards = [row for row in full_cards if row.get("machine_prefill") is True]
    auto_accept_cards = [row for row in full_cards if row.get("auto_accept") is True]
    name_assisted_cards = [row for row in full_cards if row.get("name_assisted") is True]
    name_override_cards = [row for row in full_cards if row.get("name_override_allowed") is True]
    name_recovered_cards = [row for row in full_cards if row.get("name_can_recover_weak_icon") is True]
    name_global_strong_cards = [row for row in full_cards if row.get("name_global_strong") is True]
    name_tier_ambiguous_cards = [row for row in full_cards if row.get("name_tierless_base_ambiguous") is True]
    name_conflict_cards = [row for row in full_cards if row.get("name_icon_conflict") is True]
    name_partial_conflict_cards = [row for row in full_cards if row.get("name_partial_conflict") is True]
    attribute_name_conflict_cards = [row for row in full_cards if row.get("attribute_name_conflict") is True]
    high_value_guard_cards = [row for row in full_cards if row.get("high_value_guard_active") is True]
    attribute_ocr_success_cards = [row for row in full_cards if row.get("attribute_ocr_status") == "success"]
    attribute_assisted_cards = [row for row in full_cards if row.get("attribute_assisted") is True]
    by_rarity: Dict[str, Dict[str, int]] = {}
    for row in cards:
        bucket = by_rarity.setdefault(
            str(row.get("filter_rarity", "unknown")),
            {
                "cards": 0,
                "full": 0,
                "review": 0,
                "icon_review": 0,
                "machine_prefill": 0,
                "auto_accept": 0,
                "name_override": 0,
                "name_assisted": 0,
                "name_recovered": 0,
                "name_global_strong": 0,
                "name_tier_ambiguous": 0,
                "name_conflict": 0,
                "name_partial_conflict": 0,
                "attribute_ocr_success": 0,
                "attribute_assisted": 0,
                "attribute_name_conflict": 0,
                "high_value_guard": 0,
            },
        )
        bucket["cards"] += 1
        if row.get("selected") is True:
            bucket["full"] += 1
        if row.get("needs_review") is True:
            bucket["review"] += 1
        if row.get("icon_needs_review") is True:
            bucket["icon_review"] += 1
        if row.get("machine_prefill") is True:
            bucket["machine_prefill"] += 1
        if row.get("auto_accept") is True:
            bucket["auto_accept"] += 1
        if row.get("name_assisted") is True:
            bucket["name_assisted"] += 1
        if row.get("name_override_allowed") is True:
            bucket["name_override"] += 1
        if row.get("name_can_recover_weak_icon") is True:
            bucket["name_recovered"] += 1
        if row.get("name_global_strong") is True:
            bucket["name_global_strong"] += 1
        if row.get("name_tierless_base_ambiguous") is True:
            bucket["name_tier_ambiguous"] += 1
        if row.get("name_icon_conflict") is True:
            bucket["name_conflict"] += 1
        if row.get("name_partial_conflict") is True:
            bucket["name_partial_conflict"] += 1
        if row.get("attribute_ocr_status") == "success":
            bucket["attribute_ocr_success"] += 1
        if row.get("attribute_assisted") is True:
            bucket["attribute_assisted"] += 1
        if row.get("attribute_name_conflict") is True:
            bucket["attribute_name_conflict"] += 1
        if row.get("high_value_guard_active") is True:
            bucket["high_value_guard"] += 1
    return {
        "images": len(results),
        "cards": len(cards),
        "full_cards": len(full_cards),
        "partial_or_skipped_cards": len(partial_cards),
        "auto_accept_cards": len(auto_accept_cards),
        "machine_prefill_cards": len(machine_prefill_cards),
        "name_override_cards": len(name_override_cards),
        "name_assisted_cards": len(name_assisted_cards),
        "name_recovered_cards": len(name_recovered_cards),
        "name_global_strong_cards": len(name_global_strong_cards),
        "name_tier_ambiguous_cards": len(name_tier_ambiguous_cards),
        "name_conflict_cards": len(name_conflict_cards),
        "name_partial_conflict_cards": len(name_partial_conflict_cards),
        "attribute_ocr_success_cards": len(attribute_ocr_success_cards),
        "attribute_assisted_cards": len(attribute_assisted_cards),
        "attribute_name_conflict_cards": len(attribute_name_conflict_cards),
        "high_value_guard_cards": len(high_value_guard_cards),
        "needs_review_cards": len(review_cards),
        "icon_needs_review_cards": len(icon_review_cards),
        "ocr_needs_review_cards": len(ocr_review_cards),
        "by_rarity": by_rarity,
        "note": "该结果是 v2 自动预标注，不能作为真实准确率；请优先修正 v2_prelabel_review.csv 和 draft_exp 中 needs_review=true 的卡。",
    }


# ============================================================
# 🚀 第六部分：主入口
# ============================================================

def main() -> int:
    """
    脚本入口。
    输入：
        命令行参数。
    输出：
        进程退出码。
    使用示例：
        python ocr_training_lab/equipment_icon_matcher_v2/run_v2_prelabel.py
    """
    args = parse_args()
    images = collect_images(args.input_dir, args.pattern)
    if not images:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        write_outputs(args.output_dir, [])
        print(f"没有找到 v2 输入图片: {args.input_dir / args.pattern}")
        return 1

    config = load_recognition_config(PROJECT_ROOT / "config" / "recognition" / "roi_config.json")
    catalog = load_equipment_catalog(PROJECT_ROOT)
    detector = DesignFragmentDetector()
    status = detector.check_status()
    if not status.get("available"):
        print("OpenCV/NumPy 不可用，无法生成 v2 预标注。")
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 2

    reader: Optional[EquipmentCardDigitReader] = None
    read_quantity_ocr = not bool(args.skip_ocr)
    if read_quantity_ocr or args.enable_name_ocr or args.enable_attribute_ocr:
        print("提示：正在初始化本地 PaddleOCR；Creating model/ccache 查找信息不是脚本失败，最终以 summary 为准。", flush=True)
        reader = EquipmentCardDigitReader(OcrEngine(config=config.get("ocr", {})), config.get("card_digits", {}))

    attribute_reranker: Optional[EquipmentAttributeReranker] = None
    if args.enable_attribute_rerank:
        if not args.attribute_model_json.exists():
            print(f"Wiki 属性模型不存在，跳过属性重排: {args.attribute_model_json}")
        else:
            attribute_reranker = EquipmentAttributeReranker.from_model_file(
                args.attribute_model_json,
                icon_weight=max(0.0, float(args.attribute_rerank_icon_weight)),
                attribute_weight=max(0.0, float(args.attribute_rerank_attribute_weight)),
                min_attribute_score=max(0.0, float(args.attribute_rerank_min_score)),
                min_margin=max(0.0, float(args.attribute_rerank_min_margin)),
            )

    matcher_cache: Dict[str, Optional[EquipmentIconMatcher]] = {}
    combined_gallery_cache: Dict[str, Optional[Path]] = {}
    name_resolver_cache: Dict[str, Optional[EquipmentNameResolver]] = {}
    results: List[Dict[str, Any]] = []
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for image_path, meta in images:
        matcher: Optional[EquipmentIconMatcher] = None
        if not args.skip_icons:
            if meta.rarity not in combined_gallery_cache:
                combined_gallery_cache[meta.rarity] = build_combined_gallery_csv(
                    args.output_dir,
                    meta.rarity,
                    catalog,
                    [args.accepted_gallery_csv, args.reviewed_gallery_csv],
                )
            if meta.rarity not in matcher_cache:
                matcher_cache[meta.rarity] = build_matcher_for_rarity(
                    meta.rarity,
                    config,
                    combined_gallery_cache[meta.rarity],
                    enable_region_refine=bool(args.enable_region_refine),
                )
            matcher = matcher_cache[meta.rarity]

        name_resolver: Optional[EquipmentNameResolver] = None
        if args.enable_name_ocr:
            cache_key = f"{meta.rarity}:{meta.rarity_id}"
            if cache_key not in name_resolver_cache:
                rarity_catalog = filter_catalog_by_rarity(catalog, meta.rarity_id)
                name_resolver_cache[cache_key] = EquipmentNameResolver.from_catalog(
                    rarity_catalog if rarity_catalog else catalog,
                    min_score=max(0.0, min(1.0, float(args.name_fuzzy_threshold))),
                )
            name_resolver = name_resolver_cache[cache_key]

        result = process_one(
            image_path=image_path,
            meta=meta,
            output_dir=args.output_dir,
            detector=detector,
            reader=reader,
            matcher=matcher,
            name_resolver=name_resolver,
            attribute_reranker=attribute_reranker,
            catalog=catalog,
            top_n=max(1, int(args.top_n)),
            review_confidence=max(0.0, min(1.0, float(args.review_confidence))),
            auto_accept_confidence=max(
                0.0,
                min(
                    1.0,
                    float(args.high_confidence)
                    if args.high_confidence is not None
                    else float(args.auto_accept_confidence),
                ),
            ),
            read_quantity_ocr=read_quantity_ocr,
            enable_name_ocr=bool(args.enable_name_ocr),
            name_ocr_confidence=max(0.0, min(1.0, float(args.name_ocr_confidence))),
            name_fuzzy_threshold=max(0.0, min(1.0, float(args.name_fuzzy_threshold))),
            name_assist_icon_confidence=max(0.0, min(1.0, float(args.name_assist_icon_confidence))),
            name_override_icon_confidence=max(0.0, min(1.0, float(args.name_override_icon_confidence))),
            name_global_assist_score=max(0.0, min(1.0, float(args.name_global_assist_score))),
            enable_attribute_ocr=bool(args.enable_attribute_ocr),
            attribute_ocr_confidence=max(0.0, min(1.0, float(args.attribute_ocr_confidence))),
            high_value_rarity_id=max(1, int(args.high_value_rarity_id)),
            high_value_review_confidence=max(0.0, min(1.0, float(args.high_value_review_confidence))),
            high_value_strong_name_score=max(0.0, min(1.0, float(args.high_value_strong_name_score))),
            pattern_prefix=str(args.pattern_prefix),
            write_preview=not bool(args.no_preview),
        )
        results.append(result)
        cards = result.get("cards", [])
        review = sum(1 for row in cards if row.get("needs_review") is True)
        auto_accept = sum(1 for row in cards if row.get("auto_accept") is True)
        full_cards = sum(1 for row in cards if row.get("selected") is True)
        print(
            f"{image_path.name}: rarity={meta.rarity}, page={meta.page_index}, "
            f"cards={len(cards)}, full={full_cards}, auto_accept={auto_accept}, review={review}"
        )

    write_outputs(args.output_dir, results)
    summary = summarize_results(results)
    print(f"已输出 v2 预标注到: {args.output_dir}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
