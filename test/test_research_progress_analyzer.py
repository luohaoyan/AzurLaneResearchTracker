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
from core.data.research_manager import get_research_manager


# ============================================================
# 🧪 第二部分：测试用例
# ============================================================

def _latest_phase_number() -> int:
    """从当前正式科研表读取最新科研期，避免测试绑定旧版本数据。"""
    return max(
        int(phase.get("phase_number", 0))
        for phase in get_research_manager().get_all()
        if int(phase.get("phase_number", 0)) > 0
    )


def _phase_with_rainbow_and_gold() -> tuple[int, str, str, int]:
    """找到一个同时包含彩装和金装的科研期，用于验证彩装目标逻辑。"""
    manager = get_research_manager()
    for phase in manager.get_all():
        phase_number = int(phase.get("phase_number", 0))
        if phase_number <= 0:
            continue
        equipments = manager.get_phase_equipment(phase_number)
        rainbow_id = next((str(eq["equipment_id"]) for eq in equipments if int(eq.get("rarity_id", 0)) == 5), "")
        gold_id = next((str(eq["equipment_id"]) for eq in equipments if int(eq.get("rarity_id", 0)) == 4), "")
        if rainbow_id and gold_id:
            return phase_number, rainbow_id, gold_id, len(equipments)
    raise AssertionError("当前科研表中没有同时包含金装和彩装的科研期")


def test_research_progress_analyzer_reports_latest_phase() -> None:
    """科研进度分析器应能识别当前最新科研期。"""
    analyzer = get_research_progress_analyzer()

    assert analyzer.get_latest_phase_number() == _latest_phase_number()


def test_research_progress_analyzer_calculates_phase_progress() -> None:
    """科研进度分析器应按科研期统计完成数、等值分、进度和欧非值。"""
    phase_number, rainbow_id, gold_id, equipment_total = _phase_with_rainbow_and_gold()
    analyzer = ResearchProgressAnalyzer()
    progress = analyzer.get_phase_progress(
        phase_number,
        input_data={
            rainbow_id: {"equipment_count": 0, "fragment_count": 25},
            gold_id: {"equipment_count": 1, "fragment_count": 0},
        },
    )

    assert progress["phase_number"] == phase_number
    assert progress["latest_phase"] == _latest_phase_number()
    assert progress["is_latest"] is (phase_number == _latest_phase_number())
    assert progress["equipment_total"] == equipment_total
    assert progress["completed_count"] == 1
    assert progress["overall_progress"] == 25.0
    assert progress["average_equipment_progress"] > 0
    assert progress["rainbow_target_count"] == 2
    assert progress["rainbow_target_fragments"] == 100
    assert progress["rainbow_total"] == 25
    assert progress["gold_total"] == 25
    assert progress["gold_rainbow_ratio"] == 1.0
    assert progress["total_score"] == 50
    assert progress["luck_value"] == 1.0
    assert progress["luck_level"] == "正常"
    assert any(row["progress"] == 50 for row in progress["equipment_rows"])
    assert any(row["progress"] == 100 for row in progress["equipment_rows"])


def test_research_progress_analyzer_uses_latest_phase_by_default() -> None:
    """不传期数时应默认展示最新科研期。"""
    analyzer = ResearchProgressAnalyzer()
    progress = analyzer.get_phase_progress(input_data={})

    assert progress["phase_number"] == _latest_phase_number()
    assert progress["is_latest"] is True
    assert progress["equipment_total"] > 0


def test_research_progress_analyzer_clamps_rainbow_target_to_twenty() -> None:
    """彩装目标应限制在 1 到 20 件之间，避免异常输入破坏 GUI 进度条。"""
    phase_number, rainbow_id, _gold_id, _equipment_total = _phase_with_rainbow_and_gold()
    analyzer = ResearchProgressAnalyzer()
    progress = analyzer.get_phase_progress(
        phase_number,
        rainbow_target_count=99,
        input_data={
            rainbow_id: {"equipment_count": 1, "fragment_count": 0},
        },
    )

    assert progress["rainbow_target_count"] == 20
    assert progress["rainbow_target_fragments"] == 1000
    assert progress["overall_progress"] == 5.0


def test_research_progress_analyzer_caps_completed_target_at_one_hundred() -> None:
    """当彩装碎片超过目标时，总体进度应固定显示为 100%。"""
    phase_number, rainbow_id, _gold_id, _equipment_total = _phase_with_rainbow_and_gold()
    analyzer = ResearchProgressAnalyzer()
    progress = analyzer.get_phase_progress(
        phase_number,
        rainbow_target_count=0,
        input_data={
            rainbow_id: {"equipment_count": 2, "fragment_count": 0},
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
