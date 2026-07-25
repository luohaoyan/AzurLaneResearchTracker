#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      🧪 设计图碎片识别校准脚本 (run_design_fragment_detection)║
║                                                              ║
║  【一句话解释】批量读取设计图页截图，输出卡片框、碎片数量和ID。║
║  【类比理解】它像一张透明描图纸，把每张设计图卡片的关键区域描出。║
║  【数据流说明】img_input→img_out，test_img→test_out。          ║
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# 训练脚本位于 ocr_training_lab/equipment_cards/ 下，运行时主动把项目根目录放入 import 路径。
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


# ============================================================
# 🧱 第二部分：数据对象与常量
# ============================================================

RoiRegion = Tuple[int, int, int, int]

TRUE_VALUES = {"true", "ture", "yes", "y", "1", "是", "可", "可以"}
FALSE_VALUES = {"false", "no", "n", "0", "否", "不可", "不可以"}
BOOL_KEYS = {
    "craftable",
    "quantity_readable",
    "icon_usable",
    "complete",
}
INT_KEYS = {
    "candidate_cards",
    "usable_quantity_cards",
    "usable_icon_cards",
    "fragment_owned",
    "fragment_required",
}


@dataclass(frozen=True)
class DesignFragmentAnnotation:
    """单张设计图截图的人工标注。"""

    filename: str
    fields: Mapping[str, Any]
    cards: Tuple[Mapping[str, Any], ...]

    def to_dict(self) -> Dict[str, Any]:
        """转换成 JSON 友好的字典。"""
        return {
            "filename": self.filename,
            "fields": dict(self.fields),
            "cards": [dict(card) for card in self.cards],
        }


@dataclass(frozen=True)
class CandidateAlignment:
    """检测卡片与人工 cardXX 标注之间的对齐结果。"""

    method: str
    selected: Tuple[DesignFragmentCardCandidate, ...]
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """转换成 JSON 友好的字典。"""
        return {
            "method": self.method,
            "selected_indices": [candidate.index for candidate in self.selected],
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
        python run_design_fragment_detection.py --use-test
    """
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="批量识别仓库设计图页碎片卡片。")
    parser.add_argument("--input-dir", type=Path, default=script_dir / "img_input", help="训练/校准截图目录。")
    parser.add_argument("--test-dir", type=Path, default=script_dir / "test_img", help="稳定性测试截图目录。")
    parser.add_argument("--output-dir", type=Path, default=None, help="输出目录。默认 img_input→img_out，test_img→test_out。")
    parser.add_argument("--exp-file", type=Path, default=None, help="标注文件。默认从输入目录读取 design_exp.txt。")
    parser.add_argument("--use-test", "--test", action="store_true", help="处理 test_img，并输出到 test_out。")
    parser.add_argument("--skip-ocr", action="store_true", help="只做卡片定位和图标匹配，不跑 PaddleOCR。")
    parser.add_argument("--skip-icons", action="store_true", help="只做卡片定位和碎片数量 OCR，不跑装备图库匹配。")
    parser.add_argument("--top-n", type=int, default=5, help="装备图标匹配保留 Top-N 候选。")
    parser.add_argument("--pattern", default="*.png", help="输入图片匹配模式，默认 *.png。")
    return parser.parse_args()


def resolve_output_dir(script_dir: Path, use_test: bool, output_dir: Optional[Path]) -> Path:
    """
    根据输入来源选择输出目录，避免训练结果和泛化测试结果混在一起。

    输入：
        script_dir/use_test/output_dir。
    输出：
        实际输出目录。
    使用示例：
        resolve_output_dir(Path("equipment_cards"), False, None)
    """
    if output_dir is not None:
        return output_dir
    return script_dir / ("test_out" if use_test else "img_out")


def load_recognition_config(config_path: Path) -> Dict[str, Any]:
    """
    读取识别配置；缺失时返回空配置，让各组件按安全默认值运行。

    输入：
        config_path。
    输出：
        配置字典。
    使用示例：
        config = load_recognition_config(Path("config/recognition/roi_config.json"))
    """
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


def load_equipment_names(library_path: Path) -> Dict[str, str]:
    """
    只读加载 equipment_library.csv 的 equipment_id → name 映射。

    输入：
        library_path。
    输出：
        装备名称映射。
    使用示例：
        names = load_equipment_names(Path("data/equipment_library.csv"))
    """
    if not library_path.exists():
        return {}
    names: Dict[str, str] = {}
    with library_path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            equipment_id = str(row.get("equipment_id", "")).strip()
            name = str(row.get("name", "")).strip()
            if equipment_id:
                names[equipment_id] = name
    return names


def resolve_equipment_id_by_name(equipment_name: str, equipment_names: Mapping[str, str]) -> str:
    """
    根据人工标注名称反查 equipment_id，用于发现“ID 与名称不一致”的标注。

    输入：
        equipment_name/equipment_names。
    输出：
        唯一匹配的 equipment_id；无法唯一匹配时返回空字符串。
    使用示例：
        resolved = resolve_equipment_id_by_name("试作舰载型La-9#T0", names)
    """
    normalized_target = normalize_equipment_name(equipment_name)
    if not normalized_target:
        return ""
    matches = [
        equipment_id
        for equipment_id, name in equipment_names.items()
        if normalize_equipment_name(name) == normalized_target
    ]
    return matches[0] if len(matches) == 1 else ""


def normalize_equipment_name(value: str) -> str:
    """
    规范化装备名称，主要去掉空白，保留 #T0/#T3 这类等级信息。

    输入：
        原始名称。
    输出：
        规范化名称。
    使用示例：
        normalize_equipment_name("  SG雷达#T3 ")
    """
    return re.sub(r"\s+", "", str(value or "")).strip()


def parse_design_exp(exp_path: Path) -> Dict[str, DesignFragmentAnnotation]:
    """
    解析 design_exp.txt，并兼容少量人工标注笔误。

    输入：
        exp_path。
    输出：
        filename → DesignFragmentAnnotation。
    使用示例：
        annotations = parse_design_exp(Path("img_input/design_exp.txt"))
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
            annotations[current_name] = {"fields": {}, "cards": {}}
            continue
        if not current_name or ":" not in line:
            continue

        raw_key, raw_value = line.split(":", 1)
        key = _normalize_key(raw_key.strip())
        value = _normalize_value(key, raw_value.strip())

        card_match = re.match(r"^card(\d+)\.(.+)$", key)
        if card_match:
            card_no = int(card_match.group(1))
            card_key = _normalize_key(card_match.group(2))
            card_value = _normalize_value(card_key, raw_value.strip())
            card_bucket = annotations[current_name]["cards"].setdefault(card_no, {"card_no": card_no})
            card_bucket[card_key] = card_value
            continue

        annotations[current_name]["fields"][key] = value

    parsed: Dict[str, DesignFragmentAnnotation] = {}
    for filename, payload in annotations.items():
        ordered_cards = tuple(payload["cards"][index] for index in sorted(payload["cards"]))
        parsed[filename] = DesignFragmentAnnotation(filename, payload["fields"], ordered_cards)
    return parsed


def _normalize_key(key: str) -> str:
    """统一人工标注字段名，兼容 source_corp/buildable 等笔误或旧名。"""
    normalized = key.strip()
    aliases = {
        "source_corp": "source_crop",
        "buildable": "craftable",
    }
    return aliases.get(normalized, normalized)


def _normalize_value(key: str, value: str) -> Any:
    """把字符串值转换成 bool/int/规范枚举，便于后续自动比对。"""
    text = value.strip()
    lowered = text.lower()
    if key in BOOL_KEYS:
        if lowered in TRUE_VALUES:
            return True
        if lowered in FALSE_VALUES:
            return False
        return "unknown"
    if key in INT_KEYS:
        match = re.search(r"-?\d+", text.replace(",", ""))
        return int(match.group(0)) if match else None
    if key == "visibility" and lowered == "cut":
        return "partial"
    return text


# ============================================================
# 🧮 第四部分：候选框对齐与识别辅助
# ============================================================

def align_candidates_to_annotation(
    candidates: Sequence[DesignFragmentCardCandidate],
    annotation: Optional[DesignFragmentAnnotation],
) -> CandidateAlignment:
    """
    把检测到的候选卡片对齐到人工 cardXX 标注。

    输入：
        candidates/annotation。
    输出：
        CandidateAlignment。
    使用示例：
        alignment = align_candidates_to_annotation(result.candidates, annotation)
    """
    ordered = tuple(sorted(candidates, key=lambda item: (item.bbox[1], item.bbox[0], item.index)))
    if not annotation or not annotation.cards:
        return CandidateAlignment("all_detected_no_annotation", ordered)

    label_count = len(annotation.cards)
    expected_total = _as_int(annotation.fields.get("candidate_cards"))
    top_skip, bottom_skip = _skip_hint_from_note(str(annotation.fields.get("note", "")))
    warnings: List[str] = []
    working = list(ordered)

    if expected_total and len(working) > expected_total:
        warnings.append(f"检测候选 {len(working)} 多于标注 candidate_cards={expected_total}，已优先保留前 {expected_total} 个。")
        working = working[:expected_total]

    if expected_total and len(working) == expected_total and (top_skip or bottom_skip):
        start = min(top_skip, len(working))
        end = max(start, len(working) - bottom_skip)
        hinted = tuple(working[start:end])
        if len(hinted) >= label_count:
            return CandidateAlignment("annotation_note_skip_hint", hinted[:label_count], tuple(warnings))

    if len(working) <= label_count:
        if len(working) < label_count:
            warnings.append(f"检测候选 {len(working)} 少于人工 card 标注 {label_count}，只能对齐已有候选。")
        return CandidateAlignment("detected_count_lte_labels", tuple(working[:label_count]), tuple(warnings))

    selected, score = _best_candidate_window(working, annotation.cards)
    warnings.append(f"使用滑动窗口自动对齐，窗口评分 {score:.2f}。")
    return CandidateAlignment("best_visibility_window", selected, tuple(warnings))


def _best_candidate_window(
    candidates: Sequence[DesignFragmentCardCandidate],
    labels: Sequence[Mapping[str, Any]],
) -> Tuple[Tuple[DesignFragmentCardCandidate, ...], float]:
    """在候选序列中寻找最像人工 cardXX 标注的一段连续窗口。"""
    label_count = len(labels)
    best_window: Tuple[DesignFragmentCardCandidate, ...] = tuple(candidates[:label_count])
    best_score = -1_000_000.0
    for start in range(0, len(candidates) - label_count + 1):
        window = tuple(candidates[start:start + label_count])
        score = 0.0
        for candidate, label in zip(window, labels):
            label_visibility = str(label.get("visibility", "")).lower()
            candidate_visibility = candidate.visibility.lower()
            if label_visibility in {"full", ""}:
                score += 1.0 if candidate_visibility == "full" else -2.0
            elif label_visibility in {"partial", "partial_top", "partial_bottom", "cut"}:
                score += 1.2 if candidate_visibility != "full" else 0.2
            if "partial_top" in candidate_visibility and label_visibility == "full":
                score -= 3.0
            if "partial_bottom" in candidate_visibility and label_visibility == "full":
                score -= 3.0
        if score > best_score:
            best_score = score
            best_window = window
    return best_window, best_score


def _skip_hint_from_note(note: str) -> Tuple[int, int]:
    """从中文备注里提取顶部/底部不可用卡片数量提示。"""
    top_skip = _skip_count_for_position(note, "顶部")
    bottom_skip = _skip_count_for_position(note, "底部")
    return top_skip, bottom_skip


def _skip_count_for_position(note: str, position: str) -> int:
    """判断备注中某个位置的卡片是否明确不可用。"""
    if position not in note:
        return 0
    start = note.find(position)
    end_candidates = [index for index in (note.find(";", start), note.find("；", start)) if index >= 0]
    end = min(end_candidates) if end_candidates else len(note)
    segment = note[start:end]
    if "可以使用" in segment or "可见, 可以" in segment or "可见，可以" in segment:
        return 0
    if not any(token in segment for token in ("不可使用", "无法使用", "数量不可见", "不可见")):
        return 0
    match = re.search(rf"{position}有(\d+)个", segment)
    return int(match.group(1)) if match else 2


def _relative_child_roi(parent: RoiRegion, child: RoiRegion) -> RoiRegion:
    """把绝对 ROI 转成相对父卡片 ROI，供 EquipmentCardDigitReader 使用。"""
    parent_x, parent_y, _parent_width, _parent_height = parent
    child_x, child_y, child_width, child_height = child
    return child_x - parent_x, child_y - parent_y, child_width, child_height


def _as_int(value: Any) -> int:
    """安全转换整数，失败时返回 0。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _empty_fragment_result(status: str, message: str) -> Dict[str, Any]:
    """构造跳过 OCR 时的统一空结果。"""
    return FragmentQuantityReadResult(False, status, message).to_dict()


def _empty_icon_result(status: str, message: str) -> Dict[str, Any]:
    """构造跳过图标匹配时的统一空结果。"""
    return EquipmentIconMatchResult(True, status, message).to_dict()


# ============================================================
# 🎨 第五部分：绘图与输出
# ============================================================

def draw_lab_annotations(
    detector: DesignFragmentDetector,
    image: Any,
    detection: DesignFragmentDetectionResult,
    selected: Sequence[DesignFragmentCardCandidate],
    card_rows: Sequence[Mapping[str, Any]],
) -> Any:
    """
    绘制训练标注图：灰色=检测但未对齐，绿色/橙色=用于训练的卡片。

    输入：
        detector/image/detection/selected/card_rows。
    输出：
        OpenCV BGR 图片。
    使用示例：
        annotated = draw_lab_annotations(detector, image, result, selected, rows)
    """
    cv2_module = detector._require_cv2()  # noqa: SLF001 - lab 绘图复用检测器依赖。
    annotated = image.copy()
    selected_by_index = {candidate.index: index for index, candidate in enumerate(selected)}

    for candidate in detection.candidates:
        x, y, width, height = candidate.bbox
        selected_index = selected_by_index.get(candidate.index)
        is_selected = selected_index is not None
        color = (60, 210, 60) if is_selected and candidate.visibility == "full" else (0, 180, 255) if is_selected else (120, 120, 120)
        thickness = 2 if is_selected else 1
        cv2_module.rectangle(annotated, (x, y), (x + width, y + height), color, thickness)

        ix, iy, iw, ih = candidate.icon_roi
        qx, qy, qw, qh = candidate.quantity_roi
        cv2_module.rectangle(annotated, (ix, iy), (ix + iw, iy + ih), (255, 180, 0), 1)
        cv2_module.rectangle(annotated, (qx, qy), (qx + qw, qy + qh), (255, 255, 0), 2 if is_selected else 1)

        if is_selected:
            row = card_rows[selected_index]
            label = (
                f"card{int(row.get('card_no', selected_index + 1)):02d} "
                f"{row.get('expected_equipment_id', row.get('equipment_id', 'unknown'))} "
                f"{row.get('expected_fragment_owned', row.get('fragment_owned', '?'))}/"
                f"{row.get('expected_fragment_required', row.get('fragment_required', '?'))}"
            )
        else:
            label = f"skip#{candidate.index}:{candidate.visibility}"

        cv2_module.putText(
            annotated,
            str(label)[:54],
            (x + 4, max(18, y + 18)),
            cv2_module.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2_module.LINE_AA,
        )

    cv2_module.putText(
        annotated,
        f"design fragments selected={len(selected)} detected={len(detection.candidates)} offset={detection.row_offset}",
        (20, 90),
        cv2_module.FONT_HERSHEY_SIMPLEX,
        0.65,
        (0, 255, 255),
        2,
        cv2_module.LINE_AA,
    )
    return annotated


def write_results(output_dir: Path, results: Sequence[Mapping[str, Any]]) -> None:
    """
    写出 JSON 和 CSV 识别结果，供人工验收和后续整合读取。

    输入：
        output_dir/results。
    输出：
        design_fragment_results.json/csv。
    使用示例：
        write_results(Path("img_out"), results)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "design_fragment_results.json"
    csv_path = output_dir / "design_fragment_results.csv"
    json_path.write_text(json.dumps(list(results), ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "filename",
        "card_no",
        "selected",
        "detected_index",
        "bbox",
        "icon_roi",
        "quantity_roi",
        "visibility",
        "expected_equipment_id",
        "expected_name",
        "expected_fragment_owned",
        "expected_fragment_required",
        "expected_craftable",
        "expected_library_name",
        "name_resolved_equipment_id",
        "comparison_equipment_id",
        "annotation_warning",
        "ocr_status",
        "ocr_fragment_count",
        "ocr_required_count",
        "ocr_confidence",
        "ocr_text",
        "fragment_match",
        "icon_status",
        "icon_equipment_id",
        "icon_confidence",
        "icon_match_roi",
        "icon_reference_vertical_ratio",
        "icon_match",
        "icon_top_candidates",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            for row in result.get("cards", []):
                writer.writerow({key: row.get(key, "") for key in fieldnames})


def summarize_results(results: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """
    生成样本级摘要；只报告当前样本对照结果，不宣称通用准确率。

    输入：
        results。
    输出：
        摘要字典。
    使用示例：
        summary = summarize_results(results)
    """
    rows = [row for result in results for row in result.get("cards", []) if row.get("selected")]
    ocr_available = [row for row in rows if row.get("ocr_status") not in {"skipped", "unavailable", ""}]
    icon_available = [row for row in rows if row.get("icon_status") not in {"skipped", "no_gallery", "unavailable", ""}]
    return {
        "images": len(results),
        "selected_cards": len(rows),
        "ocr_checked_cards": len(ocr_available),
        "ocr_fragment_matched_cards": sum(1 for row in ocr_available if row.get("fragment_match") is True),
        "icon_checked_cards": len(icon_available),
        "icon_matched_cards": sum(1 for row in icon_available if row.get("icon_match") is True),
        "note": "该摘要仅表示当前标注样本的对照结果；真实准确率仍需更多测试截图校准。",
    }


# ============================================================
# 🚀 第六部分：批处理主流程
# ============================================================

def process_one(
    image_path: Path,
    output_dir: Path,
    detector: DesignFragmentDetector,
    annotation: Optional[DesignFragmentAnnotation],
    reader: Optional[EquipmentCardDigitReader],
    matcher: Optional[EquipmentIconMatcher],
    equipment_names: Mapping[str, str],
    top_n: int,
) -> Dict[str, Any]:
    """
    处理单张设计图截图，并输出带框图片。

    输入：
        image_path/output_dir/detector/annotation/reader/matcher/equipment_names/top_n。
    输出：
        单张图片的结构化结果。
    使用示例：
        payload = process_one(Path("design_1.png"), out, detector, ann, reader, matcher, names, 5)
    """
    image_mode = str(annotation.fields.get("image_mode", "viewport_full")) if annotation else "viewport_full"
    detection = detector.detect(image_path, image_mode=image_mode)
    payload: Dict[str, Any] = {
        "filename": image_path.name,
        "screenshot_path": str(image_path),
        "detection": detection.to_dict(),
        "annotation": annotation.to_dict() if annotation else None,
        "alignment": {"method": "not_run", "selected_indices": [], "warnings": []},
        "annotated_output": "",
        "cards": [],
    }
    if not detection.success:
        return payload

    image = detector.load_image(image_path)
    alignment = align_candidates_to_annotation(detection.candidates, annotation)
    payload["alignment"] = alignment.to_dict()
    label_cards = annotation.cards if annotation else ()
    card_rows: List[Dict[str, Any]] = []

    for selected_index, candidate in enumerate(alignment.selected):
        expected = dict(label_cards[selected_index]) if selected_index < len(label_cards) else {"card_no": selected_index + 1}
        row = _build_card_row(
            image,
            image_path.name,
            candidate,
            expected,
            reader,
            matcher,
            equipment_names,
            top_n,
        )
        card_rows.append(row)

    selected_indices = {candidate.index for candidate in alignment.selected}
    for candidate in detection.candidates:
        if candidate.index in selected_indices:
            continue
        card_rows.append(_build_skipped_card_row(image_path.name, candidate))

    payload["cards"] = card_rows
    annotated = draw_lab_annotations(detector, image, detection, alignment.selected, card_rows)
    output_path = output_dir / f"{image_path.stem}_design_fragments.png"
    detector.write_image(output_path, annotated)
    payload["annotated_output"] = str(output_path)
    return payload


def _build_card_row(
    image: Any,
    filename: str,
    candidate: DesignFragmentCardCandidate,
    expected: Mapping[str, Any],
    reader: Optional[EquipmentCardDigitReader],
    matcher: Optional[EquipmentIconMatcher],
    equipment_names: Mapping[str, str],
    top_n: int,
) -> Dict[str, Any]:
    """构造单张已对齐卡片的 CSV/JSON 行。"""
    expected_id = str(expected.get("equipment_id", "unknown") or "unknown")
    expected_name = str(expected.get("name") or "")
    expected_library_name = equipment_names.get(expected_id, "")
    name_resolved_id = resolve_equipment_id_by_name(expected_name, equipment_names)
    annotation_warning = _annotation_warning(expected_id, expected_name, expected_library_name, name_resolved_id)
    comparison_id = name_resolved_id or expected_id
    expected_owned = expected.get("fragment_owned")
    expected_required = expected.get("fragment_required")

    if reader is not None and expected.get("quantity_readable", True) is not False:
        fragment_result = reader.read_fragment_counts(
            image,
            card_roi=candidate.bbox,
            quantity_roi=_relative_child_roi(candidate.bbox, candidate.quantity_roi),
        ).to_dict()
    else:
        fragment_result = _empty_fragment_result("skipped", "碎片数量 OCR 已按参数或标注跳过。")

    if matcher is not None and expected.get("icon_usable", True) is not False:
        icon_match_roi, reference_vertical_ratio = _icon_match_roi_for_candidate(candidate)
        icon_result = matcher.match_icon(
            image,
            icon_roi=icon_match_roi,
            top_n=top_n,
            reference_vertical_ratio=reference_vertical_ratio,
        ).to_dict()
    else:
        icon_match_roi = candidate.icon_roi
        reference_vertical_ratio = 1.0
        icon_result = _empty_icon_result("skipped", "装备图标匹配已按参数或标注跳过。")

    ocr_owned = fragment_result.get("fragment_count")
    ocr_required = fragment_result.get("required_count")
    icon_id = str(icon_result.get("equipment_id", "unknown") or "unknown")
    top_candidates = icon_result.get("candidates", [])

    return {
        "filename": filename,
        "card_no": expected.get("card_no", ""),
        "selected": True,
        "detected_index": candidate.index,
        "bbox": list(candidate.bbox),
        "icon_roi": list(candidate.icon_roi),
        "quantity_roi": list(candidate.quantity_roi),
        "visibility": candidate.visibility,
        "expected_equipment_id": expected_id,
        "expected_name": expected_name or expected_library_name,
        "expected_fragment_owned": expected_owned,
        "expected_fragment_required": expected_required,
        "expected_craftable": expected.get("craftable", ""),
        "expected_library_name": expected_library_name,
        "name_resolved_equipment_id": name_resolved_id,
        "comparison_equipment_id": comparison_id,
        "annotation_warning": annotation_warning,
        "ocr_status": fragment_result.get("status", ""),
        "ocr_fragment_count": ocr_owned,
        "ocr_required_count": ocr_required,
        "ocr_confidence": fragment_result.get("confidence", 0.0),
        "ocr_text": fragment_result.get("text", ""),
        "fragment_match": _fragment_match(expected_owned, expected_required, ocr_owned, ocr_required),
        "icon_status": icon_result.get("status", ""),
        "icon_equipment_id": icon_id,
        "icon_confidence": icon_result.get("confidence", 0.0),
        "icon_match_roi": list(icon_match_roi),
        "icon_reference_vertical_ratio": reference_vertical_ratio,
        "icon_match": bool(comparison_id != "unknown" and icon_id == comparison_id),
        "icon_top_candidates": " | ".join(
            f"{item.get('equipment_id')}:{float(item.get('confidence', 0.0)):.3f}"
            for item in top_candidates
        ),
        "fragment_ocr": fragment_result,
        "icon_match_result": icon_result,
    }


def _build_skipped_card_row(filename: str, candidate: DesignFragmentCardCandidate) -> Dict[str, Any]:
    """构造检测到但未与人工标注对齐的卡片行，便于人工复核漏/多检。"""
    return {
        "filename": filename,
        "card_no": "",
        "selected": False,
        "detected_index": candidate.index,
        "bbox": list(candidate.bbox),
        "icon_roi": list(candidate.icon_roi),
        "quantity_roi": list(candidate.quantity_roi),
        "visibility": candidate.visibility,
        "expected_equipment_id": "",
        "expected_name": "",
        "expected_fragment_owned": "",
        "expected_fragment_required": "",
        "expected_craftable": "",
        "expected_library_name": "",
        "name_resolved_equipment_id": "",
        "comparison_equipment_id": "",
        "annotation_warning": "",
        "ocr_status": "skipped",
        "ocr_fragment_count": "",
        "ocr_required_count": "",
        "ocr_confidence": "",
        "ocr_text": "",
        "fragment_match": "",
        "icon_status": "skipped",
        "icon_equipment_id": "",
        "icon_confidence": "",
        "icon_match_roi": "",
        "icon_reference_vertical_ratio": "",
        "icon_match": "",
        "icon_top_candidates": "",
    }


def _fragment_match(expected_owned: Any, expected_required: Any, ocr_owned: Any, ocr_required: Any) -> Any:
    """判断 OCR 碎片数量是否与人工标注一致；缺少一侧时返回空字符串。"""
    if expected_owned in (None, "") or ocr_owned in (None, ""):
        return ""
    if expected_required in (None, "") or ocr_required in (None, ""):
        return int(expected_owned) == int(ocr_owned)
    return int(expected_owned) == int(ocr_owned) and int(expected_required) == int(ocr_required)


def _icon_match_roi_for_candidate(candidate: DesignFragmentCardCandidate) -> Tuple[RoiRegion, float]:
    """底部半截卡片只使用可见图标区域，并返回图库同步裁剪比例。"""
    x, y, width, height = candidate.icon_roi
    if "partial_bottom" not in candidate.visibility:
        return candidate.icon_roi, 1.0
    bottom_limit = DesignFragmentDetector.BASE_BOTTOM_OVERLAY_Y
    visible_height = min(height, max(1, bottom_limit - y))
    ratio = max(0.20, min(1.0, visible_height / float(max(1, height))))
    return (x, y, width, max(1, visible_height)), ratio


def _annotation_warning(expected_id: str, expected_name: str, library_name: str, resolved_id: str) -> str:
    """生成标注 ID/名称与装备库不一致时的友好提示。"""
    if expected_id in {"", "unknown"} or not expected_name:
        return ""
    if not library_name:
        return f"equipment_library.csv 中未找到标注 ID {expected_id}。"
    if normalize_equipment_name(expected_name) == normalize_equipment_name(library_name):
        return ""
    if resolved_id and resolved_id != expected_id:
        return f"标注名称更像 {resolved_id}，但标注 ID 为 {expected_id}。"
    return f"标注名称与装备库中 {expected_id} 的名称不一致。"


def main() -> int:
    """
    脚本入口。

    输入：
        命令行参数。
    输出：
        进程退出码。
    使用示例：
        python ocr_training_lab/equipment_cards/run_design_fragment_detection.py
    """
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    source_dir = args.test_dir if args.use_test else args.input_dir
    output_dir = resolve_output_dir(script_dir, args.use_test, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    exp_path = args.exp_file if args.exp_file is not None else source_dir / "design_exp.txt"
    annotations = parse_design_exp(exp_path)
    recognition_config = load_recognition_config(PROJECT_ROOT / "config" / "recognition" / "roi_config.json")
    equipment_names = load_equipment_names(PROJECT_ROOT / "data" / "equipment_library.csv")

    detector = DesignFragmentDetector()
    detector_status = detector.check_status()
    if not detector_status["available"]:
        print("OpenCV/NumPy 不可用，无法生成设计图碎片标注结果。")
        print(json.dumps(detector_status, ensure_ascii=False, indent=2))
        return 2

    reader: Optional[EquipmentCardDigitReader] = None
    if not args.skip_ocr:
        ocr_engine = OcrEngine(config=recognition_config.get("ocr", {}))
        reader = EquipmentCardDigitReader(ocr_engine, recognition_config.get("card_digits", {}))

    matcher: Optional[EquipmentIconMatcher] = None
    if not args.skip_icons:
        matcher = EquipmentIconMatcher(config=recognition_config.get("equipment_icon_matching", {}))

    image_paths = sorted(path for path in source_dir.glob(args.pattern) if path.is_file())
    if not image_paths:
        write_results(output_dir, [])
        print(f"没有找到可处理图片: {source_dir / args.pattern}")
        return 1

    results: List[Dict[str, Any]] = []
    for image_path in image_paths:
        annotation = annotations.get(image_path.name)
        result = process_one(
            image_path,
            output_dir,
            detector,
            annotation,
            reader,
            matcher,
            equipment_names,
            max(1, int(args.top_n)),
        )
        results.append(result)
        alignment = result.get("alignment", {})
        print(
            f"{image_path.name}: status={result['detection']['status']}, "
            f"detected={len(result['detection'].get('candidates', []))}, "
            f"selected={len(alignment.get('selected_indices', []))}, "
            f"align={alignment.get('method', '')}"
        )

    write_results(output_dir, results)
    summary = summarize_results(results)
    (output_dir / "design_fragment_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已输出 {len(results)} 张图片的设计图碎片识别结果到: {output_dir}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


# ============================================================
# 🌐 第七部分：脚本入口
# ============================================================

if __name__ == "__main__":
    raise SystemExit(main())
