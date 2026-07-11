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
import inspect
import sys
from types import ModuleType
from typing import Any, Callable, Dict, Iterable, Optional

from core.automation.adb_task_api import AdbTaskResult, get_adb_task_api
from core.contracts import StructuredTaskResult, TaskCancelledError, TaskExecutionContext
from core.recognition.ocr_task_api import OcrTaskResult, get_ocr_task_api
from core.state.runtime_state import TaskStateKind, get_runtime_state_manager
from core.utils.logger import get_logger


# ============================================================
# 🏗️ 第二部分：核心类
# ============================================================

class AutomationBridgeResult(StructuredTaskResult):
    """
    自动化桥接执行结果。
    输入：
        success: 是否成功完成。
        status: missing / unavailable / success / error。
        message: 用户可见说明。
        detail: 开发者可参考的细节。
        payload/warnings: 核心层透传的结构化数据和非阻塞警告。
    输出：
        不可变结果对象，供 UI 展示和测试断言。
    使用示例：
        result = bridge.run_crawler_update()
    """

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
        "core.data.crawler_update",
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

    def run_crawler_update(
        self,
        progress_reporter: Optional[Callable[[int, str, str], object]] = None,
    ) -> AutomationBridgeResult:
        """
        安全执行资料爬取更新入口。
        输入：
            无。
        输出：
            AutomationBridgeResult: 执行结果，模块缺失时返回 missing。
        使用示例：
            result = bridge.run_crawler_update()
        """
        def report(progress: int, message: str, detail: str = "") -> None:
            """同时更新运行期状态和 GUI 任务清单。"""
            safe_progress = max(0, min(100, int(progress)))
            self.runtime_manager.set_task_state(
                TaskStateKind.EQUIPMENT_UPDATING,
                safe_progress,
                message,
                "资料爬取与更新",
                detail,
            )
            if progress_reporter is not None:
                progress_reporter(safe_progress, message, detail)

        report(5, "正在检查资料爬取模块。")
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
            if progress_reporter is not None:
                progress_reporter(0, message, "crawler module not found")
            self.logger.warning(message)
            return AutomationBridgeResult(False, "missing", message, "crawler module not found")

        entry = self._find_first_callable(module, self.CRAWLER_ENTRY_CANDIDATES)
        if entry is None:
            message = "已找到资料爬取模块，但没有发现 GUI 约定的更新入口。"
            detail = f"module={module.__name__}, expected={','.join(self.CRAWLER_ENTRY_CANDIDATES)}"
            self.runtime_manager.set_task_state(TaskStateKind.ERROR, 0, message, "资料爬取与更新", detail)
            if progress_reporter is not None:
                progress_reporter(0, message, detail)
            self.logger.warning(f"{message} {detail}")
            return AutomationBridgeResult(False, "unavailable", message, detail)

        try:
            report(8, "正在执行资料更新。")
            raw_result = self._call_crawler_entry(entry, report)
        except Exception as exc:
            message = "资料更新执行失败，可能是网页结构变化或 crawler 模块异常；请复制运行日志给开发者。"
            detail = f"{type(exc).__name__}: {exc}"
            self.runtime_manager.set_task_state(TaskStateKind.ERROR, 0, message, "资料爬取与更新", detail)
            if progress_reporter is not None:
                progress_reporter(0, message, detail)
            self.logger.exception("资料爬取更新失败")
            return AutomationBridgeResult(False, "error", message, detail)

        message = self._success_message(raw_result)
        self.runtime_manager.set_task_state(TaskStateKind.IDLE, 100, message, "资料爬取与更新")
        if progress_reporter is not None:
            progress_reporter(100, message, self._success_detail(raw_result))
        self.logger.info(message)
        payload = raw_result if isinstance(raw_result, dict) else None
        detail = self._success_detail(raw_result)
        return AutomationBridgeResult(True, "success", message, detail, payload)

    def run_adb_connection_check(
        self,
        progress_reporter: Optional[Callable[[int, str, str], object]] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AutomationBridgeResult:
        """
        安全执行 ADB 连接预检。
        输入：
            progress_reporter: 兼容旧任务的进度回调。
            task_context: v0.6.0 可取消任务上下文。
        输出：
            AutomationBridgeResult: 配置、路径和设备串号预检结果。
        使用示例：
            result = bridge.run_adb_connection_check()
        """
        return self._run_safe_api(
            TaskStateKind.AUTO_TESTING,
            "ADB 连接预检",
            "正在检查模拟器 ADB 配置。",
            get_adb_task_api().check_connection,
            progress_reporter,
            task_context,
        )

    def run_adb_screenshot_capture(
        self,
        progress_reporter: Optional[Callable[[int, str, str], object]] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AutomationBridgeResult:
        """
        安全执行 ADB 截图预检。
        输入：
            progress_reporter: 兼容旧任务的进度回调。
            task_context: v0.6.0 可取消任务上下文。
        输出：
            AutomationBridgeResult: 截图目录和命名规则预检结果。
        使用示例：
            result = bridge.run_adb_screenshot_capture()
        """
        return self._run_safe_api(
            TaskStateKind.SCREENSHOT_CAPTURING,
            "ADB 截图预检",
            "正在准备截图采集目录。",
            get_adb_task_api().capture_screenshot,
            progress_reporter,
            task_context,
        )

    def run_ocr_equipment_scan(
        self,
        progress_reporter: Optional[Callable[[int, str, str], object]] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AutomationBridgeResult:
        """
        安全执行装备 OCR 预检。
        输入：
            progress_reporter: 兼容旧任务的进度回调。
            task_context: v0.6.0 可取消任务上下文。
        输出：
            AutomationBridgeResult: 装备数量与碎片识别结构。
        使用示例：
            result = bridge.run_ocr_equipment_scan()
        """
        return self._run_safe_api(
            TaskStateKind.OCR_PROCESSING,
            "装备 OCR 预检",
            "正在检查装备 OCR 结果结构。",
            get_ocr_task_api().scan_equipment_counts,
            progress_reporter,
            task_context,
        )

    def run_ocr_resource_scan(
        self,
        progress_reporter: Optional[Callable[[int, str, str], object]] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AutomationBridgeResult:
        """
        安全执行资源 OCR 预检。
        输入：
            progress_reporter: 兼容旧任务的进度回调。
            task_context: v0.6.0 可取消任务上下文。
        输出：
            AutomationBridgeResult: 玩家资源识别结构。
        使用示例：
            result = bridge.run_ocr_resource_scan()
        """
        return self._run_safe_api(
            TaskStateKind.OCR_PROCESSING,
            "资源 OCR 预检",
            "正在检查玩家资源 OCR 结构。",
            get_ocr_task_api().scan_resource_status,
            progress_reporter,
            task_context,
        )

    def run_automation_environment_check(
        self,
        progress_reporter: Optional[Callable[[int, str, str], object]] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AutomationBridgeResult:
        """
        安全执行自动化环境预检。
        输入：
            progress_reporter: 兼容旧任务的进度回调。
            task_context: v0.6.0 可取消任务上下文。
        输出：
            AutomationBridgeResult: 配置、目录和可选依赖状态。
        使用示例：
            result = bridge.run_automation_environment_check()
        """
        return self._run_safe_api(
            TaskStateKind.AUTO_TESTING,
            "自动化环境预检",
            "正在检查自动化与 OCR 基础环境。",
            get_adb_task_api().run_environment_check,
            progress_reporter,
            task_context,
        )

    def _run_safe_api(
        self,
        kind: TaskStateKind,
        task_name: str,
        start_message: str,
        api_call: Callable[..., AdbTaskResult | OcrTaskResult],
        progress_reporter: Optional[Callable[[int, str, str], object]] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AutomationBridgeResult:
        """
        统一执行 ADB/OCR 预检 API。
        输入：
            kind: 运行期任务类型。
            task_name: 用户可见任务名。
            start_message: 启动提示。
            api_call: 支持 task_context 关键字的核心 API 函数。
            progress_reporter: 兼容旧任务的进度回调。
            task_context: v0.6.0 可取消任务上下文。
        输出：
            AutomationBridgeResult: GUI 可直接展示的结果。
        使用示例：
            self._run_safe_api(TaskStateKind.AUTO_TESTING, "环境预检", "...", api.run_environment_check)
        """
        reporter = task_context.progress_reporter if task_context is not None else progress_reporter
        self.runtime_manager.set_task_state(kind, 10, start_message, task_name)
        if reporter is not None:
            reporter(10, start_message, "")
        try:
            if task_context is not None:
                task_context.raise_if_cancelled(f"{task_name}已取消。")
            raw_result = api_call(task_context=task_context)
        except TaskCancelledError as exc:
            message = str(exc) or f"{task_name}已取消。"
            self.runtime_manager.set_task_state(TaskStateKind.IDLE, 0, message, task_name)
            if reporter is not None:
                reporter(0, message, "cancelled at safe point")
            return AutomationBridgeResult(False, "cancelled", message, "cancelled at safe point")
        except Exception as exc:
            message = f"{task_name}执行失败，请复制运行日志给开发者。"
            detail = f"{type(exc).__name__}: {exc}"
            self.runtime_manager.set_task_state(TaskStateKind.ERROR, 0, message, task_name, detail)
            if reporter is not None:
                reporter(0, message, detail)
            self.logger.exception(message)
            return AutomationBridgeResult(False, "error", message, detail)

        result = self._convert_task_result(raw_result)
        final_kind = TaskStateKind.IDLE if result.success or result.status == "cancelled" else TaskStateKind.ERROR
        self.runtime_manager.set_task_state(
            final_kind,
            100 if result.success else 0,
            result.message,
            task_name,
            "" if result.success else result.detail,
        )
        if reporter is not None:
            reporter(100 if result.success else 0, result.message, result.detail)
        return result

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
    def _call_crawler_entry(
        entry: Callable[..., Any],
        progress_callback: Callable[[int, str, str], object],
    ) -> Any:
        """
        调用 crawler 入口，并在入口支持时传入进度回调。
        输入：
            entry: crawler 更新函数。
            progress_callback: GUI 进度回调。
        输出：
            Any: crawler 原始返回值。
        使用示例：
            raw = AutomationBridge._call_crawler_entry(run_update, reporter)
        """
        try:
            signature = inspect.signature(entry)
        except (TypeError, ValueError):
            return entry()
        parameters = signature.parameters.values()
        accepts_progress = any(parameter.name == "progress_callback" for parameter in parameters)
        accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters)
        if accepts_progress or accepts_kwargs:
            return entry(progress_callback=progress_callback)
        return entry()

    @staticmethod
    def _success_message(raw_result: Any) -> str:
        """把 crawler 返回值转换成用户可见成功文案。"""
        if isinstance(raw_result, dict) and raw_result.get("message"):
            return str(raw_result["message"])
        return "资料更新流程已完成，基础数据已准备刷新。"

    @staticmethod
    def _success_detail(raw_result: Any) -> str:
        """
        把 crawler 结构化结果压缩成适合日志和 GUI 次级说明的摘要。
        输入：
            raw_result: crawler_update.run_update() 返回的 dict 或其他结果。
        输出：
            str: 包含正式表路径、计数和告警数量的简短说明。
        使用示例：
            detail = AutomationBridge._success_detail(payload)
        """
        if not isinstance(raw_result, dict):
            return str(raw_result or "")

        count_parts = []
        for key, label in (
            ("equipment_count", "装备"),
            ("image_count", "图片"),
            ("phase_count", "科研期数"),
            ("copied_image_count", "复制图片"),
        ):
            if key in raw_result:
                count_parts.append(f"{label}: {raw_result[key]}")

        path_parts = []
        for key, label in (
            ("equipment_library_path", "装备表"),
            ("equipment_images_path", "图片表"),
            ("research_phases_path", "科研表"),
        ):
            if raw_result.get(key):
                path_parts.append(f"{label}: {raw_result[key]}")

        warnings = raw_result.get("warnings") or []
        warning_text = f"告警: {len(warnings)}"
        return "；".join(["，".join(count_parts), "；".join(path_parts), warning_text]).strip("；")

    @staticmethod
    def _convert_task_result(raw_result: AdbTaskResult | OcrTaskResult) -> AutomationBridgeResult:
        """
        将核心层任务结果转换为 GUI 桥接结果。
        输入：
            raw_result: ADB 或 OCR API 返回值。
        输出：
            AutomationBridgeResult。
        使用示例：
            result = AutomationBridge._convert_task_result(raw)
        """
        return AutomationBridgeResult(
            bool(raw_result.success),
            str(raw_result.status),
            str(raw_result.message),
            str(raw_result.detail),
            raw_result.payload,
            tuple(raw_result.warnings),
        )


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
