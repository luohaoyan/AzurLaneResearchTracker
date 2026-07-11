#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🧵 GUI 后台任务管理器 (task_manager.py)         ║
║                                                              ║
║  【一句话解释】统一管理 GUI 中的长任务线程和任务清单。        ║
║  【类比理解】它像港区任务调度台，一次只允许一支远征队出港。   ║
║  【数据流说明】页面按钮 → TaskManager → QThread → 日志抽屉。  ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import inspect
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, QProcess, QThread, Signal, Slot

from core.contracts import CancellationToken, TaskCancelledError, TaskExecutionContext
from core.state.runtime_state import TaskStateKind, get_runtime_state_manager
from core.utils.logger import get_logger


# ============================================================
# 🏗️ 第二部分：核心类
# ============================================================

@dataclass(frozen=True)
class BackgroundTaskSpec:
    """
    后台任务定义。
    输入：
        task_id / title / kind 等用户可见和运行期状态信息。
    输出：
        不可变任务规格，交给 GuiTaskManager 启动。
    使用示例：
        spec = BackgroundTaskSpec("crawler_update", "资料爬取", TaskStateKind.EQUIPMENT_UPDATING)
    """

    task_id: str
    title: str
    kind: TaskStateKind
    start_message: str
    cancel_supported: bool = False


@dataclass
class TaskSnapshot:
    """
    任务清单快照。
    输入：
        任务运行中的状态字段。
    输出：
        dict，可给日志抽屉或测试读取。
    使用示例：
        task.to_dict()
    """

    task_id: str
    title: str
    kind: TaskStateKind
    status: str
    message: str
    progress: int = 0
    detail: str = ""
    cancel_supported: bool = False
    cancel_requested: bool = False
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为 GUI 可读取的字典。"""
        return {
            "task_id": self.task_id,
            "title": self.title,
            "kind": self.kind.value,
            "status": self.status,
            "message": self.message,
            "progress": self.progress,
            "detail": self.detail,
            "cancel_supported": self.cancel_supported,
            "cancel_requested": self.cancel_requested,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class BackgroundTaskWorker(QObject):
    """
    通用后台任务执行器。
    输入：
        task_id: 任务 ID。
        runner: 在线程中执行的函数，可接收 task_context 或进度回调。
        task_context: 进度和协作式取消的共享上下文。
    输出：
        finished 信号携带任务 ID 与执行结果。
    使用示例：
        worker.moveToThread(thread)
    """

    finished = Signal(str, object)

    def __init__(
        self,
        task_id: str,
        runner: Callable[..., Any],
        task_context: TaskExecutionContext,
    ) -> None:
        """保存任务 ID、执行函数和可取消任务上下文。"""
        super().__init__()
        self.task_id = task_id
        self.runner = runner
        self.task_context = task_context

    @Slot()
    def run(self) -> None:
        """
        在线程中执行任务函数。
        输入：
            无。
        输出：
            None，结果通过 finished 信号返回主线程。
        使用示例：
            thread.started.connect(worker.run)
        """
        result: Any
        try:
            result = self._call_runner()
        except TaskCancelledError as exc:
            result = {
                "success": False,
                "status": "cancelled",
                "message": str(exc) or "任务已在安全点取消。",
                "detail": "cancelled at safe point",
            }
        except Exception as exc:
            result = {
                "success": False,
                "status": "error",
                "message": "后台任务执行失败，请复制运行日志给开发者。",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        self.finished.emit(self.task_id, result)

    def _call_runner(self) -> Any:
        """
        按参数名称向 runner 注入任务上下文或旧版进度回调。
        输入：
            无，读取 runner 的函数签名。
        输出：
            Any: runner 的原始返回值。
        使用示例：
            result = self._call_runner()
        """
        try:
            signature = inspect.signature(self.runner)
        except (TypeError, ValueError):
            return self.runner()

        parameters = signature.parameters
        context_parameter = parameters.get("task_context")
        if context_parameter is not None:
            if context_parameter.kind == inspect.Parameter.POSITIONAL_ONLY:
                return self.runner(self.task_context)
            return self.runner(task_context=self.task_context)

        progress_names = {"progress_reporter", "progress_callback"}
        for parameter in parameters.values():
            if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
                if parameter.name in progress_names:
                    return self.runner(self.task_context.progress_reporter)
                break

        if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
            return self.runner(task_context=self.task_context)
        if any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters.values()):
            return self.runner(self.task_context.progress_reporter)
        return self.runner()


class GuiTaskManager(QObject):
    """
    GUI 长任务统一调度器。
    输入：
        无，内部持有当前后台线程和任务历史。
    输出：
        单例管理器，保证同一时间只有一个长任务运行。
    使用示例：
        get_gui_task_manager().start_task(spec, runner, callback)
    """

    taskChanged = Signal()
    taskProgressUpdated = Signal(str, int, str, str)

    _instance: Optional["GuiTaskManager"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "GuiTaskManager":
        """单例模式：整个 GUI 共享一个长任务调度台。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化任务调度器，重复初始化时直接返回。"""
        if hasattr(self, "_initialized"):
            return
        super().__init__()
        self.logger = get_logger()
        self.runtime_manager = get_runtime_state_manager()
        self._active_task_id: Optional[str] = None
        self._cancellation_token: Optional[CancellationToken] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[BackgroundTaskWorker] = None
        self._process: Optional[QProcess] = None
        self._process_output: Dict[str, List[str]] = {}
        self._process_error: str = ""
        self._process_finished_handled = False
        self._tasks: List[TaskSnapshot] = []
        self._finished_handlers: Dict[str, Callable[[Any], None]] = {}
        self._max_history = 20
        self.taskProgressUpdated.connect(self._apply_task_progress)
        self._initialized = True

    def start_task(
        self,
        spec: BackgroundTaskSpec,
        runner: Callable[..., Any],
        finished_handler: Optional[Callable[[Any], None]] = None,
    ) -> bool:
        """
        启动后台任务。
        输入：
            spec: 任务规格。
            runner: 在线程中执行的函数。
            finished_handler: 回到主线程后的页面回调。
        输出：
            bool: 成功启动为 True；已有任务运行时为 False。
        使用示例：
            manager.start_task(spec, bridge.run_crawler_update, self._on_finished)
        """
        if self.is_running():
            self._record_rejected_task(spec)
            return False

        self._active_task_id = spec.task_id
        snapshot = TaskSnapshot(
            task_id=spec.task_id,
            title=spec.title,
            kind=spec.kind,
            status="running",
            message=spec.start_message,
            progress=1,
            cancel_supported=spec.cancel_supported,
            started_at=datetime.now(),
        )
        self._append_snapshot(snapshot)
        self.runtime_manager.set_task_state(spec.kind, 1, spec.start_message, spec.title)

        thread = QThread()
        cancellation_token = CancellationToken()
        task_context = TaskExecutionContext(self.report_current_task_progress, cancellation_token)
        worker = BackgroundTaskWorker(spec.task_id, runner, task_context)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._finish_task)
        if finished_handler is not None:
            self._finished_handlers[spec.task_id] = finished_handler
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_thread_refs)

        self._thread = thread
        self._worker = worker
        self._cancellation_token = cancellation_token
        self.taskChanged.emit()
        thread.start()
        self.logger.info(f"后台任务已启动：{spec.title}")
        return True

    def start_process_task(
        self,
        spec: BackgroundTaskSpec,
        program: str,
        arguments: Optional[List[str]] = None,
        finished_handler: Optional[Callable[[Any], None]] = None,
    ) -> bool:
        """
        启动独立进程任务。
        输入：
            spec: 任务规格。
            program: 可执行程序路径。
            arguments: 命令行参数。
            finished_handler: 进程结束后的页面回调。
        输出：
            bool: 成功启动为 True；已有任务运行时为 False。
        使用示例：
            manager.start_process_task(spec, sys.executable, ["-m", "core.recognition.ocr_worker"])
        """
        if self.is_running():
            self._record_rejected_task(spec)
            return False

        self._active_task_id = spec.task_id
        self._cancellation_token = None
        snapshot = TaskSnapshot(
            task_id=spec.task_id,
            title=spec.title,
            kind=spec.kind,
            status="running",
            message=spec.start_message,
            progress=1,
            cancel_supported=spec.cancel_supported,
            started_at=datetime.now(),
        )
        self._append_snapshot(snapshot)
        self.runtime_manager.set_task_state(spec.kind, 1, spec.start_message, spec.title)
        if finished_handler is not None:
            self._finished_handlers[spec.task_id] = finished_handler

        process = QProcess()
        process.setProgram(program)
        process.setArguments(arguments or [])
        process.readyReadStandardOutput.connect(lambda: self._collect_process_output("stdout"))
        process.readyReadStandardError.connect(lambda: self._collect_process_output("stderr"))
        process.errorOccurred.connect(lambda error: self._record_process_error(error))
        process.finished.connect(lambda exit_code, exit_status: self._finish_process_task(spec.task_id, exit_code, exit_status))
        self._process = process
        self._process_output = {"stdout": [], "stderr": []}
        self._process_error = ""
        self._process_finished_handled = False
        self.taskChanged.emit()
        process.start()
        self.logger.info(f"后台进程任务已启动：{spec.title}")
        return True

    def request_cancel(self, task_id: Optional[str] = None) -> bool:
        """
        请求取消当前任务。
        输入：
            task_id: 可选任务 ID；为空时指向当前任务。
        输出：
            bool: 已记录取消请求为 True；当前任务不支持取消时为 False。
        使用示例：
            manager.request_cancel()
        """
        target_task_id = task_id or self._active_task_id
        snapshot = self._find_task(target_task_id)
        if snapshot is None or not snapshot.cancel_supported:
            return False
        snapshot.cancel_requested = True
        snapshot.message = "已收到取消请求，任务将在安全点结束。"
        if self._cancellation_token is not None:
            self._cancellation_token.request_cancel()
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.terminate()
        self.taskChanged.emit()
        return True

    def report_current_task_progress(self, progress: int, message: str = "", detail: str = "") -> bool:
        """
        推送当前长任务的显示进度。
        输入：
            progress: 0-100 之间的进度值。
            message: 可选的阶段提示。
            detail: 可选的细节说明。
        输出：
            bool: 成功找到当前任务时返回 True。
        """
        if self._active_task_id is None:
            return False
        self.taskProgressUpdated.emit(self._active_task_id, progress, message, detail)
        return True

    def get_current_task_progress_reporter(self) -> Callable[[int, str, str], bool]:
        """
        获取当前任务的进度上报函数。
        输入：
            无。
        输出：
            Callable: 可被桥接层或爬虫层安全调用的进度回调。
        使用示例：
            reporter = manager.get_current_task_progress_reporter()
        """
        return self.report_current_task_progress

    def clear_finished_tasks(self) -> int:
        """
        清理所有已完成或已失败的任务，仅保留进行中的任务。
        输入：
            无。
        输出：
            int: 被清理的记录数量。
        """
        if not self._tasks:
            return 0
        remaining_tasks = [snapshot for snapshot in self._tasks if snapshot.status == "running"]
        removed_count = len(self._tasks) - len(remaining_tasks)
        if removed_count <= 0:
            return 0
        self._tasks = remaining_tasks
        self.taskChanged.emit()
        self.logger.info(f"已清理 {removed_count} 条已完成任务记录")
        return removed_count

    def remove_task(self, task_id: str) -> bool:
        """
        删除一条已完成任务记录。
        输入：
            task_id: 目标任务 ID。
        输出：
            bool: 删除成功返回 True。
        """
        if not task_id:
            return False
        removed = False
        remaining_tasks: List[TaskSnapshot] = []
        for snapshot in self._tasks:
            if snapshot.task_id == task_id and snapshot.status != "running":
                removed = True
                continue
            remaining_tasks.append(snapshot)
        if not removed:
            return False
        self._tasks = remaining_tasks
        self.taskChanged.emit()
        self.logger.info(f"已删除任务记录：{task_id}")
        return True

    def is_running(self) -> bool:
        """判断是否已有后台长任务运行。"""
        thread_running = self._thread is not None and self._thread.isRunning()
        process_running = self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning
        return self._active_task_id is not None or thread_running or process_running

    def get_task_snapshots(self) -> List[Dict[str, Any]]:
        """获取任务历史，最新任务排在最前。"""
        return [snapshot.to_dict() for snapshot in reversed(self._tasks)]

    def reset_for_tests(self) -> None:
        """
        重置任务管理器状态。
        输入：
            无。
        输出：
            None。仅供测试在没有运行线程时使用。
        使用示例：
            get_gui_task_manager().reset_for_tests()
        """
        if self.is_running():
            return
        self._tasks.clear()
        self._active_task_id = None
        self._cancellation_token = None
        self._thread = None
        self._worker = None
        self._process = None
        self._process_output = {}
        self._process_error = ""
        self._process_finished_handled = False
        self._finished_handlers.clear()
        self.taskChanged.emit()

    @Slot(str, object)
    def _finish_task(self, task_id: str, result: Any) -> None:
        """后台任务完成后更新任务快照。"""
        snapshot = self._find_task(task_id)
        if snapshot is not None:
            success = self._result_success(result)
            status = self._result_value(result, "status", "success" if success else "error")
            snapshot.status = "success" if success else status
            snapshot.progress = 100 if success else snapshot.progress
            result_message = self._result_value(result, "message", "任务已完成" if success else "任务失败")
            snapshot.message = f"已执行：{result_message}" if success else result_message
            snapshot.detail = self._result_value(result, "detail", "")
            snapshot.finished_at = datetime.now()
            if snapshot.status == "cancelled":
                self.runtime_manager.set_task_state(
                    TaskStateKind.IDLE,
                    snapshot.progress,
                    snapshot.message,
                    snapshot.title,
                )
        finished_handler = self._finished_handlers.pop(task_id, None)
        if finished_handler is not None:
            finished_handler(result)
        self.taskChanged.emit()
        self.logger.info(f"后台任务已结束：{task_id}")

    def _record_rejected_task(self, spec: BackgroundTaskSpec) -> None:
        """记录被拒绝启动的任务，提醒用户一次只能运行一个长任务。"""
        active_title = self._active_task_title()
        snapshot = TaskSnapshot(
            task_id=f"{spec.task_id}_rejected_{len(self._tasks) + 1}",
            title=spec.title,
            kind=spec.kind,
            status="rejected",
            message=f"已有任务“{active_title}”正在运行，请等待完成后再启动。",
            progress=0,
            cancel_supported=False,
            started_at=datetime.now(),
            finished_at=datetime.now(),
        )
        self._append_snapshot(snapshot)
        self.logger.warning(snapshot.message)
        self.taskChanged.emit()

    def _append_snapshot(self, snapshot: TaskSnapshot) -> None:
        """追加任务快照并限制历史长度。"""
        self._tasks.append(snapshot)
        if len(self._tasks) > self._max_history:
            self._tasks = self._tasks[-self._max_history:]

    def _find_task(self, task_id: Optional[str]) -> Optional[TaskSnapshot]:
        """按任务 ID 查找任务快照。"""
        if not task_id:
            return None
        for snapshot in reversed(self._tasks):
            if snapshot.task_id == task_id:
                return snapshot
        return None

    def _active_task_title(self) -> str:
        """获取当前运行任务标题。"""
        snapshot = self._find_task(self._active_task_id)
        return snapshot.title if snapshot else "未知任务"

    def _clear_thread_refs(self) -> None:
        """清理线程和 worker 引用，避免下一次任务被误判占用。"""
        self._active_task_id = None
        self._cancellation_token = None
        self._thread = None
        self._worker = None
        self.taskChanged.emit()

    @Slot(str, int, str, str)
    def _apply_task_progress(self, task_id: str, progress: int, message: str, detail: str) -> None:
        """在主线程中刷新任务快照进度，供任务清单实时更新。"""
        snapshot = self._find_task(task_id)
        if snapshot is None or snapshot.status != "running":
            return
        snapshot.progress = max(0, min(100, int(progress)))
        if message:
            snapshot.message = message
        if detail:
            snapshot.detail = detail
        self.taskChanged.emit()

    def _collect_process_output(self, stream_name: str) -> None:
        """收集进程输出，方便失败时复制诊断信息。"""
        if self._process is None:
            return
        if stream_name == "stderr":
            data = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace")
        else:
            data = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if data:
            self._process_output.setdefault(stream_name, []).append(data)

    def _record_process_error(self, error: QProcess.ProcessError) -> None:
        """记录 QProcess 启动或运行错误。"""
        self._process_error = str(error)
        if error == QProcess.ProcessError.FailedToStart and not self._process_finished_handled:
            task_id = self._active_task_id or "process_task"
            self._process_finished_handled = True
            result = {
                "success": False,
                "status": "error",
                "message": "后台进程启动失败，请检查 OCR/ADB 运行环境。",
                "detail": f"process_error: {self._process_error}",
            }
            self._finish_task(task_id, result)
            self._clear_process_refs()

    def _finish_process_task(self, task_id: str, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        """进程结束后转换为统一任务结果。"""
        if self._process_finished_handled:
            return
        self._process_finished_handled = True
        stdout_text = "".join(self._process_output.get("stdout", [])).strip()
        stderr_text = "".join(self._process_output.get("stderr", [])).strip()
        success = exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0 and not self._process_error
        detail_parts = []
        if stdout_text:
            detail_parts.append(f"stdout: {stdout_text[-500:]}")
        if stderr_text:
            detail_parts.append(f"stderr: {stderr_text[-500:]}")
        if self._process_error:
            detail_parts.append(f"process_error: {self._process_error}")
        result = {
            "success": success,
            "status": "success" if success else "error",
            "message": "后台进程任务已完成。" if success else "后台进程任务失败，请复制运行日志给开发者。",
            "detail": "；".join(detail_parts),
        }
        self._finish_task(task_id, result)
        self._clear_process_refs()

    def _clear_process_refs(self) -> None:
        """清理进程引用，释放下一次长任务锁。"""
        process = self._process
        self._active_task_id = None
        self._cancellation_token = None
        self._process = None
        self._process_output = {}
        self._process_error = ""
        self._process_finished_handled = False
        if process is not None:
            process.deleteLater()
        self.taskChanged.emit()

    @staticmethod
    def _result_success(result: Any) -> bool:
        """兼容 dataclass 结果和 dict 结果，读取 success 字段。"""
        if isinstance(result, dict):
            return bool(result.get("success", False))
        return bool(getattr(result, "success", False))

    @staticmethod
    def _result_value(result: Any, key: str, default: str = "") -> str:
        """兼容 dataclass 结果和 dict 结果，读取字符串字段。"""
        if isinstance(result, dict):
            return str(result.get(key, default))
        return str(getattr(result, key, default))


# ============================================================
# 🌐 第三部分：全局访问函数
# ============================================================

_gui_task_manager: Optional[GuiTaskManager] = None


def get_gui_task_manager() -> GuiTaskManager:
    """
    获取全局 GUI 任务管理器。
    输入：
        无。
    输出：
        GuiTaskManager: 全局共享任务管理器。
    使用示例：
        manager = get_gui_task_manager()
    """
    global _gui_task_manager
    if _gui_task_manager is None:
        _gui_task_manager = GuiTaskManager()
    return _gui_task_manager
