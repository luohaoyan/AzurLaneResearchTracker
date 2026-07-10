#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🔗 自动化安全桥接 (automation_bridge.py)        ║
║                                                              ║
║  【一句话解释】让 GUI 安全尝试调用未来 crawler/OCR 模块。      ║
║  【类比理解】它像港区联络官，外部模块没到港也不会让主界面炸锅。║
║  【数据流说明】按钮点击 → 安全 import → RuntimeState → UI。    ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import importlib
import importlib.util
import sys
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable, Dict, Iterable, Optional

from core.state.runtime_state import TaskStateKind, get_runtime_state_manager
from core.utils.logger import get_logger


# ============================================================
# 🏗️ 第二部分：核心类
# ============================================================

@dataclass(frozen=True)
class AutomationBridgeResult:
    """
    自动化桥接执行结果。
    输入：
        success: 是否成功完成。
        status: missing / unavailable / success / error。
        message: 用户可见说明。
        detail: 开发者可参考的细节。
    输出：
        不可变结果对象，供 UI 展示和测试断言。
    使用示例：
        result = bridge.run_crawler_update()
    """

    success: bool
    status: str
    message: str
    detail: str = ""


class AutomationBridge:
    """
    GUI 自动化安全桥。
    输入：
        无，内部按约定模块名尝试寻找 crawler 入口。
    输出：
        可安全调用的桥接对象；模块缺失或异常时不会抛到 GUI 主循环。
    使用示例：
        result = AutomationBridge().run_crawler_update()
    """

    CRAWLER_MODULE_CANDIDATES = (
        "core.data.equipment_crawler",
        "core.data.crawler",
        "core.automation.crawler_update",
    )
    CRAWLER_ENTRY_CANDIDATES = (
        "run_update",
        "update_equipment_data",
        "main",
    )

    def __init__(self) -> None:
        """初始化桥接对象。"""
        self.logger = get_logger()
        self.runtime_manager = get_runtime_state_manager()

    def run_crawler_update(self) -> AutomationBridgeResult:
        """
        安全执行资料爬取更新入口。
        输入：
            无。
        输出：
            AutomationBridgeResult: 执行结果，模块缺失时返回 missing。
        使用示例：
            result = bridge.run_crawler_update()
        """
        self.runtime_manager.set_task_state(
            TaskStateKind.EQUIPMENT_UPDATING,
            5,
            "正在检查资料爬取模块。",
            "资料爬取与更新",
        )
        module = self._find_first_module(self.CRAWLER_MODULE_CANDIDATES)
        if module is None:
            message = "资料爬取模块尚未接入当前 GUI 分支；请等待 crawler 分支合并或前往 GitHub 下载新版本。"
            self.runtime_manager.set_task_state(
                TaskStateKind.ERROR,
                0,
                message,
                "资料爬取与更新",
                "crawler module not found",
            )
            self.logger.warning(message)
            return AutomationBridgeResult(False, "missing", message, "crawler module not found")

        entry = self._find_first_callable(module, self.CRAWLER_ENTRY_CANDIDATES)
        if entry is None:
            message = "已找到资料爬取模块，但没有发现 GUI 约定的更新入口。"
            detail = f"module={module.__name__}, expected={','.join(self.CRAWLER_ENTRY_CANDIDATES)}"
            self.runtime_manager.set_task_state(TaskStateKind.ERROR, 0, message, "资料爬取与更新", detail)
            self.logger.warning(f"{message} {detail}")
            return AutomationBridgeResult(False, "unavailable", message, detail)

        try:
            self.runtime_manager.set_task_state(TaskStateKind.EQUIPMENT_UPDATING, 35, "正在执行资料更新。", "资料爬取与更新")
            raw_result = entry()
        except Exception as exc:
            message = "资料更新执行失败，可能是网页结构变化或 crawler 模块异常；请复制运行日志给开发者。"
            detail = f"{type(exc).__name__}: {exc}"
            self.runtime_manager.set_task_state(TaskStateKind.ERROR, 0, message, "资料爬取与更新", detail)
            self.logger.exception("资料爬取更新失败")
            return AutomationBridgeResult(False, "error", message, detail)

        message = self._success_message(raw_result)
        self.runtime_manager.set_task_state(TaskStateKind.IDLE, 100, message, "资料爬取与更新")
        self.logger.info(message)
        return AutomationBridgeResult(True, "success", message, str(raw_result or ""))

    def _find_first_module(self, candidates: Iterable[str]) -> Optional[ModuleType]:
        """
        按候选名称查找并导入第一个可用模块。
        输入：
            candidates: 模块名候选列表。
        输出：
            Optional[ModuleType]: 找到则返回模块，否则 None。
        使用示例：
            module = self._find_first_module(["core.data.equipment_crawler"])
        """
        for module_name in candidates:
            if module_name in sys.modules:
                module = sys.modules[module_name]
                if isinstance(module, ModuleType):
                    return module
            try:
                spec = importlib.util.find_spec(module_name)
            except (ImportError, ModuleNotFoundError, ValueError) as exc:
                self.logger.debug(f"资料爬取候选模块不可用: {module_name} ({exc})")
                continue
            if spec is None:
                continue
            try:
                return importlib.import_module(module_name)
            except ImportError as exc:
                self.logger.warning(f"资料爬取模块导入失败: {module_name} ({exc})")
                return None
        return None

    @staticmethod
    def _find_first_callable(module: ModuleType, candidates: Iterable[str]) -> Optional[Callable[[], Any]]:
        """从模块中寻找第一个无参可调用入口。"""
        for name in candidates:
            entry = getattr(module, name, None)
            if callable(entry):
                return entry
        return None

    @staticmethod
    def _success_message(raw_result: Any) -> str:
        """把 crawler 返回值转换成用户可见成功文案。"""
        if isinstance(raw_result, dict) and raw_result.get("message"):
            return str(raw_result["message"])
        return "资料更新流程已完成，基础数据已准备刷新。"


# ============================================================
# 🌐 第三部分：全局访问函数
# ============================================================

_automation_bridge: Optional[AutomationBridge] = None


def get_automation_bridge() -> AutomationBridge:
    """
    获取全局自动化桥接对象。
    输入：
        无。
    输出：
        AutomationBridge: 全局共享桥接对象。
    使用示例：
        bridge = get_automation_bridge()
    """
    global _automation_bridge
    if _automation_bridge is None:
        _automation_bridge = AutomationBridge()
    return _automation_bridge
