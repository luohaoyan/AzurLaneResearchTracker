#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      装备图标 v2 Reviewed 图库构建器                         ║
║                                                              ║
║  【一句话解释】把人工校对后的装备名称裁剪成 reviewed 图标库。 ║
║  【类比理解】像把老师批改过的错题剪出来，放进更可靠的图鉴。  ║
║  【数据流说明】review_only_exp + prelabel_results → reviewed库。║
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


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - 无 OpenCV 环境时由 main 返回友好错误。
    cv2 = None
    np = None


# ============================================================
# 🧱 第二部分：数据对象与常量
# ============================================================

RoiRegion = Tuple[int, int, int, int]

DEFAULT_REVIEW_EXP = SCRIPT_DIR / "img_out" / "prelabel" / "v2_prelabel_review_only_exp.txt"
DEFAULT_PRELABEL_RESULTS = SCRIPT_DIR / "img_out" / "prelabel" / "v2_prelabel_results.json"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "reviewed_icon_gallery"
MANIFEST_CSV_NAME = "reviewed_icon_gallery_manifest.csv"
MANIFEST_JSON_NAME = "reviewed_icon_gallery_manifest.json"
RESOLVE_REPORT_CSV_NAME = "reviewed_icon_gallery_resolve_report.csv"
RESOLVE_REPORT_JSON_NAME = "reviewed_icon_gallery_resolve_report.json"


@dataclass(frozen=True)
class ReviewedCardAnnotation:
    """
    单张卡片的人工 reviewed 标注。
    输入：
        filename/card_no/accepted_equipment_name。
    输出：
        后续裁剪和名称解析使用的结构。
    使用示例：
        ann = ReviewedCardAnnotation("shot.png", 4, "液压弹射装置#T3")
    """

    filename: str
    card_no: int
    accepted_equipment_name: str
    accepted_equipment_id: str = ""
    accepted_fragment_owned: str = ""
    accepted_fragment_required: str = ""


@dataclass(frozen=True)
class EquipmentNameResolveResult:
    """
    装备名称解析结果。
    输入：
        人工标注名称。
    输出：
        当前 equipment_library.csv 中的 equipment_id/name。
    使用示例：
        result = resolver.resolve("液压弹射装置#T3")
    """

    status: str
    equipment_id: str = ""
    equipment_name: str = ""
    normalized_name: str = ""
    message: str = ""


# ============================================================
# 🏗️ 第三部分：参数、标注解析和装备库索引
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。
    输入：
        命令行参数。
    输出：
        argparse.Namespace。
    使用示例：
        python build_reviewed_icon_gallery.py
    """
    parser = argparse.ArgumentParser(description="从 v2 人工复核名称构建 reviewed 游戏内装备图标图库。")
    parser.add_argument("--review-exp", type=Path, default=DEFAULT_REVIEW_EXP, help="人工修正后的 review_only_exp 路径。")
    parser.add_argument("--prelabel-results", type=Path, default=DEFAULT_PRELABEL_RESULTS, help="v2_prelabel_results.json 路径。")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="reviewed 图库输出目录。")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的 reviewed 图标文件。")
    parser.add_argument("--pattern-prefix", default="reviewed", help="输出图标文件名前缀。")
    return parser.parse_args()


def parse_review_exp(exp_path: Path) -> Dict[Tuple[str, int], ReviewedCardAnnotation]:
    """
    解析人工修正后的 review_only_exp。
    输入：
        exp_path。
    输出：
        (filename, card_no) → ReviewedCardAnnotation。
    使用示例：
        annotations = parse_review_exp(Path("v2_prelabel_review_only_exp.txt"))
    """
    if not exp_path.exists():
        raise FileNotFoundError(f"review exp 不存在: {exp_path}")

    current_filename = ""
    fields_by_file: Dict[str, Dict[str, str]] = {}
    for raw_line in exp_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_filename = line[1:-1].strip()
            fields_by_file.setdefault(current_filename, {})
            continue
        if not current_filename or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields_by_file[current_filename][key.strip()] = value.strip()

    annotations: Dict[Tuple[str, int], ReviewedCardAnnotation] = {}
    for filename, fields in fields_by_file.items():
        card_numbers = sorted(
            {
                int(match.group(1))
                for key in fields
                for match in [re.match(r"card_(\d+)\.", key)]
                if match is not None
            }
        )
        for card_no in card_numbers:
            prefix = f"card_{card_no:02d}"
            accepted_name = fields.get(f"{prefix}.accepted_equipment_name", "").strip()
            if not accepted_name:
                continue
            annotations[(filename, card_no)] = ReviewedCardAnnotation(
                filename=filename,
                card_no=card_no,
                accepted_equipment_name=accepted_name,
                accepted_equipment_id=fields.get(f"{prefix}.accepted_equipment_id", "").strip(),
                accepted_fragment_owned=fields.get(f"{prefix}.accepted_fragment_owned", "").strip(),
                accepted_fragment_required=fields.get(f"{prefix}.accepted_fragment_required", "").strip(),
            )
    return annotations


class EquipmentNameResolver:
    """按装备名称解析当前 equipment_library.csv 中的 equipment_id。"""

    def __init__(self, project_root: Path = PROJECT_ROOT) -> None:
        """初始化名称索引；只读正式装备库，不写 CSV。"""
        self.project_root = project_root
        self.rows = self._load_rows(project_root / "data" / "equipment_library.csv")
        self.id_to_name = {row["equipment_id"]: row["name"] for row in self.rows if row.get("equipment_id") and row.get("name")}
        self.name_to_ids: Dict[str, List[str]] = {}
        self.normalized_to_ids: Dict[str, List[str]] = {}
        for row in self.rows:
            equipment_id = row.get("equipment_id", "")
            name = row.get("name", "")
            if not equipment_id or not name:
                continue
            self.name_to_ids.setdefault(name, []).append(equipment_id)
            self.normalized_to_ids.setdefault(normalize_equipment_name(name), []).append(equipment_id)

    def resolve(self, raw_name: str, fallback_equipment_id: str = "") -> EquipmentNameResolveResult:
        """把人工标注名称解析为当前装备 ID。"""
        cleaned_name = strip_leading_equipment_id(raw_name)
        normalized = normalize_equipment_name(cleaned_name)
        if not cleaned_name:
            return EquipmentNameResolveResult("empty", normalized_name=normalized, message="accepted_equipment_name 为空。")

        exact_ids = self.name_to_ids.get(cleaned_name, [])
        if len(exact_ids) == 1:
            equipment_id = exact_ids[0]
            return EquipmentNameResolveResult("exact", equipment_id, self.id_to_name[equipment_id], normalized)
        if len(exact_ids) > 1:
            return EquipmentNameResolveResult("ambiguous", normalized_name=normalized, message=f"装备名称精确匹配多个 ID: {exact_ids}")

        normalized_ids = self.normalized_to_ids.get(normalized, [])
        if len(normalized_ids) == 1:
            equipment_id = normalized_ids[0]
            return EquipmentNameResolveResult("normalized", equipment_id, self.id_to_name[equipment_id], normalized)
        if len(normalized_ids) > 1:
            return EquipmentNameResolveResult("ambiguous", normalized_name=normalized, message=f"装备名称规范化后匹配多个 ID: {normalized_ids}")

        if fallback_equipment_id and fallback_equipment_id in self.id_to_name:
            return EquipmentNameResolveResult(
                "id_fallback",
                fallback_equipment_id,
                self.id_to_name[fallback_equipment_id],
                normalized,
                "名称未解析，使用人工填写 accepted_equipment_id 兜底。",
            )
        return EquipmentNameResolveResult("unresolved", normalized_name=normalized, message=f"装备名称未在 equipment_library.csv 中找到: {cleaned_name}")

    @staticmethod
    def _load_rows(library_path: Path) -> List[Dict[str, str]]:
        """只读加载装备库。"""
        if not library_path.exists():
            return []
        with library_path.open("r", encoding="utf-8-sig", newline="") as file:
            return [dict(row) for row in csv.DictReader(file)]


def normalize_equipment_name(name: str) -> str:
    """
    规范化装备名称，减少空格/全角符号差异造成的解析失败。
    输入：
        原始装备名。
    输出：
        规范化键。
    使用示例：
        normalize_equipment_name(" 试作型四联装152mm主炮 #T0 ")
    """
    text = strip_leading_equipment_id(name)
    replacements = {
        "（": "(",
        "）": ")",
        "　": "",
        " ": "",
        "\t": "",
        "\r": "",
        "\n": "",
        "＃": "#",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return strip_tier_noise(text.strip().lower())


def strip_tier_noise(normalized_name: str) -> str:
    """
    去掉 #T3 后误输入的短英文尾巴。
    输入：
        双联装128mmSKC41高平两用炮#T3sa。
    输出：
        双联装128mmskc41高平两用炮#t3。
    使用示例：
        strip_tier_noise("液压弹射装置#t3x")
    """
    return re.sub(r"(#t[0-9]+)[a-z]{1,3}$", r"\1", str(normalized_name or ""), flags=re.IGNORECASE)


def strip_leading_equipment_id(name: str) -> str:
    """去掉误填在装备名前面的 Gxxxx/Sx-xxx ID。"""
    return re.sub(r"^(?:G\d{4}|S\d+-\d{3}|S\d+-\d{1,3})\s+", "", str(name or "").strip())


# ============================================================
# ✂️ 第四部分：裁剪图库和输出报告
# ============================================================

def load_prelabel_results(results_path: Path) -> Dict[Tuple[str, int], Tuple[Mapping[str, Any], Mapping[str, Any]]]:
    """
    加载 v2_prelabel_results.json，并按 filename/card_no 建索引。
    输入：
        results_path。
    输出：
        (filename, card_no) → (result, card_row)。
    使用示例：
        index = load_prelabel_results(Path("v2_prelabel_results.json"))
    """
    if not results_path.exists():
        raise FileNotFoundError(f"prelabel results 不存在: {results_path}")
    data = json.loads(results_path.read_text(encoding="utf-8"))
    index: Dict[Tuple[str, int], Tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    for result in data:
        filename = str(result.get("filename", "") or "")
        for row in result.get("cards", []):
            try:
                card_no = int(row.get("card_no", 0) or 0)
            except (TypeError, ValueError):
                continue
            if filename and card_no > 0:
                index[(filename, card_no)] = (result, row)
    return index


def build_reviewed_gallery(
    review_exp: Path,
    prelabel_results: Path,
    output_dir: Path,
    overwrite: bool = False,
    pattern_prefix: str = "reviewed",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    构建 reviewed 图标图库。
    输入：
        review_exp/prelabel_results/output_dir。
    输出：
        (manifest_rows, report_rows)。
    使用示例：
        rows, report = build_reviewed_gallery(exp, results, out)
    """
    annotations = parse_review_exp(review_exp)
    prelabel_index = load_prelabel_results(prelabel_results)
    resolver = EquipmentNameResolver()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows: List[Dict[str, Any]] = []
    report_rows: List[Dict[str, Any]] = []
    seen_names: Dict[str, int] = {}

    for key, annotation in sorted(annotations.items()):
        indexed = prelabel_index.get(key)
        if indexed is None:
            report_rows.append(_report_row(annotation, "missing_prelabel_row", "在 v2_prelabel_results.json 中找不到对应卡片。"))
            continue
        result, row = indexed
        resolve_result = resolver.resolve(annotation.accepted_equipment_name, annotation.accepted_equipment_id)
        if not resolve_result.equipment_id:
            report_rows.append(_report_row(annotation, resolve_result.status, resolve_result.message, resolve_result))
            continue
        if str(row.get("selected", "")) not in {"True", "true", "1"} and row.get("selected") is not True:
            report_rows.append(_report_row(annotation, "skip_partial", "卡片不是完整 selected=true，跳过图库裁剪。", resolve_result))
            continue

        screenshot_path = Path(str(result.get("screenshot_path", "") or ""))
        if not screenshot_path.is_absolute():
            screenshot_path = PROJECT_ROOT / screenshot_path
        try:
            image = read_image(screenshot_path)
            roi = validate_roi(image, parse_roi(row.get("icon_roi")))
            x, y, width, height = roi
            crop = image[y:y + height, x:x + width]
        except Exception as exc:
            report_rows.append(_report_row(annotation, "crop_error", str(exc), resolve_result))
            continue

        stem = safe_stem(f"{pattern_prefix}_{resolve_result.equipment_id}_{Path(annotation.filename).stem}_card{annotation.card_no:02d}")
        duplicate_index = seen_names.get(stem, 0) + 1
        seen_names[stem] = duplicate_index
        filename = f"{stem}_{duplicate_index:02d}.png" if duplicate_index > 1 else f"{stem}.png"
        relative_image_path = Path(resolve_result.equipment_id) / filename
        image_path = output_dir / relative_image_path
        if overwrite or not image_path.exists():
            write_image(image_path, crop)

        manifest_row = {
            "sample_id": f"{resolve_result.equipment_id}:{Path(annotation.filename).stem}:card{annotation.card_no:02d}:{duplicate_index:02d}",
            "equipment_id": resolve_result.equipment_id,
            "equipment_name": resolve_result.equipment_name,
            "accepted_equipment_name": strip_leading_equipment_id(annotation.accepted_equipment_name),
            "resolve_status": resolve_result.status,
            "image_path": str(image_path),
            "relative_image_path": str(relative_image_path).replace("\\", "/"),
            "source_filename": annotation.filename,
            "source_path": str(screenshot_path),
            "card_no": annotation.card_no,
            "rarity": row.get("filter_rarity", ""),
            "rarity_id": row.get("filter_rarity_id", ""),
            "visibility": row.get("visibility", ""),
            "icon_roi": json.dumps(list(roi), ensure_ascii=False),
            "width": width,
            "height": height,
            "suggested_equipment_id": row.get("suggested_equipment_id", ""),
            "suggested_equipment_name": row.get("suggested_equipment_name", ""),
            "source_icon_status": row.get("icon_status", ""),
            "source_icon_confidence": row.get("icon_confidence", ""),
            "accepted_fragment_owned": annotation.accepted_fragment_owned,
            "accepted_fragment_required": annotation.accepted_fragment_required,
        }
        manifest_rows.append(manifest_row)
        report_rows.append(_report_row(annotation, "ok", "已加入 reviewed 图库。", resolve_result))

    cumulative_rows = write_manifest(output_dir, manifest_rows)
    write_report(output_dir, report_rows)
    write_accepted_exp_snapshot(output_dir, cumulative_rows)
    return cumulative_rows, report_rows


def _report_row(
    annotation: ReviewedCardAnnotation,
    status: str,
    message: str,
    resolve_result: Optional[EquipmentNameResolveResult] = None,
) -> Dict[str, Any]:
    """构造名称解析/裁剪报告行。"""
    return {
        "filename": annotation.filename,
        "card_no": annotation.card_no,
        "accepted_equipment_name": annotation.accepted_equipment_name,
        "normalized_name": resolve_result.normalized_name if resolve_result else normalize_equipment_name(annotation.accepted_equipment_name),
        "resolved_equipment_id": resolve_result.equipment_id if resolve_result else "",
        "resolved_equipment_name": resolve_result.equipment_name if resolve_result else "",
        "status": status,
        "message": message,
    }


def write_manifest(output_dir: Path, rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """写出 reviewed 图库 manifest。"""
    fieldnames = [
        "sample_id",
        "equipment_id",
        "equipment_name",
        "accepted_equipment_name",
        "resolve_status",
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
        "suggested_equipment_id",
        "suggested_equipment_name",
        "source_icon_status",
        "source_icon_confidence",
        "accepted_fragment_owned",
        "accepted_fragment_required",
    ]
    merged_rows = merge_manifest_rows(load_existing_manifest(output_dir / MANIFEST_CSV_NAME), rows)
    with (output_dir / MANIFEST_CSV_NAME).open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in merged_rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    (output_dir / MANIFEST_JSON_NAME).write_text(json.dumps(merged_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged_rows


def load_existing_manifest(manifest_path: Path) -> List[Dict[str, Any]]:
    """
    读取已有 reviewed manifest，支持多轮人工样本累计。

    输入：
        reviewed_icon_gallery_manifest.csv。
    输出：
        已有 manifest 行；文件不存在时返回空列表。
    使用示例：
        rows = load_existing_manifest(output_dir / MANIFEST_CSV_NAME)
    """
    if not manifest_path.exists():
        return []
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as file:
        return [dict(row) for row in csv.DictReader(file)]


def merge_manifest_rows(
    existing_rows: Sequence[Mapping[str, Any]],
    new_rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """
    合并 reviewed manifest，避免新一轮覆盖旧训练样本。

    输入：
        existing_rows/new_rows。
    输出：
        按 source_filename + card_no 累计去重后的行。
    使用示例：
        merged = merge_manifest_rows(old_rows, current_rows)
    """
    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
    order: List[Tuple[str, str]] = []
    for row in [*existing_rows, *new_rows]:
        key = (str(row.get("source_filename", "") or ""), str(row.get("card_no", "") or ""))
        if not key[0] or not key[1]:
            key = (str(row.get("sample_id", "") or ""), str(row.get("image_path", "") or ""))
        if key not in merged:
            order.append(key)
        merged[key] = dict(row)
    return [merged[key] for key in order]


def write_report(output_dir: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """写出名称解析报告。"""
    fieldnames = [
        "filename",
        "card_no",
        "accepted_equipment_name",
        "normalized_name",
        "resolved_equipment_id",
        "resolved_equipment_name",
        "status",
        "message",
    ]
    with (output_dir / RESOLVE_REPORT_CSV_NAME).open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    (output_dir / RESOLVE_REPORT_JSON_NAME).write_text(json.dumps(list(rows), ensure_ascii=False, indent=2), encoding="utf-8")


def write_accepted_exp_snapshot(output_dir: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """
    把本轮人工 reviewed 名称保存成可读快照，防止预标注草稿被覆盖后丢失人工成果。
    输入：
        output_dir/manifest rows。
    输出：
        reviewed_icon_gallery_accepted_name_snapshot.txt。
    使用示例：
        write_accepted_exp_snapshot(out, manifest_rows)
    """
    lines: List[str] = [
        "# reviewed_icon_gallery accepted_equipment_name 快照",
        "# 该文件由 build_reviewed_icon_gallery.py 根据人工修正后的 review_only_exp 生成。",
        "# 后续若 v2_prelabel_review_only_exp 被覆盖，可用此文件追溯人工确认名称。",
        "",
    ]
    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("source_filename", "")), []).append(row)
    for filename in sorted(grouped):
        lines.append(f"[{filename}]")
        for row in sorted(grouped[filename], key=lambda item: int(item.get("card_no", 0) or 0)):
            card_no = int(row.get("card_no", 0) or 0)
            lines.append(f"card_{card_no:02d}.accepted_equipment_name:{row.get('accepted_equipment_name', '')}")
            lines.append(f"card_{card_no:02d}.resolved_equipment_id:{row.get('equipment_id', '')}")
            lines.append(f"card_{card_no:02d}.resolved_equipment_name:{row.get('equipment_name', '')}")
        lines.append("")
    (output_dir / "reviewed_icon_gallery_accepted_name_snapshot.txt").write_text("\n".join(lines), encoding="utf-8")


# ============================================================
# 🧰 第五部分：图片 IO 和小工具
# ============================================================

def read_image(image_path: Path) -> Any:
    """用 OpenCV 读取图片，兼容 Windows 中文路径。"""
    if cv2 is None or np is None:
        raise RuntimeError("OpenCV(cv2) 或 NumPy 不可用。")
    data = np.fromfile(str(image_path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None or getattr(image, "size", 0) == 0:
        raise ValueError(f"截图无法读取或已损坏: {image_path}")
    return image


def write_image(image_path: Path, image: Any) -> None:
    """用 OpenCV 写出 PNG，兼容 Windows 中文路径。"""
    if cv2 is None:
        raise RuntimeError("OpenCV(cv2) 不可用。")
    image_path.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise ValueError(f"图标编码失败: {image_path}")
    buffer.tofile(str(image_path))


def parse_roi(raw: Any) -> Optional[RoiRegion]:
    """解析 ROI 字段。"""
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        return tuple(int(value) for value in raw)  # type: ignore[return-value]
    if isinstance(raw, str):
        numbers = re.findall(r"-?\d+", raw)
        if len(numbers) >= 4:
            return tuple(int(value) for value in numbers[:4])  # type: ignore[return-value]
    return None


def validate_roi(image: Any, roi: Optional[RoiRegion]) -> RoiRegion:
    """检查 ROI 合法性。"""
    if roi is None:
        raise ValueError("缺少图标 ROI。")
    x, y, width, height = roi
    image_height, image_width = int(image.shape[0]), int(image.shape[1])
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError(f"图标 ROI 非法: {roi}")
    if x + width > image_width or y + height > image_height:
        raise ValueError(f"图标 ROI 越界: {roi} > {(image_width, image_height)}")
    return x, y, width, height


def safe_stem(value: str) -> str:
    """生成安全文件名片段。"""
    return re.sub(r"[^0-9A-Za-z_\-\.]+", "_", value).strip("_") or "reviewed_icon"


# ============================================================
# 🚀 第六部分：主入口
# ============================================================

def main() -> int:
    """
    脚本入口。
    输入：
        命令行参数。
    输出：
        退出码。
    使用示例：
        python ocr_training_lab/equipment_icon_matcher_v2/build_reviewed_icon_gallery.py
    """
    args = parse_args()
    if cv2 is None or np is None:
        print("OpenCV(cv2) 或 NumPy 不可用，无法构建 reviewed 图标图库。")
        return 2
    try:
        manifest_rows, report_rows = build_reviewed_gallery(
            review_exp=args.review_exp,
            prelabel_results=args.prelabel_results,
            output_dir=args.output_dir,
            overwrite=bool(args.overwrite),
            pattern_prefix=str(args.pattern_prefix),
        )
    except Exception as exc:
        print(f"构建 reviewed 图标图库失败: {exc}")
        return 1

    unresolved = [row for row in report_rows if row.get("status") not in {"ok"}]
    summary = {
        "review_exp": str(args.review_exp),
        "prelabel_results": str(args.prelabel_results),
        "output_dir": str(args.output_dir),
        "reviewed_samples": len(manifest_rows),
        "reviewed_equipment_ids": len({row["equipment_id"] for row in manifest_rows}),
        "report_rows": len(report_rows),
        "unresolved_or_skipped": len(unresolved),
        "manifest_csv": str(args.output_dir / MANIFEST_CSV_NAME),
        "resolve_report_csv": str(args.output_dir / RESOLVE_REPORT_CSV_NAME),
        "note": "reviewed 图库来自人工 accepted_equipment_name；未解析名称会列入 resolve_report，不会强行进图库。",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
