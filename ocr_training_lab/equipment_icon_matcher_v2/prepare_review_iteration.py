#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      equipment_icon_matcher_v2 复核迭代准备器                ║
║                                                              ║
║  【一句话解释】把每轮机器预标注封存成独立迭代，并继承旧标注。 ║
║  【类比理解】像错题本新开一页：旧答案自动抄好，只补新错题。  ║
║  【数据流说明】实验输出 + 历史人工 exp → review_iterations。  ║
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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# ============================================================
# 🧱 第二部分：常量与数据对象
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_DIR = SCRIPT_DIR / "img_out" / "name_weight_experiments" / "top10_o086_scope_tierguard"
DEFAULT_ITERATION_ROOT = SCRIPT_DIR / "review_iterations"
DEFAULT_HUMAN_ARCHIVE_CSV = SCRIPT_DIR / "human_label_archive" / "master_human_labels.csv"

REVIEW_ONLY_NAME = "v2_prelabel_review_only_exp.txt"
REVIEW_CSV_NAME = "v2_prelabel_review.csv"
SUMMARY_JSON_NAME = "v2_prelabel_summary.json"
GUIDE_TXT_NAME = "v2_prelabel_review_guide.txt"


@dataclass(frozen=True)
class AcceptedAnnotation:
    """
    一条人工确认过的装备名称标注。

    输入：
        filename/card_no/accepted_equipment_name。
    输出：
        用于给新一轮待标注文件预填。
    使用示例：
        ann = AcceptedAnnotation("v2_rare_scroll_1.png", 4, "维修工具#T2")
    """

    filename: str
    card_no: int
    accepted_equipment_name: str
    source_path: str


# ============================================================
# 🏗️ 第三部分：参数与解析逻辑
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。

    输入：
        命令行参数。
    输出：
        argparse.Namespace。
    使用示例：
        python prepare_review_iteration.py --source-dir img_out/name_weight_experiments/top10_o086_scope_tierguard
    """
    parser = argparse.ArgumentParser(description="准备 equipment_icon_matcher_v2 的人工复核迭代目录。")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR, help="本轮机器预标注输出目录。")
    parser.add_argument("--iteration-root", type=Path, default=DEFAULT_ITERATION_ROOT, help="复核迭代根目录。")
    parser.add_argument("--previous-exp", type=Path, action="append", default=[], help="历史人工标注 exp，可重复传入。")
    parser.add_argument("--human-archive-csv", type=Path, default=DEFAULT_HUMAN_ARCHIVE_CSV, help="人工标注总档案 CSV。")
    parser.add_argument("--iteration-name", default="", help="自定义迭代目录名；默认按时间生成。")
    parser.add_argument("--include-prefilled", action="store_true", help="保留已有人工作答的卡片；默认只输出仍需人工填写的新卡。")
    parser.add_argument("--include-test-iterations", action="store_true", help="显式继承 iter_testimg* 里的标注；默认跳过，避免测试集标注影响训练迭代。")
    return parser.parse_args()


def parse_accepted_annotations(exp_path: Path) -> Dict[Tuple[str, int], AcceptedAnnotation]:
    """
    从 exp 文件里解析非空 accepted_equipment_name。

    输入：
        review_only_exp 或 draft_exp 文本。
    输出：
        (filename, card_no) → AcceptedAnnotation。
    使用示例：
        annotations = parse_accepted_annotations(Path("v2_review_todo_exp.txt"))
    """
    annotations: Dict[Tuple[str, int], AcceptedAnnotation] = {}
    if not exp_path.exists() or not exp_path.is_file():
        return annotations

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
        accepted_name = match.group(2).strip()
        if not accepted_name:
            continue
        card_no = int(match.group(1))
        annotations[(current_filename, card_no)] = AcceptedAnnotation(
            filename=current_filename,
            card_no=card_no,
            accepted_equipment_name=accepted_name,
            source_path=str(exp_path),
        )
    return annotations


def collect_previous_explicit_and_iterations(
    previous_exp_paths: Sequence[Path],
    iteration_root: Path,
    include_test_iterations: bool = False,
) -> List[Path]:
    """
    收集显式传入和历史迭代里的人工标注文件。

    输入：
        --previous-exp 列表和 review_iterations 根目录。
    输出：
        按时间排序的 exp 路径列表。
    使用示例：
        paths = collect_previous_explicit_and_iterations(args.previous_exp, root)
    """
    paths: List[Path] = []
    paths.extend(path for path in previous_exp_paths if path.exists())
    if iteration_root.exists():
        patterns = (
            "iter_*/completed/v2_review_completed_exp.txt",
            "iter_*/to_label/v2_review_todo_exp.txt",
            "iter_*/to_label/v2_review_todo_exp*.txt",
        )
        for pattern in patterns:
            for path in iteration_root.glob(pattern):
                if not path.exists():
                    continue
                if is_test_iteration_path(path) and not include_test_iterations:
                    continue
                paths.append(path)

    # 后出现的标注覆盖旧标注；所以按修改时间从旧到新合并。
    unique_paths = sorted({path.resolve() for path in paths}, key=lambda item: item.stat().st_mtime)
    return list(unique_paths)


def is_test_iteration_path(path: Path) -> bool:
    """
    判断路径是否来自 test_img 专用迭代。

    输入：
        review_iterations 下的任意路径。
    输出：
        True 表示路径所在迭代目录名以 iter_testimg 开头。
    使用示例：
        is_test_iteration_path(Path("review_iterations/iter_testimg_x/to_label/v2_review_todo_exp.txt"))
    """
    parts = tuple(path.parts)
    for index, part in enumerate(parts):
        if part == "review_iterations" and index + 1 < len(parts):
            return parts[index + 1].startswith("iter_testimg")
    return False


def merge_annotations(paths: Iterable[Path]) -> Dict[Tuple[str, int], AcceptedAnnotation]:
    """
    合并多轮人工标注，后续文件覆盖旧文件。

    输入：
        多个 exp 路径。
    输出：
        合并后的人工标注索引。
    使用示例：
        previous = merge_annotations(paths)
    """
    merged: Dict[Tuple[str, int], AcceptedAnnotation] = {}
    for path in paths:
        merged.update(parse_accepted_annotations(path))
    return merged


def load_human_archive(archive_csv_path: Path) -> Dict[Tuple[str, int], AcceptedAnnotation]:
    """
    从人工标注总档案加载历史标注。

    输入：
        human_label_archive/master_human_labels.csv。
    输出：
        (filename, card_no) → AcceptedAnnotation。
    使用示例：
        annotations = load_human_archive(Path("master_human_labels.csv"))
    """
    annotations: Dict[Tuple[str, int], AcceptedAnnotation] = {}
    if not archive_csv_path.exists():
        return annotations
    with archive_csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            filename = str(row.get("filename", "") or "").strip()
            accepted_name = str(row.get("accepted_equipment_name", "") or "").strip()
            if not filename or not accepted_name:
                continue
            try:
                card_no = int(row.get("card_no", 0) or 0)
            except (TypeError, ValueError):
                card_no = 0
            if card_no <= 0:
                continue
            annotations[(filename, card_no)] = AcceptedAnnotation(
                filename=filename,
                card_no=card_no,
                accepted_equipment_name=accepted_name,
                source_path=str(archive_csv_path),
            )
    return annotations


# ============================================================
# 🧰 第四部分：迭代文件生成
# ============================================================

def build_prefilled_review_text(
    generated_text: str,
    previous_annotations: Mapping[Tuple[str, int], AcceptedAnnotation],
    machine_hints: Optional[Mapping[Tuple[str, int], Sequence[str]]] = None,
) -> Tuple[str, int, int]:
    """
    给本轮机器生成的 review_only_exp 预填历史人工名称。

    输入：
        本轮 generated_text 和历史人工标注。
    输出：
        (新文本, 预填数量, 仍为空数量)。
    使用示例：
        text, filled, blanks = build_prefilled_review_text(raw, previous, machine_hints)
    """
    current_filename = ""
    filled_count = 0
    blank_count = 0
    output_lines: List[str] = []
    hints = machine_hints or {}
    for raw_line in generated_text.splitlines():
        if is_machine_hint_line(raw_line):
            continue
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            current_filename = line[1:-1].strip()
            output_lines.append(raw_line)
            continue

        match = re.match(r"^(card_(\d+)\.accepted_equipment_name\s*:\s*)(.*)$", raw_line)
        if match is None or not current_filename:
            output_lines.append(raw_line)
            continue

        prefix = match.group(1)
        card_no = int(match.group(2))
        current_value = match.group(3).strip()
        previous = previous_annotations.get((current_filename, card_no))
        output_lines.extend(hints.get((current_filename, card_no), ()))
        if previous is not None:
            output_lines.append(f"{prefix}{previous.accepted_equipment_name}")
            filled_count += 1
        else:
            # 没有历史人工标注时，即使机器生成稿自带 accepted，也必须清空。
            # 这是为了避免把机器猜测伪装成“用户以前填过的答案”。
            output_lines.append(prefix)
            blank_count += 1

    return "\n".join(output_lines) + "\n", filled_count, blank_count


def omit_prefilled_cards_from_review_text(
    review_text: str,
    previous_annotations: Mapping[Tuple[str, int], AcceptedAnnotation],
) -> Tuple[str, int]:
    """
    从待标注文本中移除已有人工答案的卡片。

    输入：
        已经预填过的 review_text，以及历史人工标注索引。
    输出：
        (过滤后的文本, 被移除的卡片数量)。
    使用示例：
        text, omitted = omit_prefilled_cards_from_review_text(text, archive)
    """
    current_filename = ""
    omitted_count = 0
    image_header_lines: List[str] = []
    image_body_lines: List[str] = []
    output_lines: List[str] = []

    def flush_image_section() -> None:
        """把当前图片段落写入输出；如果没有待标注卡片则整个图片段落省略。"""
        if not image_header_lines:
            return
        has_card = any(re.match(r"^(?:#\s*)?card_\d+\.", line.strip()) for line in image_body_lines)
        if has_card:
            output_lines.extend(image_header_lines)
            output_lines.extend(image_body_lines)

    for raw_line in review_text.splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            flush_image_section()
            current_filename = line[1:-1].strip()
            image_header_lines = [raw_line]
            image_body_lines = []
            continue
        if not current_filename:
            output_lines.append(raw_line)
            continue

        card_match = re.match(r"^(?:#\s*)?card_(\d+)\.", line)
        if card_match is not None:
            card_no = int(card_match.group(1))
            if (current_filename, card_no) in previous_annotations:
                if line.startswith(f"card_{card_no:02d}.accepted_equipment_name"):
                    omitted_count += 1
                continue
        image_body_lines.append(raw_line)

    flush_image_section()
    return "\n".join(output_lines).rstrip() + "\n", omitted_count


def is_machine_hint_line(raw_line: str) -> bool:
    """
    判断一行是否属于机器候选提示，可在生成下一轮 todo 时重建。

    输入：
        原始 exp 行。
    输出：
        True 表示该行是可丢弃并由本轮 JSON 重建的机器提示。
    使用示例：
        is_machine_hint_line("# card_01.image_top3:...")
    """
    return re.match(r"^#\s*card_\d+\.(?:image_top3|name_top3|attribute_top3)\s*:", raw_line.strip()) is not None


def load_machine_hints(source_dir: Path) -> Dict[Tuple[str, int], List[str]]:
    """
    从本轮机器结果中读取图像 Top3 和名称 Top3，仅作为注释提示。

    输入：
        source_dir/v2_prelabel_results.json。
    输出：
        (filename, card_no) → 注释行列表。
    使用示例：
        hints = load_machine_hints(Path("img_out/name_weight_experiments/xxx"))
    """
    results_path = source_dir / "v2_prelabel_results.json"
    if not results_path.exists():
        return {}
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    hints: Dict[Tuple[str, int], List[str]] = {}
    for image_result in payload:
        filename = str(image_result.get("filename", "") or "")
        for row in image_result.get("cards", []):
            card_no = int(row.get("card_no", 0) or 0)
            if not filename or card_no <= 0:
                continue
            prefix = f"card_{card_no:02d}"
            hints[(filename, card_no)] = [
                f"# {prefix}.image_top3:{format_human_top3(row.get('icon_top_candidates', ''))}",
                f"# {prefix}.name_top3:{format_human_name_top3(row)}",
            ]
            if row.get("attribute_rerank_status") not in ("", "disabled", None):
                hints[(filename, card_no)].append(f"# {prefix}.attribute_top3:{format_human_attribute_top3(row)}")
    return hints


def format_human_top3(candidates_text: Any) -> str:
    """把 `ID:名称:分数 | ...` 压成适合人工标注阅读的 Top3。"""
    chunks: List[str] = []
    for index, raw_part in enumerate(str(candidates_text or "").split("|")[:3], start=1):
        part = raw_part.strip()
        if not part:
            continue
        pieces = part.rsplit(":", 2)
        if len(pieces) == 3:
            equipment_id, name, score = pieces
            chunks.append(f"{index}) {equipment_id.strip()} {name.strip()} {score.strip()}")
        else:
            chunks.append(f"{index}) {part}")
    return " | ".join(chunks) if chunks else "无"


def format_human_name_top3(row: Mapping[str, Any]) -> str:
    """把名称 OCR 文本和解析候选压成适合人工标注阅读的 Top3。"""
    ocr_text = str(row.get("name_ocr_text", "") or "")
    ocr_confidence = float(row.get("name_ocr_confidence", 0.0) or 0.0)
    prefix = f'OCR="{ocr_text}" conf={ocr_confidence:.3f}'
    candidates = str(row.get("name_resolve_candidates", "") or "")
    candidate_text = format_human_top3(candidates)
    if candidate_text != "无":
        return f"{prefix} | {candidate_text}"
    resolved_name = str(row.get("name_resolve_equipment_name", "") or "")
    resolved_id = str(row.get("name_resolve_equipment_id", "") or "")
    score = float(row.get("name_resolve_score", 0.0) or 0.0)
    if resolved_name or resolved_id:
        return f"{prefix} | 1) {resolved_id} {resolved_name} {score:.3f}"
    return prefix


def format_human_attribute_top3(row: Mapping[str, Any]) -> str:
    """把属性 OCR 和属性重排候选压成适合人工阅读的 Top3。"""
    ocr_text = str(row.get("attribute_ocr_text", "") or "")
    ocr_confidence = float(row.get("attribute_ocr_confidence", 0.0) or 0.0)
    prefix = f'OCR="{ocr_text}" conf={ocr_confidence:.3f}'
    candidates = str(row.get("attribute_rerank_candidates", "") or "")
    chunks: List[str] = []
    for index, raw_part in enumerate(candidates.split("|")[:3], start=1):
        part = raw_part.strip()
        if not part:
            continue
        chunks.append(f"{index}) {part}")
    if chunks:
        return f"{prefix} | {' | '.join(chunks)}"
    return prefix


def create_iteration_dir(iteration_root: Path, requested_name: str = "") -> Path:
    """
    创建新的迭代目录。

    输入：
        迭代根目录和可选名称。
    输出：
        新建的迭代目录。
    使用示例：
        path = create_iteration_dir(Path("review_iterations"))
    """
    iteration_root.mkdir(parents=True, exist_ok=True)
    name = requested_name.strip() or f"iter_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    target = iteration_root / name
    if target.exists():
        suffix = datetime.now().strftime("%f")
        target = iteration_root / f"{name}_{suffix}"
    target.mkdir(parents=True, exist_ok=False)
    return target


def copy_if_exists(source: Path, target: Path) -> bool:
    """
    如果源文件存在则复制。

    输入：
        source/target。
    输出：
        是否复制成功。
    使用示例：
        copy_if_exists(src / "summary.json", dst / "summary.json")
    """
    if not source.exists() or not source.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def write_instruction_file(path: Path, source_dir: Path, todo_path: Path) -> None:
    """
    写出中文标注说明。

    输入：
        instruction 文件路径、源目录、待标注文件路径。
    输出：
        annotation_instructions.txt。
    使用示例：
        write_instruction_file(path, source, todo)
    """
    lines = [
        "equipment_icon_matcher_v2 本轮标注说明",
        "====================================",
        "",
        "你只需要修改本目录下的 v2_review_todo_exp.txt。",
        "",
        "标注方法：",
        "1. 打开 source/annotated_source_path.txt 里记录的 annotated 图片目录。",
        "2. 对照图片里的 card 编号，只处理 v2_review_todo_exp.txt 中出现的卡。",
        "3. 主要填写或修正 card_xx.accepted_equipment_name。",
        "4. accepted_equipment_id 可以留空；后续脚本会按装备名重新解析当前 equipment_library.csv。",
        "5. 如果看不清、被裁切、或者同名多 T 等级无法确认，就保持空白，不要强行标。",
        "",
        "本轮机器输出来源：",
        str(source_dir),
        "",
        "本轮待标注文件：",
        str(todo_path),
        "",
        "你改完后告诉 Codex：v2_review_todo_exp.txt 已完成。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare_iteration(args: argparse.Namespace) -> Dict[str, object]:
    """
    准备一轮人工复核目录。

    输入：
        argparse.Namespace。
    输出：
        manifest 字典。
    使用示例：
        manifest = prepare_iteration(args)
    """
    source_dir = args.source_dir.resolve()
    generated_review = source_dir / REVIEW_ONLY_NAME
    if not generated_review.exists():
        raise FileNotFoundError(f"本轮 review_only_exp 不存在: {generated_review}")

    previous_paths = collect_previous_explicit_and_iterations(
        args.previous_exp,
        args.iteration_root,
        include_test_iterations=bool(args.include_test_iterations),
    )
    previous_annotations = load_human_archive(args.human_archive_csv)
    previous_annotations.update(merge_annotations(previous_paths))

    iteration_dir = create_iteration_dir(args.iteration_root, args.iteration_name)
    source_snapshot_dir = iteration_dir / "source"
    to_label_dir = iteration_dir / "to_label"
    archive_dir = iteration_dir / "archive"
    source_snapshot_dir.mkdir(parents=True, exist_ok=True)
    to_label_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    copy_if_exists(generated_review, source_snapshot_dir / "v2_prelabel_review_only_exp.generated.txt")
    copy_if_exists(source_dir / REVIEW_CSV_NAME, source_snapshot_dir / REVIEW_CSV_NAME)
    copy_if_exists(source_dir / SUMMARY_JSON_NAME, source_snapshot_dir / SUMMARY_JSON_NAME)
    copy_if_exists(source_dir / GUIDE_TXT_NAME, source_snapshot_dir / GUIDE_TXT_NAME)
    (source_snapshot_dir / "annotated_source_path.txt").write_text(str(source_dir / "annotated") + "\n", encoding="utf-8")

    generated_text = generated_review.read_text(encoding="utf-8-sig", errors="replace")
    machine_hints = load_machine_hints(source_dir)
    todo_text, filled_count, blank_count = build_prefilled_review_text(generated_text, previous_annotations, machine_hints)
    omitted_prefilled_count = 0
    if not bool(args.include_prefilled):
        todo_text, omitted_prefilled_count = omit_prefilled_cards_from_review_text(todo_text, previous_annotations)
    todo_path = to_label_dir / "v2_review_todo_exp.txt"
    todo_path.write_text(todo_text, encoding="utf-8")
    write_instruction_file(to_label_dir / "annotation_instructions.txt", source_dir, todo_path)

    previous_payload = [
        {
            "filename": item.filename,
            "card_no": item.card_no,
            "accepted_equipment_name": item.accepted_equipment_name,
            "source_path": item.source_path,
        }
        for item in previous_annotations.values()
    ]
    (archive_dir / "previous_annotations.json").write_text(
        json.dumps(previous_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    manifest: Dict[str, object] = {
        "iteration_dir": str(iteration_dir),
        "source_dir": str(source_dir),
        "todo_path": str(todo_path),
        "previous_exp_paths": [str(path) for path in previous_paths],
        "human_archive_csv": str(args.human_archive_csv),
        "previous_annotation_count": len(previous_annotations),
        "machine_hint_count": len(machine_hints),
        "prefilled_count": filled_count,
        "omitted_prefilled_count": omitted_prefilled_count,
        "blank_count": blank_count,
        "annotated_source_path": str(source_dir / "annotated"),
        "include_prefilled": bool(args.include_prefilled),
        "include_test_iterations": bool(args.include_test_iterations),
        "note": "请只修改 to_label/v2_review_todo_exp.txt；默认只显示没有历史人工答案的卡，img_out/prelabel 不再作为人工标注入口。",
    }
    (iteration_dir / "iteration_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (SCRIPT_DIR / "CURRENT_REVIEW_PATH.txt").write_text(str(todo_path) + "\n", encoding="utf-8")
    return manifest


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
        python prepare_review_iteration.py
    """
    args = parse_args()
    manifest = prepare_iteration(args)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
