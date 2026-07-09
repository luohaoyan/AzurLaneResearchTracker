#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║             🎛️ UI配置测试 (test_ui_config.py)               ║
║                                                              ║
║  【测试目标】确认 GUI 专属 JSON 配置可读取、可兜底、可供科研页使用。║
║  【类比理解】这组测试像检查港区布告板，确保文案和日期贴对位置。║
║  【数据流说明】config/ui/research_progress.json → UiConfigManager。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from ui.ui_config import DEFAULT_RESEARCH_PROGRESS_UI_CONFIG, UiConfigManager, get_ui_config_manager


# ============================================================
# 🧪 第二部分：测试用例
# ============================================================

def test_ui_config_manager_loads_research_progress_json() -> None:
    """UI 配置管理器应能读取科研页配置，并保留秘书舰和目标对话字段。"""
    config = get_ui_config_manager().get_research_progress_config()

    assert "phase_start_dates" in config
    assert "official_start_dates" in config
    assert "duration_messages" in config
    assert "secretary" in config
    assert "target_dialogs" in config
    assert "target_8_plus" in config["target_dialogs"]


def test_ui_config_manager_merges_missing_nested_defaults() -> None:
    """配置缺字段时应深度合并默认值，避免 GUI 因文案缺失报错。"""
    merged = UiConfigManager._merge_dicts(
        DEFAULT_RESEARCH_PROGRESS_UI_CONFIG,
        {
            "secretary": {
                "name": "测试秘书舰",
            },
            "target_dialogs": {
                "target_1": "测试目标 1",
            },
        },
    )

    assert merged["secretary"]["name"] == "测试秘书舰"
    assert "official_start_dates" in merged
    assert merged["secretary"]["dialog_duration_ms"] == 3600
    assert merged["target_dialogs"]["target_1"] == "测试目标 1"
    assert merged["target_dialogs"]["target_2_4"] == DEFAULT_RESEARCH_PROGRESS_UI_CONFIG["target_dialogs"]["target_2_4"]
