#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🧪 自动化桥接测试 (test_automation_bridge.py)   ║
║                                                              ║
║  【测试目标】确认 crawler 模块缺失、成功和异常路径都不崩溃。   ║
║  【类比理解】像港区联络测试，外部船没到也要优雅汇报。          ║
║  【数据流说明】AutomationBridge → RuntimeState → Result。     ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import sys
from types import ModuleType

import pytest

from core.state.runtime_state import get_runtime_state_manager
from ui.automation_bridge import AutomationBridge


# ============================================================
# 🧩 第二部分：pytest fixtures
# ============================================================

@pytest.fixture(autouse=True)
def reset_runtime_state() -> None:
    """每个桥接测试前后都重置运行期状态。"""
    manager = get_runtime_state_manager()
    manager.reset()
    yield
    manager.reset()


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_automation_bridge_returns_missing_when_crawler_module_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """crawler 模块不存在时应返回 missing，不向 GUI 抛异常。"""
    monkeypatch.setattr(AutomationBridge, "CRAWLER_MODULE_CANDIDATES", ("missing.alrt_crawler",))
    bridge = AutomationBridge()

    result = bridge.run_crawler_update()

    assert result.success is False
    assert result.status == "missing"
    assert "尚未接入" in result.message
    assert get_runtime_state_manager().get_full_state()["task"]["kind"] == "error"


def test_automation_bridge_calls_fake_crawler_successfully(monkeypatch: pytest.MonkeyPatch) -> None:
    """模块存在且提供 run_update 时，应调用入口并返回成功。"""
    module = ModuleType("fake_crawler_success")
    module.run_update = lambda: {
        "message": "fake crawler done",
        "equipment_count": 754,
        "image_count": 752,
        "phase_count": 10,
        "equipment_library_path": "data/equipment_library.csv",
        "equipment_images_path": "data/equipment_images.csv",
        "research_phases_path": "data/research_phases.csv",
        "warnings": [],
    }
    monkeypatch.setitem(sys.modules, "fake_crawler_success", module)
    monkeypatch.setattr(AutomationBridge, "CRAWLER_MODULE_CANDIDATES", ("fake_crawler_success",))
    bridge = AutomationBridge()

    result = bridge.run_crawler_update()

    assert result.success is True
    assert result.status == "success"
    assert result.message == "fake crawler done"
    assert result.payload is not None
    assert result.payload["equipment_count"] == 754
    assert "装备: 754" in result.detail
    assert "装备表: data/equipment_library.csv" in result.detail
    assert "告警: 0" in result.detail
    assert get_runtime_state_manager().get_full_state()["task"]["kind"] == "idle"


def test_automation_bridge_catches_crawler_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """crawler 入口执行异常时应返回 error 并写入运行期错误状态。"""
    module = ModuleType("fake_crawler_error")

    def broken_update() -> None:
        raise RuntimeError("site changed")

    module.run_update = broken_update
    monkeypatch.setitem(sys.modules, "fake_crawler_error", module)
    monkeypatch.setattr(AutomationBridge, "CRAWLER_MODULE_CANDIDATES", ("fake_crawler_error",))
    bridge = AutomationBridge()

    result = bridge.run_crawler_update()

    assert result.success is False
    assert result.status == "error"
    assert "执行失败" in result.message
    assert "site changed" in result.detail
    assert get_runtime_state_manager().get_full_state()["task"]["kind"] == "error"
