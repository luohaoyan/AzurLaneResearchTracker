#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🛟 运行期状态管理器 (runtime_state.py)          ║
║                                                              ║
║  【一句话解释】保存本次程序运行中的玩家资源和后台任务状态。   ║
║  【类比理解】它像港区白板，只记录当前值班期间的信息，关机即清。║
║  【数据流说明】OCR/任务更新 → 内存状态 → GUI 卡片与日志抽屉。  ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from core.utils.logger import get_logger


# ============================================================
# 🏗️ 第二部分：核心类
# ============================================================

class TaskStateKind(str, Enum):
    """
    当前运行任务状态枚举。
    输入：
        无，枚举值由程序内部使用。
    输出：
        str 枚举值，可用于状态判断。
    使用示例：
        TaskStateKind.OCR_PROCESSING
    """

    IDLE = "idle"
    WAITING_OCR = "waiting_ocr"
    EQUIPMENT_UPDATING = "equipment_updating"
    SCREENSHOT_CAPTURING = "screenshot_capturing"
    OCR_PROCESSING = "ocr_processing"
    STITCHING = "stitching"
    EXPORTING = "exporting"
    AUTO_TESTING = "auto_testing"
    ERROR = "error"


@dataclass
class RuntimePlayerStatus:
    """
    玩家资源运行期状态。
    输入：
        OCR 识别结果或默认空值。
    输出：
        当前运行期间的玩家资源快照，不写入本地文件。
    使用示例：
        status.update_from_ocr({"oil": 1200, "coins": 5000})
    """

    player_name: str = "等待识别"
    oil: Optional[int] = None
    coins: Optional[int] = None
    gems: Optional[int] = None
    last_ocr_time: Optional[datetime] = None

    def update_from_ocr(self, data: Dict[str, Any]) -> None:
        """
        使用 OCR 结果更新玩家资源。
        输入：
            data: OCR 输出字典，可包含 player_name / oil / coins / gems。
        输出：
            None。
        使用示例：
            update_from_ocr({"player_name": "指挥官", "oil": 1000})
        """
        if data.get("player_name"):
            self.player_name = str(data["player_name"])
        for key in ("oil", "coins", "gems"):
            if key in data and data[key] is not None:
                setattr(self, key, int(data[key]))
        self.last_ocr_time = datetime.now()

    def get_status(self) -> Dict[str, Any]:
        """
        获取玩家资源快照。
        输入：
            无。
        输出：
            dict: 可直接给 GUI 使用的状态字典。
        使用示例：
            ui_data = status.get_status()
        """
        return {
            "player_name": self.player_name,
            "oil": self.oil,
            "coins": self.coins,
            "gems": self.gems,
            "last_ocr_time": self.last_ocr_time,
            "available": self.is_available(),
        }

    def is_available(self) -> bool:
        """
        判断玩家资源是否已有完整 OCR 数据。
        输入：
            无。
        输出：
            bool: 油、物资、钻石都存在时为 True。
        使用示例：
            if status.is_available(): ...
        """
        return self.oil is not None and self.coins is not None and self.gems is not None


@dataclass
class TaskState:
    """
    当前任务运行状态。
    输入：
        任务类型、进度、用户可见文案等。
    输出：
        当前任务快照。
    使用示例：
        TaskState(kind=TaskStateKind.EXPORTING, progress=30)
    """

    kind: TaskStateKind = TaskStateKind.IDLE
    current_task: str = "无"
    progress: int = 0
    last_update_time: datetime = field(default_factory=datetime.now)
    is_running: bool = False
    user_message: str = "港区系统待命中，请选择操作。"
    last_error: str = "无"

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为 GUI 可直接读取的字典。
        输入：
            无。
        输出：
            dict: 当前任务状态。
        使用示例：
            task_data = task.to_dict()
        """
        return {
            "kind": self.kind.value,
            "kind_name": self.display_name(),
            "current_task": self.current_task,
            "progress": self.progress,
            "last_update_time": self.last_update_time,
            "is_running": self.is_running,
            "user_message": self.user_message,
            "last_error": self.last_error,
        }

    def display_name(self) -> str:
        """
        获取用户可见状态名称。
        输入：
            无。
        输出：
            str: 中文状态名称。
        使用示例：
            label.setText(task.display_name())
        """
        mapping = {
            TaskStateKind.IDLE: "空闲",
            TaskStateKind.WAITING_OCR: "等待识别",
            TaskStateKind.EQUIPMENT_UPDATING: "装备更新中",
            TaskStateKind.SCREENSHOT_CAPTURING: "截图采集中",
            TaskStateKind.OCR_PROCESSING: "OCR 识别中",
            TaskStateKind.STITCHING: "截图拼接中",
            TaskStateKind.EXPORTING: "导出中",
            TaskStateKind.AUTO_TESTING: "自动化测试中",
            TaskStateKind.ERROR: "异常",
        }
        return mapping.get(self.kind, "未知")


class RuntimeStateManager:
    """
    运行期状态管理器。
    输入：
        无，内部创建玩家状态和任务状态。
    输出：
        单例管理器，供 GUI 与后续 OCR/自动化模块共享。
    使用示例：
        manager = get_runtime_state_manager()
        manager.set_task_state(TaskStateKind.OCR_PROCESSING, 50, "识别中")
    """

    _instance: Optional["RuntimeStateManager"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "RuntimeStateManager":
        """单例模式：全局共享一份运行期状态。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化运行期状态，重复初始化时直接返回。"""
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        self.player_status = RuntimePlayerStatus()
        self.task_state = TaskState()
        self._initialized = True

    def update_player_from_ocr(self, data: Dict[str, Any]) -> None:
        """
        更新玩家 OCR 资源数据。
        输入：
            data: OCR 输出字典。
        输出：
            None。
        使用示例：
            manager.update_player_from_ocr({"oil": 3000})
        """
        self.player_status.update_from_ocr(data)
        self.logger.info("玩家资源状态已通过 OCR 更新")

    def get_player_status(self) -> Dict[str, Any]:
        """
        获取玩家状态。
        输入：
            无。
        输出：
            dict: 玩家资源状态。
        使用示例：
            player = manager.get_player_status()
        """
        return self.player_status.get_status()

    def set_task_state(
        self,
        kind: TaskStateKind,
        progress: int = 0,
        message: str = "",
        current_task: str = "",
        last_error: str = "",
    ) -> None:
        """
        设置当前任务状态。
        输入：
            kind: 状态类型。
            progress: 0-100 进度。
            message: 用户可见提示语。
            current_task: 当前任务名称。
            last_error: 最近错误。
        输出：
            None。
        使用示例：
            manager.set_task_state(TaskStateKind.EXPORTING, 80, "正在导出")
        """
        safe_progress = max(0, min(100, int(progress)))
        self.task_state = TaskState(
            kind=kind,
            current_task=current_task or self._default_task_name(kind),
            progress=safe_progress,
            last_update_time=datetime.now(),
            is_running=kind not in (TaskStateKind.IDLE, TaskStateKind.ERROR),
            user_message=message or self._default_message(kind),
            last_error=last_error or "无",
        )
        self.logger.info(f"运行状态更新：{self.task_state.display_name()} {safe_progress}%")

    def get_full_state(self) -> Dict[str, Any]:
        """
        获取完整运行期状态。
        输入：
            无。
        输出：
            dict: player + task 两部分。
        使用示例：
            state = manager.get_full_state()
        """
        return {
            "player": self.get_player_status(),
            "task": self.task_state.to_dict(),
        }

    def reset(self) -> None:
        """
        重置运行期状态。
        输入：
            无。
        输出：
            None。
        使用示例：
            manager.reset()
        """
        self.player_status = RuntimePlayerStatus()
        self.task_state = TaskState()
        self.logger.info("运行期状态已重置")

    @staticmethod
    def _default_task_name(kind: TaskStateKind) -> str:
        """按状态类型生成默认任务名称。"""
        mapping = {
            TaskStateKind.IDLE: "无",
            TaskStateKind.WAITING_OCR: "等待 OCR 更新",
            TaskStateKind.EQUIPMENT_UPDATING: "装备数据更新",
            TaskStateKind.SCREENSHOT_CAPTURING: "截图采集",
            TaskStateKind.OCR_PROCESSING: "OCR 识别",
            TaskStateKind.STITCHING: "截图拼接",
            TaskStateKind.EXPORTING: "数据导出",
            TaskStateKind.AUTO_TESTING: "自动化检测",
            TaskStateKind.ERROR: "异常处理",
        }
        return mapping.get(kind, "未知任务")

    @staticmethod
    def _default_message(kind: TaskStateKind) -> str:
        """按状态类型生成默认提示语。"""
        mapping = {
            TaskStateKind.IDLE: "港区系统待命中，请选择操作。",
            TaskStateKind.WAITING_OCR: "等待下一次资源识别。",
            TaskStateKind.EQUIPMENT_UPDATING: "正在整理装备数据，请稍等片刻。",
            TaskStateKind.SCREENSHOT_CAPTURING: "正在采集截图，先不要移动游戏窗口。",
            TaskStateKind.OCR_PROCESSING: "正在识别资源与装备数字。",
            TaskStateKind.STITCHING: "正在拼接截图，港区资料整理中。",
            TaskStateKind.EXPORTING: "正在导出数据报告。",
            TaskStateKind.AUTO_TESTING: "正在检查模拟器与识别环境。",
            TaskStateKind.ERROR: "检测到异常，请打开运行日志复制给开发者。",
        }
        return mapping.get(kind, "港区状态未知。")


# ============================================================
# 🌐 第三部分：全局访问函数
# ============================================================

_runtime_state_manager: Optional[RuntimeStateManager] = None


def get_runtime_state_manager() -> RuntimeStateManager:
    """
    获取全局运行期状态管理器。
    输入：
        无。
    输出：
        RuntimeStateManager: 全局共享实例。
    使用示例：
        manager = get_runtime_state_manager()
    """
    global _runtime_state_manager
    if _runtime_state_manager is None:
        _runtime_state_manager = RuntimeStateManager()
    return _runtime_state_manager
