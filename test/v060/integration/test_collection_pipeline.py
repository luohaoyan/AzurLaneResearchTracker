#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 v0.6.0 采集流水线整合测试                        ║
║                                                              ║
║  【测试目标】确认 ADB → OCR → 预览 → 确认写入的边界清晰。     ║
║  【类比理解】像验收账本流程，识别结果先核对，点确认才入账。   ║
║  【数据流说明】Fake ADB/OCR → CollectionPreview → Fake CSV。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from typing import Any, Dict, Optional

from core.automation.adb_task_api import AdbTaskResult
from core.contracts import RecognitionScene
from core.integration import AutomationCollectionPipeline, get_automation_collection_pipeline
from core.recognition.ocr_task_api import OcrTaskResult


# ============================================================
# 🧰 第二部分：测试替身
# ============================================================

class FakeAdbApi:
    """模拟 ADB 分支：返回固定截图路径，不触碰真实模拟器。"""

    def __init__(self) -> None:
        self.captured_scenes: list[str] = []
        self.real_capture_flags: list[bool] = []

    def check_connection(self, task_context: Optional[object] = None) -> AdbTaskResult:
        """返回可用连接状态。"""
        return AdbTaskResult(True, "ready", "ADB ready", payload={"device_serial": "127.0.0.1:5555"})

    def capture_screenshot(
        self,
        scene: RecognitionScene | str = RecognitionScene.HARBOR,
        task_context: Optional[object] = None,
        real_capture: bool = False,
    ) -> AdbTaskResult:
        """按场景返回截图路径。"""
        normalized_scene = RecognitionScene.normalize(scene)
        self.captured_scenes.append(normalized_scene.value)
        self.real_capture_flags.append(real_capture)
        return AdbTaskResult(
            True,
            "ready",
            "shot ready",
            payload={
                "screenshot_path": f"G:/shots/{normalized_scene.value}.png",
                "scene": normalized_scene.value,
            },
        )


class FakeOcrApi:
    """模拟 OCR 分支：返回资源和装备记录。"""

    def scan_resource_status(
        self,
        screenshot_path: Optional[str] = None,
        scene: RecognitionScene | str = RecognitionScene.HARBOR,
        task_context: Optional[object] = None,
    ) -> OcrTaskResult:
        """返回玩家资源识别结果。"""
        return OcrTaskResult(
            True,
            "ready",
            "resource ready",
            payload={
                "resource_status": {
                    "player_name": "测试指挥官",
                    "oil": 1234,
                    "coins": 5678,
                    "gems": 90,
                    "confidence": 0.92,
                }
            },
        )

    def scan_equipment_counts(
        self,
        screenshot_path: Optional[str] = None,
        scene: RecognitionScene | str = RecognitionScene.EQUIPMENT_LIST,
        task_context: Optional[object] = None,
    ) -> OcrTaskResult:
        """返回一条有效装备记录和一条应被跳过的坏记录。"""
        return OcrTaskResult(
            True,
            "ready",
            "equipment ready",
            payload={
                "equipment_records": [
                    {
                        "equipment_id": "S9-001",
                        "equipment_count": 2,
                        "fragment_count": 35,
                        "confidence": 0.94,
                    },
                    {
                        "equipment_id": "bad-id",
                        "equipment_count": 1,
                        "fragment_count": 2,
                        "confidence": 0.8,
                    },
                ]
            },
        )


class FakeUserDataManager:
    """记录 update_batch 调用，避免测试写入真实 data/user_records。"""

    def __init__(self) -> None:
        self.writes: list[Dict[str, Dict[str, int]]] = []

    def update_batch(self, records: Dict[str, Dict[str, int]], target_date: Optional[str] = None) -> Dict[str, Any]:
        """保存写入请求并返回成功统计。"""
        self.writes.append(records)
        return {"total": len(records), "success": len(records), "failed": 0, "failed_ids": []}


class FakeRuntimeManager:
    """记录资源 OCR 和任务状态更新。"""

    def __init__(self) -> None:
        self.player_updates: list[Dict[str, Any]] = []
        self.task_states: list[tuple[Any, int, str, str]] = []

    def update_player_from_ocr(self, data: Dict[str, Any]) -> None:
        """保存运行期资源状态。"""
        self.player_updates.append(data)

    def set_task_state(
        self,
        kind: Any,
        progress: int = 0,
        message: str = "",
        current_task: str = "",
        last_error: str = "",
    ) -> None:
        """保存任务状态更新。"""
        self.task_states.append((kind, progress, message, current_task))


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_collection_pipeline_requires_confirmation_before_daily_write() -> None:
    """采集完成后只能生成预览，确认前不能写入 UserDataManager。"""
    pipeline = get_automation_collection_pipeline()
    fake_adb = FakeAdbApi()
    fake_user_data = FakeUserDataManager()
    fake_runtime = FakeRuntimeManager()
    pipeline.reset_for_tests(fake_adb, FakeOcrApi(), fake_user_data, fake_runtime)

    try:
        result = pipeline.run_collection("quick")

        assert result.success is True
        assert result.status == "preview_ready"
        assert result.payload is not None
        assert result.payload["requires_confirmation"] is True
        assert result.payload["equipment_records"][0]["equipment_id"] == "S9-001"
        assert fake_adb.real_capture_flags == [True, True]
        assert fake_user_data.writes == []
        assert fake_runtime.player_updates[0]["oil"] == 1234
        assert any("bad-id" in warning for warning in result.warnings)

        confirm_result = pipeline.confirm_preview(str(result.payload["preview_id"]))

        assert confirm_result.success is True
        assert confirm_result.status == "success"
        assert fake_user_data.writes == [
            {"S9-001": {"equipment_count": 2, "fragment_count": 35}}
        ]
        assert confirm_result.payload is not None
        assert confirm_result.payload["write_result"]["success"] == 1
    finally:
        pipeline.reset_for_tests()


def test_collection_pipeline_rejects_unknown_profile() -> None:
    """采集模式 key 不存在时应返回 unavailable，不访问 ADB/OCR。"""
    pipeline = get_automation_collection_pipeline()
    pipeline.reset_for_tests(FakeAdbApi(), FakeOcrApi(), FakeUserDataManager(), FakeRuntimeManager())

    try:
        result = pipeline.run_collection("missing-profile")

        assert result.success is False
        assert result.status == "unavailable"
        assert "未找到采集模式" in result.message
    finally:
        pipeline.reset_for_tests()


def test_collection_pipeline_maps_ocr_name_and_skips_review_records() -> None:
    """新 OCR 主输出为名称时应运行时映射 ID，疑难卡不能直接写入。"""
    warnings: list[str] = []
    records = AutomationCollectionPipeline._equipment_records_from_payload(
        [
            {
                "final_equipment_name": "双联装381mm主炮改#T0",
                "fragment_count": 12,
                "confidence": 0.88,
                "final_status": "success",
            },
            {
                "equipment_name": "双联装381mm主炮改#T0",
                "fragment_count": 99,
                "confidence": 0.42,
                "final_status": "needs_review",
            },
        ],
        warnings,
    )

    assert [record.equipment_id for record in records] == ["S0-001"]
    assert records[0].equipment_count == 0
    assert records[0].fragment_count == 12
    assert any("needs_review" in warning for warning in warnings)
