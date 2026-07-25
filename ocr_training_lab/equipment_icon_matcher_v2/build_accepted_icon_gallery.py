#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      装备图标 v2 Accepted 图库构建器                         ║
║                                                              ║
║  【一句话解释】从已人工确认的 rarity_bucket 结果里裁剪图标。 ║
║  【类比理解】把已经认准的装备小头像剪下来，做成游戏内图鉴。  ║
║  【数据流说明】rarity_bucket_results.json → accepted图库/清单。║
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
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - 无 OpenCV 环境时由 main 返回友好错误。
    cv2 = None
    np = None


# ============================================================
# 🧱 第二部分：类型与常量
# ============================================================

RoiRegion = Tuple[int, int, int, int]

DEFAULT_SOURCE_RESULTS = (
    PROJECT_ROOT
    / "ocr_training_lab"
    / "fragment_filter_scan"
    / "rarity_bucket_img_out"
    / "rarity_bucket_results.json"
)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "accepted_icon_gallery"
MANIFEST_CSV_NAME = "accepted_icon_gallery_manifest.csv"
MANIFEST_JSON_NAME = "accepted_icon_gallery_manifest.json"


# ============================================================
# 🏗️ 第三部分：参数与基础 IO
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。
    输入：
        终端命令行。
    输出：
        argparse.Namespace。
    使用示例：
        python build_accepted_icon_gallery.py
    """
    parser = argparse.ArgumentParser(description="从 rarity_bucket accepted_* 行裁剪游戏内装备图标参考库。")
    parser.add_argument("--source-results", type=Path, default=DEFAULT_SOURCE_RESULTS, help="rarity_bucket_results.json 路径。")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="accepted 图标图库输出目录。")
    parser.add_argument("--include-partial", action="store_true", help="允许裁剪 visibility 非 full 的图标；默认跳过半截图标。")
    parser.add_argument("--overwrite", action="store_true", help="清空旧 manifest 记录并覆盖同名图标。")
    parser.add_argument("--pattern-prefix", default="accepted", help="输出文件名前缀，默认 accepted。")
    return parser.parse_args()


def load_results(source_results: Path) -> List[Dict[str, Any]]:
    """
    读取 rarity_bucket 结构化结果。
    输入：
        source_results。
    输出：
        单图 result 列表。
    使用示例：
        results = load_results(Path("rarity_bucket_results.json"))
    """
    if not source_results.exists():
        raise FileNotFoundError(f"未找到 rarity_bucket 结果文件: {source_results}")
    data = json.loads(source_results.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("rarity_bucket_results.json 顶层必须是 list。")
    return [item for item in data if isinstance(item, dict)]


def load_equipment_name_index(project_root: Path = PROJECT_ROOT) -> Dict[str, str]:
    """
    读取当前装备库中的 equipment_id → name 映射。
    输入：
        project_root。
    输出：
        equipment_id 到装备名称。
    使用示例：
        names = load_equipment_name_index()
    """
    library_path = project_root / "data" / "equipment_library.csv"
    if not library_path.exists():
        return {}
    names: Dict[str, str] = {}
    with library_path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            equipment_id = str(row.get("equipment_id", "") or "").strip()
            name = str(row.get("name", "") or "").strip()
            if equipment_id and name:
                names[equipment_id] = name
    return names


def read_image(image_path: Path) -> Any:
    """
    用 OpenCV 读取图片，兼容 Windows 中文路径。
    输入：
        图片路径。
    输出：
        OpenCV BGR 图像。
    使用示例：
        image = read_image(Path("design_rare_1.png"))
    """
    if cv2 is None or np is None:
        raise RuntimeError("OpenCV(cv2) 或 NumPy 不可用，无法裁剪图标。")
    if not image_path.exists() or not image_path.is_file():
        raise FileNotFoundError(f"截图不存在: {image_path}")
    data = np.fromfile(str(image_path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None or getattr(image, "size", 0) == 0:
        raise ValueError(f"截图无法读取或已损坏: {image_path}")
    return image


def write_image(image_path: Path, image: Any) -> None:
    """
    用 OpenCV 写出图片，兼容 Windows 中文路径。
    输入：
        输出路径和 BGR 图像。
    输出：
        PNG 文件。
    使用示例：
        write_image(Path("G0001/sample.png"), crop)
    """
    if cv2 is None:
        raise RuntimeError("OpenCV(cv2) 不可用，无法写出图标。")
    image_path.parent.mkdir(parents=True, exist_ok=True)
    success, buffer = cv2.imencode(image_path.suffix or ".png", image)
    if not success:
        raise ValueError(f"图标编码失败: {image_path}")
    buffer.tofile(str(image_path))


# ============================================================
# ✂️ 第四部分：Accepted 行筛选与裁剪
# ============================================================

def iter_accepted_cards(
    results: Sequence[Mapping[str, Any]],
    include_partial: bool = False,
) -> Iterable[Tuple[Mapping[str, Any], Mapping[str, Any]]]:
    """
    遍历可用于图库的 accepted 卡片。
    输入：
        rarity_bucket results。
    输出：
        (截图 result, 卡片 row)。
    使用示例：
        for result, card in iter_accepted_cards(results): ...
    """
    for result in results:
        for card in result.get("cards", []):
            equipment_id = str(card.get("accepted_equipment_id", "") or "").strip()
            if not equipment_id:
                continue
            if not bool(card.get("icon_selected")):
                continue
            if not include_partial and str(card.get("visibility", "")) != "full":
                continue
            if not _parse_roi(card.get("icon_match_roi") or card.get("icon_roi")):
                continue
            yield result, card


def build_gallery(
    source_results: Path,
    output_dir: Path,
    include_partial: bool = False,
    overwrite: bool = False,
    pattern_prefix: str = "accepted",
) -> List[Dict[str, Any]]:
    """
    裁剪 accepted 图标并写出 manifest。
    输入：
        source_results/output_dir/include_partial/overwrite。
    输出：
        manifest 行列表。
    使用示例：
        rows = build_gallery(DEFAULT_SOURCE_RESULTS, DEFAULT_OUTPUT_DIR)
    """
    results = load_results(source_results)
    equipment_names = load_equipment_name_index()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows: List[Dict[str, Any]] = []
    seen_names: Dict[str, int] = {}

    for result, card in iter_accepted_cards(results, include_partial=include_partial):
        screenshot_path = _resolve_screenshot_path(result, source_results)
        image = read_image(screenshot_path)
        roi = _validate_roi(image, _parse_roi(card.get("icon_match_roi") or card.get("icon_roi")))
        x, y, width, height = roi
        crop = image[y:y + height, x:x + width]
        if crop is None or getattr(crop, "size", 0) == 0:
            continue

        equipment_id = str(card.get("accepted_equipment_id", "")).strip()
        equipment_name = str(card.get("accepted_equipment_name", "") or "").strip() or equipment_names.get(equipment_id, "")
        source_filename = str(result.get("filename") or card.get("filename") or screenshot_path.name)
        rarity = _annotation_field(result, "filter_rarity")
        rarity_id = _annotation_field(result, "filter_rarity_id")
        sample_stem = _safe_stem(f"{pattern_prefix}_{equipment_id}_{Path(source_filename).stem}_card{int(card.get('card_no', 0)):02d}")
        duplicate_index = seen_names.get(sample_stem, 0) + 1
        seen_names[sample_stem] = duplicate_index
        filename = f"{sample_stem}_{duplicate_index:02d}.png" if duplicate_index > 1 else f"{sample_stem}.png"
        relative_icon_path = Path(equipment_id) / filename
        icon_path = output_dir / relative_icon_path
        if overwrite or not icon_path.exists():
            write_image(icon_path, crop)

        manifest_rows.append(
            {
                "sample_id": f"{equipment_id}:{Path(source_filename).stem}:card{int(card.get('card_no', 0)):02d}:{duplicate_index:02d}",
                "equipment_id": equipment_id,
                "equipment_name": equipment_name,
                "image_path": str(icon_path),
                "relative_image_path": str(relative_icon_path).replace("\\", "/"),
                "source_filename": source_filename,
                "source_path": str(screenshot_path),
                "card_no": int(card.get("card_no", 0) or 0),
                "rarity": rarity,
                "rarity_id": rarity_id,
                "visibility": str(card.get("visibility", "")),
                "icon_roi": json.dumps(list(roi), ensure_ascii=False),
                "width": int(width),
                "height": int(height),
                "accepted_fragment_owned": card.get("accepted_fragment_owned", ""),
                "accepted_fragment_required": card.get("accepted_fragment_required", ""),
                "source_icon_status": card.get("icon_status", ""),
                "source_icon_confidence": card.get("icon_confidence", ""),
            }
        )

    write_manifest(output_dir, manifest_rows)
    return manifest_rows


def write_manifest(output_dir: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """
    写出 CSV/JSON manifest。
    输入：
        output_dir/rows。
    输出：
        accepted_icon_gallery_manifest.csv/json。
    使用示例：
        write_manifest(Path("accepted_icon_gallery"), rows)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "sample_id",
        "equipment_id",
        "equipment_name",
        "image_path",
        "relative_image_path",
        "source_filename",
        "source_path",
        "card_no",
        "rarity",
        "rarity_id",
        "visibility",
        "icon_roi",
        "width",
        "height",
        "accepted_fragment_owned",
        "accepted_fragment_required",
        "source_icon_status",
        "source_icon_confidence",
    ]
    with (output_dir / MANIFEST_CSV_NAME).open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    (output_dir / MANIFEST_JSON_NAME).write_text(json.dumps(list(rows), ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# 🧰 第五部分：小工具函数
# ============================================================

def _resolve_screenshot_path(result: Mapping[str, Any], source_results: Path) -> Path:
    """解析截图路径；旧结果缺 screenshot_path 时回退到同目录按 filename 查找。"""
    raw_path = str(result.get("screenshot_path", "") or "").strip()
    if raw_path:
        path = Path(raw_path)
        return path if path.is_absolute() else PROJECT_ROOT / path
    filename = str(result.get("filename", "") or "").strip()
    return source_results.parent / filename


def _annotation_field(result: Mapping[str, Any], key: str) -> Any:
    """从 result.annotation.fields 中读取字段，缺失时返回空字符串。"""
    annotation = result.get("annotation") or {}
    fields = annotation.get("fields") or {}
    return fields.get(key, "")


def _parse_roi(raw: Any) -> Optional[RoiRegion]:
    """把 list 或 '[x,y,w,h]' 文本解析成 ROI。"""
    if raw is None or raw == "":
        return None
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        try:
            return tuple(int(value) for value in raw)  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    if isinstance(raw, str):
        numbers = re.findall(r"-?\d+", raw)
        if len(numbers) >= 4:
            return tuple(int(value) for value in numbers[:4])  # type: ignore[return-value]
    return None


def _validate_roi(image: Any, roi: Optional[RoiRegion]) -> RoiRegion:
    """检查 ROI 是否落在截图内，避免把半截/越界区域写入图库。"""
    if roi is None:
        raise ValueError("缺少 icon ROI。")
    x, y, width, height = roi
    image_height, image_width = int(image.shape[0]), int(image.shape[1])
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError(f"图标 ROI 非法: {roi}")
    if x + width > image_width or y + height > image_height:
        raise ValueError(f"图标 ROI 越界: {roi} > {(image_width, image_height)}")
    return x, y, width, height


def _safe_stem(value: str) -> str:
    """把装备 ID/文件名组合转换成安全文件名。"""
    return re.sub(r"[^0-9A-Za-z_\-\.]+", "_", value).strip("_") or "accepted_icon"


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
        python ocr_training_lab/equipment_icon_matcher_v2/build_accepted_icon_gallery.py
    """
    args = parse_args()
    if cv2 is None or np is None:
        print("OpenCV(cv2) 或 NumPy 不可用，无法构建 accepted 图标图库。")
        return 2
    try:
        rows = build_gallery(
            source_results=args.source_results,
            output_dir=args.output_dir,
            include_partial=bool(args.include_partial),
            overwrite=bool(args.overwrite),
            pattern_prefix=str(args.pattern_prefix),
        )
    except Exception as exc:
        print(f"构建 accepted 图标图库失败: {exc}")
        return 1

    summary = {
        "source_results": str(args.source_results),
        "output_dir": str(args.output_dir),
        "samples": len(rows),
        "equipment_ids": len({row["equipment_id"] for row in rows}),
        "manifest_csv": str(args.output_dir / MANIFEST_CSV_NAME),
        "manifest_json": str(args.output_dir / MANIFEST_JSON_NAME),
        "note": "这是游戏内 accepted 图标参考库，不代表最终识别准确率；后续需要独立 test_img 截图做泛化验证。",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
