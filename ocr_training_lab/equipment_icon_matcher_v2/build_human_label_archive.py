#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      equipment_icon_matcher_v2 人工标注总档案构建器          ║
║                                                              ║
║  【一句话解释】把用户真正确认过的标注集中归档，供后续回填。   ║
║  【类比理解】像一本“人工答案母本”，新卷子只从母本抄答案。    ║
║  【数据流说明】人工 exp → human_label_archive → 下一轮 todo。 ║
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# ============================================================
# 🧱 第二部分：常量与数据对象
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ARCHIVE_DIR = SCRIPT_DIR / "human_label_archive"


@dataclass(frozen=True)
class HumanLabel:
    """
    一条人工确认装备名。

    输入：
        filename/card_no/equipment_name/source。
    输出：
        总档案 CSV/JSON 中的一行。
    使用示例：
        label = HumanLabel("v2_rare_scroll_1.png", 3, "维修工具#T2", "completed", "path")
    """

    filename: str
    card_no: int
    accepted_equipment_name: str
    source_kind: str
    source_path: str
    source_mtime: float
    priority: int

    @property
    def key(self) -> Tuple[str, int]:
        """返回同图同卡片的稳定键。"""
        return (self.filename, self.card_no)

    def to_dict(self) -> Dict[str, Any]:
        """转换成可写 CSV/JSON 的字典。"""
        return {
            "filename": self.filename,
            "card_no": int(self.card_no),
            "accepted_equipment_name": self.accepted_equipment_name,
            "source_kind": self.source_kind,
            "source_path": self.source_path,
            "source_mtime": float(self.source_mtime),
            "priority": int(self.priority),
        }


# ============================================================
# 🏗️ 第三部分：参数与来源收集
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。

    输入：
        命令行参数。
    输出：
        argparse.Namespace。
    使用示例：
        python build_human_label_archive.py
    """
    parser = argparse.ArgumentParser(description="构建 equipment_icon_matcher_v2 人工标注总档案。")
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR, help="总档案输出目录。")
    parser.add_argument("--extra-source", type=Path, action="append", default=[], help="额外人工 exp 来源，可重复传入。")
    parser.add_argument("--include-test-iterations", action="store_true", help="显式把 iter_testimg* 复核文件也收入训练档案；默认跳过，避免测试集泄漏。")
    return parser.parse_args()


def collect_human_source_paths(
    extra_sources: Sequence[Path],
    include_test_iterations: bool = False,
) -> List[Tuple[Path, str, int]]:
    """
    收集只允许作为人工来源的 exp 文件。

    输入：
        额外来源列表，以及是否允许收集 iter_testimg*。
    输出：
        [(path, source_kind, priority)]。
    使用示例：
        paths = collect_human_source_paths([])
    """
    sources: List[Tuple[Path, str, int]] = []

    # completed 是最可信的人工作业完成版。
    for path in SCRIPT_DIR.glob("review_iterations/*/completed/*.txt"):
        if _is_test_iteration_source(path) and not include_test_iterations:
            continue
        sources.append((path, "review_completed", 100))

    # to_label 只有非空字段才会被解析；它用于保存用户正在编辑但尚未 completed 的内容。
    for path in SCRIPT_DIR.glob("review_iterations/*/to_label/v2_review_todo_exp*.txt"):
        if _is_test_iteration_source(path) and not include_test_iterations:
            continue
        sources.append((path, "review_todo_user_edit", 80))

    # 早期用户直接改过 review_only_exp；这类备份允许进入档案。
    # 注意：draft_exp 不在这里，机器预填不得进入人工档案。
    for path in SCRIPT_DIR.glob("img_out/prelabel/backups/v2_prelabel_review_only_exp*.txt"):
        sources.append((path, "legacy_review_only", 60))

    for path in extra_sources:
        if path.exists():
            sources.append((path, "manual_extra_source", 90))

    # 统一去重，保留最高优先级描述。
    best: Dict[Path, Tuple[Path, str, int]] = {}
    for path, source_kind, priority in sources:
        resolved = path.resolve()
        old = best.get(resolved)
        if old is None or priority > old[2]:
            best[resolved] = (resolved, source_kind, priority)
    return sorted(best.values(), key=lambda item: (item[2], item[0].stat().st_mtime, str(item[0])))


def _is_test_iteration_source(path: Path) -> bool:
    """
    判断人工来源是否属于 test_img 复核迭代。

    输入：
        review_iterations 下的 exp 路径。
    输出：
        True 表示默认不进入训练档案，避免独立测试集泄漏。
    使用示例：
        _is_test_iteration_source(Path("review_iterations/iter_testimg_x/to_label/v2_review_todo_exp.txt"))
    """
    parts = tuple(path.parts)
    for index, part in enumerate(parts):
        if part == "review_iterations" and index + 1 < len(parts):
            return parts[index + 1].startswith("iter_testimg")
    return False


def parse_labels_from_exp(path: Path, source_kind: str, priority: int) -> List[HumanLabel]:
    """
    从 exp 文本里解析非空 accepted_equipment_name。

    输入：
        exp 路径、来源类型和优先级。
    输出：
        HumanLabel 列表。
    使用示例：
        labels = parse_labels_from_exp(path, "review_completed", 100)
    """
    labels: List[HumanLabel] = []
    current_filename = ""
    source_mtime = path.stat().st_mtime
    for raw_line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            current_filename = line[1:-1].strip()
            continue
        if not current_filename:
            continue
        match = re.match(r"^card_(\d+)\.accepted_equipment_name\s*:\s*(.*)$", line)
        if match is None:
            continue
        accepted_name = normalize_human_equipment_name(match.group(2))
        if not accepted_name:
            continue
        labels.append(
            HumanLabel(
                filename=current_filename,
                card_no=int(match.group(1)),
                accepted_equipment_name=accepted_name,
                source_kind=source_kind,
                source_path=str(path),
                source_mtime=source_mtime,
                priority=priority,
            )
        )
    return labels


def normalize_human_equipment_name(raw_name: str) -> str:
    """
    清理人工标注里偶发的 ID 前缀。

    输入：
        raw_name，例如 "S9-001:试作舰载型Ta 152C-1/R14#T0"。
    输出：
        去掉前缀后的装备名。
    使用示例：
        normalize_human_equipment_name("G0001:液压弹射装置#T3")
    """
    value = str(raw_name or "").strip()
    value = re.sub(r"^(?:[SG]\d{1,4}(?:-\d{1,3})?)\s*:\s*", "", value, flags=re.IGNORECASE)
    return value.strip()


# ============================================================
# 🧮 第四部分：总档案合并与写出
# ============================================================

def merge_labels(labels: Iterable[HumanLabel]) -> Tuple[Dict[Tuple[str, int], HumanLabel], List[Dict[str, Any]]]:
    """
    合并人工标注；同一 key 冲突时保留高优先级/更新来源。

    输入：
        HumanLabel 迭代器。
    输出：
        (master, conflicts)。
    使用示例：
        master, conflicts = merge_labels(labels)
    """
    master: Dict[Tuple[str, int], HumanLabel] = {}
    conflicts: List[Dict[str, Any]] = []
    for label in labels:
        old = master.get(label.key)
        if old is None:
            master[label.key] = label
            continue
        if old.accepted_equipment_name == label.accepted_equipment_name:
            if (label.priority, label.source_mtime) >= (old.priority, old.source_mtime):
                master[label.key] = label
            continue

        keep_new = (label.priority, label.source_mtime) >= (old.priority, old.source_mtime)
        chosen = label if keep_new else old
        discarded = old if keep_new else label
        master[label.key] = chosen
        conflicts.append(
            {
                "filename": label.filename,
                "card_no": int(label.card_no),
                "chosen_name": chosen.accepted_equipment_name,
                "chosen_source_kind": chosen.source_kind,
                "chosen_source_path": chosen.source_path,
                "discarded_name": discarded.accepted_equipment_name,
                "discarded_source_kind": discarded.source_kind,
                "discarded_source_path": discarded.source_path,
            }
        )
    return master, conflicts


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Optional[Sequence[str]] = None) -> None:
    """
    写 CSV。

    输入：
        path/rows/fieldnames。
    输出：
        UTF-8-SIG CSV。
    使用示例：
        write_csv(path, rows)
    """
    names = list(fieldnames or sorted({key for row in rows for key in row.keys()}))
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def build_archive(
    archive_dir: Path,
    extra_sources: Sequence[Path],
    include_test_iterations: bool = False,
) -> Dict[str, Any]:
    """
    构建人工标注总档案。

    输入：
        输出目录、额外来源和是否包含 test_img 迭代。
    输出：
        summary 字典。
    使用示例：
        summary = build_archive(DEFAULT_ARCHIVE_DIR, [])
    """
    archive_dir.mkdir(parents=True, exist_ok=True)
    source_specs = collect_human_source_paths(extra_sources, include_test_iterations=include_test_iterations)
    labels: List[HumanLabel] = []
    source_rows: List[Dict[str, Any]] = []
    for path, source_kind, priority in source_specs:
        parsed = parse_labels_from_exp(path, source_kind, priority)
        labels.extend(parsed)
        source_rows.append(
            {
                "source_path": str(path),
                "source_kind": source_kind,
                "priority": int(priority),
                "labels": len(parsed),
                "source_mtime": float(path.stat().st_mtime),
            }
        )

    master, conflicts = merge_labels(labels)
    master_rows = [
        label.to_dict()
        for label in sorted(master.values(), key=lambda item: (item.filename, item.card_no))
    ]
    write_csv(
        archive_dir / "master_human_labels.csv",
        master_rows,
        (
            "filename",
            "card_no",
            "accepted_equipment_name",
            "source_kind",
            "source_path",
            "source_mtime",
            "priority",
        ),
    )
    (archive_dir / "master_human_labels.json").write_text(
        json.dumps(master_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(archive_dir / "human_label_sources.csv", source_rows)
    write_csv(archive_dir / "human_label_conflicts.csv", conflicts)
    summary = {
        "archive_dir": str(archive_dir),
        "source_files": len(source_rows),
        "parsed_labels": len(labels),
        "master_labels": len(master_rows),
        "conflicts": len(conflicts),
        "master_csv": str(archive_dir / "master_human_labels.csv"),
        "sources_csv": str(archive_dir / "human_label_sources.csv"),
        "conflicts_csv": str(archive_dir / "human_label_conflicts.csv"),
        "include_test_iterations": bool(include_test_iterations),
        "note": "该档案只收人工来源，不收 v2_prelabel_draft_exp 机器预填结果；默认跳过 iter_testimg*，避免测试集泄漏。",
    }
    (archive_dir / "human_label_archive_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


# ============================================================
# 🚀 第五部分：命令入口
# ============================================================

def main() -> int:
    """
    命令入口。

    输入：
        命令行参数。
    输出：
        进程退出码。
    使用示例：
        python build_human_label_archive.py
    """
    args = parse_args()
    summary = build_archive(args.archive_dir, args.extra_source, include_test_iterations=bool(args.include_test_iterations))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
