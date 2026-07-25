#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      筛选状态校准脚本 (run_filter_state_detection.py)        ║
║                                                              ║
║  【一句话解释】批量识别设计图筛选面板，并输出标注图/结果表。║
║  【类比理解】它像一支荧光笔，把筛选菜单里亮起的按钮圈出来。  ║
║  【数据流说明】filter_state_img_input→filter_state_img_out；  ║
║              test_img/filter_state→test_out/filter_state。    ║
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
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


# 脚本位于 ocr_training_lab/fragment_filter_scan/ 下，运行时把项目根目录加入 import 路径。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.recognition.filter_state_detector import FilterStateDetector, FilterStateResult  # noqa: E402


# ============================================================
# 🧱 第二部分：标注解析常量
# ============================================================

TRUE_VALUES = {"true", "ture", "yes", "y", "1", "是", "亮", "选中", "可见"}
FALSE_VALUES = {"false", "no", "n", "0", "否", "灭", "未选中", "不可见"}
BOOL_KEYS = {
    "filter_panel_open",
    "filter_button_visible",
    "sort_button_visible",
    "rarity_button_visible",
}
RARITY_NAMES = {"all", "ultra_rare", "super_rare", "elite", "rare", "common"}


# ============================================================
# 🏗️ 第三部分：参数和标注解析
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。
    输入：
        命令行参数。
    输出：
        argparse.Namespace。
    使用示例：
        python run_filter_state_detection.py --use-test
    """
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="批量识别仓库设计图筛选状态。")
    parser.add_argument("--input-dir", type=Path, default=script_dir / "filter_state_img_input", help="训练/校准截图目录。")
    parser.add_argument("--test-dir", type=Path, default=script_dir / "test_img" / "filter_state", help="筛选状态稳定性测试截图目录。")
    parser.add_argument("--output-dir", type=Path, default=None, help="输出目录。默认训练图→filter_state_img_out，测试图→test_out/filter_state。")
    parser.add_argument("--exp-file", type=Path, default=None, help="标注文件。默认从输入目录读取 filter_state_exp.txt。")
    parser.add_argument("--use-test", "--test", action="store_true", help="处理 test_img/filter_state，并输出到 test_out/filter_state。")
    parser.add_argument("--pattern", default="*.png", help="输入图片匹配模式，默认 *.png。")
    return parser.parse_args()


def resolve_output_dir(script_dir: Path, use_test: bool, output_dir: Optional[Path]) -> Path:
    """
    根据输入来源选择输出目录，避免训练结果和测试结果互相覆盖。
    输入：
        script_dir/use_test/output_dir。
    输出：
        实际输出目录。
    使用示例：
        resolve_output_dir(Path("fragment_filter_scan"), False, None)
    """
    if output_dir is not None:
        return output_dir
    if use_test:
        return script_dir / "test_out" / "filter_state"
    return script_dir / "filter_state_img_out"


def parse_filter_state_exp(exp_path: Path) -> Dict[str, Dict[str, Any]]:
    """
    解析 filter_state_exp.txt 标注文件。
    输入：
        exp_path。
    输出：
        filename → 字段字典。
    使用示例：
        annotations = parse_filter_state_exp(Path("filter_state_exp.txt"))
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
        value = _normalize_value(key, raw_value.strip())
        annotations[current_name][key] = value
    return annotations


def _normalize_value(key: str, value: str) -> Any:
    """把人工标注中的 true/false 转成 bool，其余字段保留字符串。"""
    lowered = value.strip().lower()
    if key in BOOL_KEYS or key.endswith(".visible") or key.endswith(".selected"):
        if lowered in TRUE_VALUES:
            return True
        if lowered in FALSE_VALUES:
            return False
        return "unknown"
    return value.strip()


# ============================================================
# 🧮 第四部分：检测结果和标注对照
# ============================================================

def selected_rarity_from_result(result: FilterStateResult) -> str:
    """
    从识别结果的稀有度选项中取当前金色选中项。
    输入：
        result。
    输出：
        all/ultra_rare/super_rare/elite/rare/common/unknown。
    使用示例：
        selected = selected_rarity_from_result(result)
    """
    selected = [option for option in result.options if option.group == "rarity" and option.selected]
    if not selected:
        return "unknown"
    return max(selected, key=lambda item: item.gold_ratio).name


def compare_with_annotation(result: FilterStateResult, annotation: Mapping[str, Any]) -> Tuple[bool, Tuple[str, ...]]:
    """
    将识别结果与人工标注进行宽容对照。
    输入：
        result/annotation。
    输出：
        是否通过、差异说明列表。
    使用示例：
        ok, mismatches = compare_with_annotation(result, annotation)
    """
    if not annotation:
        return True, ("未找到人工标注，仅输出识别结果。",)

    mismatches: List[str] = []
    _compare_field(mismatches, "filter_panel_open", annotation.get("filter_panel_open"), result.filter_panel_open)
    _compare_field(mismatches, "current_rarity_filter", annotation.get("current_rarity_filter"), result.current_rarity_filter)
    _compare_field(mismatches, "current_sort", annotation.get("current_sort"), result.current_sort)

    expected_selected = str(annotation.get("selected_option", "unknown") or "unknown")
    if expected_selected in RARITY_NAMES:
        detected_selected = selected_rarity_from_result(result) if result.filter_panel_open else result.current_rarity_filter
        _compare_field(mismatches, "selected_option", expected_selected, detected_selected)

    element_map = {element.label: element for element in result.elements}
    visible_aliases = {
        "filter_button_visible": "filter_button",
        "sort_button_visible": "sort_button",
        "rarity_button_visible": "rarity_button",
    }
    for expected_key, label in visible_aliases.items():
        if expected_key in annotation and label in element_map:
            _compare_field(mismatches, expected_key, annotation.get(expected_key), element_map[label].visible)

    option_map = {f"option_{option.name}": option for option in result.options if option.group == "rarity"}
    for option_label, option in option_map.items():
        visible_key = f"{option_label}.visible"
        selected_key = f"{option_label}.selected"
        if visible_key in annotation:
            _compare_field(mismatches, visible_key, annotation.get(visible_key), option.visible)
        if selected_key in annotation:
            _compare_field(mismatches, selected_key, annotation.get(selected_key), option.selected)

    return not mismatches, tuple(mismatches)


def _compare_field(mismatches: List[str], field: str, expected: Any, detected: Any) -> None:
    """对单个字段做宽容比较；未标注或 unknown 不作为错误。"""
    if expected is None or expected == "":
        return
    if expected == "unknown":
        return
    if isinstance(expected, bool):
        if bool(detected) != expected:
            mismatches.append(f"{field}: expected={expected}, detected={detected}")
        return
    if str(expected) != str(detected):
        mismatches.append(f"{field}: expected={expected}, detected={detected}")


def build_summary(results: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """
    汇总本批样本对照情况；只描述当前样本，不宣称通用准确率。
    输入：
        results。
    输出：
        摘要字典。
    使用示例：
        summary = build_summary(results)
    """
    annotated = [item for item in results if item.get("has_annotation")]
    passed = [item for item in annotated if item.get("annotation_match")]
    return {
        "images": len(results),
        "annotated_images": len(annotated),
        "annotation_matched_images": len(passed),
        "annotation_mismatched_images": len(annotated) - len(passed),
        "note": "该结果仅表示当前 filter_state_img_input/test_img/filter_state 样本的对照情况；正式自动化应打开筛选面板确认精确筛选项。",
    }


# ============================================================
# 🎨 第五部分：输出文件
# ============================================================

def process_one(
    image_path: Path,
    output_dir: Path,
    detector: FilterStateDetector,
    annotation: Mapping[str, Any],
) -> Dict[str, Any]:
    """
    处理单张筛选截图并输出标注图。
    输入：
        image_path/output_dir/detector/annotation。
    输出：
        单张图片的结构化结果。
    使用示例：
        payload = process_one(Path("design_filter_menu_open.png"), out, detector, annotation)
    """
    result = detector.detect(image_path)
    annotation_match, mismatches = compare_with_annotation(result, annotation)
    payload: Dict[str, Any] = {
        "filename": image_path.name,
        "screenshot_path": str(image_path),
        "has_annotation": bool(annotation),
        "annotation": dict(annotation),
        "annotation_match": bool(annotation_match),
        "annotation_mismatches": list(mismatches),
        "result": result.to_dict(),
        "annotated_output": "",
    }
    if result.status not in {"error", "unavailable", "partial_image"}:
        image = detector.load_image(image_path)
        annotated = detector.draw_annotations(image, result)
        output_path = output_dir / f"{image_path.stem}_filter_state.png"
        detector.write_image(output_path, annotated)
        payload["annotated_output"] = str(output_path)
    return payload


def write_results(output_dir: Path, results: Sequence[Mapping[str, Any]]) -> None:
    """
    写出 JSON、CSV 和 summary，方便人工验图和后续整合读取。
    输入：
        output_dir/results。
    输出：
        filter_state_results.json/csv 和 filter_state_summary.json。
    使用示例：
        write_results(Path("filter_state_img_out"), results)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "filter_state_results.json").write_text(
        json.dumps(list(results), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = build_summary(results)
    (output_dir / "filter_state_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    fieldnames = [
        "filename",
        "success",
        "status",
        "filter_panel_open",
        "filter_button_active",
        "current_rarity_filter",
        "selected_rarity",
        "current_type_filter",
        "current_camp_filter",
        "current_sort",
        "rarity_inference_source",
        "annotation_match",
        "annotation_mismatches",
        "warnings",
        "annotated_output",
    ]
    with (output_dir / "filter_state_results.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for item in results:
            result = item.get("result", {})
            writer.writerow({
                "filename": item.get("filename", ""),
                "success": result.get("success", False),
                "status": result.get("status", ""),
                "filter_panel_open": result.get("filter_panel_open", False),
                "filter_button_active": result.get("filter_button_active", False),
                "current_rarity_filter": result.get("current_rarity_filter", ""),
                "selected_rarity": _selected_rarity_from_dict(result),
                "current_type_filter": result.get("current_type_filter", ""),
                "current_camp_filter": result.get("current_camp_filter", ""),
                "current_sort": result.get("current_sort", ""),
                "rarity_inference_source": result.get("rarity_inference_source", ""),
                "annotation_match": item.get("annotation_match", False),
                "annotation_mismatches": " | ".join(str(value) for value in item.get("annotation_mismatches", [])),
                "warnings": " | ".join(str(value) for value in result.get("warnings", [])),
                "annotated_output": item.get("annotated_output", ""),
            })

    click_fieldnames = [
        "filename",
        "target_type",
        "label",
        "group",
        "name",
        "text",
        "visible",
        "enabled",
        "selected",
        "state",
        "clickable",
        "click_action",
        "center_x",
        "center_y",
        "normalized_center_x",
        "normalized_center_y",
        "base_center_x",
        "base_center_y",
        "bbox",
        "base_bbox",
        "coordinate_space",
        "confidence",
        "description",
    ]
    with (output_dir / "filter_state_click_targets.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=click_fieldnames)
        writer.writeheader()
        for row in _click_target_rows(results):
            writer.writerow(row)


def _selected_rarity_from_dict(result: Mapping[str, Any]) -> str:
    """从 result dict 中提取面板稀有度选中项。"""
    selected = [
        option
        for option in result.get("options", [])
        if option.get("group") == "rarity" and option.get("selected")
    ]
    if not selected:
        return "unknown"
    return str(max(selected, key=lambda item: float(item.get("gold_ratio", 0.0))).get("name", "unknown"))


def _click_target_rows(results: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """
    展平 elements/options 中的 ADB 点击坐标，方便自动化层和人工验收查表。
    """
    rows: List[Dict[str, Any]] = []
    for item in results:
        filename = str(item.get("filename", ""))
        result = item.get("result", {})
        for element in result.get("elements", []):
            if element.get("click_action"):
                rows.append(_click_target_row(filename, "element", element))
        for option in result.get("options", []):
            if option.get("click_action"):
                rows.append(_click_target_row(filename, "option", option))
    return rows


def _click_target_row(filename: str, target_type: str, target: Mapping[str, Any]) -> Dict[str, Any]:
    """把单个元素/选项转换成 click target CSV 行。"""
    center = target.get("center", [])
    normalized_center = target.get("normalized_center", [])
    base_center = target.get("base_center", [])
    return {
        "filename": filename,
        "target_type": target_type,
        "label": target.get("label", ""),
        "group": target.get("group", ""),
        "name": target.get("name", target.get("label", "")),
        "text": target.get("text", ""),
        "visible": target.get("visible", False),
        "enabled": target.get("enabled", False),
        "selected": target.get("selected", ""),
        "state": target.get("state", ""),
        "clickable": target.get("clickable", False),
        "click_action": target.get("click_action", ""),
        "center_x": _list_item(center, 0),
        "center_y": _list_item(center, 1),
        "normalized_center_x": _list_item(normalized_center, 0),
        "normalized_center_y": _list_item(normalized_center, 1),
        "base_center_x": _list_item(base_center, 0),
        "base_center_y": _list_item(base_center, 1),
        "bbox": _compact_json(target.get("bbox", [])),
        "base_bbox": _compact_json(target.get("base_bbox", [])),
        "coordinate_space": target.get("coordinate_space", "screen_pixels"),
        "confidence": target.get("confidence", 0.0),
        "description": target.get("description", ""),
    }


def _list_item(value: Any, index: int) -> Any:
    """安全读取 list/tuple 指定位置，缺失时返回空字符串。"""
    if not isinstance(value, (list, tuple)) or len(value) <= index:
        return ""
    return value[index]


def _compact_json(value: Any) -> str:
    """把 list/dict 压成单行 JSON，避免 CSV 里出现 Python repr。"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# ============================================================
# 🚀 第六部分：脚本入口
# ============================================================

def main() -> int:
    """
    批量处理入口。
    输入：
        命令行参数。
    输出：
        进程退出码。
    使用示例：
        python ocr_training_lab/fragment_filter_scan/run_filter_state_detection.py
    """
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    source_dir = args.test_dir if args.use_test else args.input_dir
    output_dir = resolve_output_dir(script_dir, args.use_test, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    exp_path = args.exp_file if args.exp_file is not None else source_dir / "filter_state_exp.txt"
    annotations = parse_filter_state_exp(exp_path)
    detector = FilterStateDetector()
    status = detector.check_status()
    if not status["available"]:
        print("OpenCV/NumPy 不可用，无法生成筛选状态标注结果。")
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 2

    image_paths = sorted(path for path in source_dir.glob(args.pattern) if path.is_file())
    if not image_paths:
        write_results(output_dir, [])
        print(f"没有找到可处理图片: {source_dir / args.pattern}")
        return 1

    results: List[Dict[str, Any]] = []
    for image_path in image_paths:
        annotation = annotations.get(image_path.name, {})
        payload = process_one(image_path, output_dir, detector, annotation)
        results.append(payload)
        result = payload["result"]
        print(
            f"{image_path.name}: panel={result['filter_panel_open']}, "
            f"rarity={result['current_rarity_filter']}, "
            f"selected={_selected_rarity_from_dict(result)}, "
            f"match={payload['annotation_match']}, status={result['status']}"
        )

    write_results(output_dir, results)
    print(f"已输出 {len(results)} 张筛选状态识别结果到: {output_dir}")
    print(json.dumps(build_summary(results), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
