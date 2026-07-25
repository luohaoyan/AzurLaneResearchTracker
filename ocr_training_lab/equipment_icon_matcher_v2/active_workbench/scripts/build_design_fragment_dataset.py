#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        设计图碎片数据集构建器 (build_design_fragment_dataset) ║
║                                                              ║
║  【一句话解释】把历史设计图滚动截图复制、重命名并裁成训练样本。 ║
║  【类比理解】它像一个整理台：原图进来，自动切成卡片/图标/文字块。║
║  【数据流说明】img_input → source_img/crops/training_ready/manifest。║
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
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.recognition.design_fragment_detector import (  # noqa: E402
    DesignFragmentCardCandidate,
    DesignFragmentDetector,
)


# ============================================================
# 🧱 第二部分：常量与轻量数据对象
# ============================================================

RoiRegion = Tuple[int, int, int, int]

V2_ROOT = PROJECT_ROOT / "ocr_training_lab" / "equipment_icon_matcher_v2"
DEFAULT_SOURCE_DIR = V2_ROOT / "img_input"
DEFAULT_DATASET_DIR = V2_ROOT / "active_workbench" / "04_design_fragment_dataset"
DEFAULT_REVIEWED_GALLERY_CSV = V2_ROOT / "reviewed_icon_gallery" / "reviewed_icon_gallery_manifest.csv"
DEFAULT_ACCEPTED_GALLERY_CSV = V2_ROOT / "accepted_icon_gallery" / "accepted_icon_gallery_manifest.csv"
EQUIPMENT_LIBRARY_CSV = PROJECT_ROOT / "data" / "equipment_library.csv"

RARITY_TO_ID: Dict[str, int] = {
    "common": 1,
    "rare": 2,
    "elite": 3,
    "super_rare": 4,
    "ultra_rare": 5,
    "unknown": 0,
}
RARITY_ORDER: Dict[str, int] = {
    "common": 1,
    "rare": 2,
    "elite": 3,
    "super_rare": 4,
    "ultra_rare": 5,
    "unknown": 99,
}
RARITY_ALIASES: Dict[str, str] = {
    "white": "common",
    "blue": "rare",
    "purple": "elite",
    "gold": "super_rare",
    "rainbow": "ultra_rare",
    "ur": "ultra_rare",
}
SORT_TOKENS = {"buildable", "quantity", "number", "rarity"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
NAME_RATIO: Tuple[float, float, float, float] = (0.385, 0.040, 0.350, 0.235)
GENERATED_CHILDREN = ("source_img", "crops", "training_ready", "manifests")


@dataclass(frozen=True)
class SourceImageMeta:
    """单张设计图页截图的文件名元信息。"""

    filename: str
    rarity: str
    rarity_id: int
    sort_mode: str
    page_index: int


@dataclass(frozen=True)
class EquipmentItem:
    """装备库中的一件装备。"""

    equipment_id: str
    equipment_name: str
    rarity_id: int


@dataclass(frozen=True)
class LabelRecord:
    """单张卡片当前能找到的最好标签。"""

    equipment_name: str
    equipment_id: str
    label_source: str
    label_source_path: str
    label_trusted: bool
    priority: int
    modified_time_ns: int = 0
    fragment_owned: str = ""
    fragment_required: str = ""
    resolve_status: str = ""


@dataclass(frozen=True)
class MachineRecord:
    """旧识别流程给出的机器候选信息。"""

    suggested_equipment_name: str
    suggested_equipment_id: str
    icon_status: str
    icon_confidence: float
    icon_top_candidates: str
    name_ocr_text: str
    name_resolve_equipment_name: str
    name_resolve_score: float
    ocr_fragment_count: str
    ocr_required_count: str
    ocr_confidence: float
    csv_path: str
    modified_time_ns: int


# ============================================================
# 🧰 第三部分：路径、文件名和 CSV 工具
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。

    输入：
        终端参数。
    输出：
        argparse.Namespace。
    使用示例：
        python build_design_fragment_dataset.py --clean-generated
    """
    parser = argparse.ArgumentParser(description="整理设计图页历史截图并生成裁剪训练数据集。")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR, help="历史设计图截图输入目录。")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR, help="新数据集输出目录。")
    parser.add_argument("--reviewed-gallery-csv", type=Path, default=DEFAULT_REVIEWED_GALLERY_CSV, help="人工 reviewed 图库 manifest。")
    parser.add_argument("--accepted-gallery-csv", type=Path, default=DEFAULT_ACCEPTED_GALLERY_CSV, help="accepted 图库 manifest。")
    parser.add_argument("--equipment-library-csv", type=Path, default=EQUIPMENT_LIBRARY_CSV, help="只读装备库 CSV。")
    parser.add_argument("--pattern", default="*", help="输入图片匹配模式，默认读取所有图片后缀。")
    parser.add_argument("--clean-generated", action="store_true", help="先清理本数据集目录内的旧生成物。")
    return parser.parse_args()


def normalize_rarity(raw_value: str) -> str:
    """
    标准化稀有度文本。

    输入：
        文件名中的稀有度片段。
    输出：
        common/rare/elite/super_rare/ultra_rare/unknown。
    使用示例：
        normalize_rarity("UR") -> "ultra_rare"
    """
    text = str(raw_value or "").strip().lower().replace("-", "_")
    text = re.sub(r"_+", "_", text)
    return RARITY_ALIASES.get(text, text if text in RARITY_TO_ID else "unknown")


def parse_source_filename(image_path: Path) -> SourceImageMeta:
    """
    从历史截图文件名解析设计图筛选信息。

    输入：
        v2_super_rare_scroll_1.png 或 frag_super_rare_buildable_scroll_001.png。
    输出：
        SourceImageMeta。
    使用示例：
        meta = parse_source_filename(Path("v2_ultra_rare_scroll_2.png"))
    """
    stem = image_path.stem.lower()
    parts = stem.split("_")
    sort_mode = "buildable"
    page_index = 0
    rarity = "unknown"

    scroll_index = next((index for index, item in enumerate(parts) if item == "scroll"), -1)
    if scroll_index >= 1 and scroll_index + 1 < len(parts):
        try:
            page_index = int(parts[scroll_index + 1])
        except ValueError:
            page_index = 0
        rarity_parts = parts[1:scroll_index] if parts[0] in {"v2", "frag", "fragment"} else parts[:scroll_index]
        if rarity_parts and rarity_parts[-1] in SORT_TOKENS:
            sort_mode = "quantity" if rarity_parts[-1] == "number" else rarity_parts[-1]
            rarity_parts = rarity_parts[:-1]
        if parts[0] == "v2" and rarity_parts and rarity_parts[0] == "test":
            rarity_parts = rarity_parts[1:]
        rarity = normalize_rarity("_".join(rarity_parts))

    return SourceImageMeta(
        filename=image_path.name,
        rarity=rarity,
        rarity_id=RARITY_TO_ID.get(rarity, 0),
        sort_mode=sort_mode,
        page_index=page_index,
    )


def normalized_source_name(meta: SourceImageMeta, suffix: str) -> str:
    """
    生成统一的新原图文件名。

    输入：
        SourceImageMeta 和原后缀。
    输出：
        fragment_design_buildable_super_rare_scroll_001.png 这类稳定名称。
    使用示例：
        name = normalized_source_name(meta, ".png")
    """
    index = max(0, int(meta.page_index))
    return f"fragment_design_{meta.sort_mode}_{meta.rarity}_scroll_{index:03d}{suffix.lower()}"


def collect_source_images(source_dir: Path, pattern: str = "*") -> List[Tuple[Path, SourceImageMeta]]:
    """
    收集历史设计图截图并稳定排序。

    输入：
        source_dir/pattern。
    输出：
        [(image_path, meta)]。
    使用示例：
        images = collect_source_images(Path("img_input"))
    """
    if not source_dir.exists():
        return []
    images: List[Tuple[Path, SourceImageMeta]] = []
    for image_path in source_dir.glob(pattern):
        if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        images.append((image_path, parse_source_filename(image_path)))
    images.sort(key=lambda item: (RARITY_ORDER.get(item[1].rarity, 99), item[1].page_index, item[0].name))
    return images


def sanitize_filename(raw_value: str, fallback: str = "unknown") -> str:
    """
    把装备名转换成 Windows 安全文件夹名。

    输入：
        可能包含 / : * ? 等字符的装备名。
    输出：
        可作为文件/文件夹名的短字符串。
    使用示例：
        sanitize_filename("试作型三联装406mm/45主炮Mk7#T0")
    """
    text = str(raw_value or "").strip() or fallback
    text = re.sub(r'[<>:"/\\|?*\r\n\t]+', "_", text)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"_+", "_", text).strip("._ ")
    return (text or fallback)[:120]


def normalize_equipment_name(raw_value: str) -> str:
    """
    标准化装备名，用于“名字找 ID”的宽松匹配。

    输入：
        人工标注或 OCR/CSV 中的装备名。
    输出：
        去掉空格和常见全半角差异后的字符串。
    使用示例：
        normalize_equipment_name("B-38 三联装152mm主炮MK-5#T3")
    """
    text = str(raw_value or "").strip()
    text = text.replace("＃", "#").replace("（", "(").replace("）", ")")
    text = text.replace("“", '"').replace("”", '"').replace("Ⅱ", "II")
    return re.sub(r"\s+", "", text)


def read_csv_dicts(path: Path) -> List[Dict[str, str]]:
    """
    读取 CSV 为字典列表；不存在时返回空列表。

    输入：
        CSV 路径。
    输出：
        List[Dict[str, str]]。
    使用示例：
        rows = read_csv_dicts(Path("manifest.csv"))
    """
    if not path.exists() or not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [dict(row) for row in csv.DictReader(file)]


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    """
    写出 UTF-8-SIG CSV，方便 Excel 直接打开。

    输入：
        输出路径、行、字段顺序。
    输出：
        一个 CSV 文件。
    使用示例：
        write_csv(path, rows, ("filename", "card_no"))
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def roi_to_json(roi: RoiRegion) -> str:
    """把 ROI 元组转成紧凑 JSON 文本，CSV 中更容易筛选。"""
    return json.dumps([int(item) for item in roi], ensure_ascii=False)


def relative_path(path: Path) -> str:
    """尽量把绝对路径压成项目相对路径，manifest 更短更好读。"""
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
    except Exception:
        return str(path)


# ============================================================
# 🏷️ 第四部分：标签融合与装备库解析
# ============================================================

def load_equipment_library(path: Path = EQUIPMENT_LIBRARY_CSV) -> Tuple[Dict[str, EquipmentItem], Dict[str, str]]:
    """
    读取装备库，只用于“装备名 → 当前 equipment_id”的解析。

    输入：
        data/equipment_library.csv。
    输出：
        (id_map, normalized_name_to_id)。
    使用示例：
        catalog, name_to_id = load_equipment_library()
    """
    catalog: Dict[str, EquipmentItem] = {}
    normalized_name_to_id: Dict[str, str] = {}
    duplicates: Dict[str, int] = {}
    for row in read_csv_dicts(path):
        equipment_id = str(row.get("equipment_id", "") or "").strip()
        equipment_name = str(row.get("name", "") or "").strip()
        if not equipment_id or not equipment_name:
            continue
        try:
            rarity_id = int(row.get("rarity_id", 0) or 0)
        except ValueError:
            rarity_id = 0
        catalog[equipment_id] = EquipmentItem(equipment_id, equipment_name, rarity_id)
        normalized = normalize_equipment_name(equipment_name)
        if normalized in normalized_name_to_id and normalized_name_to_id[normalized] != equipment_id:
            duplicates[normalized] = duplicates.get(normalized, 1) + 1
        else:
            normalized_name_to_id[normalized] = equipment_id
    for normalized in duplicates:
        normalized_name_to_id.pop(normalized, None)
    return catalog, normalized_name_to_id


def resolve_equipment_id(
    equipment_name: str,
    explicit_equipment_id: str,
    catalog: Mapping[str, EquipmentItem],
    name_to_id: Mapping[str, str],
) -> Tuple[str, str]:
    """
    按用户要求优先用装备名解析当前 ID。

    输入：
        装备名、旧 ID、装备库。
    输出：
        (resolved_id, resolve_status)。
    使用示例：
        equipment_id, status = resolve_equipment_id("对空雷达#T3", "", catalog, name_to_id)
    """
    normalized = normalize_equipment_name(equipment_name)
    if not normalized:
        return "", "empty_name"
    resolved_id = name_to_id.get(normalized, "")
    if resolved_id:
        return resolved_id, "name_exact_or_normalized"
    if explicit_equipment_id and explicit_equipment_id in catalog:
        item = catalog[explicit_equipment_id]
        if normalize_equipment_name(item.equipment_name) == normalized:
            return explicit_equipment_id, "explicit_id_name_verified"
    return explicit_equipment_id.strip(), "unresolved_name"


def put_label(label_map: Dict[Tuple[str, int], LabelRecord], key: Tuple[str, int], record: LabelRecord) -> None:
    """
    按优先级写入标签，避免低可信机器标注覆盖人工标注。

    输入：
        标签字典、(filename, card_no)、新标签。
    输出：
        原地更新 label_map。
    使用示例：
        put_label(labels, ("v2_rare_scroll_1.png", 3), record)
    """
    old_record = label_map.get(key)
    if old_record is None:
        label_map[key] = record
        return
    if record.priority > old_record.priority:
        label_map[key] = record
        return
    if record.priority == old_record.priority and record.modified_time_ns >= old_record.modified_time_ns:
        label_map[key] = record


def load_gallery_labels(
    gallery_csv_path: Path,
    catalog: Mapping[str, EquipmentItem],
    name_to_id: Mapping[str, str],
    source_name: str,
    priority: int,
) -> Dict[Tuple[str, int], LabelRecord]:
    """
    从 reviewed/accepted 图库 manifest 读取已确认标签。

    输入：
        manifest CSV。
    输出：
        {(source_filename, card_no): LabelRecord}。
    使用示例：
        labels = load_gallery_labels(reviewed_csv, catalog, name_to_id, "reviewed_gallery", 100)
    """
    labels: Dict[Tuple[str, int], LabelRecord] = {}
    modified_time_ns = gallery_csv_path.stat().st_mtime_ns if gallery_csv_path.exists() else 0
    for row in read_csv_dicts(gallery_csv_path):
        filename = str(row.get("source_filename", "") or Path(str(row.get("source_path", "") or "")).name).strip()
        if not filename:
            continue
        try:
            card_no = int(str(row.get("card_no", "0") or "0"))
        except ValueError:
            continue
        equipment_name = str(row.get("accepted_equipment_name", "") or row.get("equipment_name", "") or "").strip()
        if not equipment_name:
            continue
        explicit_id = str(row.get("equipment_id", "") or "").strip()
        equipment_id, resolve_status = resolve_equipment_id(equipment_name, explicit_id, catalog, name_to_id)
        put_label(
            labels,
            (filename, card_no),
            LabelRecord(
                equipment_name=equipment_name,
                equipment_id=equipment_id,
                label_source=source_name,
                label_source_path=str(gallery_csv_path),
                label_trusted=True,
                priority=priority,
                modified_time_ns=modified_time_ns,
                fragment_owned=str(row.get("accepted_fragment_owned", "") or "").strip(),
                fragment_required=str(row.get("accepted_fragment_required", "") or "").strip(),
                resolve_status=resolve_status,
            ),
        )
    return labels


def discover_exp_label_files(project_root: Path = PROJECT_ROOT) -> List[Path]:
    """
    查找人工复核 exp 文件；只读，不修改。

    输入：
        项目根目录。
    输出：
        按修改时间排序的 exp 文件路径。
    使用示例：
        files = discover_exp_label_files(PROJECT_ROOT)
    """
    v2_root = project_root / "ocr_training_lab" / "equipment_icon_matcher_v2"
    roots = (
        v2_root / "review_iterations",
        v2_root / "collection_next" / "img_out",
        project_root / "ocr_training_lab" / "equipment_attribute_scan",
    )
    files: List[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*exp*"):
            if not path.is_file():
                continue
            lower_parts = {part.lower() for part in path.parts}
            if "backups" in lower_parts or "__pycache__" in lower_parts:
                continue
            # 只收实际复核入口，避免把说明模板或纯机器草稿当人工标签。
            lower_name = path.name.lower()
            in_to_label = any(part.lower() == "to_label" for part in path.parts)
            is_review_only = lower_name.startswith("v2_prelabel_review_only_exp")
            is_recovered = "recovered" in lower_name
            if in_to_label or is_review_only or is_recovered:
                files.append(path)
    files.sort(key=lambda item: item.stat().st_mtime_ns)
    return files


def parse_exp_label_file(
    path: Path,
    catalog: Optional[Mapping[str, EquipmentItem]] = None,
    name_to_id: Optional[Mapping[str, str]] = None,
) -> Dict[Tuple[str, int], LabelRecord]:
    """
    解析人工复核 exp 文件中的 accepted_equipment_name。

    输入：
        exp 文本路径。
    输出：
        {(filename, card_no): LabelRecord}。
    使用示例：
        labels = parse_exp_label_file(Path("v2_review_todo_exp.txt"))
    """
    catalog = catalog or {}
    name_to_id = name_to_id or {}
    labels: Dict[Tuple[str, int], LabelRecord] = {}
    if not path.exists() or not path.is_file():
        return labels

    current_filename = ""
    pending_values: Dict[int, Dict[str, str]] = {}
    modified_time_ns = path.stat().st_mtime_ns
    header_pattern = re.compile(r"^\[(?P<filename>[^\]]+)\]\s*$")
    accepted_pattern = re.compile(r"^card_(?P<card>\d+)\.accepted_equipment_name\s*:\s*(?P<value>.*)$")
    current_id_pattern = re.compile(r"^card_(?P<card>\d+)\.current_resolved_equipment_id\s*:\s*(?P<value>.*)$")
    owned_pattern = re.compile(r"^card_(?P<card>\d+)\.accepted_fragment_owned\s*:\s*(?P<value>.*)$")
    required_pattern = re.compile(r"^card_(?P<card>\d+)\.accepted_fragment_required\s*:\s*(?P<value>.*)$")

    def flush_pending() -> None:
        for card_no, values in pending_values.items():
            equipment_name = values.get("equipment_name", "").strip()
            if not current_filename or not equipment_name:
                continue
            explicit_id = values.get("equipment_id", "")
            equipment_id, resolve_status = resolve_equipment_id(equipment_name, explicit_id, catalog, name_to_id)
            put_label(
                labels,
                (current_filename, card_no),
                LabelRecord(
                    equipment_name=equipment_name,
                    equipment_id=equipment_id,
                    label_source="user_exp_label",
                    label_source_path=str(path),
                    label_trusted=True,
                    priority=90,
                    modified_time_ns=modified_time_ns,
                    fragment_owned=values.get("fragment_owned", ""),
                    fragment_required=values.get("fragment_required", ""),
                    resolve_status=resolve_status,
                ),
            )

    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        header_match = header_pattern.match(line)
        if header_match:
            flush_pending()
            current_filename = header_match.group("filename").strip()
            pending_values = {}
            continue
        accepted_match = accepted_pattern.match(line)
        if accepted_match:
            card_no = int(accepted_match.group("card"))
            pending_values.setdefault(card_no, {})["equipment_name"] = accepted_match.group("value").strip()
            continue
        current_id_match = current_id_pattern.match(line)
        if current_id_match:
            card_no = int(current_id_match.group("card"))
            pending_values.setdefault(card_no, {})["equipment_id"] = current_id_match.group("value").strip()
            continue
        owned_match = owned_pattern.match(line)
        if owned_match:
            card_no = int(owned_match.group("card"))
            pending_values.setdefault(card_no, {})["fragment_owned"] = owned_match.group("value").strip()
            continue
        required_match = required_pattern.match(line)
        if required_match:
            card_no = int(required_match.group("card"))
            pending_values.setdefault(card_no, {})["fragment_required"] = required_match.group("value").strip()
            continue
    flush_pending()
    return labels


def load_exp_labels(
    catalog: Mapping[str, EquipmentItem],
    name_to_id: Mapping[str, str],
    exp_files: Optional[Sequence[Path]] = None,
) -> Dict[Tuple[str, int], LabelRecord]:
    """
    汇总多轮人工 exp 标签，新版本自动覆盖旧版本。

    输入：
        装备库和可选 exp 文件列表。
    输出：
        {(filename, card_no): LabelRecord}。
    使用示例：
        labels = load_exp_labels(catalog, name_to_id)
    """
    labels: Dict[Tuple[str, int], LabelRecord] = {}
    for path in exp_files or discover_exp_label_files(PROJECT_ROOT):
        for key, record in parse_exp_label_file(path, catalog, name_to_id).items():
            put_label(labels, key, record)
    return labels


def boolish(raw_value: Any) -> bool:
    """把 CSV 里的 True/False 字符串转成 bool。"""
    return str(raw_value or "").strip().lower() in {"1", "true", "yes", "y"}


def floatish(raw_value: Any, default: float = 0.0) -> float:
    """把 CSV 文本安全转成 float。"""
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return default


def load_machine_records(v2_root: Path = V2_ROOT) -> Dict[Tuple[str, int], MachineRecord]:
    """
    汇总历史 v2_prelabel_results.csv 中的机器候选。

    输入：
        equipment_icon_matcher_v2 根目录。
    输出：
        {(filename, card_no): MachineRecord}，同卡保留最新结果。
    使用示例：
        machine = load_machine_records()
    """
    records: Dict[Tuple[str, int], MachineRecord] = {}
    csv_paths = sorted(v2_root.rglob("v2_prelabel_results.csv"), key=lambda item: item.stat().st_mtime_ns)
    for csv_path in csv_paths:
        if "04_design_fragment_dataset" in {part for part in csv_path.parts}:
            continue
        modified_time_ns = csv_path.stat().st_mtime_ns
        for row in read_csv_dicts(csv_path):
            filename = str(row.get("filename", "") or "").strip()
            if not filename:
                continue
            try:
                card_no = int(str(row.get("card_no", "0") or "0"))
            except ValueError:
                continue
            suggested_name = str(row.get("suggested_equipment_name", "") or row.get("accepted_equipment_name", "") or "").strip()
            suggested_id = str(row.get("suggested_equipment_id", "") or row.get("current_resolved_equipment_id", "") or "").strip()
            records[(filename, card_no)] = MachineRecord(
                suggested_equipment_name=suggested_name,
                suggested_equipment_id=suggested_id,
                icon_status=str(row.get("icon_status", "") or "").strip(),
                icon_confidence=floatish(row.get("icon_confidence", 0.0)),
                icon_top_candidates=str(row.get("icon_top_candidates", "") or "").strip(),
                name_ocr_text=str(row.get("name_ocr_text", "") or "").strip(),
                name_resolve_equipment_name=str(row.get("name_resolve_equipment_name", "") or "").strip(),
                name_resolve_score=floatish(row.get("name_resolve_score", 0.0)),
                ocr_fragment_count=str(row.get("ocr_fragment_count", "") or row.get("accepted_fragment_owned", "") or "").strip(),
                ocr_required_count=str(row.get("ocr_required_count", "") or row.get("accepted_fragment_required", "") or "").strip(),
                ocr_confidence=floatish(row.get("ocr_confidence", 0.0)),
                csv_path=str(csv_path),
                modified_time_ns=modified_time_ns,
            )
    return records


def choose_best_label(
    filename: str,
    card_no: int,
    trusted_labels: Mapping[Tuple[str, int], LabelRecord],
    machine_records: Mapping[Tuple[str, int], MachineRecord],
    catalog: Mapping[str, EquipmentItem],
    name_to_id: Mapping[str, str],
) -> LabelRecord:
    """
    给一张卡片选择最终标签来源。

    输入：
        文件名、卡号、人工标签集合、机器结果集合。
    输出：
        LabelRecord；若只有机器建议则 label_trusted=False。
    使用示例：
        label = choose_best_label("v2_rare_scroll_1.png", 3, labels, machine, catalog, name_to_id)
    """
    key = (filename, card_no)
    trusted = trusted_labels.get(key)
    if trusted is not None:
        return trusted

    machine = machine_records.get(key)
    if machine is not None and machine.suggested_equipment_name:
        equipment_id, resolve_status = resolve_equipment_id(
            machine.suggested_equipment_name,
            machine.suggested_equipment_id,
            catalog,
            name_to_id,
        )
        return LabelRecord(
            equipment_name=machine.suggested_equipment_name,
            equipment_id=equipment_id,
            label_source="machine_suggested",
            label_source_path=machine.csv_path,
            label_trusted=False,
            priority=30,
            modified_time_ns=machine.modified_time_ns,
            fragment_owned=machine.ocr_fragment_count,
            fragment_required=machine.ocr_required_count,
            resolve_status=resolve_status,
        )

    return LabelRecord(
        equipment_name="",
        equipment_id="",
        label_source="unlabeled",
        label_source_path="",
        label_trusted=False,
        priority=0,
        resolve_status="no_label",
    )


def build_trusted_label_map(
    catalog: Mapping[str, EquipmentItem],
    name_to_id: Mapping[str, str],
    reviewed_gallery_csv: Path,
    accepted_gallery_csv: Path,
) -> Dict[Tuple[str, int], LabelRecord]:
    """
    按“人工图库 > accepted 图库 > 人工 exp”的顺序汇总可信标签。

    输入：
        装备库和 manifest 路径。
    输出：
        {(filename, card_no): LabelRecord}。
    使用示例：
        labels = build_trusted_label_map(catalog, name_to_id, reviewed_csv, accepted_csv)
    """
    labels: Dict[Tuple[str, int], LabelRecord] = {}
    for source in (
        load_exp_labels(catalog, name_to_id),
        load_gallery_labels(accepted_gallery_csv, catalog, name_to_id, "accepted_gallery", 95),
        load_gallery_labels(reviewed_gallery_csv, catalog, name_to_id, "reviewed_gallery", 100),
    ):
        for key, record in source.items():
            put_label(labels, key, record)
    return labels


# ============================================================
# ✂️ 第五部分：图像裁剪与数据集生成
# ============================================================

def clean_generated_children(dataset_dir: Path) -> None:
    """
    清理本数据集目录内的旧生成物，防止输出混杂。

    输入：
        dataset_dir。
    输出：
        删除 source_img/crops/training_ready/manifests 这些固定子目录。
    使用示例：
        clean_generated_children(DEFAULT_DATASET_DIR)
    """
    dataset_root = dataset_dir.resolve()
    for child_name in GENERATED_CHILDREN:
        child = (dataset_dir / child_name).resolve()
        if not str(child).lower().startswith(str(dataset_root).lower()):
            raise RuntimeError(f"拒绝清理数据集目录外路径: {child}")
        if child.exists():
            shutil.rmtree(child)


def ensure_dataset_layout(dataset_dir: Path) -> Dict[str, Path]:
    """
    创建设计图数据集目录结构。

    输入：
        dataset_dir。
    输出：
        常用子目录字典。
    使用示例：
        dirs = ensure_dataset_layout(DEFAULT_DATASET_DIR)
    """
    dirs = {
        "source_img": dataset_dir / "source_img",
        "manifests": dataset_dir / "manifests",
        "logs": dataset_dir / "logs",
        "full_card": dataset_dir / "crops" / "full" / "card",
        "full_icon": dataset_dir / "crops" / "full" / "icon",
        "full_name": dataset_dir / "crops" / "full" / "name",
        "full_quantity": dataset_dir / "crops" / "full" / "quantity",
        "full_attribute": dataset_dir / "crops" / "full" / "attribute",
        "partial_card": dataset_dir / "crops" / "partial" / "card",
        "partial_icon": dataset_dir / "crops" / "partial" / "icon",
        "partial_name": dataset_dir / "crops" / "partial" / "name",
        "partial_quantity": dataset_dir / "crops" / "partial" / "quantity",
        "partial_attribute": dataset_dir / "crops" / "partial" / "attribute",
        "ready_icon": dataset_dir / "training_ready" / "icon_by_equipment_name",
        "ready_card": dataset_dir / "training_ready" / "card_by_equipment_name",
        "ready_name": dataset_dir / "training_ready" / "name_roi_by_equipment_name",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def crop_roi(image: Any, roi: RoiRegion) -> Any:
    """
    从 OpenCV 图像中裁剪 ROI。

    输入：
        BGR 图像和 [x, y, w, h]。
    输出：
        裁剪后的图像副本。
    使用示例：
        icon = crop_roi(image, candidate.icon_roi)
    """
    x, y, width, height = roi
    return image[int(y): int(y + height), int(x): int(x + width)].copy()


def write_image(detector: DesignFragmentDetector, path: Path, image: Any) -> str:
    """
    写出裁剪图，并返回项目相对路径。

    输入：
        detector、输出路径、图像。
    输出：
        项目相对路径字符串。
    使用示例：
        rel = write_image(detector, path, crop)
    """
    detector.write_image(path, image)
    return relative_path(path)


def name_roi_for_candidate(candidate: DesignFragmentCardCandidate) -> RoiRegion:
    """根据卡片几何计算装备名称 ROI。"""
    x, y, width, height = candidate.bbox
    rel_x, rel_y, rel_width, rel_height = NAME_RATIO
    return (
        x + int(round(width * rel_x)),
        y + int(round(height * rel_y)),
        max(1, int(round(width * rel_width))),
        max(1, int(round(height * rel_height))),
    )


def attribute_roi_for_candidate(candidate: DesignFragmentCardCandidate) -> RoiRegion:
    """根据卡片几何计算右侧“伤害/射速”等属性文字 ROI。"""
    x, y, width, height = candidate.bbox
    icon_x, _icon_y, icon_width, _icon_height = candidate.icon_roi
    quantity_x, _quantity_y, _quantity_width, _quantity_height = candidate.quantity_roi
    left = icon_x + icon_width + 14
    top = y + int(round(height * 0.30))
    right = max(left + 1, quantity_x - 8)
    bottom = y + height - 8
    return (left, top, max(1, right - left), max(1, bottom - top))


def copy_to_training_ready(source_crop: Path, target_root: Path, equipment_name: str) -> str:
    """
    把可信全卡样本复制到按装备名分组的 training_ready 目录。

    输入：
        裁剪图路径、目标根目录、装备名。
    输出：
        复制后项目相对路径。
    使用示例：
        path = copy_to_training_ready(icon_path, ready_icon_dir, "对空雷达#T3")
    """
    class_dir = target_root / sanitize_filename(equipment_name)
    class_dir.mkdir(parents=True, exist_ok=True)
    target = class_dir / source_crop.name
    shutil.copy2(source_crop, target)
    return relative_path(target)


def process_one_image(
    source_path: Path,
    meta: SourceImageMeta,
    dirs: Mapping[str, Path],
    detector: DesignFragmentDetector,
    trusted_labels: Mapping[Tuple[str, int], LabelRecord],
    machine_records: Mapping[Tuple[str, int], MachineRecord],
    catalog: Mapping[str, EquipmentItem],
    name_to_id: Mapping[str, str],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    复制、重命名并裁剪单张设计图截图。

    输入：
        原截图、元信息、输出目录、检测器和标签集合。
    输出：
        (manifest_rows, image_summary)。
    使用示例：
        rows, info = process_one_image(path, meta, dirs, detector, labels, machine, catalog, name_to_id)
    """
    normalized_name = normalized_source_name(meta, source_path.suffix)
    normalized_path = dirs["source_img"] / normalized_name
    shutil.copy2(source_path, normalized_path)

    detection = detector.detect(source_path, image_mode="viewport_full")
    image_summary: Dict[str, Any] = {
        "source_filename": source_path.name,
        "normalized_filename": normalized_name,
        "status": detection.status,
        "message": detection.message,
        "image_size": list(detection.image_size),
        "cards": 0,
        "full_cards": 0,
        "partial_cards": 0,
    }
    if not detection.success:
        return [], image_summary

    image = detector.load_image(source_path)
    rows: List[Dict[str, Any]] = []
    candidates = sorted(detection.candidates, key=lambda item: (item.bbox[1], item.bbox[0]))
    for card_no, candidate in enumerate(candidates, start=1):
        visibility_group = "full" if candidate.visibility == "full" else "partial"
        name_roi = name_roi_for_candidate(candidate)
        attribute_roi = attribute_roi_for_candidate(candidate)
        label = choose_best_label(source_path.name, card_no, trusted_labels, machine_records, catalog, name_to_id)
        machine = machine_records.get((source_path.name, card_no))
        stem = f"{Path(normalized_name).stem}_card{card_no:02d}_{visibility_group}"

        card_path = dirs[f"{visibility_group}_card"] / f"{stem}_card.png"
        icon_path = dirs[f"{visibility_group}_icon"] / f"{stem}_icon.png"
        name_path = dirs[f"{visibility_group}_name"] / f"{stem}_name.png"
        quantity_path = dirs[f"{visibility_group}_quantity"] / f"{stem}_quantity.png"
        attribute_path = dirs[f"{visibility_group}_attribute"] / f"{stem}_attribute.png"

        card_rel = write_image(detector, card_path, crop_roi(image, candidate.bbox))
        icon_rel = write_image(detector, icon_path, crop_roi(image, candidate.icon_roi))
        name_rel = write_image(detector, name_path, crop_roi(image, name_roi))
        quantity_rel = write_image(detector, quantity_path, crop_roi(image, candidate.quantity_roi))
        attribute_rel = write_image(detector, attribute_path, crop_roi(image, attribute_roi))

        training_icon_rel = ""
        training_card_rel = ""
        training_name_rel = ""
        selected_for_training = bool(candidate.visibility == "full" and label.label_trusted and label.equipment_name)
        if selected_for_training:
            training_icon_rel = copy_to_training_ready(icon_path, dirs["ready_icon"], label.equipment_name)
            training_card_rel = copy_to_training_ready(card_path, dirs["ready_card"], label.equipment_name)
            training_name_rel = copy_to_training_ready(name_path, dirs["ready_name"], label.equipment_name)

        if candidate.visibility == "full":
            image_summary["full_cards"] += 1
        else:
            image_summary["partial_cards"] += 1
        image_summary["cards"] += 1

        rows.append(
            {
                "source_filename": source_path.name,
                "normalized_filename": normalized_name,
                "source_path": relative_path(source_path),
                "normalized_source_path": relative_path(normalized_path),
                "filter_rarity": meta.rarity,
                "filter_rarity_id": meta.rarity_id,
                "sort_mode": meta.sort_mode,
                "page_index": meta.page_index,
                "card_no": card_no,
                "row_index": candidate.row_index,
                "column_index": candidate.column_index,
                "visibility": candidate.visibility,
                "selected_for_training": selected_for_training,
                "label_source": label.label_source,
                "label_trusted": label.label_trusted,
                "accepted_equipment_name": label.equipment_name,
                "current_resolved_equipment_id": label.equipment_id,
                "label_resolve_status": label.resolve_status,
                "fragment_owned": label.fragment_owned,
                "fragment_required": label.fragment_required,
                "machine_suggested_equipment_name": machine.suggested_equipment_name if machine else "",
                "machine_suggested_equipment_id": machine.suggested_equipment_id if machine else "",
                "machine_icon_status": machine.icon_status if machine else "",
                "machine_icon_confidence": machine.icon_confidence if machine else "",
                "machine_icon_top_candidates": machine.icon_top_candidates if machine else "",
                "machine_name_ocr_text": machine.name_ocr_text if machine else "",
                "machine_name_resolve_equipment_name": machine.name_resolve_equipment_name if machine else "",
                "machine_name_resolve_score": machine.name_resolve_score if machine else "",
                "label_source_path": relative_path(Path(label.label_source_path)) if label.label_source_path else "",
                "machine_source_path": relative_path(Path(machine.csv_path)) if machine else "",
                "bbox": roi_to_json(candidate.bbox),
                "raw_bbox": roi_to_json(candidate.raw_bbox),
                "icon_roi": roi_to_json(candidate.icon_roi),
                "name_roi": roi_to_json(name_roi),
                "quantity_roi": roi_to_json(candidate.quantity_roi),
                "attribute_roi": roi_to_json(attribute_roi),
                "card_crop_path": card_rel,
                "icon_crop_path": icon_rel,
                "name_crop_path": name_rel,
                "quantity_crop_path": quantity_rel,
                "attribute_crop_path": attribute_rel,
                "training_icon_path": training_icon_rel,
                "training_card_path": training_card_rel,
                "training_name_path": training_name_rel,
            }
        )
    return rows, image_summary


def build_summary(rows: Sequence[Mapping[str, Any]], image_summaries: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """
    生成数据集摘要。

    输入：
        manifest rows 和每图摘要。
    输出：
        JSON 可序列化摘要。
    使用示例：
        summary = build_summary(rows, image_summaries)
    """
    by_rarity: Dict[str, Dict[str, int]] = {}
    by_label_source: Dict[str, int] = {}
    unresolved_names: List[Dict[str, Any]] = []
    unique_trusted_names = set()
    for row in rows:
        rarity = str(row.get("filter_rarity", "unknown") or "unknown")
        bucket = by_rarity.setdefault(rarity, {"cards": 0, "full": 0, "partial": 0, "training_ready": 0})
        bucket["cards"] += 1
        if row.get("visibility") == "full":
            bucket["full"] += 1
        else:
            bucket["partial"] += 1
        if row.get("selected_for_training") is True:
            bucket["training_ready"] += 1
        label_source = str(row.get("label_source", "unlabeled") or "unlabeled")
        by_label_source[label_source] = by_label_source.get(label_source, 0) + 1
        if row.get("selected_for_training") is True and row.get("accepted_equipment_name"):
            unique_trusted_names.add(str(row.get("accepted_equipment_name")))
        if row.get("label_resolve_status") == "unresolved_name":
            unresolved_names.append(
                {
                    "source_filename": row.get("source_filename", ""),
                    "card_no": row.get("card_no", ""),
                    "accepted_equipment_name": row.get("accepted_equipment_name", ""),
                }
            )
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_images": len(image_summaries),
        "source_images_success": sum(1 for item in image_summaries if item.get("status") == "success"),
        "cards": len(rows),
        "full_cards": sum(1 for row in rows if row.get("visibility") == "full"),
        "partial_cards": sum(1 for row in rows if row.get("visibility") != "full"),
        "training_ready_samples": sum(1 for row in rows if row.get("selected_for_training") is True),
        "unique_trusted_equipment_names": len(unique_trusted_names),
        "by_rarity": by_rarity,
        "by_label_source": by_label_source,
        "unresolved_label_names": unresolved_names[:100],
        "note": "training_ready 只复制 visibility=full 且 label_trusted=true 的样本；machine_suggested 仅供参考，不作为训练真值。",
    }


def write_human_readme(dataset_dir: Path, summary: Mapping[str, Any]) -> None:
    """
    写出当前数据集使用说明。

    输入：
        dataset_dir 和 summary。
    输出：
        README.txt。
    使用示例：
        write_human_readme(dataset_dir, summary)
    """
    text = f"""设计图碎片数据集裁剪区
========================

这个目录专门用于把旧的设计图滚动截图整理成后续训练可用的数据集。
原始历史截图不会被移动或删除；脚本只会复制到 source_img。

一、双击运行
------------

直接双击本目录下：

RUN_BUILD_DATASET.bat

脚本会读取：

G:\\ALLPeoject\\PythonProject\\AzurLaneResearchTracker-OCR\\ocr_training_lab\\equipment_icon_matcher_v2\\img_input

然后输出到本目录。

二、你主要看哪里
----------------

1. manifests\\design_fragment_dataset_summary.json
   看本轮总数和每个稀有度数量。

2. manifests\\design_fragment_dataset_manifest.csv
   每张卡片、每个裁剪 ROI、标签来源都在这里。

3. manifests\\design_fragment_training_ready_manifest.csv
   只包含已经进入 training_ready 的可信训练样本。

4. manifests\\design_fragment_machine_only_full_cards.csv
   只包含“完整卡片但目前只有机器建议”的样本。
   后续如果真要人工补，只优先看这个小清单。

5. training_ready\\icon_by_equipment_name
   这里是后续训练图标识别最应该优先使用的样本。
   只有“完整卡片 + 可信人工标签”的样本会进入这里。

6. crops\\full
   所有完整卡片的裁剪图，包含 card/icon/name/quantity/attribute。

7. crops\\partial
   顶部或底部被裁掉的卡片。默认不进入训练，只保留供排查。

三、标签来源说明
----------------

reviewed_gallery:
  你之前人工确认并进入 reviewed_icon_gallery 的标签，可信。

accepted_gallery:
  早期 accepted 图库标签，可信。

user_exp_label:
  从多轮人工复核 exp 文件中读取到的 accepted_equipment_name，可信。

machine_suggested:
  历史识别流程给出的机器建议，只供参考，不进入 training_ready。

unlabeled:
  没有找到标签。

四、本轮结果
------------

source_images: {summary.get("source_images", 0)}
cards: {summary.get("cards", 0)}
full_cards: {summary.get("full_cards", 0)}
partial_cards: {summary.get("partial_cards", 0)}
training_ready_samples: {summary.get("training_ready_samples", 0)}
unique_trusted_equipment_names: {summary.get("unique_trusted_equipment_names", 0)}

五、下一步
----------

你现在不用重新逐卡标注这一批旧截图。
后续如果要补强某些装备，我会只给你列“缺样本或高风险装备清单”，不要再把全部卡片扔给你重填。
"""
    (dataset_dir / "README.txt").write_text(text, encoding="utf-8")


def build_dataset(
    source_dir: Path = DEFAULT_SOURCE_DIR,
    dataset_dir: Path = DEFAULT_DATASET_DIR,
    reviewed_gallery_csv: Path = DEFAULT_REVIEWED_GALLERY_CSV,
    accepted_gallery_csv: Path = DEFAULT_ACCEPTED_GALLERY_CSV,
    equipment_library_csv: Path = EQUIPMENT_LIBRARY_CSV,
    pattern: str = "*",
    clean_generated: bool = False,
) -> Dict[str, Any]:
    """
    构建设计图碎片裁剪数据集。

    输入：
        历史截图目录、数据集目录、标签/装备库路径。
    输出：
        summary 字典。
    使用示例：
        summary = build_dataset(clean_generated=True)
    """
    if clean_generated:
        clean_generated_children(dataset_dir)
    dirs = ensure_dataset_layout(dataset_dir)
    images = collect_source_images(source_dir, pattern)
    catalog, name_to_id = load_equipment_library(equipment_library_csv)
    trusted_labels = build_trusted_label_map(catalog, name_to_id, reviewed_gallery_csv, accepted_gallery_csv)
    machine_records = load_machine_records(V2_ROOT)
    detector = DesignFragmentDetector()
    status = detector.check_status()

    rows: List[Dict[str, Any]] = []
    image_summaries: List[Dict[str, Any]] = []
    warnings: List[str] = []
    if not status.get("available"):
        warnings.append("OpenCV/NumPy 不可用，无法裁剪图片。")
    elif not images:
        warnings.append(f"没有找到输入图片: {source_dir}")
    else:
        for source_path, meta in images:
            image_rows, image_summary = process_one_image(
                source_path,
                meta,
                dirs,
                detector,
                trusted_labels,
                machine_records,
                catalog,
                name_to_id,
            )
            rows.extend(image_rows)
            image_summaries.append(image_summary)
            print(
                f"{source_path.name} -> {image_summary.get('normalized_filename')} "
                f"cards={image_summary.get('cards')} full={image_summary.get('full_cards')} "
                f"partial={image_summary.get('partial_cards')}"
            )

    summary = build_summary(rows, image_summaries)
    summary["warnings"] = warnings
    summary["paths"] = {
        "source_dir": str(source_dir),
        "dataset_dir": str(dataset_dir),
        "manifest_csv": str(dirs["manifests"] / "design_fragment_dataset_manifest.csv"),
        "summary_json": str(dirs["manifests"] / "design_fragment_dataset_summary.json"),
    }
    summary["label_inputs"] = {
        "reviewed_gallery_csv": str(reviewed_gallery_csv),
        "accepted_gallery_csv": str(accepted_gallery_csv),
        "trusted_labels": len(trusted_labels),
        "machine_records": len(machine_records),
    }

    manifest_fields = (
        "source_filename",
        "normalized_filename",
        "source_path",
        "normalized_source_path",
        "filter_rarity",
        "filter_rarity_id",
        "sort_mode",
        "page_index",
        "card_no",
        "row_index",
        "column_index",
        "visibility",
        "selected_for_training",
        "label_source",
        "label_trusted",
        "accepted_equipment_name",
        "current_resolved_equipment_id",
        "label_resolve_status",
        "fragment_owned",
        "fragment_required",
        "machine_suggested_equipment_name",
        "machine_suggested_equipment_id",
        "machine_icon_status",
        "machine_icon_confidence",
        "machine_icon_top_candidates",
        "machine_name_ocr_text",
        "machine_name_resolve_equipment_name",
        "machine_name_resolve_score",
        "label_source_path",
        "machine_source_path",
        "bbox",
        "raw_bbox",
        "icon_roi",
        "name_roi",
        "quantity_roi",
        "attribute_roi",
        "card_crop_path",
        "icon_crop_path",
        "name_crop_path",
        "quantity_crop_path",
        "attribute_crop_path",
        "training_icon_path",
        "training_card_path",
        "training_name_path",
    )
    write_csv(dirs["manifests"] / "design_fragment_dataset_manifest.csv", rows, manifest_fields)
    write_csv(
        dirs["manifests"] / "design_fragment_training_ready_manifest.csv",
        [row for row in rows if row.get("selected_for_training") is True],
        manifest_fields,
    )
    write_csv(
        dirs["manifests"] / "design_fragment_machine_only_full_cards.csv",
        [
            row
            for row in rows
            if row.get("visibility") == "full" and row.get("label_source") == "machine_suggested"
        ],
        manifest_fields,
    )
    write_csv(dirs["manifests"] / "design_fragment_image_summary.csv", image_summaries, ("source_filename", "normalized_filename", "status", "message", "image_size", "cards", "full_cards", "partial_cards"))
    (dirs["manifests"] / "design_fragment_dataset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (dirs["logs"] / "latest_build_log.json").write_text(json.dumps({"summary": summary, "images": image_summaries}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_human_readme(dataset_dir, summary)
    return summary


# ============================================================
# 🚀 第六部分：脚本入口
# ============================================================

def main() -> int:
    """
    命令行入口。

    输入：
        用户命令行参数。
    输出：
        进程退出码。
    使用示例：
        python ocr_training_lab/equipment_icon_matcher_v2/active_workbench/scripts/build_design_fragment_dataset.py --clean-generated
    """
    args = parse_args()
    summary = build_dataset(
        source_dir=args.source_dir,
        dataset_dir=args.dataset_dir,
        reviewed_gallery_csv=args.reviewed_gallery_csv,
        accepted_gallery_csv=args.accepted_gallery_csv,
        equipment_library_csv=args.equipment_library_csv,
        pattern=args.pattern,
        clean_generated=bool(args.clean_generated),
    )
    print("")
    print("Design fragment dataset build finished.")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not summary.get("warnings") else 1


if __name__ == "__main__":
    raise SystemExit(main())
