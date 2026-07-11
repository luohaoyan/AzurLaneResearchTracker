#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 v0.6.0 共享数据契约测试                          ║
║                                                              ║
║  【测试目标】冻结 ADB、OCR、Bridge、场景和每日记录字段。       ║
║  【类比理解】像核对三路开发使用的插头尺寸是否完全一致。        ║
║  【数据流说明】共享契约 → 模块结果 → 标准 payload。           ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import pytest

from core.automation.adb_task_api import AdbTaskResult, get_adb_task_api
from core.contracts import (
    EquipmentRecognitionRecord,
    RecognitionDetection,
    RecognitionDetectionType,
    RecognitionResult,
    RecognitionScene,
    ResourceRecognitionRecord,
    ScreenshotArtifact,
    StructuredTaskResult,
)
from core.recognition.ocr_task_api import OcrTaskResult, get_ocr_task_api
from ui.automation_bridge import AutomationBridgeResult


# ============================================================
# 🧪 第二部分：测试用例
# ============================================================

def test_module_results_share_structured_task_contract() -> None:
    """ADB、OCR 和 Bridge 应保留类名并共享同一顶层字段。"""
    result_types = (AdbTaskResult, OcrTaskResult, AutomationBridgeResult)

    for result_type in result_types:
        result = result_type(True, "ready", "检查完成", payload={"value": 1}, warnings=("提示",))
        assert isinstance(result, StructuredTaskResult)
        assert result.to_dict()["warnings"] == ["提示"]
        assert result.payload == {"value": 1}


def test_recognition_scene_names_are_frozen() -> None:
    """ADB 与 OCR 的场景名称必须保持四个约定值。"""
    assert [scene.value for scene in RecognitionScene] == [
        "harbor",
        "equipment_list",
        "research",
        "phase_select",
    ]
    assert RecognitionScene.normalize("equipment_list") is RecognitionScene.EQUIPMENT_LIST

    with pytest.raises(ValueError):
        RecognitionScene.normalize("unknown_scene")


def test_screenshot_artifact_is_direct_ocr_input() -> None:
    """ADB 截图结果应同时携带绝对路径、场景和设备串号。"""
    artifact = ScreenshotArtifact(
        "G:/shots/harbor.png",
        RecognitionScene.HARBOR,
        "127.0.0.1:5555",
    )

    assert artifact.to_dict() == {
        "screenshot_path": "G:/shots/harbor.png",
        "scene": "harbor",
        "device_serial": "127.0.0.1:5555",
    }


def test_equipment_record_uses_daily_csv_field_names() -> None:
    """装备记录字段必须直接对应 UserDataManager 的每日 CSV。"""
    record = EquipmentRecognitionRecord("S9-001", 2, 35, 0.93)

    assert record.to_dict() == {
        "equipment_id": "S9-001",
        "equipment_count": 2,
        "fragment_count": 35,
        "confidence": 0.93,
    }

    with pytest.raises(ValueError):
        EquipmentRecognitionRecord("bad-id", 1, 2, 0.9)


def test_recognition_result_serializes_without_ocr_library_types() -> None:
    """RecognitionResult payload 只能包含基础 Python 类型。"""
    detection = RecognitionDetection(
        "oil",
        RecognitionDetectionType.RESOURCE,
        1234,
        0.95,
        (10, 20, 100, 30),
    )
    resource_status = ResourceRecognitionRecord("指挥官", 1234, 5678, 90, 0.91)
    result = RecognitionResult(
        True,
        RecognitionScene.HARBOR,
        screenshot_path="G:/shots/harbor.png",
        detections=(detection,),
        resource_status=resource_status,
        warnings=("资源区域轻微模糊",),
    )

    payload = result.to_payload()
    assert payload["scene"] == "harbor"
    assert payload["detections"][0]["type"] == "resource"
    assert payload["resource_status"]["coins"] == 5678
    assert payload["warnings"] == ["资源区域轻微模糊"]


def test_reserved_apis_publish_frozen_scene_and_record_schema() -> None:
    """现有占位 API 也应立即遵守阶段 0 契约。"""
    screenshot_result = get_adb_task_api().capture_screenshot(RecognitionScene.RESEARCH)
    equipment_result = get_ocr_task_api().scan_equipment_counts(scene=RecognitionScene.EQUIPMENT_LIST)
    resource_result = get_ocr_task_api().scan_resource_status(scene=RecognitionScene.HARBOR)

    assert screenshot_result.payload is not None
    assert screenshot_result.payload["scene"] == "research"
    assert screenshot_result.payload["screenshot_path"] is None

    assert equipment_result.payload is not None
    equipment_fields = [field["name"] for field in equipment_result.payload["result_schema"]]
    assert equipment_fields == ["equipment_id", "equipment_count", "fragment_count", "confidence"]
    assert equipment_result.payload["equipment_records"] == []

    assert resource_result.payload is not None
    assert resource_result.payload["scene"] == "harbor"
    assert resource_result.payload["resource_status"] is None
