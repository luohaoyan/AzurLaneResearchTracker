#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      🧪 equipment_icon_matcher_v2 人工档案测试              ║
║                                                              ║
║  【测试目标】确认 test_img 复核默认不会泄漏进训练档案。       ║
║  【类比理解】像考试卷答案不能提前塞进复习资料里。              ║
║  【数据流说明】review_iterations → human_label_archive。      ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import importlib.util
import sys
from pathlib import Path
from typing import Any


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAB_SCRIPT = PROJECT_ROOT / "ocr_training_lab" / "equipment_icon_matcher_v2" / "build_human_label_archive.py"


def _load_lab_module() -> Any:
    """按文件路径加载人工档案脚本，避免把 lab 目录改成正式包。"""
    spec = importlib.util.spec_from_file_location("build_human_label_archive_for_test", LAB_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_exp(path: Path, accepted_name: str) -> None:
    """写一份最小人工 exp。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "[v2_ultra_rare_scroll_001.png]",
                f"card_01.accepted_equipment_name:{accepted_name}",
                "",
            ]
        ),
        encoding="utf-8",
    )


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_collect_human_source_paths_skips_testimg_iterations_by_default(tmp_path: Path) -> None:
    """独立测试图复核默认不能混入训练档案，避免后续准确率虚高。"""
    lab = _load_lab_module()
    lab.SCRIPT_DIR = tmp_path
    train_exp = tmp_path / "review_iterations" / "iter_train" / "to_label" / "v2_review_todo_exp.txt"
    test_exp = tmp_path / "review_iterations" / "iter_testimg_guard" / "to_label" / "v2_review_todo_exp.txt"
    _write_exp(train_exp, "试作型四联装152mm主炮#T0")
    _write_exp(test_exp, "试作型三联装234mm主炮#T0")

    default_sources = lab.collect_human_source_paths([])
    included_sources = lab.collect_human_source_paths([], include_test_iterations=True)

    assert [path for path, _kind, _priority in default_sources] == [train_exp.resolve()]
    assert {path for path, _kind, _priority in included_sources} == {train_exp.resolve(), test_exp.resolve()}


def test_build_archive_can_include_testimg_only_when_explicit(tmp_path: Path) -> None:
    """只有显式允许时，test_img 复核才会作为训练样本进入 master。"""
    lab = _load_lab_module()
    lab.SCRIPT_DIR = tmp_path
    test_exp = tmp_path / "review_iterations" / "iter_testimg_guard" / "to_label" / "v2_review_todo_exp.txt"
    _write_exp(test_exp, "试作型三联装234mm主炮#T0")

    skipped = lab.build_archive(tmp_path / "archive_skip", [], include_test_iterations=False)
    included = lab.build_archive(tmp_path / "archive_include", [], include_test_iterations=True)

    assert skipped["master_labels"] == 0
    assert skipped["include_test_iterations"] is False
    assert included["master_labels"] == 1
    assert included["include_test_iterations"] is True


def test_build_archive_strips_accidental_equipment_id_prefix_from_name(tmp_path: Path) -> None:
    """人工 accepted 名称里偶尔混入 G0001: 前缀时，应自动清理掉再归档。"""
    lab = _load_lab_module()
    lab.SCRIPT_DIR = tmp_path
    train_exp = tmp_path / "review_iterations" / "iter_train" / "completed" / "v2_review_completed_exp.txt"
    _write_exp(train_exp, "S9-001:试作舰载型Ta 152C-1/R14#T0")

    summary = lab.build_archive(tmp_path / "archive", [])

    assert summary["master_labels"] == 1
    master_csv = (tmp_path / "archive" / "master_human_labels.csv").read_text(encoding="utf-8-sig")
    assert "S9-001:试作舰载型Ta 152C-1/R14#T0" not in master_csv
    assert "试作舰载型Ta 152C-1/R14#T0" in master_csv
