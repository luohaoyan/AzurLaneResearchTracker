#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        🧪 Wiki 属性辅助训练集构建器                           ║
║                                                              ║
║  【一句话解释】把 v2 人工确认样本迁移成 Wiki 属性标注训练集。  ║
║  【类比理解】像把你已经批改过的图标作业，自动补上属性答案。    ║
║  【数据流说明】v2 labels + prelabel + wiki CSV → training_set。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import csv
import json
import math
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - Pillow 缺失时仍可生成 CSV/JSON。
    Image = None
    ImageDraw = None
    ImageFont = None


# ============================================================
# 🧱 第二部分：常量与数据对象
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
V2_DIR = PROJECT_ROOT / "ocr_training_lab" / "equipment_icon_matcher_v2"

DEFAULT_PRELABEL_JSON = V2_DIR / "img_out" / "prelabel" / "v2_prelabel_results.json"
DEFAULT_HUMAN_ARCHIVE_CSV = V2_DIR / "human_label_archive" / "master_human_labels.csv"
DEFAULT_WIKI_SIGNATURE_CSV = SCRIPT_DIR / "wiki_out" / "human_archive_cache_only_check" / "wiki_equipment_attribute_signatures.csv"
DEFAULT_SOURCE_IMAGE_DIR = V2_DIR / "img_input"
DEFAULT_OUTPUT_ROOT = SCRIPT_DIR / "wiki_attribute_training_set"
DEFAULT_FONT_PATHS = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
)

RARITY_ORDER = {
    "rare": 2,
    "elite": 3,
    "super_rare": 4,
    "ultra_rare": 5,
}

# 明确人工笔误修正：只用于训练集迁移，不回写源人工档案。
MANUAL_LABEL_CORRECTIONS = {
    "双联装128mmSKC41高平两用炮#T3sa": "双联装128mmSKC41高平两用炮#T3",
}

SAMPLE_FIELDNAMES = [
    "filename",
    "card_no",
    "copied_image",
    "source_image",
    "filter_rarity",
    "filter_rarity_id",
    "page_index",
    "scroll_position",
    "visibility",
    "equipment_id",
    "equipment_name",
    "wiki_slug",
    "wiki_url",
    "attribute_signature",
    "damage_initial",
    "fire_rate_initial",
    "stat_1_label",
    "stat_1_initial",
    "stat_2_label",
    "stat_2_initial",
    "stat_3_label",
    "stat_3_initial",
    "extra_detection_range",
    "ammo_type",
    "skill_name",
    "card_bbox",
    "icon_roi",
    "name_roi",
    "quantity_roi",
    "attribute_roi",
    "train_split",
    "notes",
]


@dataclass(frozen=True)
class HumanLabel:
    """
    一条人工确认装备名。

    输入：
        filename/card_no/accepted_equipment_name。
    输出：
        训练集构建时的可靠装备名来源。
    使用示例：
        label = HumanLabel("v2_elite_scroll_1.png", 1, "舰艇维修设备#T2")
    """

    filename: str
    card_no: int
    equipment_name: str


@dataclass(frozen=True)
class WikiSignature:
    """
    Wiki 属性签名行。

    输入：
        wiki_equipment_attribute_signatures.csv 中 parse_status=success 的行。
    输出：
        用于自动填充属性标签。
    使用示例：
        sig.attribute_signature
    """

    row: Mapping[str, str]

    @property
    def equipment_name(self) -> str:
        """返回装备名称。"""
        return str(self.row.get("equipment_name", "") or "").strip()

    @property
    def equipment_id(self) -> str:
        """返回当前装备库 ID。"""
        return str(self.row.get("equipment_id", "") or "").strip()

    @property
    def attribute_signature(self) -> str:
        """返回短属性签名。"""
        return str(self.row.get("attribute_signature", "") or "").strip()

    def value(self, key: str) -> str:
        """按字段名取值，空值返回空字符串。"""
        return str(self.row.get(key, "") or "").strip()


# ============================================================
# 🧰 第三部分：读取输入数据
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。

    输入：
        终端参数。
    输出：
        argparse.Namespace。
    使用示例：
        python build_wiki_attribute_training_set.py
    """
    parser = argparse.ArgumentParser(description="从 v2 人工标注 + Wiki 属性签名构建属性辅助训练集。")
    parser.add_argument("--prelabel-json", type=Path, default=DEFAULT_PRELABEL_JSON, help="v2_prelabel_results.json。")
    parser.add_argument("--human-archive-csv", type=Path, default=DEFAULT_HUMAN_ARCHIVE_CSV, help="人工标注总档案 CSV。")
    parser.add_argument("--wiki-signature-csv", type=Path, default=DEFAULT_WIKI_SIGNATURE_CSV, help="Wiki 属性签名 CSV。")
    parser.add_argument("--extra-wiki-signature-csv", type=Path, action="append", default=[], help="补充 Wiki 属性签名 CSV，可重复传入。")
    parser.add_argument("--source-image-dir", type=Path, default=DEFAULT_SOURCE_IMAGE_DIR, help="v2 原始截图目录。")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="训练集输出根目录。")
    parser.add_argument("--max-per-equipment", type=int, default=0, help="每件装备最多保留几张卡；0 表示不限制。")
    parser.add_argument("--include-partial", action="store_true", help="默认只使用 full 卡；启用后包含 partial/blocked。")
    parser.add_argument("--copy-images", action="store_true", default=True, help="复制被选中的 v2 截图到 img_input。")
    parser.add_argument("--no-copy-images", action="store_false", dest="copy_images", help="不复制图片，只生成标注表。")
    parser.add_argument("--draw-annotations", action="store_true", default=True, help="输出带属性标签的人工检查图。")
    parser.add_argument("--no-draw-annotations", action="store_false", dest="draw_annotations", help="不输出标注图。")
    return parser.parse_args()


def normalize_name(value: str) -> str:
    """
    规范化装备名用于匹配，保留 #T 级别。

    输入：
        装备名称。
    输出：
        去空白后的名称。
    使用示例：
        normalize_name(" 基础声呐#T3 ")
    """
    text = str(value or "").replace("\xa0", " ").strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+#", "#", text)
    return text


def apply_manual_label_correction(equipment_name: str) -> str:
    """
    应用明确人工笔误修正。

    输入：
        人工 accepted_equipment_name。
    输出：
        修正后的装备名；没有规则时原样返回。
    使用示例：
        apply_manual_label_correction("双联装128mmSKC41高平两用炮#T3sa")
    """
    normalized = normalize_name(equipment_name)
    return MANUAL_LABEL_CORRECTIONS.get(normalized, normalized)


def load_human_labels(path: Path) -> Dict[Tuple[str, int], HumanLabel]:
    """
    读取 v2 人工确认装备名档案。

    输入：
        master_human_labels.csv。
    输出：
        (filename, card_no) → HumanLabel。
    使用示例：
        labels = load_human_labels(path)
    """
    labels: Dict[Tuple[str, int], HumanLabel] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            filename = str(row.get("filename", "") or "").strip()
            equipment_name = apply_manual_label_correction(str(row.get("accepted_equipment_name", "") or ""))
            if not filename or not equipment_name:
                continue
            try:
                card_no = int(row.get("card_no", 0) or 0)
            except (TypeError, ValueError):
                card_no = 0
            if card_no <= 0:
                continue
            labels[(filename, card_no)] = HumanLabel(filename, card_no, equipment_name)
    return labels


def load_wiki_signatures(path: Path) -> Dict[str, WikiSignature]:
    """
    读取 Wiki 属性签名表。

    输入：
        wiki_equipment_attribute_signatures.csv。
    输出：
        equipment_name → WikiSignature。
    使用示例：
        signatures = load_wiki_signatures(path)
    """
    signatures: Dict[str, WikiSignature] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            if str(row.get("parse_status", "") or "") != "success":
                continue
            signature = WikiSignature(dict(row))
            if signature.equipment_name and signature.attribute_signature:
                signatures[normalize_name(signature.equipment_name)] = signature
    return signatures


def load_wiki_signatures_many(paths: Sequence[Path]) -> Dict[str, WikiSignature]:
    """
    合并多个 Wiki 属性签名 CSV，后面的补充表只填补缺失项。

    输入：
        多个 wiki_equipment_attribute_signatures.csv 路径。
    输出：
        equipment_name → WikiSignature。
    使用示例：
        signatures = load_wiki_signatures_many([main, extra])
    """
    merged: Dict[str, WikiSignature] = {}
    for path in paths:
        if not path.exists():
            continue
        for name, signature in load_wiki_signatures(path).items():
            merged.setdefault(name, signature)
    return merged


def load_prelabel_results(path: Path) -> List[Dict[str, Any]]:
    """
    读取 v2 预标注结果。

    输入：
        v2_prelabel_results.json。
    输出：
        图片结果列表。
    使用示例：
        results = load_prelabel_results(path)
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"预标注 JSON 应为列表: {path}")
    return [dict(item) for item in data]


# ============================================================
# 🏗️ 第四部分：样本选择和训练数据构建
# ============================================================

def build_attribute_roi(card: Mapping[str, Any]) -> List[int]:
    """
    根据设计图卡片框估算右侧属性文字区域。

    输入：
        v2 card dict，至少包含 bbox/icon_roi/name_roi/quantity_roi。
    输出：
        [x, y, w, h]，用于后续 OCR 读取伤害/射速/属性文字。
    使用示例：
        roi = build_attribute_roi(card)
    """
    bbox = list(card.get("bbox", []) or [])
    icon_roi = list(card.get("icon_roi", []) or [])
    quantity_roi = list(card.get("quantity_roi", []) or [])
    if len(bbox) != 4:
        return []
    x, y, w, h = [int(v) for v in bbox]
    left = int(icon_roi[0] + icon_roi[2] + 14) if len(icon_roi) == 4 else x + int(w * 0.25)
    top = y + int(h * 0.30)
    right_limit = int(quantity_roi[0] - 8) if len(quantity_roi) == 4 else x + int(w * 0.78)
    width = max(1, right_limit - left)
    height = max(1, y + h - top - 8)
    return [left, top, width, height]


def select_training_samples(
    prelabel_results: Sequence[Mapping[str, Any]],
    human_labels: Mapping[Tuple[str, int], HumanLabel],
    wiki_signatures: Mapping[str, WikiSignature],
    *,
    include_partial: bool = False,
    max_per_equipment: int = 0,
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """
    从 v2 样本里选择可用于 Wiki 属性训练的完整卡片。

    输入：
        prelabel 结果、人工标签、Wiki 签名。
    输出：
        (训练样本行, 跳过原因行)。
    使用示例：
        rows, skipped = select_training_samples(results, labels, signatures)
    """
    samples: List[Dict[str, str]] = []
    skipped: List[Dict[str, str]] = []
    per_equipment_counter: Counter[str] = Counter()

    for image_item in prelabel_results:
        filename = str(image_item.get("filename", "") or "").strip()
        source_image = str(image_item.get("screenshot_path", "") or "").strip()
        for card in image_item.get("cards", []) or []:
            try:
                card_no = int(card.get("card_no", 0) or 0)
            except (TypeError, ValueError):
                card_no = 0
            label = human_labels.get((filename, card_no))
            if label is None:
                continue
            visibility = str(card.get("visibility", "") or "").strip()
            if not include_partial and visibility != "full":
                skipped.append(_skip_row(filename, card_no, label.equipment_name, "visibility_not_full", visibility))
                continue
            signature = wiki_signatures.get(normalize_name(label.equipment_name))
            if signature is None:
                skipped.append(_skip_row(filename, card_no, label.equipment_name, "wiki_signature_missing", visibility))
                continue
            if max_per_equipment > 0 and per_equipment_counter[label.equipment_name] >= max_per_equipment:
                skipped.append(_skip_row(filename, card_no, label.equipment_name, "max_per_equipment", visibility))
                continue
            per_equipment_counter[label.equipment_name] += 1
            train_split = choose_train_split(filename, card_no)
            samples.append(build_sample_row(filename, source_image, card, label, signature, train_split))
    return samples, skipped


def _skip_row(filename: str, card_no: int, equipment_name: str, reason: str, visibility: str) -> Dict[str, str]:
    """构造跳过样本的审计行。"""
    return {
        "filename": filename,
        "card_no": str(card_no),
        "equipment_name": equipment_name,
        "reason": reason,
        "visibility": visibility,
    }


def choose_train_split(filename: str, card_no: int) -> str:
    """
    稳定划分 train/validation，避免每次生成结果抖动。

    输入：
        filename/card_no。
    输出：
        train 或 validation。
    使用示例：
        split = choose_train_split("v2_elite_scroll_1.png", 1)
    """
    value = sum(ord(ch) for ch in f"{filename}:{card_no}")
    return "validation" if value % 5 == 0 else "train"


def build_sample_row(
    filename: str,
    source_image: str,
    card: Mapping[str, Any],
    label: HumanLabel,
    signature: WikiSignature,
    train_split: str,
) -> Dict[str, str]:
    """
    构造单张卡片训练样本行。

    输入：
        v2 card、人工标签和 Wiki 签名。
    输出：
        扁平 CSV 行。
    使用示例：
        row = build_sample_row(...)
    """
    attribute_roi = build_attribute_roi(card)
    return {
        "filename": filename,
        "card_no": str(label.card_no),
        "copied_image": filename,
        "source_image": source_image,
        "filter_rarity": str(card.get("filter_rarity", "") or ""),
        "filter_rarity_id": str(card.get("filter_rarity_id", "") or ""),
        "page_index": str(card.get("page_index", "") or ""),
        "scroll_position": str(card.get("scroll_position", "") or ""),
        "visibility": str(card.get("visibility", "") or ""),
        "equipment_id": signature.equipment_id,
        "equipment_name": label.equipment_name,
        "wiki_slug": signature.value("wiki_slug"),
        "wiki_url": signature.value("wiki_url"),
        "attribute_signature": signature.attribute_signature,
        "damage_initial": signature.value("damage_initial"),
        "fire_rate_initial": signature.value("fire_rate_initial"),
        "stat_1_label": signature.value("stat_1_label"),
        "stat_1_initial": signature.value("stat_1_initial"),
        "stat_2_label": signature.value("stat_2_label"),
        "stat_2_initial": signature.value("stat_2_initial"),
        "stat_3_label": signature.value("stat_3_label"),
        "stat_3_initial": signature.value("stat_3_initial"),
        "extra_detection_range": signature.value("extra_detection_range"),
        "ammo_type": signature.value("ammo_type"),
        "skill_name": signature.value("skill_name"),
        "card_bbox": json.dumps(card.get("bbox", []) or [], ensure_ascii=False),
        "icon_roi": json.dumps(card.get("icon_roi", []) or [], ensure_ascii=False),
        "name_roi": json.dumps(card.get("name_roi", []) or [], ensure_ascii=False),
        "quantity_roi": json.dumps(card.get("quantity_roi", []) or [], ensure_ascii=False),
        "attribute_roi": json.dumps(attribute_roi, ensure_ascii=False),
        "train_split": train_split,
        "notes": "wiki_prefilled_from_human_label",
    }


# ============================================================
# 🧠 第五部分：属性签名轻量模型
# ============================================================

def tokenize_attribute_signature(signature: str) -> List[str]:
    """
    把属性签名拆成可匹配 token。

    输入：
        伤害=17x4|标准射速=3.43s/轮|炮击=65。
    输出：
        token 列表。
    使用示例：
        tokens = tokenize_attribute_signature(signature)
    """
    text = str(signature or "").lower().replace("×", "x")
    tokens: List[str] = []
    for part in re.split(r"[|,，;；\s]+", text):
        part = part.strip()
        if not part:
            continue
        tokens.append(part)
        if "=" in part:
            label, value = part.split("=", 1)
            if label:
                tokens.append(label)
            if value:
                tokens.append(value)
    return sorted(set(tokens))


def build_attribute_model(samples: Sequence[Mapping[str, str]]) -> Dict[str, Any]:
    """
    根据训练样本构建属性签名检索模型。

    输入：
        wiki_prefilled_samples.csv 对应行。
    输出：
        包含 token、idf、装备索引和训练统计的 JSON 对象。
    使用示例：
        model = build_attribute_model(samples)
    """
    by_equipment: Dict[str, Dict[str, Any]] = {}
    for row in samples:
        equipment_name = str(row.get("equipment_name", "") or "")
        if not equipment_name:
            continue
        by_equipment.setdefault(
            equipment_name,
            {
                "equipment_id": row.get("equipment_id", ""),
                "equipment_name": equipment_name,
                "filter_rarity_id": row.get("filter_rarity_id", ""),
                "attribute_signature": row.get("attribute_signature", ""),
                "tokens": tokenize_attribute_signature(str(row.get("attribute_signature", "") or "")),
                "sample_count": 0,
            },
        )
        by_equipment[equipment_name]["sample_count"] += 1

    document_count = max(1, len(by_equipment))
    document_frequency: Counter[str] = Counter()
    for item in by_equipment.values():
        document_frequency.update(set(item["tokens"]))

    idf = {
        token: round(math.log((document_count + 1) / (frequency + 1)) + 1.0, 6)
        for token, frequency in sorted(document_frequency.items())
    }
    return {
        "model_type": "wiki_attribute_signature_tfidf_v1",
        "document_count": document_count,
        "sample_count": len(samples),
        "token_idf": idf,
        "equipment_index": list(sorted(by_equipment.values(), key=lambda item: item["equipment_name"])),
        "note": "该模型来自 Wiki 属性签名和人工确认装备名，用于属性 OCR 候选重排；不是神经网络模型。",
    }


# ============================================================
# 🖼️ 第六部分：输出文件和标注图
# ============================================================

def prepare_output_dirs(output_root: Path) -> Dict[str, Path]:
    """
    创建训练集输出目录。

    输入：
        output_root。
    输出：
        子目录映射。
    使用示例：
        dirs = prepare_output_dirs(Path("wiki_attribute_training_set"))
    """
    dirs = {
        "root": output_root,
        "img_input": output_root / "img_input",
        "img_out": output_root / "img_out",
        "model": output_root / "model",
        "tables": output_root / "tables",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def copy_sample_images(samples: Sequence[Mapping[str, str]], source_image_dir: Path, target_dir: Path) -> List[str]:
    """
    复制被选中的 v2 截图。

    输入：
        样本行、源图片目录、目标目录。
    输出：
        缺失图片列表。
    使用示例：
        missing = copy_sample_images(samples, source, target)
    """
    missing: List[str] = []
    copied: set[str] = set()
    for row in samples:
        filename = str(row.get("filename", "") or "")
        if not filename or filename in copied:
            continue
        source = source_image_dir / filename
        target = target_dir / filename
        if not source.exists():
            missing.append(filename)
            continue
        shutil.copy2(source, target)
        copied.add(filename)
    return missing


def write_csv(path: Path, rows: Sequence[Mapping[str, str]], fieldnames: Sequence[str]) -> None:
    """写出 CSV 文件。"""
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_exp_file(path: Path, samples: Sequence[Mapping[str, str]]) -> None:
    """
    写出接近 attribute_exp 格式的训练标注文件。

    输入：
        样本行。
    输出：
        wiki_prefilled_attribute_exp.txt。
    使用示例：
        write_exp_file(path, samples)
    """
    lines: List[str] = [
        "# wiki_prefilled_attribute_exp",
        "# 该文件由 build_wiki_attribute_training_set.py 生成。",
        "# equipment_name 来自你已人工确认的 v2 标注；属性字段来自 Wiki 签名。",
        "# 不建议直接手改该文件；如需修正，请修正源人工标注或 Wiki 别名后重新生成。",
        "",
    ]
    by_filename: Dict[str, List[Mapping[str, str]]] = defaultdict(list)
    for row in samples:
        by_filename[str(row["filename"])].append(row)
    for filename in sorted(by_filename):
        lines.append(f"[{filename}]")
        for row in sorted(by_filename[filename], key=lambda item: int(item["card_no"])):
            prefix = f"card_{int(row['card_no']):02d}"
            lines.extend(
                [
                    f"{prefix}.visibility:{row['visibility']}",
                    f"{prefix}.do_not_train:false",
                    f"{prefix}.equipment_name:{row['equipment_name']}",
                    f"{prefix}.equipment_id:{row['equipment_id']}",
                    f"{prefix}.wiki_signature:{row['attribute_signature']}",
                    f"{prefix}.wiki_url:{row['wiki_url']}",
                    f"{prefix}.attr_damage:{row['damage_initial']}",
                    f"{prefix}.attr_fire_rate:{row['fire_rate_initial']}",
                    f"{prefix}.attr_stat_1_label:{row['stat_1_label']}",
                    f"{prefix}.attr_stat_1_value:{row['stat_1_initial']}",
                    f"{prefix}.attr_stat_2_label:{row['stat_2_label']}",
                    f"{prefix}.attr_stat_2_value:{row['stat_2_initial']}",
                    f"{prefix}.attr_stat_3_label:{row['stat_3_label']}",
                    f"{prefix}.attr_stat_3_value:{row['stat_3_initial']}",
                    f"{prefix}.attr_extra_text:{_extra_text(row)}",
                    f"{prefix}.attribute_roi:{row['attribute_roi']}",
                    f"{prefix}.attribute_confidence:wiki",
                    f"{prefix}.notes:{row['notes']}",
                    "",
                ]
            )
    path.write_text("\n".join(lines), encoding="utf-8")


def _extra_text(row: Mapping[str, str]) -> str:
    """把弹药、技能、额外侦测范围拼成辅助文本。"""
    parts: List[str] = []
    if row.get("ammo_type"):
        parts.append(f"弹药={row['ammo_type']}")
    if row.get("extra_detection_range"):
        parts.append(f"额外侦测范围={row['extra_detection_range']}")
    if row.get("skill_name"):
        parts.append(f"技能={row['skill_name']}")
    return "|".join(parts)


def draw_annotation_images(samples: Sequence[Mapping[str, str]], image_dir: Path, output_dir: Path) -> None:
    """
    在样本截图上绘制卡片框和 Wiki 属性签名。

    输入：
        样本行、输入图片目录、输出目录。
    输出：
        *_wiki_attr.png。
    使用示例：
        draw_annotation_images(samples, img_input, img_out)
    """
    if Image is None or ImageDraw is None:
        return
    grouped: Dict[str, List[Mapping[str, str]]] = defaultdict(list)
    for row in samples:
        grouped[str(row["filename"])].append(row)
    font = load_font(16)
    small_font = load_font(13)
    for filename, rows in grouped.items():
        image_path = image_dir / filename
        if not image_path.exists():
            continue
        image = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(image)
        for row in rows:
            bbox = parse_roi(row.get("card_bbox", ""))
            attribute_roi = parse_roi(row.get("attribute_roi", ""))
            if len(bbox) == 4:
                draw.rectangle((bbox[0], bbox[1], bbox[0] + bbox[2], bbox[1] + bbox[3]), outline=(0, 210, 255), width=2)
            if len(attribute_roi) == 4:
                draw.rectangle(
                    (
                        attribute_roi[0],
                        attribute_roi[1],
                        attribute_roi[0] + attribute_roi[2],
                        attribute_roi[1] + attribute_roi[3],
                    ),
                    outline=(255, 180, 0),
                    width=2,
                )
            text_x = bbox[0] + 4 if len(bbox) == 4 else 8
            text_y = bbox[1] + 4 if len(bbox) == 4 else 8
            title = f"card{int(row['card_no']):02d} {row['equipment_name']}"
            draw_text_with_shadow(draw, (text_x, text_y), title, font, (255, 255, 0))
            draw_text_with_shadow(draw, (text_x, text_y + 20), row["attribute_signature"][:48], small_font, (180, 255, 180))
        image.save(output_dir / f"{Path(filename).stem}_wiki_attr.png")


def parse_roi(value: str) -> List[int]:
    """解析 JSON ROI 字符串。"""
    try:
        data = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list) or len(data) != 4:
        return []
    return [int(item) for item in data]


def load_font(size: int) -> Any:
    """加载中文字体，失败时使用默认字体。"""
    if ImageFont is None:
        return None
    for path in DEFAULT_FONT_PATHS:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def draw_text_with_shadow(draw: Any, xy: Tuple[int, int], text: str, font: Any, fill: Tuple[int, int, int]) -> None:
    """绘制带阴影文字，提高截图上可读性。"""
    x, y = xy
    draw.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=fill)


def write_summary(
    path: Path,
    samples: Sequence[Mapping[str, str]],
    skipped: Sequence[Mapping[str, str]],
    missing_images: Sequence[str],
) -> None:
    """写出训练集摘要。"""
    summary = {
        "samples": len(samples),
        "unique_images": len({row["filename"] for row in samples}),
        "unique_equipment": len({row["equipment_name"] for row in samples}),
        "train_split": dict(Counter(row["train_split"] for row in samples)),
        "rarity": dict(Counter(row["filter_rarity"] for row in samples)),
        "skipped": len(skipped),
        "skipped_reasons": dict(Counter(row["reason"] for row in skipped)),
        "missing_images": list(missing_images),
        "note": "训练样本来自 v2 人工确认装备名 + Wiki 属性签名；裁切卡默认不进入训练。",
    }
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# 🚪 第七部分：命令行入口
# ============================================================

def main() -> int:
    """
    命令行入口。

    输入：
        终端参数。
    输出：
        进程返回码。
    使用示例：
        python ocr_training_lab/equipment_attribute_scan/build_wiki_attribute_training_set.py
    """
    args = parse_args()
    prelabel_results = load_prelabel_results(args.prelabel_json)
    human_labels = load_human_labels(args.human_archive_csv)
    wiki_signatures = load_wiki_signatures_many([args.wiki_signature_csv, *args.extra_wiki_signature_csv])
    samples, skipped = select_training_samples(
        prelabel_results,
        human_labels,
        wiki_signatures,
        include_partial=args.include_partial,
        max_per_equipment=max(0, args.max_per_equipment),
    )

    dirs = prepare_output_dirs(args.output_root)
    missing_images: List[str] = []
    if args.copy_images:
        missing_images = copy_sample_images(samples, args.source_image_dir, dirs["img_input"])

    write_csv(dirs["tables"] / "wiki_attribute_training_samples.csv", samples, SAMPLE_FIELDNAMES)
    write_csv(dirs["tables"] / "wiki_attribute_training_skipped.csv", skipped, ["filename", "card_no", "equipment_name", "reason", "visibility"])
    (dirs["tables"] / "wiki_attribute_training_samples.json").write_text(
        json.dumps(samples, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_exp_file(dirs["root"] / "wiki_prefilled_attribute_exp.txt", samples)
    model = build_attribute_model(samples)
    (dirs["model"] / "wiki_attribute_signature_model.json").write_text(
        json.dumps(model, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_summary(dirs["root"] / "wiki_attribute_training_summary.json", samples, skipped, missing_images)
    if args.draw_annotations:
        draw_annotation_images(samples, dirs["img_input"], dirs["img_out"])

    print(f"Wiki 属性训练集构建完成：samples={len(samples)} unique_equipment={len({row['equipment_name'] for row in samples})}")
    print(f"输出目录: {args.output_root}")
    print(f"训练表: {dirs['tables'] / 'wiki_attribute_training_samples.csv'}")
    print(f"轻量模型: {dirs['model'] / 'wiki_attribute_signature_model.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
