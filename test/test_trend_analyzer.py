#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              📈 历史趋势分析测试 (test_trend_analyzer.py)    ║
║                                                              ║
║  【测试目标】确认历史用户记录能转换为装备数量等趋势序列。     ║
║  【类比理解】这组测试像翻查港区日记，核对每天统计是否正确。   ║
║  【数据流说明】临时 user_records → TrendAnalyzer → 断言。     ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from pathlib import Path
from typing import Generator

import pytest

from core.calculation.trend_analyzer import TrendAnalyzer, get_trend_analyzer
from core.calculation.user_data_manager import get_user_data_manager


# ============================================================
# 🧩 第二部分：pytest fixtures
# ============================================================

@pytest.fixture()
def trend_analyzer_with_history(tmp_path: Path) -> Generator[TrendAnalyzer, None, None]:
    """使用临时 user_records 目录构造历史记录，避免污染真实用户数据。"""
    user_data_manager = get_user_data_manager()
    old_records_dir = user_data_manager._records_dir
    temp_records_dir = tmp_path / "user_records"
    temp_records_dir.mkdir(parents=True, exist_ok=True)
    user_data_manager._records_dir = temp_records_dir

    user_data_manager.update_batch({
        "S1-001": {"equipment_count": 1, "fragment_count": 20},
        "S1-002": {"equipment_count": 0, "fragment_count": 10},
        "S2-001": {"equipment_count": 1, "fragment_count": 0},
    }, "2026-07-01")
    user_data_manager.update_batch({
        "S1-001": {"equipment_count": 2, "fragment_count": 30},
        "S1-002": {"equipment_count": 1, "fragment_count": 15},
    }, "2026-07-02")
    user_data_manager.update_batch({
        "S1-001": {"equipment_count": 3, "fragment_count": 0},
    }, "2026-07-03")

    analyzer = get_trend_analyzer()
    analyzer._user_data_manager = user_data_manager
    try:
        yield analyzer
    finally:
        user_data_manager._records_dir = old_records_dir
        analyzer._user_data_manager = user_data_manager


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_trend_analyzer_reports_available_date_range(trend_analyzer_with_history: TrendAnalyzer) -> None:
    """趋势分析器应能返回历史记录日期范围。"""
    date_range = trend_analyzer_with_history.get_available_date_range()

    assert date_range == {"start": "2026-07-01", "end": "2026-07-03", "count": 3}


def test_trend_analyzer_calculates_phase_equipment_metrics(
    trend_analyzer_with_history: TrendAnalyzer,
) -> None:
    """按科研期筛选时，应只统计该期装备的数量、碎片、等值分和欧非值。"""
    rows = trend_analyzer_with_history.get_trend("2026-07-01", "2026-07-02", phase_number=1)

    assert len(rows) == 2
    assert rows[0]["date"] == "2026-07-01"
    assert rows[0]["equipment_count"] == 1
    assert rows[0]["fragment_count"] == 30
    assert rows[0]["equivalent_score"] == 55
    assert rows[0]["luck_value"] == 0.0
    assert rows[0]["luck_level"] == "极非"

    assert rows[1]["date"] == "2026-07-02"
    assert rows[1]["equipment_count"] == 3
    assert rows[1]["fragment_count"] == 45
    assert rows[1]["equivalent_score"] == 120
    assert rows[1]["luck_value"] == 0.0


def test_trend_analyzer_calculates_all_equipment_metrics(
    trend_analyzer_with_history: TrendAnalyzer,
) -> None:
    """不指定科研期时，应统计当天全部用户记录。"""
    rows = trend_analyzer_with_history.get_trend("2026-07-01", "2026-07-01")

    assert len(rows) == 1
    assert rows[0]["equipment_count"] == 2
    assert rows[0]["fragment_count"] == 30
    assert rows[0]["equivalent_score"] == 80
    assert rows[0]["luck_value"] is not None


def test_trend_analyzer_metric_series(trend_analyzer_with_history: TrendAnalyzer) -> None:
    """单指标序列应只返回日期和值，便于后续 QtCharts 绘制折线。"""
    series = trend_analyzer_with_history.get_metric_series(
        "equipment_count",
        "2026-07-01",
        "2026-07-02",
        phase_number=1,
    )

    assert series == [
        {"date": "2026-07-01", "value": 1},
        {"date": "2026-07-02", "value": 3},
    ]


def test_trend_analyzer_multi_metric_series(trend_analyzer_with_history: TrendAnalyzer) -> None:
    """多指标序列应一次返回多条曲线数据，便于历史趋势页叠加展示。"""
    series_map = trend_analyzer_with_history.get_multi_metric_series(
        ["equipment_count", "fragment_count", "luck_value"],
        "2026-07-01",
        "2026-07-02",
        phase_number=1,
    )

    assert set(series_map) == {"equipment_count", "fragment_count", "luck_value"}
    assert series_map["equipment_count"] == [
        {"date": "2026-07-01", "value": 1},
        {"date": "2026-07-02", "value": 3},
    ]
    assert series_map["fragment_count"] == [
        {"date": "2026-07-01", "value": 30},
        {"date": "2026-07-02", "value": 45},
    ]
    assert series_map["luck_value"][0]["value"] == 0.0


def test_trend_analyzer_metric_specs_are_user_facing(trend_analyzer_with_history: TrendAnalyzer) -> None:
    """趋势指标定义应只包含用户可理解的名称和图表颜色，不暴露装备内部字段。"""
    specs = trend_analyzer_with_history.get_metric_specs()

    assert [spec.key for spec in specs] == [
        "equipment_count",
        "fragment_count",
        "equivalent_score",
        "luck_value",
    ]
    assert all(spec.title for spec in specs)
    assert all(spec.color.startswith("#") for spec in specs)


def test_trend_analyzer_rejects_invalid_query(trend_analyzer_with_history: TrendAnalyzer) -> None:
    """趋势查询应拒绝非法日期和未知指标，避免 GUI 传入坏参数后静默失败。"""
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        trend_analyzer_with_history.get_trend("2026-99-99")

    with pytest.raises(ValueError, match="开始日期不能晚于结束日期"):
        trend_analyzer_with_history.get_trend("2026-07-03", "2026-07-01")

    with pytest.raises(ValueError, match="未知趋势指标"):
        trend_analyzer_with_history.get_metric_series("unknown_metric")

    with pytest.raises(ValueError, match="未知趋势指标"):
        trend_analyzer_with_history.get_multi_metric_series(["equipment_count", "unknown_metric"])
