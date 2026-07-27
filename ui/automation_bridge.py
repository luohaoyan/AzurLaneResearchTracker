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
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Callable, Dict, Iterable, Optional, Sequence

from core.automation.adb_task_api import AdbTaskResult, get_adb_task_api
from core.automation.equipment_page import get_equipment_page_adb_api
from core.contracts import StructuredTaskResult, TaskCancelledError, TaskExecutionContext
from core.recognition.ocr_task_api import OcrTaskResult, get_ocr_task_api
from core.state.runtime_state import TaskStateKind, get_runtime_state_manager
from core.utils.logger import get_logger
from core.utils.path_manager import PathManager


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
        *,
        simulator_key: Optional[str] = None,
        serial: Optional[str] = None,
        port: Optional[str | int] = None,
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
            "正在检测模拟器 ADB 真实连接状态。",
            lambda task_context=None: get_adb_task_api().check_connection(
                task_context=task_context,
                strict_status=True,
                simulator_key=simulator_key,
                serial=serial,
                port=port,
            ),
            progress_reporter,
            task_context,
        )

    def run_adb_auto_connect(
        self,
        progress_reporter: Optional[Callable[[int, str, str], object]] = None,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        simulator_key: Optional[str] = None,
        serial: Optional[str] = None,
        port: Optional[str | int] = None,
    ) -> AutomationBridgeResult:
        """
        安全执行模拟器自动连接。
        """
        return self._run_safe_api(
            TaskStateKind.AUTO_TESTING,
            "模拟器自动连接",
            "正在自动发现并连接当前模拟器。",
            lambda task_context=None: get_adb_task_api().auto_connect_simulator(
                task_context=task_context,
                simulator_key=simulator_key,
                serial=serial,
                port=port,
            ),
            progress_reporter,
            task_context,
        )

    def run_game_auto_login(
        self,
        progress_reporter: Optional[Callable[[int, str, str], object]] = None,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        client_key: Optional[str] = None,
        server_key: Optional[str] = None,
        simulator_key: Optional[str] = None,
        serial: Optional[str] = None,
        port: Optional[str | int] = None,
    ) -> AutomationBridgeResult:
        """
        安全执行碧蓝航线游戏自动启动。
        """
        return self._run_safe_api(
            TaskStateKind.AUTO_TESTING,
            "游戏自动登录",
            "正在扫描模拟器应用列表并启动碧蓝航线。",
            lambda task_context=None: get_adb_task_api().run_azur_lane_auto_login(
                task_context=task_context,
                client_key=client_key,
                server_key=server_key,
                simulator_key=simulator_key,
                serial=serial,
                port=port,
            ),
            progress_reporter,
            task_context,
        )

    def run_game_enter_home(
        self,
        progress_reporter: Optional[Callable[[int, str, str], object]] = None,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        client_key: Optional[str] = None,
        server_key: Optional[str] = None,
        simulator_key: Optional[str] = None,
        serial: Optional[str] = None,
        port: Optional[str | int] = None,
    ) -> AutomationBridgeResult:
        """
        安全执行从模拟器当前画面进入港区主页的完整检测。
        输入：
            当前 UI 选择的客户端、服务器和模拟器连接参数。
        输出：
            AutomationBridgeResult；只有识别到 harbor 才会 success=True。
        使用示例：
            result = bridge.run_game_enter_home(server_key="莱茵演习")
        """
        return self._run_safe_api(
            TaskStateKind.AUTO_TESTING,
            "进入游戏主页",
            "正在从模拟器桌面进入港区主页。",
            lambda task_context=None: get_adb_task_api().run_azur_lane_enter_home(
                task_context=task_context,
                client_key=client_key,
                server_key=server_key,
                simulator_key=simulator_key,
                serial=serial,
                port=port,
            ),
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

    def run_design_chart_flow(
        self,
        progress_reporter: Optional[Callable[[int, str, str], object]] = None,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        rarities: Optional[Sequence[str]] = None,
        resume_cursor: Optional[int] = None,
    ) -> AutomationBridgeResult:
        """
        安全执行设计图完整流程测试。
        输入：
            progress_reporter: 兼容旧任务的进度回调。
            task_context: v0.6.0 可取消任务上下文。
        输出：
            AutomationBridgeResult: 设计图页切换、稀有度切换和断点续跑信息。
        使用示例：
            result = bridge.run_design_chart_flow()
        """
        reporter = task_context.progress_reporter if task_context is not None else progress_reporter
        task_name = "设计图功能测试"
        rarity_text = ",".join(str(item).strip() for item in (rarities or ("common", "rare", "elite", "super_rare", "ultra_rare")))
        self.logger.info(f"[设计图] 桥接任务开始 | rarities={rarity_text}；resume_cursor={resume_cursor if resume_cursor is not None else 'auto'}")
        self.runtime_manager.set_task_state(TaskStateKind.AUTO_TESTING, 5, "正在准备设计图完整流程。", task_name)
        if reporter is not None:
            reporter(5, "正在准备设计图完整流程。", "")

        api = get_equipment_page_adb_api()
        warnings: list[str] = []
        try:
            if task_context is not None:
                task_context.raise_if_cancelled(f"{task_name}已取消。")

            if reporter is not None:
                reporter(15, "正在切换到设计图页。", "")
            design_ready = api.ensure_warehouse_design_page_ready(task_context=task_context)
            warnings.extend(design_ready.warnings)
            self.logger.info(
                f"[设计图] 仓库页切换结果 | success={bool(design_ready.success)}；status={design_ready.status}"
                f"；confirmed={bool((design_ready.payload or {}).get('design_tab_confirmed', False))}"
            )
            if not design_ready.success:
                payload = dict(design_ready.payload or {})
                payload.update({"design_page_result": design_ready.to_dict(), "resume_cursor_loaded": 0})
                self.runtime_manager.set_task_state(TaskStateKind.ERROR, 0, design_ready.message, task_name, design_ready.detail)
                if reporter is not None:
                    reporter(0, design_ready.message, design_ready.detail)
                return AutomationBridgeResult(False, design_ready.status, design_ready.message, design_ready.detail, payload, tuple(warnings))

            loaded_resume_cursor, resume_summary_path = self._latest_design_rarity_resume_cursor(api)
            effective_resume_cursor = loaded_resume_cursor if resume_cursor is None else max(0, int(resume_cursor))
            effective_rarities = tuple(str(item).strip() for item in (rarities or ("common", "rare", "elite", "super_rare", "ultra_rare")))
            self.logger.info(
                f"[设计图] 断点解析完成 | source={str(resume_summary_path) if resume_summary_path is not None else 'none'}"
                f"；auto_loaded={loaded_resume_cursor}；effective={effective_resume_cursor}"
            )
            if reporter is not None:
                reporter(35, "正在读取断点游标。", str(resume_summary_path) if resume_summary_path is not None else "无历史 summary")
                reporter(55, "正在执行设计图稀有度切换。", f"resume_cursor={effective_resume_cursor}")
            session = api.capture_design_rarity_sequence(
                rarities=effective_rarities,
                resume_cursor=effective_resume_cursor,
                task_context=task_context,
            )
            warnings.extend(session.warnings)
            session_frames = getattr(session, "frames", ())
            session_frame_count = len(session_frames) if hasattr(session_frames, "__len__") else 0
            session_duplicate_count = int(getattr(session, "duplicate_frame_count", 0))
            session_next_cursor = int(getattr(session, "next_resume_cursor", effective_resume_cursor))
            session_run_dir = str(getattr(session, "run_dir", ""))
            self.logger.info(
                f"[设计图] 稀有度切换结果 | success={bool(session.success)}；status={session.status}"
                f"；frames={session_frame_count}；duplicates={session_duplicate_count}"
                f"；next_resume_cursor={session_next_cursor}"
            )
            payload = session.to_dict()
            payload.update(
                {
                    "design_page_result": design_ready.to_dict(),
                    "resume_cursor_source": str(resume_summary_path) if resume_summary_path is not None else "",
                    "resume_cursor_loaded": int(effective_resume_cursor),
                    "rarities_requested": list(effective_rarities),
                    "resume_cursor_auto_loaded": int(loaded_resume_cursor),
                }
            )
            success = bool(design_ready.success and session.success)
            status = session.status if session.success else session.status or "error"
            message = "设计图完整流程已完成。" if success else "设计图完整流程已执行，但部分步骤失败。"
            detail = f"design_tab={design_ready.status}; resume_cursor={effective_resume_cursor}; run_dir={session.run_dir}"
            final_kind = TaskStateKind.IDLE if success else TaskStateKind.ERROR
            self.runtime_manager.set_task_state(
                final_kind,
                100 if success else 0,
                message,
                task_name,
                "" if success else session.message,
            )
            if reporter is not None:
                reporter(100 if success else 0, message, detail)
            self.logger.info(
                f"[设计图] 桥接任务完成 | success={success}；status={status}；resume_cursor={effective_resume_cursor}；run_dir={session_run_dir}"
            )
            return AutomationBridgeResult(success, status, message, detail, payload, tuple(warnings))
        except TaskCancelledError as exc:
            message = str(exc) or f"{task_name}已取消。"
            self.runtime_manager.set_task_state(TaskStateKind.IDLE, 0, message, task_name)
            if reporter is not None:
                reporter(0, message, "cancelled at safe point")
            self.logger.warning(f"[设计图] 桥接任务取消 | message={message}")
            return AutomationBridgeResult(False, "cancelled", message, "cancelled at safe point", warnings=tuple(warnings))
        except Exception as exc:
            message = f"{task_name}执行失败，请复制运行日志给开发者。"
            detail = f"{type(exc).__name__}: {exc}"
            self.runtime_manager.set_task_state(TaskStateKind.ERROR, 0, message, task_name, detail)
            if reporter is not None:
                reporter(0, message, detail)
            self.logger.exception("[设计图] 桥接任务异常")
            return AutomationBridgeResult(False, "error", message, detail, warnings=tuple(warnings))

    def run_design_fragment_scan(
        self,
        progress_reporter: Optional[Callable[[int, str, str], object]] = None,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        rarity_state: str = "super_rare",
        resume_cursor: int = 0,
        scroll_step_px: int = 0,
        until_bottom: bool = True,
        enforce_rarity_filter: bool = False,
        generate_preview: bool = False,
    ) -> AutomationBridgeResult:
        """
        在设计图功能测试面板中执行一次“分帧采集 + 识别”。

        输入：
            rarity_state: 当前已在模拟器中选择的单个稀有度。
            resume_cursor: 断点游标，通常从 0 开始。
            scroll_step_px: ADB 每次滚动步长；0 表示使用采集层默认值。
            until_bottom: 是否持续采集到列表底部。
            enforce_rarity_filter: 是否把稀有度作为硬候选过滤条件。
            generate_preview: 是否生成 annotated 预览图；正式接入建议关闭。
        输出：
            AutomationBridgeResult: 包含 output_dir、recognition_summary 和 ADB 上下文的结构化结果。
        使用示例：
            result = bridge.run_design_fragment_scan(rarity_state="super_rare")
        """
        reporter = task_context.progress_reporter if task_context is not None else progress_reporter
        task_name = "设计图扫图识别"
        rarity = str(rarity_state or "").strip().lower() or "super_rare"
        warnings: list[str] = []

        def report(progress: int, message: str, detail: str = "") -> None:
            """同时更新任务状态和 GUI 进度。"""
            safe_progress = max(0, min(100, int(progress)))
            self.runtime_manager.set_task_state(
                TaskStateKind.OCR_PROCESSING,
                safe_progress,
                message,
                task_name,
                detail,
            )
            if reporter is not None:
                reporter(safe_progress, message, detail)

        report(3, "正在准备设计图扫图识别。", f"rarity_state={rarity}")
        try:
            if task_context is not None:
                task_context.raise_if_cancelled(f"{task_name}已取消。")

            # 延迟导入工作台，避免 GUI/pytest 启动时加载 PaddleOCR、ONNX 等重依赖。
            from recognition_workbench.run_adb_design_fragment_recognition import (
                capture_adb_design_frames,
                collect_frame_paths,
                load_manifest,
                run_recognition_for_images,
                write_adb_context,
            )

            report(8, "正在通过 ADB 采集设计图分帧。", "默认使用当前已打开的设计图页")
            capture_args = SimpleNamespace(
                frame_count=8,
                overlap_ratio=0.35,
                scroll_step_px=max(0, int(scroll_step_px)),
                scroll_settle_ms=800,
                resume_cursor=max(0, int(resume_cursor)),
                prepare_page=False,
                no_stop_on_repeat=False,
                ensure_top=True,
                until_bottom=bool(until_bottom),
                filter_state="all",
                rarity_state=rarity,
                sort_state="buildable",
                notify_actions=False,
                device_message_mode="none",
                capture_session_id="",
            )
            manifest_path, capture_session = capture_adb_design_frames(capture_args)
            if manifest_path is None:
                message = "设计图分帧采集没有生成 manifest.json。"
                report(0, message, "capture returned no manifest")
                return AutomationBridgeResult(False, "capture_failed", message, "capture returned no manifest")

            manifest = load_manifest(manifest_path)
            image_paths, frame_records = collect_frame_paths(manifest)
            report(35, "分帧采集完成，正在整理可识别图片。", f"selected_frames={len(image_paths)}")
            run_name = f"ui_design_scan_{time.strftime('%Y%m%d_%H%M%S')}"
            output_dir = PathManager.get_project_root() / "recognition_workbench" / "adb_test_out"
            run_dir = output_dir / run_name

            if not image_paths:
                empty_summary = {
                    "images": 0,
                    "detected_cards": 0,
                    "final_success": 0,
                    "needs_review": 0,
                    "warning": "No usable ADB frames were selected for OCR.",
                }
                write_adb_context(
                    run_dir,
                    manifest_path=manifest_path,
                    manifest=manifest,
                    selected_frames=frame_records,
                    capture_session=capture_session,
                    recognition_summary=empty_summary,
                )
                report(100, "设计图扫图完成，但没有可识别帧。", str(run_dir))
                return AutomationBridgeResult(
                    False,
                    "no_frames",
                    "设计图扫图完成，但没有可识别帧。",
                    str(run_dir),
                    {"output_dir": str(run_dir), **empty_summary},
                    tuple(warnings),
                )

            report(45, "正在执行 OpenCV + OCR + ONNX/PyTorch assist。", f"rarity_state={rarity}")
            summary = run_recognition_for_images(
                image_paths,
                run_dir,
                image_mode="viewport_full",
                model=None,
                onnx_dir=None,
                onnx_model="equipment_icon_resnet18_fp16.onnx",
                nn_backend="auto",
                nn_mode="assist",
                skip_ocr=False,
                skip_icons=False,
                disable_nn=False,
                nn_min_confidence=0.55,
                nn_min_margin=0.08,
                nn_trigger_threshold=0.82,
                rarity_state=rarity,
                enforce_rarity_filter=bool(enforce_rarity_filter),
                no_preview=not bool(generate_preview),
            )
            write_adb_context(
                run_dir,
                manifest_path=manifest_path,
                manifest=manifest,
                selected_frames=frame_records,
                capture_session=capture_session,
                recognition_summary=summary,
            )
            payload = {
                "output_dir": str(run_dir),
                "manifest_path": str(manifest_path),
                "rarity_state": rarity,
                "capture_session": capture_session or {},
                "recognition_summary": summary,
                "selected_frame_count": len(frame_records),
                "next_resume_cursor": manifest.get("next_resume_cursor"),
            }
            success = int(summary.get("final_success", 0) or 0) > 0
            status = "ready" if success else "needs_review"
            message = "设计图扫图识别完成。" if success else "设计图扫图完成，但结果需要人工复核。"
            detail = (
                f"frames={len(frame_records)}；detected_cards={summary.get('detected_cards', 0)}；"
                f"final_success={summary.get('final_success', 0)}；run_dir={run_dir}"
            )
            report(100 if success else 90, message, detail)
            self.logger.info(
                f"[设计图扫图] 完成 | success={success}；rarity={rarity}；"
                f"frames={len(frame_records)}；run_dir={run_dir}"
            )
            return AutomationBridgeResult(success, status, message, detail, payload, tuple(warnings))
        except TaskCancelledError as exc:
            message = str(exc) or f"{task_name}已取消。"
            report(0, message, "cancelled at safe point")
            self.logger.warning(f"[设计图扫图] 任务取消 | message={message}")
            return AutomationBridgeResult(False, "cancelled", message, "cancelled at safe point")
        except Exception as exc:
            message = f"{task_name}执行失败，请复制运行日志给开发者。"
            detail = f"{type(exc).__name__}: {exc}"
            report(0, message, detail)
            self.logger.exception("[设计图扫图] 桥接任务异常")
            return AutomationBridgeResult(False, "error", message, detail, warnings=tuple(warnings))

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

    def _latest_design_rarity_resume_cursor(self, api: object) -> tuple[int, Optional[Path]]:
        """从最新的设计图稀有度 summary.json 读取断点续跑游标。"""
        root = PathManager.get_work_dir() / "automation" / "equipment_page" / "design_rarity_runs"
        if not root.exists():
            self.logger.debug(f"[设计图] 断点目录不存在 | root={root}")
            return 0, None
        summaries = sorted(
            (path for path in root.glob("run_*/summary.json") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not summaries:
            self.logger.debug(f"[设计图] 未找到可用 summary | root={root}")
            return 0, None
        summary_path = summaries[0]
        try:
            cursor = int(api.load_design_rarity_resume_cursor(summary_path))
        except Exception as exc:
            self.logger.warning(f"[设计图] 读取断点游标失败 | summary={summary_path}；error={type(exc).__name__}: {exc}")
            cursor = 0
        else:
            self.logger.debug(f"[设计图] 读取断点游标成功 | summary={summary_path}；next_resume_cursor={cursor}")
        return max(0, cursor), summary_path


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
