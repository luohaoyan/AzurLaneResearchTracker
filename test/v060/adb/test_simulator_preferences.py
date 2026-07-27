#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 v0.6.0 模拟器偏好与上下文回退测试               ║
║                                                              ║
║  【测试目标】验证 auto 选择时会复用最近一次成功连接。         ║
║  【类比理解】像程序启动时先记住上次连上的那台模拟器。          ║
║  【数据流说明】config.json → SimulatorPreferences → ADB API。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from pathlib import Path

from core.automation.adb_task_api import get_adb_task_api
from core.automation.simulator_preferences import SimulatorPreferences


# ============================================================
# 🧪 第二部分：测试用例
# ============================================================

def test_get_simulator_context_prefers_last_successful_connection(tmp_path: Path) -> None:
    """auto 选择时应优先复用上一次已成功连接的模拟器。"""
    api = get_adb_task_api()
    original_preferences = api.simulator_preferences
    preferences = SimulatorPreferences(tmp_path / "config.json")
    preferences.record_connection(
        simulator_key="leidian",
        simulator_name="雷电模拟器",
        serial="127.0.0.1:5555",
        port="5555",
        status="ready",
        success=True,
        auto_selected=True,
        message="连接成功。",
    )
    api.simulator_preferences = preferences
    try:
        context = api._get_simulator_context(simulator_key="auto")
    finally:
        api.simulator_preferences = original_preferences

    assert context["key"] == "leidian"
    assert context["name"] == "雷电模拟器"
    assert context["device_serial"] == "127.0.0.1:5555"
    assert context["default_device_serial"] == "127.0.0.1:5555"
