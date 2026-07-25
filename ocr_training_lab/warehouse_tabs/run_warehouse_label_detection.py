#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║       🧪 仓库标签训练标注脚本 (run_warehouse_label_detection)║
║                                                              ║
║  【一句话解释】批量读取仓库截图，输出带框图片和结构化结果。  ║
║  【类比理解】它像一支荧光笔，把识别器看到的按钮都圈出来。  ║
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
import sys
from pathlib import Path
from typing import Any, Dict, List


# 训练脚本位于 ocr_training_lab/warehouse_tabs/ 下，运行时主动把项目根目录放入 import 路径。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.recognition.warehouse_label_detector import WarehouseLabelDetector, WarehouseLabelResult


# ============================================================
# 🏗️ 第二部分：批处理逻辑
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。
    输入：
        命令行参数。
    输出：
        argparse.Namespace。
    使用示例：
        python run_warehouse_label_detection.py --use-test
    """
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="批量识别仓库标签并输出标注图。")
    parser.add_argument("--input-dir", type=Path, default=script_dir / "img_input", help="训练/输入截图目录。")
    parser.add_argument("--test-dir", type=Path, default=script_dir / "test_img", help="稳定性测试截图目录。")
    parser.add_argument("--output-dir", type=Path, default=None, help="标注图和结果输出目录。默认 img_input→img_out，test_img→test_out。")
    parser.add_argument("--use-test", action="store_true", help="改为处理 test_img，而不是 img_input。")
    parser.add_argument("--no-templates", action="store_true", help="不从 img_input 构建排序状态模板。")
    parser.add_argument("--max-templates", type=int, default=12, help="每个排序状态最多使用多少张模板。")
    return parser.parse_args()


def write_image(path: Path, image: Any, detector: WarehouseLabelDetector) -> None:
    """
    写出 OpenCV 图片，兼容 Windows 中文路径。
    输入：
        path/image/detector。
    输出：
        无，目标 PNG 文件。
    使用示例：
        write_image(out_path, annotated, detector)
    """
    cv2_module, _np_module = detector._require_dependencies()  # noqa: SLF001 - lab 脚本只复用检测器依赖检查。
    ok, encoded = cv2_module.imencode(".png", image)
    if not ok:
        raise ValueError(f"无法编码输出图片: {path}")
    encoded.tofile(str(path))


def resolve_output_dir(script_dir: Path, use_test: bool, output_dir: Path | None) -> Path:
    """
    根据输入来源选择输出目录，避免训练标注结果和稳定性测试结果互相覆盖。
    输入：
        script_dir/use_test/output_dir。
    输出：
        实际输出目录。
    使用示例：
        resolve_output_dir(Path("warehouse_tabs"), True, None)
    """
    if output_dir is not None:
        return output_dir
    return script_dir / ("test_out" if use_test else "img_out")


def write_results(output_dir: Path, results: List[Dict[str, Any]]) -> None:
    """
    写出 JSON 和 CSV 识别结果，方便人工查看或后续自动比对。
    输入：
        output_dir/results。
    输出：
        warehouse_label_results.json/csv。
    使用示例：
        write_results(Path("img_out"), rows)
    """
    json_path = output_dir / "warehouse_label_results.json"
    csv_path = output_dir / "warehouse_label_results.csv"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "filename",
        "success",
        "status",
        "page_type",
        "sort_mode",
        "filter_panel_open",
        "warnings",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for item in results:
            writer.writerow({
                "filename": Path(str(item.get("screenshot_path", ""))).name,
                "success": item.get("success", False),
                "status": item.get("status", ""),
                "page_type": item.get("page_type", ""),
                "sort_mode": item.get("sort_mode", ""),
                "filter_panel_open": item.get("filter_panel_open", False),
                "warnings": " | ".join(str(warning) for warning in item.get("warnings", [])),
            })


def process_one(
    image_path: Path,
    output_dir: Path,
    detector: WarehouseLabelDetector,
    sort_templates: Dict[str, tuple[Any, ...]],
) -> WarehouseLabelResult:
    """
    处理单张截图并输出带框标注图。
    输入：
        image_path/output_dir/detector/sort_templates。
    输出：
        WarehouseLabelResult。
    使用示例：
        result = process_one(Path("shot.png"), Path("img_out"), detector, templates)
    """
    result = detector.detect(image_path, sort_templates=sort_templates)
    if result.status not in {"error", "unavailable"}:
        image = detector.load_image(image_path)
        annotated = detector.draw_annotations(image, result)
        output_path = output_dir / f"{image_path.stem}_labels.png"
        write_image(output_path, annotated, detector)
    return result


def main() -> int:
    """
    脚本入口。
    输入：
        命令行参数。
    输出：
        进程退出码。
    使用示例：
        python ocr_training_lab/warehouse_tabs/run_warehouse_label_detection.py
    """
    args = parse_args()
    detector = WarehouseLabelDetector()
    status = detector.check_status()
    if not status["available"]:
        print("OpenCV/NumPy 不可用，无法生成仓库标签标注结果。")
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 2

    source_dir = args.test_dir if args.use_test else args.input_dir
    output_dir = resolve_output_dir(Path(__file__).resolve().parent, args.use_test, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sort_templates: Dict[str, tuple[Any, ...]] = {}
    if not args.no_templates:
        sort_templates = detector.build_sort_template_bank(args.input_dir, max_per_label=args.max_templates)

    image_paths = sorted(path for path in source_dir.glob("*.png") if path.is_file())
    if not image_paths:
        print(f"没有找到可处理 PNG 图片: {source_dir}")
        write_results(output_dir, [])
        return 1

    results: List[Dict[str, Any]] = []
    for image_path in image_paths:
        result = process_one(image_path, output_dir, detector, sort_templates)
        result_dict = result.to_dict()
        results.append(result_dict)
        print(
            f"{image_path.name}: page={result.page_type}, sort={result.sort_mode}, "
            f"filter={result.filter_panel_open}, status={result.status}"
        )

    write_results(output_dir, results)
    print(f"已输出 {len(results)} 张图片的识别结果到: {output_dir}")
    print(f"排序模板数量: {', '.join(f'{key}={len(value)}' for key, value in sort_templates.items()) or '未使用'}")
    return 0


# ============================================================
# 🌐 第三部分：脚本入口
# ============================================================

if __name__ == "__main__":
    raise SystemExit(main())
