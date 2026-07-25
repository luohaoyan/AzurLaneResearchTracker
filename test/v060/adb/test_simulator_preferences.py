#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 v0.6.0 模拟器偏好与连接记录测试                  ║
║                                                              ║
║  【测试目标】确认用户选择和连接历史安全写入临时 JSON。        ║
║  【数据流说明】SimulatorPreferences → tmp_path/config.json。  ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

from pathlib import Path

from core.automation.simulator_preferences import SimulatorPreferences


def test_simulator_preferences_persist_selection_and_connection_history(tmp_path: Path) -> None:
    """用户选择和成功次数应能在下一次读取时恢复。"""
    preferences = SimulatorPreferences(tmp_path / "config.json")

    assert preferences.save_selection("leidian", serial="127.0.0.1:5555", port="5555")
    assert preferences.record_connection(
        simulator_key="leidian",
        simulator_name="雷电模拟器",
        serial="127.0.0.1:5555",
        port="5555",
        status="ready",
        success=True,
        message="连接成功",
    )
    assert preferences.record_connection(
        simulator_key="leidian",
        simulator_name="雷电模拟器",
        serial="127.0.0.1:5555",
        port="5555",
        status="ready",
        success=True,
    )

    loaded = preferences.load()
    selection = loaded["simulator_preferences"]
    assert selection["selection"] == "leidian"
    assert selection["serial"] == "127.0.0.1:5555"
    assert selection["port"] == "5555"
    assert selection["history"][0]["connection_count"] == 2
    assert selection["last_connection"]["last_success"] is True


def test_simulator_preferences_save_failure_is_non_fatal(tmp_path: Path) -> None:
    """JSON 目录不可写时返回 False，不向 ADB 调用方抛异常。"""
    target = tmp_path / "not_a_file"
    target.mkdir()
    preferences = SimulatorPreferences(target)

    assert preferences.save_selection("auto") is False
