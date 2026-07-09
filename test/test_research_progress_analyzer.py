#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          📊 科研进度分析测试 (test_research_progress_analyzer.py) ║
║                                                              ║
║  【测试目标】确认科研进度分析器能把用户记录转换成进度与欧非评价。║
║  【类比理解】这组测试像核对科研档案板，确认每件装备进度挂对位置。║
║  【数据流说明】显式用户记录 → ResearchProgressAnalyzer → 断言。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from core.calculation.research_progress_analyzer import (
    ResearchProgressAnalyzer,
    get_research_progress_analyzer,
)


# ============================================================
# 🧪 第二部分：测试用例
# ============================================================

def test_research_progress_analyzer_reports_latest_phase() -> None:
    """科研进度分析器应能识别当前最新科研期。"""
    analyzer = get_research_progress_analyzer()

    assert analyzer.get_latest_phase_number() == 6


def test_research_progress_analyzer_calculates_phase_progress() -> None:
    """科研进度分析器应按科研期统计完成数、等值分、进度和欧非值。"""
    analyzer = ResearchProgressAnalyzer()
    progress = analyzer.get_phase_progress(
        1,
        input_data={
            "S1-001": {"equipment_count": 0, "fragment_count": 25},
            "S1-002": {"equipment_count": 1, "fragment_count": 0},
        },
    )

    assert progress["phase_number"] == 1
    assert progress["latest_phase"] == 6
    assert progress["is_latest"] is False
    assert progress["equipment_total"] == 2
    assert progress["completed_count"] == 1
    assert progress["overall_progress"] == 25.0
    assert progress["average_equipment_progress"] == 75
    assert progress["rainbow_target_count"] == 2
    assert progress["rainbow_target_fragments"] == 100
    assert progress["rainbow_total"] == 25
    assert progress["gold_total"] == 25
    assert progress["gold_rainbow_ratio"] == 1.0
    assert progress["total_score"] == 50
    assert progress["luck_value"] == 1.0
    assert progress["luck_level"] == "正常"
    assert [row["progress"] for row in progress["equipment_rows"]] == [50, 100]


def test_research_progress_analyzer_uses_latest_phase_by_default() -> None:
    """不传期数时应默认展示最新科研期。"""
    analyzer = ResearchProgressAnalyzer()
    progress = analyzer.get_phase_progress(input_data={})

    assert progress["phase_number"] == 6
    assert progress["is_latest"] is True
    assert progress["equipment_total"] == 2


def test_research_progress_analyzer_clamps_rainbow_target_to_twenty() -> None:
    """彩装目标应限制在 1 到 20 件之间，避免异常输入破坏 GUI 进度条。"""
    analyzer = ResearchProgressAnalyzer()
    progress = analyzer.get_phase_progress(
        1,
        rainbow_target_count=99,
        input_data={
            "S1-001": {"equipment_count": 1, "fragment_count": 0},
            "S1-002": {"equipment_count": 1, "fragment_count": 0},
        },
    )

    assert progress["rainbow_target_count"] == 20
    assert progress["rainbow_target_fragments"] == 1000
    assert progress["overall_progress"] == 5.0


def test_research_progress_analyzer_caps_completed_target_at_one_hundred() -> None:
    """当彩装碎片超过目标时，总体进度应固定显示为 100%。"""
    analyzer = ResearchProgressAnalyzer()
    progress = analyzer.get_phase_progress(
        1,
        rainbow_target_count=0,
        input_data={
            "S1-001": {"equipment_count": 2, "fragment_count": 0},
            "S1-002": {"equipment_count": 0, "fragment_count": 0},
        },
    )

    assert progress["rainbow_target_count"] == 1
    assert progress["rainbow_total"] == 100
    assert progress["overall_progress"] == 100.0


def test_research_progress_analyzer_handles_invalid_phase() -> None:
    """非法科研期应返回稳定空结构，避免 GUI 刷新时报错。"""
    analyzer = ResearchProgressAnalyzer()
    progress = analyzer.get_phase_progress(999, input_data={})

    assert progress["phase_number"] == 999
    assert progress["equipment_total"] == 0
    assert progress["equipment_rows"] == []
    assert "不存在" in progress["message"]
