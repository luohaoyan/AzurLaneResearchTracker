#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量运行港区资源识别，并输出标注图、JSON 和 CSV。"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.recognition.harbor_resource_detector import HarborResourceDetector

_VISUAL_NAME_EQUIVALENTS = str.maketrans(
    {
        "o": "0",
        "O": "0",
        "0": "0",
        "l": "1",
        "L": "1",
        "I": "1",
        "1": "1",
    }
)


def build_parser() -> argparse.ArgumentParser:
    """建立命令行参数。"""
    parser = argparse.ArgumentParser(description="批量识别港区主页用户名与资源数量")
    parser.add_argument("--test", action="store_true", help="读取 test_img，而不是 img_input")
    parser.add_argument("--input-dir", type=Path, help="自定义输入目录")
    parser.add_argument("--output-dir", type=Path, help="自定义输出目录")
    return parser


def load_expected(input_dir: Path) -> Dict[str, Dict[str, str]]:
    """读取 epx.txt/exp.txt 真值标注；没有标注时返回空字典。"""
    expected_path = input_dir / "epx.txt"
    if not expected_path.exists():
        expected_path = input_dir / "exp.txt"
    if not expected_path.exists():
        return {}

    expected: Dict[str, Dict[str, str]] = {}
    for line in expected_path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        filename, raw_items = (item.strip() for item in line.split("=", 1))
        fields: Dict[str, str] = {}
        for part in re.split(r"[,;]", raw_items):
            if ":" not in part:
                continue
            key, value = (item.strip() for item in part.split(":", 1))
            fields[key] = value
        if filename and fields:
            expected[filename] = fields
    return expected


def normalize_player_name_for_eval(value: Any) -> str:
    """把用户名里的 OCR 视觉混淆字符归一化，仅用于样本评估对照。"""
    text = str(value or "").strip()
    normalized = text.translate(_VISUAL_NAME_EQUIVALENTS).casefold()
    return "".join(char for char in normalized if not char.isspace())


def values_match_for_eval(field: str, expected_value: str, actual_value: str) -> tuple[bool, str]:
    """判断标注和识别值是否匹配，并区分精确匹配与视觉等价匹配。"""
    if expected_value == actual_value:
        return True, "exact"
    if field == "name" and normalize_player_name_for_eval(expected_value) == normalize_player_name_for_eval(actual_value):
        return True, "visual_equivalent"
    return False, "different"


def resolve_output_dir(lab_dir: Path, use_test: bool, output_dir: Path | None) -> Path:
    """根据输入来源选择输出目录，避免训练输出和测试输出互相覆盖。"""
    if output_dir is not None:
        return output_dir
    return lab_dir / ("test_out" if use_test else "img_out")


def write_eval_csv(rows: List[Dict[str, Any]], expected: Mapping[str, Mapping[str, str]], output_dir: Path) -> None:
    """把识别结果和 epx.txt 真值逐字段对照，便于后续校准。"""
    if not expected:
        return
    field_map = {
        "ui": "ui_version",
        "name": "player_name",
        "oil": "oil",
        "coins": "coins",
        "gems": "gems",
    }
    eval_path = output_dir / "harbor_resource_eval.csv"
    with eval_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["filename", "field", "expected", "actual", "matched", "match_mode", "status", "confidence"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            filename = str(row.get("filename", ""))
            expected_row = expected.get(filename, {})
            for expected_field, actual_field in field_map.items():
                if expected_field not in expected_row:
                    continue
                expected_value = str(expected_row[expected_field])
                actual_value = str(row.get(actual_field))
                matched, match_mode = values_match_for_eval(expected_field, expected_value, actual_value)
                writer.writerow(
                    {
                        "filename": filename,
                        "field": expected_field,
                        "expected": expected_value,
                        "actual": actual_value,
                        "matched": matched,
                        "match_mode": match_mode,
                        "status": row.get("status"),
                        "confidence": row.get("confidence"),
                    }
                )


def main() -> int:
    """执行批量识别，不修改正式配置或用户数据。"""
    args = build_parser().parse_args()
    lab_dir = Path(__file__).resolve().parent
    input_dir = args.input_dir or lab_dir / ("test_img" if args.test else "img_input")
    output_dir = resolve_output_dir(lab_dir, args.test, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    detector = HarborResourceDetector()
    expected = load_expected(input_dir)
    rows: List[Dict[str, Any]] = []
    for image_path in sorted(path for path in input_dir.iterdir() if path.suffix.lower() in {".png", ".jpg", ".jpeg"}):
        result = detector.detect(image_path)
        rows.append({"filename": image_path.name, **result.to_dict()})
        if result.rois:
            image = detector.load_image(image_path)
            annotated = detector.draw_annotations(image, result)
            detector._cv2.imwrite(str(output_dir / f"{image_path.stem}_resources.png"), annotated)

    json_path = output_dir / "harbor_resource_results.json"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = output_dir / "harbor_resource_results.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["filename", "ui_version", "player_name", "oil", "coins", "gems", "confidence", "status", "warnings"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: json.dumps(row.get(name), ensure_ascii=False) if name == "warnings" else row.get(name) for name in fieldnames})
    write_eval_csv(rows, expected, output_dir)
    print(f"已处理 {len(rows)} 张图片；输出目录: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
