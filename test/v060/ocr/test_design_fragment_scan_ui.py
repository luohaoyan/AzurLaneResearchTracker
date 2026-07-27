#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 设计图扫图入口测试 (test_design_fragment_scan_ui.py) ║
║                                                              ║
║  【一句话解释】验证 UI 扫图入口与 OpenCV/OCR/NN 桥接参数。      ║
║  【类比理解】它像演练，不连接真实模拟器，只检查按钮和传令内容。║
║  【数据流说明】UI 参数 → TaskManager → AutomationBridge。       ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from pathlib import Path
from typing import Generator

import pytest
from PySide6.QtWidgets import QApplication

from core.utils.path_manager import PathManager
from ui.automation_bridge import AutomationBridge, AutomationBridgeResult
from ui.future_hooks import get_feature_hook_registry
from ui.main_window import MainWindow


# ============================================================
# 🧪 第二部分：测试夹具
# ============================================================

@pytest.fixture
def qapp() -> Generator[QApplication, None, None]:
    """创建离屏 QApplication，避免测试真正打开桌面窗口。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# ============================================================
# ✅ 第三部分：测试用例
# ============================================================

def test_design_scan_controls_stay_in_design_panel(qapp: QApplication) -> None:
    """扫图按钮和输入控件应只属于设计图面板，不再复用到模拟器连接面板。"""
    window = MainWindow(registry=get_feature_hook_registry())
    page = window.pages["automation_lab"]

    assert page.design_scan_button.text() == "扫图识别"
    assert page.design_scan_rarity_edit.text() == "super_rare"
    assert page.design_scan_resume_cursor_edit.text() == "0"
    assert page.design_scan_until_bottom_check.isChecked()
    assert page.emulator_connect_button is not page.design_flow_button
    assert page.emulator_connect_button is not page.design_scan_button

    window.close()


def test_design_scan_button_passes_rarity_and_capture_options(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """点击扫图后，UI 应把稀有度、断点、滚动和开关传给桥接层。"""
    calls: dict[str, object] = {}

    class FakeBridge:
        def run_design_fragment_scan(self, task_context=None, **kwargs) -> AutomationBridgeResult:
            calls.update(kwargs)
            return AutomationBridgeResult(
                True,
                "ready",
                "设计图扫图识别完成",
                "frames=2；final_success=2",
                {"output_dir": "fake-output"},
            )

    window = MainWindow(registry=get_feature_hook_registry())
    page = window.pages["automation_lab"]
    page.automation_bridge = FakeBridge()
    monkeypatch.setattr(
        page.task_manager,
        "start_task",
        lambda spec, runner, callback: (callback(runner(None)), True)[1],
    )

    page.design_scan_rarity_edit.setText("金")
    page.design_scan_resume_cursor_edit.setText("2")
    page.design_scan_scroll_step_edit.setText("280")
    page.design_scan_until_bottom_check.setChecked(False)
    page.design_scan_enforce_rarity_check.setChecked(True)
    page.design_scan_preview_check.setChecked(True)
    page.design_scan_button.click()

    assert calls == {
        "rarity_state": "super_rare",
        "resume_cursor": 2,
        "scroll_step_px": 280,
        "until_bottom": False,
        "enforce_rarity_filter": True,
        "generate_preview": True,
    }
    assert "设计图扫图识别完成" in page.design_scan_status_label.text()

    window.close()


def test_design_scan_rejects_multiple_rarities(qapp: QApplication) -> None:
    """扫图入口只接受一个稀有度，避免把筛选状态和识别候选混在一起。"""
    window = MainWindow(registry=get_feature_hook_registry())
    page = window.pages["automation_lab"]
    page.design_scan_rarity_edit.setText("rare elite")
    page.design_scan_button.click()

    assert "必须填写一个有效值" in page.design_scan_status_label.text()
    window.close()


def test_emulator_auto_connect_button_uses_real_adb_task(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    """模拟器连接区域的自动连接按钮应调用 adb_auto_connect，而不是设计图任务。"""
    calls: dict[str, object] = {}

    class FakeBridge:
        def run_adb_auto_connect(self, task_context=None, **kwargs) -> AutomationBridgeResult:
            calls.update(kwargs)
            return AutomationBridgeResult(
                True,
                "ready",
                "模拟器自动连接完成",
                "fake connected",
                {
                    "connection_status": "ready",
                    "simulator_name": "雷电模拟器",
                    "device_serial": "127.0.0.1:5555",
                    "port": 5555,
                },
            )

    window = MainWindow(registry=get_feature_hook_registry())
    page = window.pages["automation_lab"]
    page.automation_bridge = FakeBridge()
    monkeypatch.setattr(
        page.task_manager,
        "start_task",
        lambda spec, runner, callback: (callback(runner(None)), True)[1],
    )
    page.emulator_selector.setCurrentIndex(0)
    page.emulator_serial_edit.setText("127.0.0.1:5555")
    page.emulator_port_edit.setText("5555")
    page.emulator_connect_button.click()

    assert calls == {
        "simulator_key": "auto",
        "serial": "127.0.0.1:5555",
        "port": "5555",
    }
    assert "已连接" in page.emulator_status_label.text()
    assert "已连接" in page.emulator_status_badge.text()
    window.close()


def test_design_scan_bridge_uses_latest_workbench_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """桥接层应调用当前 ADB 工作台的采集、识别和上下文输出函数。"""
    import recognition_workbench.run_adb_design_fragment_recognition as workbench

    calls: dict[str, object] = {}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")

    def fake_capture(args):
        calls["capture_args"] = args
        return manifest_path, {"session_id": "fake-session"}

    def fake_load_manifest(path):
        calls["manifest_path"] = Path(path)
        return {
            "session_id": "fake-session",
            "page_name": "research_design_chart",
            "rarity_state": "super_rare",
            "next_resume_cursor": 4,
        }

    def fake_collect(manifest):
        return [tmp_path / "frame_000.png"], [{"frame_index": 0, "selected": True}]

    def fake_recognize(image_paths, run_dir, **kwargs):
        calls["recognition_kwargs"] = kwargs
        return {"images": 1, "detected_cards": 1, "final_success": 1, "needs_review": 0}

    def fake_write(output_dir, **kwargs):
        calls["context_output_dir"] = Path(output_dir)

    monkeypatch.setattr(workbench, "capture_adb_design_frames", fake_capture)
    monkeypatch.setattr(workbench, "load_manifest", fake_load_manifest)
    monkeypatch.setattr(workbench, "collect_frame_paths", fake_collect)
    monkeypatch.setattr(workbench, "run_recognition_for_images", fake_recognize)
    monkeypatch.setattr(workbench, "write_adb_context", fake_write)
    monkeypatch.setattr(PathManager, "get_project_root", lambda: tmp_path)

    result = AutomationBridge().run_design_fragment_scan(
        rarity_state="super_rare",
        resume_cursor=3,
        scroll_step_px=280,
        until_bottom=True,
        enforce_rarity_filter=True,
        generate_preview=False,
    )

    assert result.success is True
    capture_args = calls["capture_args"]
    assert capture_args.rarity_state == "super_rare"
    assert capture_args.resume_cursor == 3
    assert capture_args.scroll_step_px == 280
    assert capture_args.until_bottom is True
    assert calls["recognition_kwargs"]["nn_mode"] == "assist"
    assert calls["recognition_kwargs"]["enforce_rarity_filter"] is True
    assert calls["recognition_kwargs"]["no_preview"] is True
    assert Path(calls["context_output_dir"]).parent == tmp_path / "recognition_workbench" / "adb_test_out"
