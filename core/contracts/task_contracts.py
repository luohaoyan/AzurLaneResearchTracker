#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          📜 v0.6.0 共享任务契约 (task_contracts.py)          ║
║                                                              ║
║  【一句话解释】冻结 ADB、OCR 与 GUI 整合层共同使用的数据结构。║
║  【类比理解】它像标准集装箱，三路开发只约定箱型不干涉货物。   ║
║  【数据流说明】截图 → 识别结果 → 预览确认 → 每日用户数据。    ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import re
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Event
from typing import Any, Callable, Dict, Optional, Tuple


# ============================================================
# 🧱 第二部分：基础类型与枚举
# ============================================================

TaskProgressReporter = Callable[[int, str, str], object]
RoiRegion = Tuple[int, int, int, int]


class RecognitionScene(StrEnum):
    """
    游戏截图场景名称。
    输入：
        无。
    输出：
        ADB、OCR 和整合层共同使用的稳定场景字符串。
    使用示例：
        scene = RecognitionScene.EQUIPMENT_LIST
    """

    HARBOR = "harbor"
    EQUIPMENT_LIST = "equipment_list"
    RESEARCH = "research"
    PHASE_SELECT = "phase_select"

    @classmethod
    def normalize(cls, value: "RecognitionScene | str") -> "RecognitionScene":
        """把字符串或枚举统一转换为场景枚举，非法值直接抛出 ValueError。"""
        return value if isinstance(value, cls) else cls(str(value).strip())


class RecognitionDetectionType(StrEnum):
    """
    单项识别结果类型。
    输入：
        无。
    输出：
        装备数量、碎片、资源或 UI 元素等稳定类型名称。
    使用示例：
        detection_type = RecognitionDetectionType.FRAGMENT_COUNT
    """

    EQUIPMENT_COUNT = "equipment_count"
    FRAGMENT_COUNT = "fragment_count"
    RESOURCE = "resource"
    UI_ELEMENT = "ui_element"


# ============================================================
# 🏗️ 第三部分：共享结果对象
# ============================================================

@dataclass(frozen=True)
class StructuredTaskResult:
    """
    ADB、OCR 与 GUI Bridge 共用的顶层任务结果。
    输入：
        success/status/message/detail/payload/warnings。
    输出：
        不可变结构，具体模块可通过继承保留自己的公开类名。
    使用示例：
        result = StructuredTaskResult(True, "ready", "检查完成")
    """

    success: bool
    status: str
    message: str
    detail: str = ""
    payload: Optional[Dict[str, Any]] = None
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """转换为可序列化字典，供进程通信、日志和测试使用。"""
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "detail": self.detail,
            "payload": self.payload,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ScreenshotArtifact:
    """
    ADB 截图输出契约。
    输入：
        screenshot_path/scene/device_serial。
    输出：
        可直接交给 OCR 分支的截图描述。
    使用示例：
        artifact = ScreenshotArtifact("C:/shots/a.png", RecognitionScene.HARBOR, "127.0.0.1:5555")
    """

    screenshot_path: str
    scene: RecognitionScene
    device_serial: str

    def to_dict(self) -> Dict[str, str]:
        """转换为 ADB payload 使用的基础字典。"""
        return {
            "screenshot_path": self.screenshot_path,
            "scene": self.scene.value,
            "device_serial": self.device_serial,
        }


@dataclass(frozen=True)
class RecognitionDetection:
    """
    OCR 或模板匹配产生的单项检测。
    输入：
        label/type/value/confidence/roi。
    输出：
        与 PaddleOCR、OpenCV 实现无关的标准检测记录。
    使用示例：
        detection = RecognitionDetection("oil", RecognitionDetectionType.RESOURCE, 1200, 0.95, (0, 0, 100, 50))
    """

    label: str
    detection_type: RecognitionDetectionType
    value: int
    confidence: float
    roi: RoiRegion

    def __post_init__(self) -> None:
        """校验数量、置信度和 ROI，避免无效结果进入整合层。"""
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence 必须位于 0.0 到 1.0 之间")
        if len(self.roi) != 4 or any(int(item) < 0 for item in self.roi):
            raise ValueError("roi 必须是四个非负整数")

    def to_dict(self) -> Dict[str, Any]:
        """转换为 OCR payload 中的 detections 字典。"""
        return {
            "label": self.label,
            "type": self.detection_type.value,
            "value": int(self.value),
            "confidence": float(self.confidence),
            "roi": [int(item) for item in self.roi],
        }


@dataclass(frozen=True)
class EquipmentRecognitionRecord:
    """
    可写入 UserDataManager 的装备识别记录。
    输入：
        equipment_id/equipment_count/fragment_count/confidence。
    输出：
        字段名与 data/user_records 每日 CSV 完全一致的记录。
    使用示例：
        record = EquipmentRecognitionRecord("S9-001", 1, 25, 0.93)
    """

    equipment_id: str
    equipment_count: int
    fragment_count: int
    confidence: float

    def __post_init__(self) -> None:
        """校验装备 ID、数量和置信度，阻止明显错误进入预览。"""
        if re.fullmatch(r"(?:S\d+-\d{3}|G\d{4})", self.equipment_id) is None:
            raise ValueError(f"无效装备 ID: {self.equipment_id}")
        if self.equipment_count < 0 or self.fragment_count < 0:
            raise ValueError("装备数量和碎片数量不能为负数")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence 必须位于 0.0 到 1.0 之间")

    def to_dict(self) -> Dict[str, Any]:
        """转换为整合层可直接映射到 update_batch 的字典。"""
        return {
            "equipment_id": self.equipment_id,
            "equipment_count": int(self.equipment_count),
            "fragment_count": int(self.fragment_count),
            "confidence": float(self.confidence),
        }


@dataclass(frozen=True)
class ResourceRecognitionRecord:
    """
    港区资源 OCR 结果。
    输入：
        player_name/oil/coins/gems/confidence。
    输出：
        可交给 RuntimePlayerStatus.update_from_ocr 的资源快照。
    使用示例：
        record = ResourceRecognitionRecord("指挥官", 1000, 2000, 300, 0.91)
    """

    player_name: str
    oil: int
    coins: int
    gems: int
    confidence: float

    def __post_init__(self) -> None:
        """校验资源数量和置信度，防止负数资源进入运行期状态。"""
        if min(self.oil, self.coins, self.gems) < 0:
            raise ValueError("资源数量不能为负数")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence 必须位于 0.0 到 1.0 之间")

    def to_dict(self) -> Dict[str, Any]:
        """转换为 RuntimePlayerStatus 可读取的字典。"""
        return {
            "player_name": self.player_name,
            "oil": int(self.oil),
            "coins": int(self.coins),
            "gems": int(self.gems),
            "confidence": float(self.confidence),
        }


@dataclass(frozen=True)
class RecognitionResult:
    """
    OCR 分支交给整合分支的完整识别结果。
    输入：
        success/scene/detections/equipment_records/resource_status 等字段。
    输出：
        不依赖 PaddleOCR 或 OpenCV 类型的稳定结果。
    使用示例：
        result = RecognitionResult(True, RecognitionScene.HARBOR)
    """

    success: bool
    scene: RecognitionScene
    screenshot_path: Optional[str] = None
    detections: Tuple[RecognitionDetection, ...] = ()
    equipment_records: Tuple[EquipmentRecognitionRecord, ...] = ()
    resource_status: Optional[ResourceRecognitionRecord] = None
    warnings: Tuple[str, ...] = ()
    message: str = ""
    detail: str = ""

    def to_payload(self) -> Dict[str, Any]:
        """转换为 OcrTaskResult.payload 使用的标准字典。"""
        return {
            "scene": self.scene.value,
            "screenshot_path": self.screenshot_path,
            "detections": [item.to_dict() for item in self.detections],
            "equipment_records": [item.to_dict() for item in self.equipment_records],
            "resource_status": self.resource_status.to_dict() if self.resource_status else None,
            "warnings": list(self.warnings),
        }


# ============================================================
# 🛑 第四部分：协作式取消
# ============================================================

class TaskCancelledError(RuntimeError):
    """
    任务在安全检查点响应取消请求时抛出的专用异常。
    输入：
        可选取消原因。
    输出：
        TaskManager 将其转换为 cancelled 状态而不是 error。
    使用示例：
        raise TaskCancelledError("用户取消 OCR")
    """


@dataclass
class CancellationToken:
    """
    跨 GUI 主线程与后台线程共享的取消令牌。
    输入：
        无，内部使用 threading.Event 保证线程安全。
    输出：
        后台任务可在截图、点击、翻页、ROI 等安全点查询。
    使用示例：
        token.request_cancel(); token.raise_if_cancelled()
    """

    _event: Event = field(default_factory=Event, init=False, repr=False)

    def request_cancel(self) -> None:
        """记录取消请求；不会强杀线程或破坏正在写入的数据。"""
        self._event.set()

    def is_cancelled(self) -> bool:
        """返回是否已收到取消请求。"""
        return self._event.is_set()

    def raise_if_cancelled(self, message: str = "任务已在安全点取消。") -> None:
        """已取消时抛出专用异常，未取消时继续执行。"""
        if self.is_cancelled():
            raise TaskCancelledError(message)


@dataclass(frozen=True)
class TaskExecutionContext:
    """
    TaskManager 注入后台 runner 的执行上下文。
    输入：
        progress_reporter 与 cancellation_token。
    输出：
        统一的进度上报和协作式取消入口。
    使用示例：
        context.report_progress(50, "正在识别"); context.raise_if_cancelled()
    """

    progress_reporter: Optional[TaskProgressReporter] = None
    cancellation_token: CancellationToken = field(default_factory=CancellationToken)

    def report_progress(self, progress: int, message: str = "", detail: str = "") -> object:
        """安全上报 0-100 进度；未配置回调时返回 False。"""
        if self.progress_reporter is None:
            return False
        safe_progress = max(0, min(100, int(progress)))
        return self.progress_reporter(safe_progress, message, detail)

    def is_cancelled(self) -> bool:
        """返回当前任务是否已收到取消请求。"""
        return self.cancellation_token.is_cancelled()

    def raise_if_cancelled(self, message: str = "任务已在安全点取消。") -> None:
        """代理取消令牌，在 ADB/OCR 安全点终止后续步骤。"""
        self.cancellation_token.raise_if_cancelled(message)
