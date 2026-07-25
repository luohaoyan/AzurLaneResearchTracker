#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      稀有度分桶预标注脚本 (run_rarity_bucket_detection.py)   ║
║                                                              ║
║  【一句话解释】按稀有度筛选后的设计图页，批量输出卡片预标注。║
║  【类比理解】它像先按颜色分好装备图鉴，再逐格抄出可能是谁。  ║
║  【数据流说明】rarity_bucket_img_input→rarity_bucket_img_out；║
║              test_img/rarity_bucket→test_out/rarity_bucket。 ║
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
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


# 脚本位于 ocr_training_lab/fragment_filter_scan/ 下，运行时主动把项目根目录加入 import 路径。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.recognition.design_fragment_detector import (  # noqa: E402
    DesignFragmentCardCandidate,
    DesignFragmentDetectionResult,
    DesignFragmentDetector,
)
from core.recognition.equipment_card_reader import EquipmentCardDigitReader, FragmentQuantityReadResult  # noqa: E402
from core.recognition.equipment_icon_matcher import EquipmentIconMatchResult, EquipmentIconMatcher  # noqa: E402
from core.recognition.ocr_engine import OcrEngine  # noqa: E402


# Paddle 在 Windows 下会用 `where ccache` 探测编译缓存工具；没装 ccache 时会打印一条
# 与 OCR 推理无关的 UserWarning。这里过滤掉它，避免人工运行脚本时误认为模型加载失败。
warnings.filterwarnings("ignore", message="No ccache found.*", category=UserWarning)


# ============================================================
# 🧱 第二部分：数据对象与常量
# ============================================================

RoiRegion = Tuple[int, int, int, int]

TRUE_VALUES = {"true", "ture", "yes", "y", "1", "是", "on", "开启"}
FALSE_VALUES = {"false", "no", "n", "0", "否", "off", "关闭"}
BOOL_KEYS = {"overview"}
INT_KEYS = {
    "filter_rarity_id",
    "page_index",
    "candidate_cards",
    "usable_quantity_cards",
    "usable_icon_cards",
}
RARITY_ALIASES = {
    "ur": "ultra_rare",
    "ultra": "ultra_rare",
    "ultra_rare": "ultra_rare",
    "utral_rare": "ultra_rare",
    "rainbow": "ultra_rare",
    "ssr": "super_rare",
    "gold": "super_rare",
    "super_rare": "super_rare",
    "purple": "elite",
    "elite": "elite",
    "blue": "rare",
    "rare": "rare",
    "white": "common",
    "common": "common",
    "all": "all",
    "unknown": "unknown",
}
RARITY_TO_ID = {
    "common": 1,
    "rare": 2,
    "elite": 3,
    "super_rare": 4,
    "ultra_rare": 5,
}


@dataclass(frozen=True)
class RarityBucketAnnotation:
    """
    单张稀有度分桶截图的人工标注。
    输入：
        filename/fields。
    输出：
        截图级标注，供候选卡片数量和分桶图库过滤使用。
    使用示例：
        ann = annotations["design_super_rare_1.png"]
    """

    filename: str
    fields: Mapping[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """转换成 JSON 友好的普通字典。"""
        return {
            "filename": self.filename,
            "fields": dict(self.fields),
        }


@dataclass(frozen=True)
class CandidateSelection:
    """
    检测候选与截图级标注之间的选择结果。
    输入：
        selected/quantity_selected/icon_selected/warnings。
    输出：
        本张图哪些卡片参与 OCR，哪些卡片参与图标匹配。
    使用示例：
        selection = select_candidates_for_annotation(result.candidates, ann)
    """

    selected: Tuple[DesignFragmentCardCandidate, ...]
    quantity_selected: Tuple[DesignFragmentCardCandidate, ...]
    icon_selected: Tuple[DesignFragmentCardCandidate, ...]
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """转换成 JSON 友好的普通字典。"""
        return {
            "selected_indices": [item.index for item in self.selected],
            "quantity_indices": [item.index for item in self.quantity_selected],
            "icon_indices": [item.index for item in self.icon_selected],
            "warnings": list(self.warnings),
        }


# ============================================================
# 🏗️ 第三部分：参数、配置与标注解析
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。
    输入：
        命令行参数。
    输出：
        argparse.Namespace。
    使用示例：
        python run_rarity_bucket_detection.py --skip-ocr
    """
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="批量识别设计图稀有度分桶截图，输出预标注结果。")
    parser.add_argument("--input-dir", type=Path, default=script_dir / "rarity_bucket_img_input", help="训练/校准截图目录。")
    parser.add_argument("--test-dir", type=Path, default=script_dir / "test_img" / "rarity_bucket", help="稀有度分桶稳定性测试截图目录。")
    parser.add_argument("--output-dir", type=Path, default=None, help="输出目录。默认训练图→rarity_bucket_img_out，测试图→test_out/rarity_bucket。")
    parser.add_argument("--exp-file", type=Path, default=None, help="标注文件。默认从输入目录读取 rarity_bucket_exp.txt。")
    parser.add_argument("--use-test", "--test", action="store_true", help="处理 test_img/rarity_bucket，并输出到 test_out/rarity_bucket。")
    parser.add_argument("--skip-ocr", action="store_true", help="跳过碎片数量 OCR，只做卡片和图标预标注。")
    parser.add_argument("--skip-icons", action="store_true", help="跳过装备图标匹配，只做卡片和数量预标注。")
    parser.add_argument("--top-n", type=int, default=5, help="每张卡片保留多少个装备图标候选。")
    parser.add_argument("--pattern", default="*.png", help="输入图片匹配模式，默认 *.png。")
    return parser.parse_args()


def resolve_output_dir(script_dir: Path, use_test: bool, output_dir: Optional[Path]) -> Path:
    """
    根据输入来源选择输出目录，避免训练与泛化测试混在一起。
    输入：
        script_dir/use_test/output_dir。
    输出：
        实际输出目录。
    使用示例：
        resolve_output_dir(Path("fragment_filter_scan"), True, None)
    """
    if output_dir is not None:
        return output_dir
    if use_test:
        return script_dir / "test_out" / "rarity_bucket"
    return script_dir / "rarity_bucket_img_out"


def parse_rarity_bucket_exp(exp_path: Path) -> Dict[str, RarityBucketAnnotation]:
    """
    解析 rarity_bucket_exp.txt，兼容少量手工拼写误差。
    输入：
        exp_path。
    输出：
        filename → RarityBucketAnnotation。
    使用示例：
        annotations = parse_rarity_bucket_exp(Path("rarity_bucket_exp.txt"))
    """
    if not exp_path.exists():
        return {}

    annotations: Dict[str, Dict[str, Any]] = {}
    current_name = ""
    for raw_line in exp_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_name = line[1:-1].strip()
            annotations.setdefault(current_name, {})
            continue
        if not current_name or ":" not in line:
            continue
        raw_key, raw_value = line.split(":", 1)
        key = raw_key.strip()
        value = _normalize_annotation_value(key, raw_value.strip())
        annotations[current_name][key] = value

    parsed: Dict[str, RarityBucketAnnotation] = {}
    for filename, fields in annotations.items():
        normalized_fields = dict(fields)
        rarity = normalize_rarity(str(normalized_fields.get("filter_rarity", "unknown")))
        normalized_fields["filter_rarity"] = rarity
        if "filter_rarity_id" not in normalized_fields and rarity in RARITY_TO_ID:
            normalized_fields["filter_rarity_id"] = RARITY_TO_ID[rarity]
        parsed[filename] = RarityBucketAnnotation(filename, normalized_fields)
    return parsed


def _normalize_annotation_value(key: str, value: str) -> Any:
    """把手工标注中的 bool/int/unknown 转成脚本更好处理的类型。"""
    text = value.strip()
    lowered = text.lower()
    if key in BOOL_KEYS:
        if lowered in TRUE_VALUES:
            return True
        if lowered in FALSE_VALUES:
            return False
        return "unknown"
    if key in INT_KEYS:
        if lowered == "unknown":
            return "unknown"
        match = re.search(r"-?\d+", text.replace(",", ""))
        return int(match.group(0)) if match else "unknown"
    if key == "filter_rarity":
        return normalize_rarity(text)
    return text


def normalize_rarity(value: str) -> str:
    """
    规范化稀有度字段。
    输入：
        ut ral/ur/gold 等手写值。
    输出：
        ultra_rare/super_rare/elite/rare/common/all/unknown。
    使用示例：
        normalize_rarity("utral_rare") == "ultra_rare"
    """
    normalized = re.sub(r"[\s\-]+", "_", str(value or "").strip().lower())
    return RARITY_ALIASES.get(normalized, normalized or "unknown")


def load_recognition_config(config_path: Path) -> Dict[str, Any]:
    """
    读取识别配置，缺失时返回空配置。
    输入：
        config_path。
    输出：
        配置字典。
    使用示例：
        config = load_recognition_config(PROJECT_ROOT / "config" / "recognition" / "roi_config.json")
    """
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


def load_equipment_catalog(project_root: Path) -> Dict[str, Dict[str, Any]]:
    """
    只读加载装备库和图片映射，按 equipment_id 合并。
    输入：
        project_root。
    输出：
        equipment_id → name/rarity_id/type/image_path。
    使用示例：
        catalog = load_equipment_catalog(PROJECT_ROOT)
    """
    library_path = project_root / "data" / "equipment_library.csv"
    images_path = project_root / "data" / "equipment_images.csv"
    catalog: Dict[str, Dict[str, Any]] = {}

    if library_path.exists():
        with library_path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                equipment_id = str(row.get("equipment_id", "")).strip()
                if not equipment_id:
                    continue
                catalog[equipment_id] = {
                    "equipment_id": equipment_id,
                    "name": str(row.get("name", "")).strip(),
                    "rarity_id": _safe_int(row.get("rarity_id")),
                    "type": str(row.get("type", "")).strip(),
                    "image_path": "",
                }

    if images_path.exists():
        with images_path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                equipment_id = str(row.get("equipment_id", "")).strip()
                if not equipment_id:
                    continue
                catalog.setdefault(equipment_id, {"equipment_id": equipment_id, "name": "", "rarity_id": 0, "type": ""})
                catalog[equipment_id]["image_path"] = str(row.get("image_path", "")).strip()
    return catalog


def _safe_int(value: Any) -> int:
    """安全转整数，失败时返回 0。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ============================================================
# 🧮 第四部分：候选选择、识别和绘图
# ============================================================

def select_candidates_for_annotation(
    candidates: Sequence[DesignFragmentCardCandidate],
    annotation: Optional[RarityBucketAnnotation],
) -> CandidateSelection:
    """
    根据截图级标注选择有效卡片、数量 OCR 卡片和图标匹配卡片。
    输入：
        candidates/annotation。
    输出：
        CandidateSelection。
    使用示例：
        selection = select_candidates_for_annotation(result.candidates, annotation)
    """
    ordered = tuple(sorted(candidates, key=lambda item: (item.bbox[1], item.bbox[0], item.index)))
    if annotation is None:
        return CandidateSelection(ordered, ordered, ordered)

    fields = annotation.fields
    expected_cards = _field_int(fields.get("candidate_cards"), len(ordered))
    usable_quantity = _field_int(fields.get("usable_quantity_cards"), expected_cards)
    usable_icons = _field_int(fields.get("usable_icon_cards"), expected_cards)
    warnings: List[str] = []

    if expected_cards <= 0:
        if ordered:
            warnings.append(f"标注 candidate_cards=0，但检测器找到 {len(ordered)} 个几何候选；已按空列表处理。")
        return CandidateSelection((), (), (), tuple(warnings))

    if len(ordered) < expected_cards:
        warnings.append(f"检测候选 {len(ordered)} 少于标注 candidate_cards={expected_cards}，只能使用已有候选。")
    elif len(ordered) > expected_cards:
        warnings.append(f"检测候选 {len(ordered)} 多于标注 candidate_cards={expected_cards}，已优先保留前 {expected_cards} 个。")
    selected = tuple(ordered[:expected_cards])

    quantity_selected = tuple(selected[:max(0, min(usable_quantity, len(selected)))])
    top_skip, bottom_skip = _icon_skip_from_note(str(fields.get("note", "")))
    icon_window = selected[top_skip: len(selected) - bottom_skip if bottom_skip else len(selected)]
    if len(icon_window) < usable_icons:
        warnings.append(
            f"图标可用窗口 {len(icon_window)} 少于 usable_icon_cards={usable_icons}，已回退为从候选中顺序选择。"
        )
        icon_window = selected
    icon_selected = tuple(icon_window[:max(0, min(usable_icons, len(icon_window)))])
    return CandidateSelection(selected, quantity_selected, icon_selected, tuple(warnings))


def _field_int(value: Any, default: int) -> int:
    """从标注字段中读取整数，unknown/缺失时用默认值。"""
    if value in (None, "", "unknown"):
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _icon_skip_from_note(note: str) -> Tuple[int, int]:
    """从备注里判断顶部/底部遮挡图标应跳过多少张；默认每行两列，所以跳过 2。"""
    return _skip_count_for_position(note, "顶部"), _skip_count_for_position(note, "底部")


def _skip_count_for_position(note: str, position: str) -> int:
    """读取“顶部/底部两个装备被遮挡”这类标注。"""
    if position not in note:
        return 0
    start = note.find(position)
    end_candidates = [index for index in (note.find(",", start), note.find("，", start), note.find(";", start), note.find("；", start)) if index >= 0]
    end = min(end_candidates) if end_candidates else len(note)
    segment = note[start:end]
    if not any(token in segment for token in ("遮挡", "被挡", "不可见", "无法", "挡住")):
        return 0
    match = re.search(rf"{position}.*?(\d+)个", segment)
    return int(match.group(1)) if match else 2


def build_bucket_matcher(
    rarity: str,
    catalog: Mapping[str, Mapping[str, Any]],
    config: Mapping[str, Any],
    project_root: Path,
) -> Tuple[Optional[EquipmentIconMatcher], Tuple[str, ...]]:
    """
    构建只包含当前稀有度装备的图标匹配器，提升速度并减少跨稀有度误认。
    输入：
        rarity/catalog/config/project_root。
    输出：
        matcher/warnings。
    使用示例：
        matcher, warnings = build_bucket_matcher("super_rare", catalog, config, PROJECT_ROOT)
    """
    rarity_id = RARITY_TO_ID.get(rarity, 0)
    if rarity_id <= 0:
        return None, (f"未知稀有度 {rarity}，无法构建分桶图库。",)

    try:
        import cv2
        import numpy as np
    except Exception as exc:  # pragma: no cover - 无 OpenCV 环境由测试覆盖高层行为。
        return None, (f"OpenCV/NumPy 不可用，无法加载分桶图库: {exc}",)

    reference_images: Dict[str, Any] = {}
    reference_paths: Dict[str, str] = {}
    warnings: List[str] = []
    for equipment_id, item in catalog.items():
        if int(item.get("rarity_id", 0) or 0) != rarity_id:
            continue
        image_path_text = str(item.get("image_path", "") or "").strip()
        if not image_path_text:
            continue
        image_path = Path(image_path_text)
        resolved = image_path if image_path.is_absolute() else project_root / image_path
        data = np.fromfile(str(resolved), dtype=np.uint8) if resolved.exists() else None
        image = cv2.imdecode(data, cv2.IMREAD_COLOR) if data is not None else None
        if image is None or getattr(image, "size", 0) == 0:
            warnings.append(f"{equipment_id}: 装备图片无法读取: {resolved}")
            continue
        reference_images[equipment_id] = image
        reference_paths[equipment_id] = str(resolved)

    if not reference_images:
        warnings.append(f"{rarity} 分桶图库为空，图标匹配会跳过。")
        return None, tuple(warnings)

    matcher_config = dict(config.get("equipment_icon_matching", {}))
    return EquipmentIconMatcher(config=matcher_config, reference_images=reference_images, reference_paths=reference_paths), tuple(warnings)


def _relative_child_roi(parent: RoiRegion, child: RoiRegion) -> RoiRegion:
    """把绝对 ROI 转为相对父卡片 ROI。"""
    parent_x, parent_y, _parent_width, _parent_height = parent
    child_x, child_y, child_width, child_height = child
    return child_x - parent_x, child_y - parent_y, child_width, child_height


def _empty_fragment_result(status: str, message: str) -> Dict[str, Any]:
    """构造跳过 OCR 时的统一空结果。"""
    return FragmentQuantityReadResult(False, status, message).to_dict()


def _empty_icon_result(status: str, message: str) -> Dict[str, Any]:
    """构造跳过图标匹配时的统一空结果。"""
    return EquipmentIconMatchResult(True, status, message).to_dict()


def _icon_match_roi_for_candidate(candidate: DesignFragmentCardCandidate) -> Tuple[RoiRegion, float]:
    """底部半截卡片只使用可见图标区域，并让图库按同等可见比例裁剪。"""
    x, y, width, height = candidate.icon_roi
    if "partial_bottom" not in candidate.visibility:
        return candidate.icon_roi, 1.0
    bottom_limit = DesignFragmentDetector.BASE_BOTTOM_OVERLAY_Y
    visible_height = min(height, max(1, bottom_limit - y))
    ratio = max(0.20, min(1.0, visible_height / float(max(1, height))))
    return (x, y, width, max(1, visible_height)), ratio


def draw_bucket_annotations(
    detector: DesignFragmentDetector,
    image: Any,
    detection: DesignFragmentDetectionResult,
    selection: CandidateSelection,
    card_rows: Sequence[Mapping[str, Any]],
    annotation: Optional[RarityBucketAnnotation],
) -> Any:
    """
    绘制分桶预标注图。
    输入：
        detector/image/detection/selection/card_rows/annotation。
    输出：
        OpenCV BGR 图片。
    使用示例：
        annotated = draw_bucket_annotations(detector, image, detection, selection, rows, ann)
    """
    cv2_module = detector._require_cv2()  # noqa: SLF001 - lab 绘图复用检测器依赖。
    annotated = image.copy()
    selected_indices = {item.index for item in selection.selected}
    quantity_indices = {item.index for item in selection.quantity_selected}
    icon_indices = {item.index for item in selection.icon_selected}
    row_by_index = {int(row.get("detected_index", -1)): row for row in card_rows}

    for candidate in detection.candidates:
        is_selected = candidate.index in selected_indices
        quantity_selected = candidate.index in quantity_indices
        icon_selected = candidate.index in icon_indices
        if not is_selected:
            color = (120, 120, 120)
        elif quantity_selected and icon_selected:
            color = (60, 220, 60)
        elif quantity_selected:
            color = (0, 210, 255)
        else:
            color = (255, 160, 0)

        x, y, width, height = candidate.bbox
        cv2_module.rectangle(annotated, (x, y), (x + width, y + height), color, 2 if is_selected else 1)
        ix, iy, iw, ih = candidate.icon_roi
        qx, qy, qw, qh = candidate.quantity_roi
        cv2_module.rectangle(annotated, (ix, iy), (ix + iw, iy + ih), (255, 180, 0), 2 if icon_selected else 1)
        cv2_module.rectangle(annotated, (qx, qy), (qx + qw, qy + qh), (255, 255, 0), 2 if quantity_selected else 1)

        row = row_by_index.get(candidate.index, {})
        display_equipment_id = row.get("accepted_equipment_id") or row.get("icon_equipment_id", "")
        label = (
            f"card{row.get('card_no', candidate.index)} "
            f"{display_equipment_id} "
            f"{row.get('ocr_fragment_count', '')}/{row.get('ocr_required_count', '')}"
        )
        if not is_selected:
            label = f"skip#{candidate.index}:{candidate.visibility}"
        cv2_module.putText(
            annotated,
            str(label)[:56],
            (x + 4, max(18, y + 18)),
            cv2_module.FONT_HERSHEY_SIMPLEX,
            0.43,
            color,
            1,
            cv2_module.LINE_AA,
        )

    rarity = str(annotation.fields.get("filter_rarity", "unknown")) if annotation else "unknown"
    overview = str(annotation.fields.get("overview", "unknown")) if annotation else "unknown"
    summary = f"rarity={rarity} overview={overview} selected={len(selection.selected)} q={len(selection.quantity_selected)} icon={len(selection.icon_selected)}"
    cv2_module.putText(
        annotated,
        summary,
        (20, 90),
        cv2_module.FONT_HERSHEY_SIMPLEX,
        0.65,
        (0, 255, 255),
        2,
        cv2_module.LINE_AA,
    )
    return annotated


# ============================================================
# 🎨 第五部分：批处理与输出
# ============================================================

def process_one(
    image_path: Path,
    output_dir: Path,
    detector: DesignFragmentDetector,
    annotation: Optional[RarityBucketAnnotation],
    reader: Optional[EquipmentCardDigitReader],
    matcher: Optional[EquipmentIconMatcher],
    catalog: Mapping[str, Mapping[str, Any]],
    top_n: int,
) -> Dict[str, Any]:
    """
    处理单张稀有度分桶截图。
    输入：
        image_path/output_dir/detector/annotation/reader/matcher/catalog/top_n。
    输出：
        单张图片结构化结果。
    使用示例：
        payload = process_one(Path("design_rare_1.png"), out, detector, ann, reader, matcher, catalog, 5)
    """
    image_mode = str(annotation.fields.get("image_mode", "viewport_full")) if annotation else "viewport_full"
    detection = detector.detect(image_path, image_mode=image_mode)
    payload: Dict[str, Any] = {
        "filename": image_path.name,
        "screenshot_path": str(image_path),
        "annotation": annotation.to_dict() if annotation else None,
        "detection": detection.to_dict(),
        "selection": {"selected_indices": [], "quantity_indices": [], "icon_indices": [], "warnings": []},
        "annotated_output": "",
        "cards": [],
        "warnings": [],
    }
    if not detection.success:
        return payload

    image = detector.load_image(image_path)
    selection = select_candidates_for_annotation(detection.candidates, annotation)
    payload["selection"] = selection.to_dict()
    payload["warnings"].extend(selection.warnings)

    quantity_indices = {item.index for item in selection.quantity_selected}
    icon_indices = {item.index for item in selection.icon_selected}
    card_rows: List[Dict[str, Any]] = []
    for card_no, candidate in enumerate(selection.selected, start=1):
        row = build_card_row(
            image,
            image_path.name,
            card_no,
            candidate,
            candidate.index in quantity_indices,
            candidate.index in icon_indices,
            reader,
            matcher,
            catalog,
            top_n,
            annotation,
        )
        card_rows.append(row)

    selected_indices = {item.index for item in selection.selected}
    for candidate in detection.candidates:
        if candidate.index not in selected_indices:
            card_rows.append(build_skipped_card_row(image_path.name, candidate))

    payload["cards"] = card_rows
    annotated = draw_bucket_annotations(detector, image, detection, selection, card_rows, annotation)
    output_path = output_dir / f"{image_path.stem}_rarity_bucket.png"
    detector.write_image(output_path, annotated)
    payload["annotated_output"] = str(output_path)
    return payload


def build_card_row(
    image: Any,
    filename: str,
    card_no: int,
    candidate: DesignFragmentCardCandidate,
    quantity_selected: bool,
    icon_selected: bool,
    reader: Optional[EquipmentCardDigitReader],
    matcher: Optional[EquipmentIconMatcher],
    catalog: Mapping[str, Mapping[str, Any]],
    top_n: int,
    annotation: Optional[RarityBucketAnnotation] = None,
) -> Dict[str, Any]:
    """构造单张卡片的预标注行。"""
    if reader is not None and quantity_selected:
        fragment_result = reader.read_fragment_counts(
            image,
            card_roi=candidate.bbox,
            quantity_roi=_relative_child_roi(candidate.bbox, candidate.quantity_roi),
        ).to_dict()
    elif quantity_selected:
        fragment_result = _empty_fragment_result("skipped", "碎片数量 OCR 按参数跳过。")
    else:
        fragment_result = _empty_fragment_result("not_selected", "该卡片未被标注为数量可读。")

    if matcher is not None and icon_selected:
        icon_match_roi, reference_vertical_ratio = _icon_match_roi_for_candidate(candidate)
        icon_result = matcher.match_icon(
            image,
            icon_roi=icon_match_roi,
            top_n=top_n,
            reference_vertical_ratio=reference_vertical_ratio,
        ).to_dict()
    elif icon_selected:
        icon_match_roi = candidate.icon_roi
        reference_vertical_ratio = 1.0
        icon_result = _empty_icon_result("skipped", "装备图标匹配按参数跳过。")
    else:
        icon_match_roi = candidate.icon_roi
        reference_vertical_ratio = 1.0
        icon_result = _empty_icon_result("not_selected", "该卡片图标区域被遮挡或不可用。")

    icon_id = str(icon_result.get("equipment_id", "unknown") or "unknown")
    catalog_item = catalog.get(icon_id, {})
    top_candidates = icon_result.get("candidates", [])
    accepted = _accepted_fields_for_card(annotation, card_no)
    accepted_equipment_id = str(accepted.get("accepted_equipment_id", "") or "")
    accepted_fragment_owned = accepted.get("accepted_fragment_owned", "")
    accepted_fragment_required = accepted.get("accepted_fragment_required", "")
    needs_review = _needs_review(quantity_selected, icon_selected, fragment_result, icon_result)
    if accepted_equipment_id:
        needs_review = False
    return {
        "filename": filename,
        "card_no": card_no,
        "selected": True,
        "quantity_selected": quantity_selected,
        "icon_selected": icon_selected,
        "detected_index": candidate.index,
        "bbox": list(candidate.bbox),
        "icon_roi": list(candidate.icon_roi),
        "quantity_roi": list(candidate.quantity_roi),
        "visibility": candidate.visibility,
        "ocr_status": fragment_result.get("status", ""),
        "ocr_fragment_count": fragment_result.get("fragment_count"),
        "ocr_required_count": fragment_result.get("required_count"),
        "ocr_confidence": fragment_result.get("confidence", 0.0),
        "ocr_text": fragment_result.get("text", ""),
        "icon_status": icon_result.get("status", ""),
        "icon_equipment_id": icon_id,
        "icon_equipment_name": catalog_item.get("name", ""),
        "icon_confidence": icon_result.get("confidence", 0.0),
        "icon_match_roi": list(icon_match_roi),
        "icon_reference_vertical_ratio": reference_vertical_ratio,
        "icon_top_candidates": " | ".join(
            f"{item.get('equipment_id')}:{catalog.get(str(item.get('equipment_id')), {}).get('name', '')}:{float(item.get('confidence', 0.0)):.3f}"
            for item in top_candidates
        ),
        "accepted_equipment_id": accepted_equipment_id,
        "accepted_fragment_owned": accepted_fragment_owned,
        "accepted_fragment_required": accepted_fragment_required,
        "needs_review": needs_review,
        "fragment_ocr": fragment_result,
        "icon_match_result": icon_result,
    }


def build_skipped_card_row(filename: str, candidate: DesignFragmentCardCandidate) -> Dict[str, Any]:
    """构造检测到但不属于标注候选范围的行。"""
    return {
        "filename": filename,
        "card_no": "",
        "selected": False,
        "quantity_selected": False,
        "icon_selected": False,
        "detected_index": candidate.index,
        "bbox": list(candidate.bbox),
        "icon_roi": list(candidate.icon_roi),
        "quantity_roi": list(candidate.quantity_roi),
        "visibility": candidate.visibility,
        "ocr_status": "skipped",
        "ocr_fragment_count": "",
        "ocr_required_count": "",
        "ocr_confidence": "",
        "ocr_text": "",
        "icon_status": "skipped",
        "icon_equipment_id": "",
        "icon_equipment_name": "",
        "icon_confidence": "",
        "icon_match_roi": "",
        "icon_reference_vertical_ratio": "",
        "icon_top_candidates": "",
        "accepted_equipment_id": "",
        "accepted_fragment_owned": "",
        "accepted_fragment_required": "",
        "needs_review": "",
    }


def _accepted_fields_for_card(
    annotation: Optional[RarityBucketAnnotation],
    card_no: int,
) -> Dict[str, Any]:
    """
    从 exp.txt 中读取某张卡片的人工确认字段。

    支持三种等价前缀，方便人工标注时少踩格式坑：
    - card_4.accepted_equipment_id
    - card_04.accepted_equipment_id
    - card04.accepted_equipment_id
    """
    if annotation is None:
        return {}
    fields = annotation.fields
    prefixes = (f"card_{card_no}", f"card_{card_no:02d}", f"card{card_no:02d}")
    for prefix in prefixes:
        accepted: Dict[str, Any] = {}
        equipment_id = fields.get(f"{prefix}.accepted_equipment_id")
        fragment_owned = fields.get(f"{prefix}.accepted_fragment_owned")
        fragment_required = fields.get(f"{prefix}.accepted_fragment_required")
        if equipment_id not in (None, ""):
            accepted["accepted_equipment_id"] = str(equipment_id).strip()
        if fragment_owned not in (None, ""):
            accepted["accepted_fragment_owned"] = _field_int(fragment_owned, fragment_owned)
        if fragment_required not in (None, ""):
            accepted["accepted_fragment_required"] = _field_int(fragment_required, fragment_required)
        if accepted:
            return accepted
    return {}


def _needs_review(
    quantity_selected: bool,
    icon_selected: bool,
    fragment_result: Mapping[str, Any],
    icon_result: Mapping[str, Any],
) -> bool:
    """判断预标注行是否需要人工复核。"""
    if quantity_selected and fragment_result.get("status") != "success":
        return True
    if icon_selected and icon_result.get("status") != "success":
        return True
    return False


def write_results(output_dir: Path, results: Sequence[Mapping[str, Any]]) -> None:
    """
    写出 JSON、CSV 和 summary。
    输入：
        output_dir/results。
    输出：
        rarity_bucket_results.json/csv 和 rarity_bucket_summary.json。
    使用示例：
        write_results(Path("rarity_bucket_img_out"), results)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "rarity_bucket_results.json").write_text(
        json.dumps(list(results), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "rarity_bucket_summary.json").write_text(
        json.dumps(summarize_results(results), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    fieldnames = [
        "filename",
        "filter_rarity",
        "filter_rarity_id",
        "overview",
        "scroll_position",
        "page_index",
        "card_no",
        "selected",
        "quantity_selected",
        "icon_selected",
        "detected_index",
        "bbox",
        "visibility",
        "ocr_status",
        "ocr_fragment_count",
        "ocr_required_count",
        "ocr_confidence",
        "ocr_text",
        "icon_status",
        "icon_equipment_id",
        "icon_equipment_name",
        "icon_confidence",
        "icon_top_candidates",
        "needs_review",
        "accepted_equipment_id",
        "accepted_fragment_owned",
        "accepted_fragment_required",
    ]
    with (output_dir / "rarity_bucket_results.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            fields = (result.get("annotation") or {}).get("fields", {})
            for row in result.get("cards", []):
                writer.writerow({
                    "filename": result.get("filename", ""),
                    "filter_rarity": fields.get("filter_rarity", ""),
                    "filter_rarity_id": fields.get("filter_rarity_id", ""),
                    "overview": fields.get("overview", ""),
                    "scroll_position": fields.get("scroll_position", ""),
                    "page_index": fields.get("page_index", ""),
                    **{key: row.get(key, "") for key in fieldnames if key not in {"filename", "filter_rarity", "filter_rarity_id", "overview", "scroll_position", "page_index"}},
                })


def summarize_results(results: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """
    汇总当前样本表现；不宣称通用准确率。
    输入：
        results。
    输出：
        摘要字典。
    使用示例：
        summary = summarize_results(results)
    """
    cards = [row for result in results for row in result.get("cards", []) if row.get("selected")]
    quantity_cards = [row for row in cards if row.get("quantity_selected")]
    icon_cards = [row for row in cards if row.get("icon_selected")]
    return {
        "images": len(results),
        "selected_cards": len(cards),
        "quantity_selected_cards": len(quantity_cards),
        "icon_selected_cards": len(icon_cards),
        "ocr_success_cards": sum(1 for row in quantity_cards if row.get("ocr_status") == "success"),
        "icon_success_cards": sum(1 for row in icon_cards if row.get("icon_status") == "success"),
        "needs_review_cards": sum(1 for row in cards if row.get("needs_review") is True),
        "note": "该摘要仅表示当前稀有度分桶样本的预标注结果；正式准确率仍需人工复核 accepted_* 字段后统计。",
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
        python ocr_training_lab/fragment_filter_scan/run_rarity_bucket_detection.py
    """
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    source_dir = args.test_dir if args.use_test else args.input_dir
    output_dir = resolve_output_dir(script_dir, args.use_test, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    exp_path = args.exp_file if args.exp_file is not None else source_dir / "rarity_bucket_exp.txt"
    annotations = parse_rarity_bucket_exp(exp_path)
    config = load_recognition_config(PROJECT_ROOT / "config" / "recognition" / "roi_config.json")
    catalog = load_equipment_catalog(PROJECT_ROOT)
    detector = DesignFragmentDetector()
    status = detector.check_status()
    if not status["available"]:
        print("OpenCV/NumPy 不可用，无法生成稀有度分桶预标注结果。")
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 2

    reader: Optional[EquipmentCardDigitReader] = None
    if not args.skip_ocr:
        print("提示：正在初始化本地 PaddleOCR；Creating model/ccache 查找信息不是脚本失败，最终以 status 和 summary 为准。", flush=True)
        reader = EquipmentCardDigitReader(OcrEngine(config=config.get("ocr", {})), config.get("card_digits", {}))

    image_paths = sorted(path for path in source_dir.glob(args.pattern) if path.is_file())
    if not image_paths:
        write_results(output_dir, [])
        print(f"没有找到可处理图片: {source_dir / args.pattern}")
        return 1

    matcher_cache: Dict[str, Tuple[Optional[EquipmentIconMatcher], Tuple[str, ...]]] = {}
    results: List[Dict[str, Any]] = []
    for image_path in image_paths:
        annotation = annotations.get(image_path.name)
        rarity = str(annotation.fields.get("filter_rarity", "unknown")) if annotation else "unknown"
        matcher: Optional[EquipmentIconMatcher] = None
        matcher_warnings: Tuple[str, ...] = ()
        if not args.skip_icons:
            if rarity not in matcher_cache:
                matcher_cache[rarity] = build_bucket_matcher(rarity, catalog, config, PROJECT_ROOT)
            matcher, matcher_warnings = matcher_cache[rarity]

        result = process_one(
            image_path,
            output_dir,
            detector,
            annotation,
            reader,
            matcher,
            catalog,
            max(1, int(args.top_n)),
        )
        result["warnings"].extend(matcher_warnings)
        results.append(result)
        selection = result.get("selection", {})
        print(
            f"{image_path.name}: rarity={rarity}, status={result['detection']['status']}, "
            f"raw={len(result['detection'].get('candidates', []))}, "
            f"selected={len(selection.get('selected_indices', []))}, "
            f"q={len(selection.get('quantity_indices', []))}, icon={len(selection.get('icon_indices', []))}"
        )

    write_results(output_dir, results)
    print(f"已输出 {len(results)} 张稀有度分桶预标注结果到: {output_dir}")
    print(json.dumps(summarize_results(results), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
