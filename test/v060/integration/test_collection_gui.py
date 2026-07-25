#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 v0.6.0 采集 GUI 预览确认测试                     ║
║                                                              ║
║  【测试目标】确认自动化实验室先展示预览，再由用户确认写入。   ║
║  【类比理解】像把识别清单放到桌面，指挥官点头后才登记。       ║
║  【数据流说明】按钮 → TaskManager → FakeBridge → 预览表。    ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import os
from typing import Any, Generator, Optional

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.state.runtime_state import get_runtime_state_manager
from ui.automation_bridge import AutomationBridgeResult
from ui.main_window import MainWindow
from ui.task_manager import get_gui_task_manager


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeCollectionBridge:
    """模拟 AutomationBridge 的采集与确认接口。"""

    def __init__(self) -> None:
        self.confirmed_preview_ids: list[str] = []

    def run_quick_collection(self, task_context: Optional[object] = None) -> AutomationBridgeResult:
        """返回一条待确认采集预览。"""
        record = {
            "equipment_id": "S9-001",
            "equipment_count": 2,
            "fragment_count": 35,
            "confidence": 0.94,
        }
        return AutomationBridgeResult(
            True,
            "preview_ready",
            "快速采集已生成 1 条装备记录预览，请确认后写入。",
            "预览ID=preview_gui",
            {
                "preview_id": "preview_gui",
                "requires_confirmation": True,
                "equipment_records": [record],
                "preview": {
                    "preview_id": "preview_gui",
                    "equipment_records": [record],
                    "warnings": [],
                },
            },
        )

    def confirm_collection_preview(
        self,
        preview_id: str,
        task_context: Optional[object] = None,
    ) -> AutomationBridgeResult:
        """记录确认写入请求。"""
        self.confirmed_preview_ids.append(preview_id)
        return AutomationBridgeResult(
            True,
            "success",
            "已写入 1 条装备记录。",
            "",
            {"write_result": {"total": 1, "success": 1, "failed": 0, "failed_ids": []}},
        )

    def discard_collection_preview(self, preview_id: str) -> bool:
        """模拟丢弃成功。"""
        return bool(preview_id)


def _wait_until(condition: Any, timeout_ms: int = 2500, interval_ms: int = 25) -> bool:
    """等待 Qt 事件循环推进后台任务。"""
    elapsed = 0
    while elapsed <= timeout_ms:
        if condition():
            return True
        QTest.qWait(interval_ms)
        elapsed += interval_ms
    return bool(condition())


@pytest.fixture(scope="session")
def qapp() -> Generator[QApplication, None, None]:
    """创建离屏 QApplication。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def reset_task_state() -> Generator[None, None, None]:
    """每个 GUI 用例前后清理全局任务状态。"""
    manager = get_gui_task_manager()
    runtime = get_runtime_state_manager()
    manager.reset_for_tests()
    runtime.reset()
    yield
    assert _wait_until(lambda: not manager.is_running())
    manager.reset_for_tests()
    runtime.reset()


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_automation_lab_collection_preview_must_be_confirmed(qapp: QApplication) -> None:
    """自动化实验室应先显示预览，点击确认后才调用写入接口。"""
    window = MainWindow()
    page = window.pages["automation_lab"]
    fake_bridge = FakeCollectionBridge()
    page.automation_bridge = fake_bridge
    committed: list[bool] = []
    page.collectionCommitted.connect(lambda: committed.append(True))

    page.collection_start_button.click()

    assert _wait_until(lambda: page.collection_preview_table.rowCount() == 1)
    assert page.collection_preview_table.item(0, 0).text() == "S9-001"
    assert page.collection_confirm_button.isEnabled() is True
    assert fake_bridge.confirmed_preview_ids == []

    page.collection_confirm_button.click()

    assert _wait_until(lambda: fake_bridge.confirmed_preview_ids == ["preview_gui"])
    assert _wait_until(lambda: committed == [True])
    assert page.collection_preview_table.rowCount() == 0
    assert "已写入 1 条装备记录" in page.collection_status_label.text()

    window.close()
