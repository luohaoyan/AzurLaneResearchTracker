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
import logging
from pathlib import Path
from types import ModuleType

import pytest

from core.state.runtime_state import get_runtime_state_manager
from core.utils.path_manager import PathManager
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


def test_automation_bridge_runs_design_chart_flow_with_resume_cursor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """设计图完整流程应自动读取最新 summary 的断点游标并返回结构化结果。"""
    work_dir = tmp_path / "workdir"
    summary_path = work_dir / "automation" / "equipment_page" / "design_rarity_runs" / "run_demo" / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("{\"resume_cursor\": 1, \"next_resume_cursor\": 3}", encoding="utf-8")

    class FakeDesignReadyResult:
        success = True
        status = "ready"
        message = "已切到设计图页"
        detail = "page_type=design"
        warnings = ("design-tab-check",)

        def __init__(self) -> None:
            self.payload = {"design_tab_confirmed": True}

        def to_dict(self) -> dict[str, object]:
            return {
                "success": self.success,
                "status": self.status,
                "message": self.message,
                "detail": self.detail,
                "payload": self.payload,
                "warnings": list(self.warnings),
            }

    class FakeDesignSessionResult:
        success = True
        status = "ready"
        message = "设计图稀有度流程完成"
        detail = "run ok"
        warnings = ("sweep-ok",)

        def __init__(self) -> None:
            self.run_dir = str(tmp_path / "run")
            self.summary_path = str(tmp_path / "run" / "summary.json")

        def to_dict(self) -> dict[str, object]:
            return {
                "success": self.success,
                "status": self.status,
                "message": self.message,
                "detail": self.detail,
                "payload": {"frames": []},
                "warnings": list(self.warnings),
                "run_dir": self.run_dir,
                "summary_path": self.summary_path,
            }

    class FakeEquipmentPageApi:
        def ensure_warehouse_design_page_ready(self, task_context=None):
            return FakeDesignReadyResult()

        def capture_design_rarity_sequence(self, *, rarities=None, resume_cursor=0, task_context=None):
            assert resume_cursor == 3
            assert tuple(rarities or ())[:2] == ("common", "rare")
            return FakeDesignSessionResult()

        def load_design_rarity_resume_cursor(self, summary_path: str | Path) -> int:
            assert Path(summary_path) == summary_path.resolve()
            return 3

    monkeypatch.setattr(PathManager, "get_work_dir", lambda: work_dir)
    monkeypatch.setattr("ui.automation_bridge.get_equipment_page_adb_api", lambda: FakeEquipmentPageApi())

    bridge = AutomationBridge()
    caplog.set_level(logging.INFO)
    result = bridge.run_design_chart_flow()

    assert result.success is True
    assert result.status == "ready"
    assert result.payload is not None
    assert result.payload["resume_cursor_loaded"] == 3
    assert "resume_cursor=3" in result.detail
    messages = [record.message for record in caplog.records if "[设计图]" in record.message]
    assert any("桥接任务开始" in message for message in messages)
    assert any("断点解析完成" in message for message in messages)
    assert any("桥接任务完成" in message for message in messages)
    assert not any('"frames"' in message or '"payload"' in message for message in messages)
    assert get_runtime_state_manager().get_full_state()["task"]["kind"] == "idle"
