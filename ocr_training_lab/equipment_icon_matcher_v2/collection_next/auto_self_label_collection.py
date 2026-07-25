#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      collection_next 自标注合并器                            ║
║                                                              ║
║  【一句话解释】把机器结果、名称 OCR 和历史标注合成自标注稿。   ║
║  【类比理解】像我先替你把明显题做完，只把真没把握的题留空。    ║
║  【数据流说明】v2_prelabel_results.csv → review/self_label。   ║
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
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    # 测试环境中 stdout/stderr 可能不是标准流；忽略即可。
    pass


# ============================================================
# 🧱 第二部分：路径、别名与数据对象
# ============================================================

THIS_DIR = Path(__file__).resolve().parent
V2_DIR = THIS_DIR.parent
PROJECT_ROOT = V2_DIR.parents[1]
DEFAULT_SOURCE_DIR = THIS_DIR / "img_out" / "run_20260719_152339"
DEFAULT_OUTPUT_ROOT = THIS_DIR / "review"
DEFAULT_HUMAN_ARCHIVE_CSV = V2_DIR / "human_label_archive" / "master_human_labels.csv"
RESULTS_CSV_NAME = "v2_prelabel_results.csv"

# 这些不是正式装备别名表，只服务于本批 collection_next 的自标注减负。
# 目标只写基础名，最终仍以机器候选里的完整 “装备名#T等级” 为准。
DISPLAY_ALIAS_TARGETS: Tuple[Tuple[str, str], ...] = (
    ("海怒", "海怒"),
    ("海然", "海怒"),
    ("海毒牙", "海毒牙"),
    ("希方各", "海毒牙"),
    ("泽克", "零战五二型"),
    ("列风", "烈风"),
    ("赫尔卡特", "F6F地狱猫"),
)

# Codex 本轮直接看 annotated 图后确认的覆盖项。
# 这些仍属于 self-label，不写入用户人工档案；目的是把本批重复肉眼劳动从用户身上拿回来。
VISUAL_SELF_LABEL_OVERRIDES: Dict[Tuple[str, str], str] = {
    ("frag_super_rare_number_scroll_001.png", "4"): "四联装380mm主炮Mle1935#T3",
    ("frag_super_rare_rarity_scroll_001.png", "6"): "试作型四联装610mm鱼雷（巡洋用）#T0",
    ("frag_super_rare_buildable_scroll_002.png", "1"): "BR.810#T0",
    ("frag_super_rare_buildable_scroll_006.png", "7"): "试作型四联装610mm鱼雷（巡洋用）#T0",
    ("frag_super_rare_buildable_scroll_007.png", "1"): "试作型三联装152mm主炮Model1936#T0",
    ("frag_super_rare_buildable_scroll_007.png", "2"): "试作型三联装406mm/50主炮#T0",
    ("frag_super_rare_buildable_scroll_008.png", "3"): "试作型三联装406mm主炮Model1940#T0",
    ("frag_super_rare_buildable_scroll_008.png", "4"): "试作型三联装152mm主炮Model1936#T0",
    ("frag_super_rare_buildable_scroll_008.png", "5"): "试作型三联装406mm/45主炮Mk7#T0",
    ("frag_super_rare_buildable_scroll_008.png", "6"): "试作型三联装152mm主炮Model1936#T0",
    ("frag_super_rare_buildable_scroll_008.png", "7"): "试作型三联装406mm/45主炮Mk7#T0",
    ("frag_super_rare_buildable_scroll_009.png", "1"): "四联装380mm主炮Mle1935#T3",
    ("frag_super_rare_buildable_scroll_009.png", "2"): "试作型三联装254mm主炮Model1939#T0",
    ("frag_ultra_rare_rarity_scroll_001.png", "4"): "试作型四联装305mmSKC39主炮#T0",
    ("frag_ultra_rare_rarity_scroll_002.png", "1"): "试作型双联装457mm主炮MkA#T0",
    ("frag_ultra_rare_rarity_scroll_002.png", "4"): "试作型四联装305mmSKC39主炮#T0",
}

VISUAL_REJECT_OVERRIDES: Dict[Tuple[str, str], str] = {
    ("frag_ultra_rare_buildable_scroll_003.png", "1"): "顶部空白/误检卡片，不用于训练",
    ("frag_ultra_rare_buildable_scroll_003.png", "2"): "顶部空白/误检卡片，不用于训练",
}


@dataclass(frozen=True)
class Candidate:
    """
    图标或名称候选。

    输入：
        equipment_id/name/score。
    输出：
        便于自标注规则判断的结构化候选。
    使用示例：
        cand = Candidate("G0158", "海怒#T0", 0.78)
    """

    equipment_id: str
    equipment_name: str
    score: float


@dataclass(frozen=True)
class SelfLabelDecision:
    """
    单张卡片的自标注决策。

    输入：
        机器 CSV 行。
    输出：
        accepted_equipment_name / decision / reason。
    使用示例：
        decision = decide_self_label(row, previous)
    """

    accepted_equipment_name: str
    decision: str
    reason: str
    confidence: float


# ============================================================
# 🏗️ 第三部分：参数与通用解析
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。

    输入：
        终端命令行。
    输出：
        argparse.Namespace。
    使用示例：
        python auto_self_label_collection.py --source-dir img_out/run_xxx
    """
    parser = argparse.ArgumentParser(description="为 collection_next 当前机器结果生成 Codex 自标注稿。")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR, help="包含 v2_prelabel_results.csv 的输出目录。")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="自标注输出根目录。")
    parser.add_argument("--output-name", default="", help="输出子目录名；默认 self_label_yyyyMMdd_HHmmss。")
    parser.add_argument("--human-archive-csv", type=Path, default=DEFAULT_HUMAN_ARCHIVE_CSV, help="历史人工标注总档案。")
    parser.add_argument("--user-review-exp", type=Path, default=None, help="用户本轮已经填写的 review_only_exp；其 accepted_equipment_name 最高优先级。")
    parser.add_argument("--disable-visual-overrides", action="store_true", help="禁用按文件名+card_no 写死的旧视觉覆盖项；新账号复用截图名时必须开启。")
    parser.add_argument("--ignore-human-archive", action="store_true", help="忽略历史人工档案；新账号/复用文件名的数据收集必须开启，避免旧标签污染新截图。")
    return parser.parse_args()


def normalize_name_text(value: str) -> str:
    """
    规范化装备名或 OCR 文本，降低空格/符号/大小写影响。

    输入：
        任意装备名或 OCR 文本。
    输出：
        小写、去空格和常见标点后的文本。
    使用示例：
        normalize_name_text("F6F 地狱猫#T3")
    """
    text = str(value or "").strip().lower()
    text = text.replace("＃", "#").replace("（", "(").replace("）", ")")
    return re.sub(r"[\s\"'“”‘’，,。.:：;；/\\_\-]+", "", text)


def base_name(value: str) -> str:
    """
    去掉 #T 等级后的基础装备名。

    输入：
        装备完整名。
    输出：
        基础名。
    使用示例：
        base_name("海怒#T0") == "海怒"
    """
    return re.sub(r"#t\d+$", "", normalize_name_text(value), flags=re.IGNORECASE)


def parse_bool(value: object) -> bool:
    """
    解析 CSV 中的布尔文本。

    输入：
        True/False 或字符串。
    输出：
        bool。
    使用示例：
        parse_bool("True") is True
    """
    return str(value or "").strip().lower() == "true"


def parse_float(value: object) -> float:
    """
    安全解析浮点数。

    输入：
        CSV 文本。
    输出：
        float，失败返回 0。
    使用示例：
        parse_float("0.91")
    """
    try:
        return float(str(value or "").strip())
    except ValueError:
        return 0.0


def parse_candidates(value: str) -> List[Candidate]:
    """
    解析脚本输出的候选串。

    输入：
        G0158:海怒#T0:0.776 | G0162:紫电改二#T0:0.785
    输出：
        Candidate 列表。
    使用示例：
        candidates = parse_candidates(row["icon_top_candidates"])
    """
    candidates: List[Candidate] = []
    for part in str(value or "").split("|"):
        text = part.strip()
        if not text:
            continue
        pieces = text.rsplit(":", 1)
        if len(pieces) != 2:
            continue
        score = parse_float(pieces[1])
        left = pieces[0]
        id_and_name = left.split(":", 1)
        if len(id_and_name) != 2:
            continue
        candidates.append(Candidate(id_and_name[0].strip(), id_and_name[1].strip(), score))
    return candidates


def load_previous_human_labels(archive_csv_path: Path) -> Dict[Tuple[str, str], str]:
    """
    读取历史人工标注，用于同文件同卡自动继承。

    输入：
        master_human_labels.csv。
    输出：
        (filename, card_no) → accepted_equipment_name。
    使用示例：
        labels = load_previous_human_labels(path)
    """
    labels: Dict[Tuple[str, str], str] = {}
    if not archive_csv_path.exists():
        return labels
    with archive_csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            filename = str(row.get("filename", "") or "").strip()
            card_no = str(row.get("card_no", "") or "").strip()
            accepted = str(row.get("accepted_equipment_name", "") or "").strip()
            if filename and card_no and accepted:
                labels[(filename, card_no)] = accepted
    return labels


def load_user_review_exp(exp_path: Optional[Path]) -> Dict[Tuple[str, str], str]:
    """
    读取用户本轮已经填写的 review_only_exp。

    输入：
        v2_prelabel_review_only_exp.txt 路径。
    输出：
        (filename, card_no) → accepted_equipment_name。
    使用示例：
        user_labels = load_user_review_exp(Path("v2_prelabel_review_only_exp.txt"))
    """
    labels: Dict[Tuple[str, str], str] = {}
    if exp_path is None or not exp_path.exists():
        return labels

    current_filename = ""
    for raw_line in exp_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            current_filename = line[1:-1].strip()
            continue
        if not current_filename:
            continue
        match = re.match(r"^card_(\d+)\.accepted_equipment_name\s*:\s*(.*)$", line)
        if match is None:
            continue
        accepted_name = str(match.group(2) or "").strip()
        if not accepted_name:
            continue
        labels[(current_filename, str(int(match.group(1))))] = accepted_name
    return labels


# ============================================================
# 🧠 第四部分：自标注决策
# ============================================================

def find_alias_candidate(name_ocr_text: str, candidates: Sequence[Candidate]) -> Optional[Candidate]:
    """
    用游戏显示名/和谐名在候选中找唯一目标。

    输入：
        OCR 文本和图标 top-N 候选。
    输出：
        命中唯一候选时返回 Candidate，否则 None。
    使用示例：
        “海怒” 在 top-N 中命中 “海怒#T0”。
    """
    normalized_ocr = normalize_name_text(name_ocr_text)
    if not normalized_ocr:
        return None

    for alias, target_base in DISPLAY_ALIAS_TARGETS:
        alias_key = normalize_name_text(alias)
        target_key = normalize_name_text(target_base)
        if alias_key and alias_key not in normalized_ocr:
            continue
        matched = [candidate for candidate in candidates if target_key and target_key in base_name(candidate.equipment_name)]
        unique_by_name = {candidate.equipment_name: candidate for candidate in matched}
        if len(unique_by_name) == 1:
            return next(iter(unique_by_name.values()))
    return None


def candidate_repeated_support(candidates: Sequence[Candidate], equipment_name: str) -> int:
    """
    统计同一装备名在 top-N 中出现次数。

    输入：
        候选列表和装备名。
    输出：
        出现次数。
    使用示例：
        repeated = candidate_repeated_support(candidates, "试作舰载型天雷#T0")
    """
    key = normalize_name_text(equipment_name)
    return sum(1 for candidate in candidates if normalize_name_text(candidate.equipment_name) == key)


def first_distinct_icon_margin(candidates: Sequence[Candidate], equipment_name: str) -> float:
    """
    计算 top1 与第一个不同装备候选的分差。

    输入：
        图标 top-N 候选和 suggested 装备名。
    输出：
        与第一个不同装备名的 score 差；候选不足时返回 0。
    使用示例：
        margin = first_distinct_icon_margin(candidates, "试作型三联装152mm主炮#T0")
    """
    if not candidates:
        return 0.0
    target_key = normalize_name_text(equipment_name)
    top_score = float(candidates[0].score)
    for candidate in candidates[1:]:
        if normalize_name_text(candidate.equipment_name) != target_key:
            return top_score - float(candidate.score)
    return 0.0


def decide_self_label(
    row: Mapping[str, str],
    previous_human: Mapping[Tuple[str, str], str],
    user_review_labels: Optional[Mapping[Tuple[str, str], str]] = None,
    use_visual_overrides: bool = True,
) -> SelfLabelDecision:
    """
    给一张卡片做 Codex 自标注决策。

    输入：
        v2_prelabel_results.csv 的一行和历史人工标注。
    输出：
        SelfLabelDecision。
    使用示例：
        decision = decide_self_label(row, previous_human)
    """
    filename = str(row.get("filename", "") or "").strip()
    card_no = str(row.get("card_no", "") or "").strip()
    user_review_name = (user_review_labels or {}).get((filename, card_no), "")
    if user_review_name:
        return SelfLabelDecision(user_review_name, "user_review_exp", "用户本轮已填写标注，最高优先级", 1.0)

    if use_visual_overrides and (filename, card_no) in VISUAL_REJECT_OVERRIDES:
        return SelfLabelDecision(
            "",
            "visual_reject_false_positive",
            VISUAL_REJECT_OVERRIDES[(filename, card_no)],
            1.0,
        )
    if use_visual_overrides and (filename, card_no) in VISUAL_SELF_LABEL_OVERRIDES:
        return SelfLabelDecision(
            VISUAL_SELF_LABEL_OVERRIDES[(filename, card_no)],
            "visual_self_label",
            "Codex 查看 annotated 图后确认",
            0.98,
        )

    previous_name = previous_human.get((filename, card_no), "")
    if previous_name:
        return SelfLabelDecision(previous_name, "previous_human", "继承历史人工标注", 1.0)

    existing = str(row.get("accepted_equipment_name", "") or "").strip()
    suggested = str(row.get("suggested_equipment_name", "") or "").strip()
    name_resolved = str(row.get("name_resolve_equipment_name", "") or "").strip()
    name_text = str(row.get("name_ocr_text", "") or "").strip()
    icon_status = str(row.get("icon_status", "") or "").strip()
    review_reason = str(row.get("review_reason", "") or "").strip()
    icon_confidence = parse_float(row.get("icon_confidence", "0"))
    name_score = parse_float(row.get("name_resolve_score", "0"))
    candidates = parse_candidates(str(row.get("icon_top_candidates", "") or ""))

    if existing:
        return SelfLabelDecision(existing, "existing_prefill", "沿用机器已有预填", max(icon_confidence, name_score))

    alias_candidate = find_alias_candidate(name_text, candidates)
    if alias_candidate is not None and alias_candidate.score >= 0.70:
        return SelfLabelDecision(
            alias_candidate.equipment_name,
            "display_alias_in_candidates",
            f"名称 OCR `{name_text}` 命中候选 `{alias_candidate.equipment_name}`",
            max(alias_candidate.score, 0.91),
        )

    if name_resolved and normalize_name_text(name_resolved) == normalize_name_text(suggested) and name_score >= 0.90:
        return SelfLabelDecision(
            name_resolved,
            "name_icon_agree",
            "名称 OCR 与图标 top1 指向同一装备",
            max(icon_confidence, name_score),
        )

    # OCR 读到泛化前缀时，不让它覆盖图标；但图标 top1 很高或重复出现时，可由我承担自标注。
    repeated = candidate_repeated_support(candidates, suggested)
    if suggested and "name_icon_conflict" in review_reason and icon_confidence >= 0.95:
        return SelfLabelDecision(
            suggested,
            "strong_icon_over_weak_name_conflict",
            "图标置信度极高，名称 OCR 为弱冲突",
            icon_confidence,
        )

    if suggested and icon_status == "success" and icon_confidence >= 0.88 and "name_icon_conflict" not in review_reason:
        return SelfLabelDecision(suggested, "strong_icon", "图标 top1 置信度接近高可信阈值", icon_confidence)

    distinct_margin = first_distinct_icon_margin(candidates, suggested)
    if (
        suggested
        and icon_status == "success"
        and icon_confidence >= 0.84
        and distinct_margin >= 0.055
        and "name_icon_conflict" not in review_reason
    ):
        return SelfLabelDecision(
            suggested,
            "distinct_icon_margin",
            f"图标 top1 与第一个不同装备候选分差 {distinct_margin:.3f}，仅用于 Codex 自标注减负",
            max(icon_confidence, 0.87),
        )

    if suggested and repeated >= 2 and icon_confidence >= 0.74 and "name_icon_conflict" not in review_reason:
        return SelfLabelDecision(
            suggested,
            "repeated_icon_candidate",
            f"同一装备在 top-N 中重复出现 {repeated} 次",
            max(icon_confidence, 0.86),
        )

    if suggested and name_resolved and name_score >= 0.90 and "name_icon_conflict" not in review_reason:
        return SelfLabelDecision(name_resolved, "strong_name", "名称 OCR 强命中装备库", name_score)

    return SelfLabelDecision("", "unresolved", "证据不足，暂不写入自标注", 0.0)


# ============================================================
# 🧾 第五部分：输出文件
# ============================================================

def build_output_dir(output_root: Path, output_name: str) -> Path:
    """
    构造自标注输出目录。

    输入：
        output_root/output_name。
    输出：
        review/self_label_xxx。
    使用示例：
        out = build_output_dir(Path("review"), "")
    """
    name = output_name.strip() or f"self_label_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return output_root / name


def write_self_labeled_exp(path: Path, rows: Sequence[Mapping[str, str]], decisions: Mapping[Tuple[str, str], SelfLabelDecision]) -> None:
    """
    写出 Codex 自标注 exp。

    输入：
        所有 CSV 行和决策。
    输出：
        self_labeled_exp.txt。
    使用示例：
        write_self_labeled_exp(path, rows, decisions)
    """
    lines: List[str] = [
        "collection_next Codex 自标注稿",
        "============================",
        "",
        "说明：",
        "1. 这是 Codex 根据图标、名称 OCR、候选列表和历史标注生成的自标注。",
        "2. 它不是用户人工标注，不会写入 master_human_labels.csv。",
        "3. accepted_equipment_name 已尽量由 Codex 填好；unresolved 单独列在 unresolved_minimal_review.txt。",
        "",
    ]
    current_filename = ""
    for row in rows:
        if not parse_bool(row.get("selected")):
            continue
        filename = str(row.get("filename", "") or "").strip()
        card_no = str(row.get("card_no", "") or "").strip()
        decision = decisions[(filename, card_no)]
        if filename != current_filename:
            if current_filename:
                lines.append("")
            current_filename = filename
            lines.append(f"[{filename}]")
        lines.extend(
            [
                f"card_{int(card_no):02d}.accepted_equipment_name: {decision.accepted_equipment_name}",
                f"card_{int(card_no):02d}.self_label_decision: {decision.decision}",
                f"card_{int(card_no):02d}.self_label_reason: {decision.reason}",
                f"card_{int(card_no):02d}.suggested: {row.get('suggested_equipment_name', '')}",
                f"card_{int(card_no):02d}.name_ocr: {row.get('name_ocr_text', '')}",
                f"card_{int(card_no):02d}.icon_confidence: {row.get('icon_confidence', '')}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_minimal_review(path: Path, rows: Sequence[Mapping[str, str]], decisions: Mapping[Tuple[str, str], SelfLabelDecision]) -> None:
    """
    只写真正未解决的极小复核清单。

    输入：
        所有 CSV 行和决策。
    输出：
        unresolved_minimal_review.txt。
    使用示例：
        write_minimal_review(path, rows, decisions)
    """
    unresolved = [
        row
        for row in rows
        if parse_bool(row.get("selected"))
        and decisions[(str(row.get("filename", "")).strip(), str(row.get("card_no", "")).strip())].decision == "unresolved"
    ]
    lines = [
        "真正未解决的卡片",
        "================",
        "",
        "这些我没有强行填，因为证据不足；后续优先用更多截图/属性 OCR/装备页截图解决。",
        "你现在可以先不管这个文件。",
        "",
        f"unresolved_count: {len(unresolved)}",
        "",
    ]
    for row in unresolved:
        card_no = int(str(row.get("card_no", "0") or "0"))
        lines.extend(
            [
                f"[{row.get('filename', '')} card_{card_no:02d}]",
                f"suggested: {row.get('suggested_equipment_name', '')}",
                f"icon_status: {row.get('icon_status', '')}",
                f"icon_confidence: {row.get('icon_confidence', '')}",
                f"name_ocr: {row.get('name_ocr_text', '')}",
                f"name_candidates: {row.get('name_resolve_candidates', '')}",
                f"icon_candidates: {row.get('icon_top_candidates', '')}",
                f"review_reason: {row.get('review_reason', '')}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_decision_csv(path: Path, rows: Sequence[Mapping[str, str]], decisions: Mapping[Tuple[str, str], SelfLabelDecision]) -> None:
    """
    写出结构化自标注 CSV。

    输入：
        所有 CSV 行和决策。
    输出：
        self_labeled_cards.csv。
    使用示例：
        write_decision_csv(path, rows, decisions)
    """
    fieldnames = [
        "filename",
        "card_no",
        "accepted_equipment_name",
        "self_label_decision",
        "self_label_confidence",
        "self_label_reason",
        "suggested_equipment_name",
        "icon_status",
        "icon_confidence",
        "name_ocr_text",
        "name_resolve_equipment_name",
        "name_resolve_score",
        "review_reason",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            if not parse_bool(row.get("selected")):
                continue
            key = (str(row.get("filename", "")).strip(), str(row.get("card_no", "")).strip())
            decision = decisions[key]
            writer.writerow(
                {
                    "filename": row.get("filename", ""),
                    "card_no": row.get("card_no", ""),
                    "accepted_equipment_name": decision.accepted_equipment_name,
                    "self_label_decision": decision.decision,
                    "self_label_confidence": f"{decision.confidence:.6f}",
                    "self_label_reason": decision.reason,
                    "suggested_equipment_name": row.get("suggested_equipment_name", ""),
                    "icon_status": row.get("icon_status", ""),
                    "icon_confidence": row.get("icon_confidence", ""),
                    "name_ocr_text": row.get("name_ocr_text", ""),
                    "name_resolve_equipment_name": row.get("name_resolve_equipment_name", ""),
                    "name_resolve_score": row.get("name_resolve_score", ""),
                    "review_reason": row.get("review_reason", ""),
                }
            )


def summarize(rows: Sequence[Mapping[str, str]], decisions: Mapping[Tuple[str, str], SelfLabelDecision]) -> Dict[str, object]:
    """
    汇总自标注结果。

    输入：
        所有 CSV 行和决策。
    输出：
        JSON 友好的汇总字典。
    使用示例：
        payload = summarize(rows, decisions)
    """
    selected_rows = [row for row in rows if parse_bool(row.get("selected"))]
    counts: Dict[str, int] = {}
    for row in selected_rows:
        key = (str(row.get("filename", "")).strip(), str(row.get("card_no", "")).strip())
        decision = decisions[key].decision
        counts[decision] = counts.get(decision, 0) + 1
    accepted_count = 0
    unresolved_count = 0
    excluded_count = 0
    for row in selected_rows:
        decision = decisions[(str(row.get("filename", "")).strip(), str(row.get("card_no", "")).strip())]
        if decision.accepted_equipment_name:
            accepted_count += 1
        if decision.decision == "unresolved":
            unresolved_count += 1
        if decision.decision.startswith("visual_reject"):
            excluded_count += 1
    return {
        "selected_cards": len(selected_rows),
        "self_labeled_cards": accepted_count,
        "excluded_cards": excluded_count,
        "unresolved_cards": unresolved_count,
        "decision_counts": counts,
        "note": "self_labeled_cards 是 Codex 自标注，不等同人工 100% 标注；unresolved 可先暂不处理。",
    }


# ============================================================
# 🚀 第六部分：命令入口
# ============================================================

def main() -> int:
    """
    生成 collection_next 自标注输出。

    输入：
        v2_prelabel_results.csv。
    输出：
        self_labeled_exp.txt / self_labeled_cards.csv / unresolved_minimal_review.txt / summary.json。
    使用示例：
        python auto_self_label_collection.py --source-dir img_out/run_xxx
    """
    args = parse_args()
    source_dir = args.source_dir.resolve()
    results_csv = source_dir / RESULTS_CSV_NAME
    if not results_csv.exists():
        print(f"找不到机器结果 CSV: {results_csv}")
        return 1

    with results_csv.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    previous_human = {} if bool(args.ignore_human_archive) else load_previous_human_labels(args.human_archive_csv.resolve())
    user_review_labels = load_user_review_exp(args.user_review_exp.resolve() if args.user_review_exp is not None else None)

    decisions: Dict[Tuple[str, str], SelfLabelDecision] = {}
    for row in rows:
        if not parse_bool(row.get("selected")):
            continue
        key = (str(row.get("filename", "")).strip(), str(row.get("card_no", "")).strip())
        decisions[key] = decide_self_label(
            row,
            previous_human,
            user_review_labels,
            use_visual_overrides=not bool(args.disable_visual_overrides),
        )

    output_dir = build_output_dir(args.output_root.resolve(), args.output_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_self_labeled_exp(output_dir / "self_labeled_exp.txt", rows, decisions)
    write_minimal_review(output_dir / "unresolved_minimal_review.txt", rows, decisions)
    write_decision_csv(output_dir / "self_labeled_cards.csv", rows, decisions)
    summary = summarize(rows, decisions)
    (output_dir / "self_label_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
