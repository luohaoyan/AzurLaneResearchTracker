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

from ui.ui_config import (
    DEFAULT_APPEARANCE_UI_CONFIG,
    DEFAULT_RESEARCH_PROGRESS_UI_CONFIG,
    DEFAULT_SECRETARY_LINES_UI_CONFIG,
    UiConfigManager,
    get_ui_config_manager,
)


# ============================================================
# 🧪 第二部分：测试用例
# ============================================================

def test_ui_config_manager_loads_research_progress_json() -> None:
    """UI 配置管理器应能读取科研页配置，并保留秘书舰和目标对话字段。"""
    config = get_ui_config_manager().get_research_progress_config()

    assert "phase_settings" in config
    assert "phase_start_dates" in config
    assert "phase_targets" in config
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


def test_ui_config_manager_loads_appearance_json() -> None:
    """UI 配置管理器应能读取外观配置，并保留默认皮肤和表格密度字段。"""
    config = get_ui_config_manager().get_appearance_config()

    assert config["active_skin"]
    assert "table_density" in config
    assert "custom_background" in config
    assert "skin_notes" in config
    assert "harbor_night" in config["skin_notes"]
    assert "dragon_empery" in config["skin_notes"]


def test_ui_config_manager_saves_active_skin_and_can_restore() -> None:
    """保存当前皮肤时应写入 appearance.json，并允许测试结束后恢复原配置。"""
    manager = get_ui_config_manager()
    original_config = manager.get_appearance_config()

    try:
        manager.save_active_skin("iron_blood")
        updated = manager.get_appearance_config()

        assert updated["active_skin"] == "iron_blood"
    finally:
        manager.config_loader.save_config("ui", "appearance", original_config)


def test_ui_config_manager_appearance_defaults_merge_nested_notes() -> None:
    """外观配置缺少 skin_notes 子字段时，应能回退到默认说明。"""
    merged = UiConfigManager._merge_dicts(
        DEFAULT_APPEARANCE_UI_CONFIG,
        {
            "active_skin": "sakura_mist",
            "skin_notes": {
                "sakura_mist": "测试明亮皮肤",
            },
        },
    )

    assert merged["active_skin"] == "sakura_mist"
    assert merged["skin_notes"]["sakura_mist"] == "测试明亮皮肤"
    assert "harbor_night" in merged["skin_notes"]
    assert "custom_background" in merged


def test_ui_config_manager_saves_phase_target_and_setting() -> None:
    """科研目标数量应按 PR 期数独立保存到 phase_settings。"""
    manager = get_ui_config_manager()
    original_config = manager.get_research_progress_config()

    try:
        manager.save_phase_target_count(8, 4)
        manager.save_phase_start_date(8, "2026-06-01")
        setting = manager.get_phase_setting(8)
        config = manager.get_research_progress_config()

        assert setting["target"] == 4
        assert setting["start_date"] == "2026-06-01"
        assert config["phase_settings"]["PR8"]["target"] == 4
        assert config["phase_settings"]["PR8"]["start_date"] == "2026-06-01"
    finally:
        manager.config_loader.save_config("ui", "research_progress", original_config)


def test_ui_config_manager_loads_secretary_lines_json() -> None:
    """UI 配置管理器应能读取秘书舰台词配置，为后续爬虫补全台词预留。"""
    config = get_ui_config_manager().get_secretary_lines_config()

    assert config["active_secretary"]
    assert config["dialog_duration_ms"] <= 3000
    assert "secretaries" in config
    assert "default" in config["secretaries"]
    assert config["secretaries"]["default"]["lines"]["target_changed"]


def test_ui_config_manager_secretary_lines_defaults_merge() -> None:
    """秘书舰台词配置缺少场景时，应能回退到默认台词字段。"""
    merged = UiConfigManager._merge_dicts(
        DEFAULT_SECRETARY_LINES_UI_CONFIG,
        {
            "active_secretary": "test",
            "secretaries": {
                "test": {
                    "name": "测试秘书舰",
                    "lines": {
                        "target_changed": ["测试台词"],
                    },
                },
            },
        },
    )

    assert merged["active_secretary"] == "test"
    assert merged["secretaries"]["test"]["name"] == "测试秘书舰"
    assert merged["secretaries"]["default"]["lines"]["idle"]
