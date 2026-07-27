#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║             🛰️ 研究页 ADB API (research_page_adb_api.py)    ║
║                                                              ║
║  【一句话解释】为科研页/设计图页提供分帧截图和滚动采集能力。  ║
║  【类比理解】它像摄影机轨道控制器，只管拍和滚，不做识别。   ║
║  【数据流说明】页面动作 → 帧序列 → manifest/actions/summary。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

from PIL import Image

from core.automation.adb_controller import AdbCommandResult, AdbController
from core.contracts import RecognitionScene, TaskExecutionContext
from core.recognition import get_design_fragment_detector
from core.utils.config_loader import get_config_loader
from core.utils.logger import get_logger
from core.utils.path_manager import PathManager

from .research_page_constants import (
    BASE_RESOLUTION,
    DEFAULT_ACTION_NOTIFICATION_TITLE,
    DEFAULT_BOTTOM_CONFIRMATIONS,
    DEFAULT_CAPTURE_RETRY_LIMIT,
    DEFAULT_FILTER_STATE,
    DEFAULT_PAGE_NAME,
    DEFAULT_PAGE_STATE,
    DEFAULT_POST_ACTION_DELAY_MS,
    DEFAULT_SCROLL_SETTLE_DELAY_MS,
    DEFAULT_RARITY_STATE,
    DEFAULT_SCROLL_DURATION_MS,
    DEFAULT_SCROLL_OVERLAP_RATIO,
    DEFAULT_AUTO_SCROLL_STEP_CAP_PX,
    DEFAULT_SCROLL_RETRY_LIMIT,
    DEFAULT_SCROLL_STEP_PX,
    DEFAULT_SORT_STATE,
    SCROLL_ANCHORS,
)
from .research_page_models import (
    ResearchPageAdbResult,
    ResearchPageCaptureArtifact,
    ResearchPageScrollSession,
)


# ============================================================
# 🏗️ 第二部分：研究页 ADB API
# ============================================================

class ResearchPageAdbApi:
    """
    科研页/设计图页专用 ADB 自动化门面。
    输入：
        通过 config/config.json 和 config/simulators/*.json 读取当前模拟器。
    输出：
        结构化预检结果、连续帧截图和可断点续扫的采集会话。
    使用示例：
        api = get_research_page_adb_api()
        session = api.capture_design_chart_sequence(frame_count=6)
    """

    _instance: Optional["ResearchPageAdbApi"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "ResearchPageAdbApi":
        """单例模式：科研页采集与 GUI/OCR 整合层共享同一套配置读取逻辑。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化研究页 API，重复初始化时直接返回。"""
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        self.config_loader = get_config_loader()
        self._controller_factory: Callable[[Dict[str, Any]], AdbController] = AdbController
        self._scene_probe: Optional[Callable[..., object]] = None
        self._state_probe: Optional[Callable[..., object]] = None
        self._initialized = True

    def configure_probes(
        self,
        *,
        scene_probe: Optional[Callable[..., object]] = None,
        state_probe: Optional[Callable[..., object]] = None,
    ) -> None:
        """
        注入页面状态探针。
        输入：
            scene_probe: 判断是否进入科研页；state_probe: 返回更细的 screen_state。
        输出：
            无；后续 ensure/capture 流程会复用这些探针。
        使用示例：
            api.configure_probes(scene_probe=lambda scene: True)
        """
        self._scene_probe = scene_probe
        self._state_probe = state_probe

    def check_connection(self, task_context: Optional[TaskExecutionContext] = None) -> ResearchPageAdbResult:
        """
        检查科研页采集所需的 ADB、设备、分辨率和截图能力。
        输入：
            task_context: 可选任务上下文，用于响应取消。
        输出：
            ResearchPageAdbResult，payload 中包含 adb_path/device_serial/display_environment。
        使用示例：
            result = api.check_connection()
        """
        self._raise_if_cancelled(task_context, "研究页 ADB 连接检查已取消。")
        simulator = self._get_simulator_context()
        controller = self._create_controller(simulator)
        adb_resolution = controller.find_adb()
        if not adb_resolution.available:
            payload = self._base_payload(simulator, controller, adb_path=None, adb_ready=False)
            payload.update(adb_resolution.to_dict())
            message = "未找到可用 ADB，科研页采集不可用。"
            return ResearchPageAdbResult(False, "unavailable", message, "请开启模拟器 ADB/Android 调试开关后重试。", payload, tuple(adb_resolution.warnings))

        connection = controller.check_connection(serial=simulator["device_serial"] or None, task_context=task_context)
        payload = self._base_payload(
            simulator,
            controller,
            adb_path=connection.adb_path,
            adb_ready=connection.success,
            device_serial=connection.selected_device.serial if connection.selected_device else simulator["device_serial"],
        )
        payload["adb_resolution"] = adb_resolution.to_dict()
        payload["connection"] = connection.to_payload()
        if not connection.success or connection.selected_device is None:
            warnings = list(adb_resolution.warnings)
            warnings.extend(connection.warnings)
            return ResearchPageAdbResult(False, connection.status, connection.message, "设备未就绪，无法继续科研页采集。", payload, tuple(warnings))

        display_check = controller.check_display_environment(serial=connection.selected_device.serial, task_context=task_context)
        payload["display_environment"] = display_check.to_dict()
        payload["real_capture_enabled"] = False
        warnings = list(adb_resolution.warnings)
        warnings.extend(connection.warnings)
        warnings.extend(display_check.warnings)

        resolution = display_check.resolution
        simulator_type = str(simulator["config"].get("type", "") or "").lower()
        if resolution is None:
            message = "无法读取模拟器分辨率，科研页采集要求 1280x720。"
            payload["real_capture_enabled"] = False
            return ResearchPageAdbResult(False, "unsupported_resolution", message, self._resolution_detail(display_check), payload, tuple(warnings + list(display_check.suggestions)))
        if tuple(resolution) != BASE_RESOLUTION:
            message = f"当前分辨率为 {resolution[0]}x{resolution[1]}，科研页采集仅支持 1280x720。"
            payload["real_capture_enabled"] = False
            return ResearchPageAdbResult(False, "unsupported_resolution", message, self._resolution_detail(display_check), payload, tuple(warnings + list(display_check.suggestions)))
        if simulator_type == "mumu" and "tablet" not in (display_check.characteristics or "").lower():
            message = "MuMu 模拟器需要切换为平板模式后才能进行科研页采集。"
            payload["real_capture_enabled"] = False
            return ResearchPageAdbResult(False, "unsupported_mode", message, self._resolution_detail(display_check), payload, tuple(warnings + list(display_check.suggestions)))

        payload["real_capture_enabled"] = True
        payload["display_environment"] = display_check.to_dict()
        detail = f"模拟器={simulator['name']}；ADB={payload['adb_path'] or '未找到'}；分辨率={resolution[0]}x{resolution[1]}"
        message = "科研页采集环境已就绪。"
        return ResearchPageAdbResult(True, "ready", message, detail, payload, tuple(warnings))

    def ensure_research_page_ready(
        self,
        scene_probe: Optional[Callable[..., object]] = None,
        state_probe: Optional[Callable[..., object]] = None,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        serial: Optional[str] = None,
        notify: bool = False,
    ) -> ResearchPageAdbResult:
        """
        进入科研页并等待页面状态稳定。
        输入：
            scene_probe/state_probe: 可注入的页面探针；notify: 是否显示模拟器提示。
        输出：
            ResearchPageAdbResult，payload 中保留导航结果和截图证据。
        使用示例：
            api.ensure_research_page_ready(scene_probe=lambda scene: True)
        """
        self._raise_if_cancelled(task_context, "进入科研页任务已取消。")
        simulator = self._get_simulator_context()
        controller = self._create_controller(simulator)
        if notify:
            self._notify_device(controller, "正在进入科研页", serial=serial or simulator["device_serial"] or None, task_context=task_context)
        effective_scene_probe = scene_probe or self._scene_probe or self._optimistic_scene_probe
        effective_state_probe = state_probe or self._state_probe or self._optimistic_state_probe
        if scene_probe is None and self._scene_probe is None:
            self.logger.warning("未注入 scene_probe，科研页导航将使用乐观探针。")
        if state_probe is None and self._state_probe is None:
            self.logger.warning("未注入 state_probe，科研页状态将使用乐观探针。")

        navigation = controller.run_sequence(
            "enter_research",
            effective_scene_probe,
            state_probe=effective_state_probe,
            serial=serial or simulator["device_serial"] or None,
            task_context=task_context,
        )
        navigation_payload = self._navigation_result_payload(navigation)
        payload = {
            "simulator_key": simulator["key"],
            "simulator_name": simulator["name"],
            **navigation_payload,
            "page_name": DEFAULT_PAGE_NAME,
            "page_state": DEFAULT_PAGE_STATE,
        }
        detail = navigation.detail or f"序列={navigation.sequence_name}；尝试={navigation.attempts}"
        return ResearchPageAdbResult(navigation.success, navigation.status, navigation.message, detail, payload, tuple(navigation.warnings))

    def capture_design_chart_sequence(
        self,
        frame_count: int,
        *,
        overlap_ratio: float = DEFAULT_SCROLL_OVERLAP_RATIO,
        scroll_step_px: int = DEFAULT_SCROLL_STEP_PX,
        scroll_duration_ms: int = DEFAULT_SCROLL_DURATION_MS,
        scroll_settle_delay_ms: int = DEFAULT_SCROLL_SETTLE_DELAY_MS,
        resume_cursor: int = 0,
        capture_retry_limit: int = DEFAULT_CAPTURE_RETRY_LIMIT,
        scroll_retry_limit: int = DEFAULT_SCROLL_RETRY_LIMIT,
        stop_on_repeat: bool = True,
        ensure_top: bool = False,
        capture_until_bottom: bool = False,
        page_name: str = DEFAULT_PAGE_NAME,
        page_state: str = DEFAULT_PAGE_STATE,
        filter_state: str = DEFAULT_FILTER_STATE,
        rarity_state: str = DEFAULT_RARITY_STATE,
        sort_state: str = DEFAULT_SORT_STATE,
        task_context: Optional[TaskExecutionContext] = None,
        scene_probe: Optional[Callable[..., object]] = None,
        state_probe: Optional[Callable[..., object]] = None,
        prepare_page: bool = True,
        notify_actions: bool = False,
        device_message_mode: str = "none",
        serial: Optional[str] = None,
        session_id: str = "",
    ) -> ResearchPageScrollSession:
        """
        连续采集科研页/设计图页 viewport 序列，并写出 manifest/actions/summary。
        输入：
            frame_count: 采集帧数；overlap_ratio: 帧间重叠比例；resume_cursor: 断点续接游标。
        输出：
            ResearchPageScrollSession，包含 frames/manifest/actions/device_info/summary。
        使用示例：
            session = api.capture_design_chart_sequence(8, overlap_ratio=0.35)
        """
        self._raise_if_cancelled(task_context, "科研页滚动采集已取消。")
        safe_frame_count = int(frame_count)
        safe_overlap_ratio = float(overlap_ratio)
        safe_scroll_settle_delay_ms = max(0, int(scroll_settle_delay_ms))
        safe_resume_cursor = max(0, int(resume_cursor))
        safe_capture_retry_limit = max(0, int(capture_retry_limit))
        safe_scroll_retry_limit = max(0, int(scroll_retry_limit))
        if safe_frame_count <= 0:
            return self._invalid_session(
                "frame_count 必须大于 0。",
                session_id=session_id,
                page_name=page_name,
                page_state=page_state,
                resume_cursor=safe_resume_cursor,
                status="invalid_frame_count",
            )
        if not 0.0 <= safe_overlap_ratio < 1.0:
            return self._invalid_session(
                "overlap_ratio 必须位于 0.0 到 1.0 之间。",
                session_id=session_id,
                page_name=page_name,
                page_state=page_state,
                resume_cursor=safe_resume_cursor,
                status="invalid_overlap",
            )
        if safe_capture_retry_limit < 0 or safe_scroll_retry_limit < 0:
            return self._invalid_session(
                "重试次数不能为负数。",
                session_id=session_id,
                page_name=page_name,
                page_state=page_state,
                resume_cursor=safe_resume_cursor,
                status="invalid_retry_limit",
            )

        simulator = self._get_simulator_context()
        controller = self._create_controller(simulator)
        safe_session_id = self._normalize_session_id(session_id)
        run_dir = self._capture_root_dir() / f"run_{safe_session_id}"
        frames_dir = run_dir / "frames"
        run_dir.mkdir(parents=True, exist_ok=True)
        frames_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = run_dir / "manifest.json"
        actions_log_path = run_dir / "actions.log"
        device_info_path = run_dir / "device_info.json"
        summary_path = run_dir / "summary.json"

        warnings: list[str] = []
        action_entries: list[Dict[str, Any]] = []
        frames: list[ResearchPageCaptureArtifact] = []
        bottom_reached = False
        duplicate_count = 0
        terminal_failure = False
        cancelled_exc: Optional[BaseException] = None
        next_scroll_index = safe_resume_cursor

        connection_result, display_result, device_payload = self._collect_device_info(
            simulator,
            controller,
            serial=serial,
            task_context=task_context,
        )
        warnings.extend(device_payload.get("warnings", []))
        self._atomic_write_json(device_info_path, device_payload)
        if not device_payload.get("real_capture_enabled", False):
            summary_payload = self._build_summary_payload(
                session_id=safe_session_id,
                page_name=page_name,
                page_state=page_state,
                frames=frames,
                warnings=warnings,
                resume_cursor=safe_resume_cursor,
                bottom_reached=bottom_reached,
                scroll_step_px=self._effective_scroll_step_px(scroll_step_px, safe_overlap_ratio),
                overlap_ratio=safe_overlap_ratio,
                filter_state=filter_state,
                rarity_state=rarity_state,
                sort_state=sort_state,
                device_payload=device_payload,
                cancelled=False,
                duplicate_count=duplicate_count,
                action_entries=action_entries,
            )
            self._write_capture_outputs(
                manifest_path=manifest_path,
                actions_log_path=actions_log_path,
                summary_path=summary_path,
                session_id=safe_session_id,
                page_name=page_name,
                page_state=page_state,
                frames=frames,
                resume_cursor=safe_resume_cursor,
                bottom_reached=bottom_reached,
                filter_state=filter_state,
                rarity_state=rarity_state,
                sort_state=sort_state,
                scroll_step_px=self._effective_scroll_step_px(scroll_step_px, safe_overlap_ratio),
                overlap_ratio=safe_overlap_ratio,
                warnings=warnings,
                action_entries=action_entries,
                device_payload=device_payload,
                summary_payload=summary_payload,
            )
            message = device_payload.get("capture_unavailable_message") or device_payload.get("message") or "科研页采集环境不可用。"
            return ResearchPageScrollSession(
                safe_session_id,
                page_name,
                page_state,
                tuple(frames),
                str(run_dir.resolve()),
                str(frames_dir.resolve()),
                str(manifest_path.resolve()),
                str(actions_log_path.resolve()),
                str(device_info_path.resolve()),
                str(summary_path.resolve()),
                safe_resume_cursor,
                bottom_reached,
                filter_state=filter_state,
                rarity_state=rarity_state,
                sort_state=sort_state,
                scroll_step_px=self._effective_scroll_step_px(scroll_step_px, safe_overlap_ratio),
                overlap_ratio=safe_overlap_ratio,
                warnings=tuple(warnings),
                success=False,
                status=str(device_payload.get("status", "unavailable")),
                message=message,
            )

        if prepare_page:
            self._raise_if_cancelled(task_context, "科研页准备已取消。")
            navigation = self.ensure_research_page_ready(
                scene_probe=scene_probe,
                state_probe=state_probe,
                task_context=task_context,
                serial=serial,
                notify=notify_actions and device_message_mode in {"notification", "auto"},
            )
            warnings.extend(navigation.warnings)
            action_entries.append(
                self._action_entry(
                    action_name="enter_research",
                    result=navigation.status,
                    message=navigation.message,
                    page_name=page_name,
                    page_state=page_state,
                    scroll_index=safe_resume_cursor,
                    scroll_offset_px=safe_resume_cursor * self._effective_scroll_step_px(scroll_step_px, safe_overlap_ratio),
                    details=navigation.to_dict(),
                )
            )
            if not navigation.success:
                warnings.append("科研页准备步骤未完全成功，继续按当前画面采集。")
                self.logger.warning(
                    "科研页准备步骤未完全成功：page=%s；status=%s；message=%s；将继续采集当前画面。",
                    page_name,
                    navigation.status,
                    navigation.message,
                )

        effective_scroll_step_px = self._effective_scroll_step_px(scroll_step_px, safe_overlap_ratio)
        self.logger.info(
            "科研页采集开始：page=%s；state=%s；rarity=%s；resume_cursor=%s；frame_count=%s；scroll_step_px=%s；overlap_ratio=%.2f；ensure_top=%s；until_bottom=%s",
            page_name,
            page_state,
            rarity_state or "all",
            safe_resume_cursor,
            safe_frame_count,
            effective_scroll_step_px,
            safe_overlap_ratio,
            bool(ensure_top),
            bool(capture_until_bottom),
        )
        if ensure_top:
            restore_result = self._restore_design_chart_viewport(
                controller,
                simulator,
                frames_dir,
                page_name=page_name,
                page_state=page_state,
                filter_state=filter_state,
                rarity_state=rarity_state,
                sort_state=sort_state,
                scroll_step_px=effective_scroll_step_px,
                scroll_duration_ms=scroll_duration_ms,
                scroll_retry_limit=safe_scroll_retry_limit,
                target_scroll_index=safe_resume_cursor,
                task_context=task_context,
                serial=serial,
            )
            warnings.extend(restore_result["warnings"])
            action_entries.extend(restore_result["actions"])
            if not restore_result["success"]:
                device_payload["warnings"] = warnings
                summary_payload = self._build_summary_payload(
                    session_id=safe_session_id,
                    page_name=page_name,
                    page_state=page_state,
                    frames=frames,
                    warnings=warnings,
                    resume_cursor=safe_resume_cursor,
                    bottom_reached=bottom_reached,
                    scroll_step_px=effective_scroll_step_px,
                    overlap_ratio=safe_overlap_ratio,
                    filter_state=filter_state,
                    rarity_state=rarity_state,
                    sort_state=sort_state,
                    device_payload=device_payload,
                    cancelled=False,
                    duplicate_count=duplicate_count,
                    action_entries=action_entries,
                    next_resume_cursor=next_scroll_index,
                )
                self._write_capture_outputs(
                    manifest_path=manifest_path,
                    actions_log_path=actions_log_path,
                    summary_path=summary_path,
                    session_id=safe_session_id,
                    page_name=page_name,
                    page_state=page_state,
                    frames=frames,
                    resume_cursor=safe_resume_cursor,
                    bottom_reached=bottom_reached,
                    filter_state=filter_state,
                    rarity_state=rarity_state,
                    sort_state=sort_state,
                    scroll_step_px=effective_scroll_step_px,
                    overlap_ratio=safe_overlap_ratio,
                    warnings=warnings,
                    action_entries=action_entries,
                    device_payload=device_payload,
                    summary_payload=summary_payload,
                )
                return ResearchPageScrollSession(
                    safe_session_id,
                    page_name,
                    page_state,
                    tuple(frames),
                    str(run_dir.resolve()),
                    str(frames_dir.resolve()),
                    str(manifest_path.resolve()),
                    str(actions_log_path.resolve()),
                    str(device_info_path.resolve()),
                    str(summary_path.resolve()),
                    safe_resume_cursor,
                    bottom_reached,
                    filter_state=filter_state,
                    rarity_state=rarity_state,
                    sort_state=sort_state,
                    scroll_step_px=effective_scroll_step_px,
                    overlap_ratio=safe_overlap_ratio,
                    warnings=tuple(warnings),
                    success=False,
                    status=str(restore_result.get("status", "error")),
                    message=str(restore_result.get("message", "科研页顶部回卷失败。")),
                )
            if restore_result["top_reached"]:
                self.logger.info(
                    "科研页顶部对齐完成：page=%s；resume_cursor=%s；seek_steps=%s",
                    page_name,
                    safe_resume_cursor,
                    restore_result.get("seek_steps", 0),
                )
        elif safe_resume_cursor > 0:
            self.logger.info(
                "科研页采集跳过回顶：将直接从当前画面按 resume_cursor=%s 继续。",
                safe_resume_cursor,
            )

        previous_sha1 = ""
        previous_content_signature: Optional[Tuple[Any, ...]] = None
        content_repeat_streak = 0
        bottom_candidate_streak = 0
        duplicate_streak = 0
        hard_frame_cap = max(safe_frame_count, 120) if capture_until_bottom else safe_frame_count
        frame_offset = 0
        while frame_offset < hard_frame_cap:
            self._raise_if_cancelled(task_context, "科研页滚动采集已取消。")
            current_frame_index = frame_offset
            current_scroll_index = safe_resume_cursor + frame_offset
            current_scroll_offset = current_scroll_index * effective_scroll_step_px

            if notify_actions and device_message_mode in {"notification", "auto"}:
                self._notify_device(
                    controller,
                    f"{page_name}：采集中第 {frame_offset + 1}/{safe_frame_count} 帧",
                    serial=serial or simulator["device_serial"] or None,
                    task_context=task_context,
                )

            capture_result = self._capture_frame_with_retry(
                controller,
                simulator,
                frames_dir,
                page_name=page_name,
                page_state=page_state,
                filter_state=filter_state,
                rarity_state=rarity_state,
                sort_state=sort_state,
                session_id=safe_session_id,
                frame_index=current_frame_index,
                scroll_index=current_scroll_index,
                scroll_offset_px=current_scroll_offset,
                overlap_ratio=safe_overlap_ratio,
                scroll_direction="down",
                scroll_pixels=effective_scroll_step_px,
                capture_retry_limit=safe_capture_retry_limit,
                task_context=task_context,
                serial=serial,
            )
            action_entries.extend(capture_result["actions"])
            if capture_result["artifact"] is None:
                warnings.extend(capture_result["warnings"])
                terminal_failure = True
                break

            artifact = capture_result["artifact"]
            current_content_signature = self._design_content_signature(Path(artifact.screenshot_path))
            same_content_viewport = previous_content_signature is not None and current_content_signature == previous_content_signature
            if same_content_viewport:
                content_repeat_streak += 1
            else:
                content_repeat_streak = 0
            bottom_content_confirmed = content_repeat_streak >= DEFAULT_BOTTOM_CONFIRMATIONS and current_scroll_index > safe_resume_cursor
            previous_content_signature = current_content_signature
            if artifact.scrollbar_detected and artifact.scrollbar_state == "bottom":
                bottom_candidate_streak += 1
            else:
                # 只要下一帧回到 middle/top，就清除候选状态，避免一次颜色误检把整轮扫图截断。
                bottom_candidate_streak = 0

            is_same_as_previous = bool(previous_sha1 and artifact.sha1 == previous_sha1)
            if is_same_as_previous:
                duplicate_count += 1
                duplicate_streak += 1
                should_confirm_bottom = (
                    bottom_candidate_streak >= DEFAULT_BOTTOM_CONFIRMATIONS
                    or duplicate_streak >= DEFAULT_BOTTOM_CONFIRMATIONS
                    or bottom_content_confirmed
                )
                artifact = self._with_frame_flags(
                    artifact,
                    bottom_reached=should_confirm_bottom,
                    is_duplicate_frame=True,
                    duplicate_of_scroll_index=current_scroll_index - 1,
                )
                warnings.append(
                    "检测到连续截图相同，先记录为重复帧并继续做一次滚动确认。"
                    if not should_confirm_bottom
                    else "连续截图相同已达到确认阈值，判定列表到底。"
                )
                frames.append(artifact)
                action_entries.append(
                    self._action_entry(
                        action_name="duplicate_frame" if not should_confirm_bottom else "duplicate_bottom_confirmed",
                        result="repeat" if not should_confirm_bottom else "bottom",
                        message="连续帧相同，已记录重复帧。" if not should_confirm_bottom else "连续重复帧确认到底部。",
                        page_name=page_name,
                        page_state=page_state,
                        scroll_index=current_scroll_index,
                        scroll_offset_px=current_scroll_offset,
                        details=artifact.to_dict(),
                    )
                )
                next_scroll_index = current_scroll_index + 1
                if should_confirm_bottom:
                    bottom_reached = True
                if should_confirm_bottom and stop_on_repeat:
                    break
            else:
                duplicate_streak = 0
                previous_sha1 = artifact.sha1
                if bottom_candidate_streak >= DEFAULT_BOTTOM_CONFIRMATIONS or bottom_content_confirmed:
                    bottom_reached = True
                    artifact = self._with_frame_flags(
                        artifact,
                        bottom_reached=True,
                        is_duplicate_frame=False,
                        duplicate_of_scroll_index=None,
                    )
                    warnings.append(
                        "滚动条连续两帧处于 bottom，确认列表到底。"
                        if bottom_candidate_streak >= DEFAULT_BOTTOM_CONFIRMATIONS
                        else "连续两次拖动后设计图布局未变化，确认列表到底。"
                    )
                    action_entries.append(
                        self._action_entry(
                            action_name="scrollbar_bottom_confirmed" if bottom_candidate_streak >= DEFAULT_BOTTOM_CONFIRMATIONS else "content_bottom_confirmed",
                            result="bottom",
                            message="滚动条连续两帧位于底部，已确认到底。" if bottom_candidate_streak >= DEFAULT_BOTTOM_CONFIRMATIONS else "连续两次拖动后设计图布局未变化，已确认到底。",
                            page_name=page_name,
                            page_state=page_state,
                            scroll_index=current_scroll_index,
                            scroll_offset_px=current_scroll_offset,
                            details=artifact.to_dict(),
                        )
                    )
                frames.append(artifact)
                next_scroll_index = current_scroll_index + 1

            if bottom_reached:
                break
            if not capture_until_bottom and frame_offset >= safe_frame_count - 1:
                break

            scroll_result = self._scroll_with_retry(
                controller,
                serial=serial,
                task_context=task_context,
                page_name=page_name,
                page_state=page_state,
                scroll_index=current_scroll_index,
                scroll_offset_px=current_scroll_offset,
                scroll_step_px=effective_scroll_step_px,
                scroll_duration_ms=scroll_duration_ms,
                scroll_retry_limit=safe_scroll_retry_limit,
                scroll_direction="down",
            )
            action_entries.extend(scroll_result["actions"])
            warnings.extend(scroll_result["warnings"])
            if not scroll_result["success"]:
                terminal_failure = True
                break
            # 滑动结束后必须留出停顿，避免在惯性滚动期间截图，导致相邻帧跳过底部卡片。
            self._sleep_with_cancel(safe_scroll_settle_delay_ms / 1000.0, task_context)
            frame_offset += 1

        if capture_until_bottom and not bottom_reached and frame_offset >= hard_frame_cap:
            warnings.append(f"已达到抓取硬上限 {hard_frame_cap} 帧，仍未确认到底部。")

        session_warnings = tuple(warnings)
        summary_payload = self._build_summary_payload(
            session_id=safe_session_id,
            page_name=page_name,
            page_state=page_state,
            frames=frames,
            warnings=warnings,
            resume_cursor=safe_resume_cursor,
            bottom_reached=bottom_reached,
            scroll_step_px=effective_scroll_step_px,
            overlap_ratio=safe_overlap_ratio,
            filter_state=filter_state,
            rarity_state=rarity_state,
            sort_state=sort_state,
            device_payload=device_payload,
            cancelled=cancelled_exc is not None,
            duplicate_count=duplicate_count,
            action_entries=action_entries,
            next_resume_cursor=next_scroll_index,
        )
        self._write_capture_outputs(
            manifest_path=manifest_path,
            actions_log_path=actions_log_path,
            summary_path=summary_path,
            session_id=safe_session_id,
            page_name=page_name,
            page_state=page_state,
            frames=frames,
            resume_cursor=safe_resume_cursor,
            bottom_reached=bottom_reached,
            filter_state=filter_state,
            rarity_state=rarity_state,
            sort_state=sort_state,
            scroll_step_px=effective_scroll_step_px,
            overlap_ratio=safe_overlap_ratio,
            warnings=warnings,
            action_entries=action_entries,
            device_payload=device_payload,
            summary_payload=summary_payload,
        )
        if cancelled_exc is not None:
            raise cancelled_exc

        success = bool(frames) and not terminal_failure
        status = "ready" if success else ("warning" if frames else "error")
        message = "科研页分帧采集完成。" if frames else "科研页分帧采集失败。"
        return ResearchPageScrollSession(
            safe_session_id,
            page_name,
            page_state,
            tuple(frames),
            str(run_dir.resolve()),
            str(frames_dir.resolve()),
            str(manifest_path.resolve()),
            str(actions_log_path.resolve()),
            str(device_info_path.resolve()),
            str(summary_path.resolve()),
            next_scroll_index,
            bottom_reached,
            filter_state=filter_state,
            rarity_state=rarity_state,
            sort_state=sort_state,
            scroll_step_px=effective_scroll_step_px,
            overlap_ratio=safe_overlap_ratio,
            warnings=session_warnings,
            success=success,
            status=status,
            message=message,
        )

    def load_resume_cursor(self, summary_path: str | Path) -> int:
        """
        从 summary.json 读取下一次可续跑的 scroll_index。
        输入：
            summary_path: 由 capture_design_chart_sequence 写出的 summary.json。
        输出：
            下一次采集应传入的 resume_cursor；文件缺失时返回 0。
        使用示例：
            resume_cursor = api.load_resume_cursor(session.summary_path)
        """
        path = Path(summary_path)
        if not path.exists():
            return 0
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, dict):
            return 0
        next_cursor = payload.get("next_resume_cursor", payload.get("resume_cursor", 0))
        try:
            return max(0, int(next_cursor))
        except (TypeError, ValueError):
            return 0

    def capture_current_screen(
        self,
        *,
        session_id: str = "",
        page_name: str = DEFAULT_PAGE_NAME,
        page_state: str = DEFAULT_PAGE_STATE,
        filter_state: str = DEFAULT_FILTER_STATE,
        rarity_state: str = DEFAULT_RARITY_STATE,
        sort_state: str = DEFAULT_SORT_STATE,
        task_context: Optional[TaskExecutionContext] = None,
        serial: Optional[str] = None,
    ) -> ResearchPageCaptureArtifact:
        """
        截取当前科研页 viewport，不做拼接。
        输入：
            session_id: 采集会话 ID；page_state: 当前页面粗粒度状态。
        输出：
            ResearchPageCaptureArtifact，截图路径为绝对路径。
        使用示例：
            artifact = api.capture_current_screen()
        """
        self._raise_if_cancelled(task_context, "科研页截图已取消。")
        simulator = self._get_simulator_context()
        controller = self._create_controller(simulator)
        effective_session_id = self._normalize_session_id(session_id)
        output_dir = self._capture_root_dir() / f"run_{effective_session_id}" / "frames"
        output_dir.mkdir(parents=True, exist_ok=True)
        screenshot = controller.capture_screenshot(
            RecognitionScene.RESEARCH,
            serial=serial or simulator["device_serial"] or None,
            output_dir=output_dir,
            screen_state=page_state,
            scene_hint=page_name,
            task_context=task_context,
        )
        if not screenshot.success or screenshot.artifact is None:
            return self._build_failed_artifact(
                screenshot,
                effective_session_id,
                frame_index=0,
                scroll_index=0,
                scroll_offset_px=0,
                page_name=page_name,
                page_state=page_state,
                filter_state=filter_state,
                rarity_state=rarity_state,
                sort_state=sort_state,
                overlap_ratio=DEFAULT_SCROLL_OVERLAP_RATIO,
            )
        screenshot_path = self._ensure_frame_filename(Path(screenshot.artifact.screenshot_path), 0)
        return self._build_success_artifact(
            screenshot,
            screenshot_path,
            session_id=effective_session_id,
            frame_index=0,
            scroll_index=0,
            scroll_offset_px=0,
            page_name=page_name,
            page_state=page_state,
            filter_state=filter_state,
            rarity_state=rarity_state,
            sort_state=sort_state,
            scroll_direction="down",
            scroll_pixels=0,
            overlap_ratio=DEFAULT_SCROLL_OVERLAP_RATIO,
            bottom_reached=False,
            is_duplicate_frame=False,
            duplicate_of_scroll_index=None,
            needs_retry=False,
            retry_count=screenshot.retry_count,
        )

    def _collect_device_info(
        self,
        simulator: Dict[str, Any],
        controller: AdbController,
        *,
        serial: Optional[str],
        task_context: Optional[TaskExecutionContext],
    ) -> Tuple[object, object, Dict[str, Any]]:
        """收集 ADB、设备和显示环境信息，供 capture/check_connection 复用。"""
        adb_resolution = controller.find_adb()
        if not adb_resolution.available:
            payload = self._base_payload(simulator, controller, adb_path=None, adb_ready=False)
            payload.update(
                {
                    "adb_resolution": adb_resolution.to_dict(),
                    "connection": None,
                    "display_environment": None,
                    "device_info_path": "",
                    "capture_unavailable_message": "未找到可用 ADB，科研页采集不可用。",
                    "real_capture_enabled": False,
                    "warnings": list(adb_resolution.warnings),
                    "status": "unavailable",
                }
            )
            return None, None, payload

        connection = controller.check_connection(serial=serial or simulator["device_serial"] or None, task_context=task_context)
        payload = self._base_payload(
            simulator,
            controller,
            adb_path=connection.adb_path,
            adb_ready=connection.success,
            device_serial=connection.selected_device.serial if connection.selected_device else simulator["device_serial"],
        )
        payload["adb_resolution"] = adb_resolution.to_dict()
        payload["connection"] = connection.to_payload()
        if not connection.success or connection.selected_device is None:
            payload.update(
                {
                    "display_environment": None,
                    "capture_unavailable_message": connection.message,
                    "real_capture_enabled": False,
                    "warnings": list(adb_resolution.warnings) + list(connection.warnings),
                    "status": connection.status,
                }
            )
            return connection, None, payload

        display = controller.check_display_environment(serial=connection.selected_device.serial, task_context=task_context)
        device_info = self._build_device_info_payload(simulator, connection, display, controller)
        payload.update(
            {
                "display_environment": display.to_dict(),
                "capture_unavailable_message": "",
                "real_capture_enabled": device_info["real_capture_enabled"],
                "warnings": list(adb_resolution.warnings) + list(connection.warnings) + list(display.warnings),
                "status": "ready" if device_info["real_capture_enabled"] else "unsupported_display",
            }
        )
        return connection, display, device_info

    def _build_device_info_payload(
        self,
        simulator: Dict[str, Any],
        connection: Any,
        display: Any,
        controller: AdbController,
    ) -> Dict[str, Any]:
        """构造 device_info.json 的内容。"""
        game_config = self.config_loader.get_game_config()
        resolution = list(display.resolution) if getattr(display, "resolution", None) else list(controller.screen_size)
        simulator_type = str(simulator["config"].get("type", "") or "").lower()
        display_warnings = list(getattr(display, "warnings", ()))
        unsupported = False
        capture_message = "科研页采集环境已就绪。"
        if getattr(display, "resolution", None) is None:
            unsupported = True
            capture_message = "无法读取模拟器分辨率，科研页采集要求 1280x720。"
        elif tuple(display.resolution) != BASE_RESOLUTION:
            unsupported = True
            capture_message = f"当前分辨率为 {display.resolution[0]}x{display.resolution[1]}，科研页采集仅支持 1280x720。"
        elif simulator_type == "mumu" and "tablet" not in str(getattr(display, "characteristics", "")).lower():
            unsupported = True
            capture_message = "MuMu 模拟器需要平板模式才能进行科研页采集。"

        return {
            "page_name": DEFAULT_PAGE_NAME,
            "page_state": DEFAULT_PAGE_STATE,
            "simulator_key": simulator["key"],
            "simulator_name": simulator["name"],
            "simulator_type": simulator_type,
            "game_package": game_config.get("package_name", ""),
            "game_activity": game_config.get("activity_name", ""),
            "adb_path": connection.adb_path,
            "adb_source": connection.adb_source,
            "device_serial": connection.selected_device.serial if connection.selected_device else simulator.get("device_serial") or None,
            "device_state": connection.selected_device.state if connection.selected_device else None,
            "connection_status": connection.status,
            "real_capture_enabled": connection.success and not unsupported,
            "recommended_resolution": list(BASE_RESOLUTION),
            "resolution": resolution,
            "density": getattr(display, "density", None),
            "characteristics": getattr(display, "characteristics", ""),
            "display_status": getattr(display, "status", "unavailable"),
            "display_warnings": display_warnings,
            "display_suggestions": list(getattr(display, "suggestions", ())),
            "capture_unavailable_message": capture_message if unsupported else "",
            "status": "ready" if not unsupported else "unsupported_display",
            "warnings": list(connection.warnings) + display_warnings,
        }

    def _capture_frame_with_retry(
        self,
        controller: AdbController,
        simulator: Dict[str, Any],
        frames_dir: Path,
        *,
        page_name: str,
        page_state: str,
        filter_state: str,
        rarity_state: str,
        sort_state: str,
        session_id: str,
        frame_index: int,
        scroll_index: int,
        scroll_offset_px: int,
        overlap_ratio: float,
        scroll_direction: str,
        scroll_pixels: int,
        capture_retry_limit: int,
        task_context: Optional[TaskExecutionContext],
        serial: Optional[str],
    ) -> Dict[str, Any]:
        """采集单帧并在失败时按配置重试一次。"""
        actions: list[Dict[str, Any]] = []
        warnings: list[str] = []
        last_failure: Optional[ResearchPageCaptureArtifact] = None
        for attempt in range(capture_retry_limit + 1):
            self._raise_if_cancelled(task_context, "科研页截图已取消。")
            screenshot = controller.capture_screenshot(
                RecognitionScene.RESEARCH,
                serial=serial or simulator["device_serial"] or None,
                output_dir=frames_dir,
                screen_state=page_state,
                scene_hint=page_name,
                task_context=task_context,
            )
            if screenshot.success and screenshot.artifact is not None:
                raw_path = Path(screenshot.artifact.screenshot_path)
                final_path = self._ensure_frame_filename(raw_path, scroll_index)
                sha1_value = self._sha1_file(final_path)
                scrollbar_info = self._analyze_scrollbar_state(final_path)
                artifact = ResearchPageCaptureArtifact(
                    str(final_path.resolve()),
                    session_id,
                    frame_index,
                    scroll_index,
                    scroll_offset_px,
                    page_name=page_name,
                    page_state=page_state,
                    filter_state=filter_state,
                    rarity_state=rarity_state,
                    sort_state=sort_state,
                    scene=RecognitionScene.RESEARCH.value,
                    action_name="capture_viewport",
                    action_result=screenshot.status,
                    action_message=screenshot.message,
                    sha1=sha1_value,
                    resolution=screenshot.resolution or controller.screen_size,
                    scroll_direction=scroll_direction,
                    scroll_pixels=scroll_pixels,
                    overlap_ratio=overlap_ratio,
                    device_serial=screenshot.artifact.device_serial,
                    adb_path=screenshot.adb_path,
                    adb_source=screenshot.adb_source,
                    timestamp=screenshot.timestamp,
                    bottom_reached=False,
                    is_duplicate_frame=False,
                    duplicate_of_scroll_index=None,
                    scrollbar_detected=bool(scrollbar_info.get("detected", False)),
                    scrollbar_state=str(scrollbar_info.get("state", "unknown")),
                    scrollbar_thumb_top=scrollbar_info.get("thumb_top"),
                    scrollbar_thumb_bottom=scrollbar_info.get("thumb_bottom"),
                    needs_retry=attempt > 0,
                    retry_count=attempt,
                    success=True,
                    status=screenshot.status,
                    message=screenshot.message,
                    warnings=screenshot.warnings,
                )
                actions.append(
                    self._action_entry(
                        action_name="capture_viewport",
                        result=screenshot.status,
                        message=screenshot.message,
                        page_name=page_name,
                        page_state=page_state,
                        scroll_index=scroll_index,
                        scroll_offset_px=scroll_offset_px,
                        details=artifact.to_dict(),
                    )
                )
                if attempt > 0:
                    warnings.append(f"第 {scroll_index} 帧截图在第 {attempt + 1} 次尝试后成功。")
                return {"artifact": artifact, "warnings": warnings, "actions": actions}
            last_failure = self._build_failed_artifact(
                screenshot,
                session_id,
                frame_index=frame_index,
                scroll_index=scroll_index,
                scroll_offset_px=scroll_offset_px,
                page_name=page_name,
                page_state=page_state,
                filter_state=filter_state,
                rarity_state=rarity_state,
                sort_state=sort_state,
                overlap_ratio=overlap_ratio,
            )
            warnings.extend(screenshot.warnings)
            actions.append(
                self._action_entry(
                    action_name="capture_viewport",
                    result=screenshot.status,
                    message=screenshot.message,
                    page_name=page_name,
                    page_state=page_state,
                    scroll_index=scroll_index,
                    scroll_offset_px=scroll_offset_px,
                    details=last_failure.to_dict(),
                )
            )
            if attempt < capture_retry_limit:
                warnings.append(f"第 {scroll_index} 帧截图失败，准备重试第 {attempt + 2} 次。")
                self._sleep_with_cancel(DEFAULT_POST_ACTION_DELAY_MS / 1000.0, task_context)
        if last_failure is None:
            last_failure = self._build_failed_artifact(
                AdbCommandResult(False, "error", "科研页截图失败。"),
                session_id,
                frame_index=frame_index,
                scroll_index=scroll_index,
                scroll_offset_px=scroll_offset_px,
                page_name=page_name,
                page_state=page_state,
                filter_state=filter_state,
                rarity_state=rarity_state,
                sort_state=sort_state,
                overlap_ratio=overlap_ratio,
            )
        return {"artifact": None, "warnings": warnings, "actions": actions, "failure": last_failure}

    def _scroll_with_retry(
        self,
        controller: AdbController,
        *,
        serial: Optional[str],
        task_context: Optional[TaskExecutionContext],
        page_name: str,
        page_state: str,
        scroll_index: int,
        scroll_offset_px: int,
        scroll_step_px: int,
        scroll_duration_ms: int,
        scroll_retry_limit: int,
        scroll_direction: str = "down",
        action_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """执行一次滚动，并在失败时按配置重试一次。"""
        warnings: list[str] = []
        actions: list[Dict[str, Any]] = []
        normalized_direction = "up" if str(scroll_direction).lower() == "up" else "down"
        start_x, start_y, end_x, end_y = SCROLL_ANCHORS[normalized_direction]
        effective_action_name = action_name or f"scroll_{normalized_direction}"
        for attempt in range(scroll_retry_limit + 1):
            self._raise_if_cancelled(task_context, "科研页滚动已取消。")
            if normalized_direction == "down":
                adjusted_end_y = end_y if scroll_step_px <= 0 else max(80, start_y - int(scroll_step_px))
            else:
                adjusted_end_y = end_y if scroll_step_px <= 0 else min(BASE_RESOLUTION[1] - 80, start_y + int(scroll_step_px))
            scroll_result = controller.swipe(
                start_x,
                start_y,
                end_x,
                adjusted_end_y,
                int(scroll_duration_ms),
                serial=serial,
                base_resolution=BASE_RESOLUTION,
                task_context=task_context,
            )
            actions.append(
                self._action_entry(
                    action_name=effective_action_name,
                    result=scroll_result.status,
                    message=scroll_result.message,
                    page_name=page_name,
                    page_state=page_state,
                    scroll_index=scroll_index,
                    scroll_offset_px=scroll_offset_px,
                    details=scroll_result.to_dict(),
                )
            )
            if scroll_result.success:
                if attempt > 0:
                    warnings.append(f"滚动在第 {attempt + 1} 次尝试后成功。")
                return {"success": True, "warnings": warnings, "actions": actions}
            warnings.append(f"滚动失败: {scroll_result.status}")
            if attempt < scroll_retry_limit:
                self._sleep_with_cancel(DEFAULT_POST_ACTION_DELAY_MS / 1000.0, task_context)
        return {"success": False, "warnings": warnings, "actions": actions}

    def _restore_design_chart_viewport(
        self,
        controller: AdbController,
        simulator: Dict[str, Any],
        frames_dir: Path,
        *,
        page_name: str,
        page_state: str,
        filter_state: str,
        rarity_state: str,
        sort_state: str,
        scroll_step_px: int,
        scroll_duration_ms: int,
        scroll_retry_limit: int,
        target_scroll_index: int,
        task_context: Optional[TaskExecutionContext],
        serial: Optional[str],
    ) -> Dict[str, Any]:
        """
        先把科研设计图列表回卷到顶部，再按目标游标前进。
        输入：
            target_scroll_index: 从顶部开始需要前进的逻辑游标。
        输出：
            dict，包含 success/top_reached/seek_steps/actions/warnings。
        """
        warnings: list[str] = []
        actions: list[Dict[str, Any]] = []
        top_reached = False
        if target_scroll_index < 0:
            target_scroll_index = 0

        restore_start = time.time()
        self.logger.info(
            "科研页回顶开始：page=%s；state=%s；rarity=%s；target_scroll_index=%s；scroll_step_px=%s",
            page_name,
            page_state,
            rarity_state or "all",
            int(target_scroll_index),
            int(scroll_step_px),
        )

        probe_dir = frames_dir / "_top_restore_probe"
        probe_dir.mkdir(parents=True, exist_ok=True)
        previous_probe_path: Optional[Path] = None
        previous_probe_signature: Optional[Tuple[Any, ...]] = None
        top_repeat_streak = 0
        restore_limit = max(24, int(target_scroll_index) + 24)
        restore_pause_seconds = max(DEFAULT_POST_ACTION_DELAY_MS, 800) / 1000.0
        for restore_step in range(restore_limit):
            self._raise_if_cancelled(task_context, "科研页回顶已取消。")
            probe_result = controller.capture_screenshot(
                RecognitionScene.RESEARCH,
                serial=serial or simulator["device_serial"] or None,
                output_dir=probe_dir,
                screen_state=page_state,
                scene_hint=page_name,
                task_context=task_context,
            )
            if not probe_result.success or probe_result.artifact is None:
                warnings.extend(probe_result.warnings)
                actions.append(
                    self._action_entry(
                        action_name="top_probe_capture",
                        result=probe_result.status,
                        message=probe_result.message,
                        page_name=page_name,
                        page_state=page_state,
                        scroll_index=0,
                        scroll_offset_px=0,
                        details=probe_result.to_dict(),
                    )
                )
                if previous_probe_path is not None:
                    self._safe_unlink(previous_probe_path)
                self._safe_cleanup_dir(probe_dir)
                return {
                    "success": False,
                    "top_reached": False,
                    "seek_steps": 0,
                    "actions": actions,
                    "warnings": warnings,
                    "status": probe_result.status,
                    "message": probe_result.message,
                }

            probe_path = Path(probe_result.artifact.screenshot_path)
            probe_signature = self._design_content_signature(probe_path)
            if previous_probe_signature is not None and probe_signature == previous_probe_signature:
                top_repeat_streak += 1
            else:
                top_repeat_streak = 0
            # top_repeat_streak 记录的是“第二帧起的重复次数”，
            # 因此配置为连续两帧确认时，第二帧对应 streak=1。
            if top_repeat_streak >= max(1, DEFAULT_BOTTOM_CONFIRMATIONS - 1):
                top_reached = True
                self._safe_unlink(probe_path)
                if previous_probe_path is not None:
                    self._safe_unlink(previous_probe_path)
                break

            if previous_probe_path is not None:
                self._safe_unlink(previous_probe_path)
            previous_probe_path = probe_path
            previous_probe_signature = probe_signature

            scroll_result = self._scroll_with_retry(
                controller,
                serial=serial,
                task_context=task_context,
                page_name=page_name,
                page_state=page_state,
                scroll_index=restore_step,
                scroll_offset_px=restore_step * scroll_step_px,
                scroll_step_px=scroll_step_px,
                scroll_duration_ms=scroll_duration_ms,
                scroll_retry_limit=scroll_retry_limit,
                scroll_direction="up",
                action_name="seek_scroll_up",
            )
            actions.extend(scroll_result["actions"])
            warnings.extend(scroll_result["warnings"])
            if not scroll_result["success"]:
                if previous_probe_path is not None:
                    self._safe_unlink(previous_probe_path)
                self._safe_cleanup_dir(probe_dir)
                return {
                    "success": False,
                    "top_reached": False,
                    "seek_steps": restore_step,
                    "actions": actions,
                    "warnings": warnings,
                    "status": "error",
                    "message": "科研页顶部回卷失败。",
                }
            self._sleep_with_cancel(restore_pause_seconds, task_context)

        if previous_probe_path is not None:
            self._safe_unlink(previous_probe_path)
        self._safe_cleanup_dir(probe_dir)

        if not top_reached:
            warnings.append("顶部回卷达到上限，未能通过连续相同布局确认回到列表顶部。")
            elapsed_ms = int((time.time() - restore_start) * 1000)
            self.logger.warning(
                "科研页回顶未完成：page=%s；target_scroll_index=%s；耗时=%s ms",
                page_name,
                int(target_scroll_index),
                elapsed_ms,
            )
            return {
                "success": False,
                "top_reached": False,
                "seek_steps": 0,
                "actions": actions,
                "warnings": warnings,
                "status": "timeout",
                "message": "科研页顶部回卷未完成。",
            }

        warnings.append("科研页已回到顶部，开始按逻辑游标继续采集。")

        seek_steps = 0
        for seek_step in range(int(target_scroll_index)):
            self._raise_if_cancelled(task_context, "科研页回顶后定位已取消。")
            seek_result = self._scroll_with_retry(
                controller,
                serial=serial,
                task_context=task_context,
                page_name=page_name,
                page_state=page_state,
                scroll_index=seek_step,
                scroll_offset_px=seek_steps * scroll_step_px,
                scroll_step_px=scroll_step_px,
                scroll_duration_ms=scroll_duration_ms,
                scroll_retry_limit=scroll_retry_limit,
                scroll_direction="down",
                action_name="seek_scroll_down",
            )
            actions.extend(seek_result["actions"])
            warnings.extend(seek_result["warnings"])
            if not seek_result["success"]:
                return {
                    "success": False,
                    "top_reached": top_reached,
                    "seek_steps": seek_steps,
                    "actions": actions,
                    "warnings": warnings,
                    "status": "error",
                    "message": "科研页逻辑游标定位失败。",
                }
            seek_steps += 1
            self._sleep_with_cancel(restore_pause_seconds, task_context)

        elapsed_ms = int((time.time() - restore_start) * 1000)
        self.logger.info(
            "科研页回顶完成：top_reached=%s；seek_steps=%s；耗时=%s ms",
            top_reached,
            seek_steps,
            elapsed_ms,
        )
        return {
            "success": True,
            "top_reached": top_reached,
            "seek_steps": seek_steps,
            "actions": actions,
            "warnings": warnings,
            "status": "ready",
            "message": "科研页顶部回卷完成。",
        }

    def _write_capture_outputs(
        self,
        *,
        manifest_path: Path,
        actions_log_path: Path,
        summary_path: Path,
        session_id: str,
        page_name: str,
        page_state: str,
        frames: Sequence[ResearchPageCaptureArtifact],
        resume_cursor: int,
        bottom_reached: bool,
        filter_state: str,
        rarity_state: str,
        sort_state: str,
        scroll_step_px: int,
        overlap_ratio: float,
        warnings: Sequence[str],
        action_entries: Sequence[Dict[str, Any]],
        device_payload: Dict[str, Any],
        summary_payload: Dict[str, Any],
    ) -> None:
        """一次性写出 manifest、actions.log、summary.json，保持原子替换。"""
        manifest_payload = {
            "session_id": session_id,
            "page_name": page_name,
            "page_state": page_state,
            "filter_state": filter_state,
            "rarity_state": rarity_state,
            "sort_state": sort_state,
            "resume_cursor": int(resume_cursor),
            "next_resume_cursor": int(summary_payload.get("next_resume_cursor", resume_cursor + len(frames))),
            "bottom_reached": bool(bottom_reached),
            "scroll_step_px": int(scroll_step_px),
            "overlap_ratio": float(overlap_ratio),
            "frames": [frame.to_dict() for frame in frames],
            "warnings": list(warnings),
            "device_info_path": device_payload.get("device_info_path", str(summary_path.parent / "device_info.json")),
            "actions_log_path": str(actions_log_path.resolve()),
            "summary_path": str(summary_path.resolve()),
        }
        self._atomic_write_json(manifest_path, manifest_payload)
        self._atomic_write_text_lines(actions_log_path, action_entries)
        self._atomic_write_json(summary_path, summary_payload)

    def _build_summary_payload(
        self,
        *,
        session_id: str,
        page_name: str,
        page_state: str,
        frames: Sequence[ResearchPageCaptureArtifact],
        warnings: Sequence[str],
        resume_cursor: int,
        bottom_reached: bool,
        scroll_step_px: int,
        overlap_ratio: float,
        filter_state: str,
        rarity_state: str,
        sort_state: str,
        device_payload: Dict[str, Any],
        cancelled: bool,
        duplicate_count: int,
        action_entries: Sequence[Dict[str, Any]],
        next_resume_cursor: Optional[int] = None,
    ) -> Dict[str, Any]:
        """汇总本次采集统计信息。"""
        next_cursor = int(next_resume_cursor if next_resume_cursor is not None else resume_cursor + len(frames))
        return {
            "session_id": session_id,
            "page_name": page_name,
            "page_state": page_state,
            "frame_count": len(frames),
            "duplicate_frame_count": int(duplicate_count),
            "bottom_reached": bool(bottom_reached),
            "cancelled": bool(cancelled),
            "resume_cursor": int(resume_cursor),
            "next_resume_cursor": next_cursor,
            "scroll_step_px": int(scroll_step_px),
            "overlap_ratio": float(overlap_ratio),
            "filter_state": filter_state,
            "rarity_state": rarity_state,
            "sort_state": sort_state,
            "warnings": list(warnings),
            "action_count": len(action_entries),
            "device_serial": device_payload.get("device_serial"),
            "adb_path": device_payload.get("adb_path"),
            "display_status": device_payload.get("display_status"),
            "resolution": device_payload.get("resolution"),
            "real_capture_enabled": device_payload.get("real_capture_enabled", False),
            "files": {
                "manifest": "manifest.json",
                "actions_log": "actions.log",
                "device_info": "device_info.json",
                "summary": "summary.json",
            },
        }

    def _build_failed_artifact(
        self,
        screenshot: AdbCommandResult | object,
        session_id: str,
        *,
        frame_index: int,
        scroll_index: int,
        scroll_offset_px: int,
        page_name: str,
        page_state: str,
        filter_state: str,
        rarity_state: str,
        sort_state: str,
        overlap_ratio: float,
    ) -> ResearchPageCaptureArtifact:
        """把失败的截图命令包装成可追踪的 artifact。"""
        message = getattr(screenshot, "message", "科研页截图失败。")
        status = getattr(screenshot, "status", "error")
        warnings = tuple(getattr(screenshot, "warnings", ()))
        adb_path = getattr(screenshot, "adb_path", None)
        adb_source = getattr(screenshot, "adb_source", "missing")
        resolution = getattr(screenshot, "resolution", None) or BASE_RESOLUTION
        timestamp = getattr(screenshot, "timestamp", datetime.now().isoformat(timespec="seconds"))
        return ResearchPageCaptureArtifact(
            "",
            session_id,
            frame_index,
            scroll_index,
            scroll_offset_px,
            page_name=page_name,
            page_state=page_state,
            filter_state=filter_state,
            rarity_state=rarity_state,
            sort_state=sort_state,
            scene=RecognitionScene.RESEARCH.value,
            action_name="capture_viewport",
            action_result=status,
            action_message=message,
            sha1="",
            resolution=resolution,
            scroll_direction="down",
            scroll_pixels=0,
            overlap_ratio=overlap_ratio,
            adb_path=adb_path,
            adb_source=adb_source,
            timestamp=timestamp,
            bottom_reached=False,
            is_duplicate_frame=False,
            duplicate_of_scroll_index=None,
            needs_retry=True,
            retry_count=getattr(screenshot, "retry_count", 0),
            success=False,
            status=status,
            message=message,
            warnings=warnings,
        )

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        """尽量删除临时探针截图，避免回顶过程留下无用文件。"""
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def _safe_cleanup_dir(self, path: Path) -> None:
        """在探针文件清空后，顺手移除空目录。"""
        try:
            path.rmdir()
        except OSError:
            pass

    def _build_success_artifact(
        self,
        screenshot: object,
        screenshot_path: Path,
        *,
        session_id: str,
        frame_index: int,
        scroll_index: int,
        scroll_offset_px: int,
        page_name: str,
        page_state: str,
        filter_state: str,
        rarity_state: str,
        sort_state: str,
        scroll_direction: str,
        scroll_pixels: int,
        overlap_ratio: float,
        bottom_reached: bool,
        is_duplicate_frame: bool,
        duplicate_of_scroll_index: Optional[int],
        needs_retry: bool,
        retry_count: int,
    ) -> ResearchPageCaptureArtifact:
        """把成功截图包装成标准 artifact。"""
        artifact = getattr(screenshot, "artifact")
        scrollbar_info = self._analyze_scrollbar_state(screenshot_path)
        return ResearchPageCaptureArtifact(
            str(Path(screenshot_path).resolve()),
            session_id,
            frame_index,
            scroll_index,
            scroll_offset_px,
            page_name=page_name,
            page_state=page_state,
            filter_state=filter_state,
            rarity_state=rarity_state,
            sort_state=sort_state,
            scene=RecognitionScene.RESEARCH.value,
            action_name="capture_viewport",
            action_result=getattr(screenshot, "status", "ready"),
            action_message=getattr(screenshot, "message", "科研页截图完成。"),
            sha1=self._sha1_file(screenshot_path),
            resolution=getattr(screenshot, "resolution", None) or BASE_RESOLUTION,
            scroll_direction=scroll_direction,
            scroll_pixels=scroll_pixels,
            overlap_ratio=overlap_ratio,
            device_serial=getattr(artifact, "device_serial", ""),
            adb_path=getattr(screenshot, "adb_path", None),
            adb_source=getattr(screenshot, "adb_source", "missing"),
            timestamp=getattr(screenshot, "timestamp", datetime.now().isoformat(timespec="seconds")),
            bottom_reached=bottom_reached,
            is_duplicate_frame=is_duplicate_frame,
            duplicate_of_scroll_index=duplicate_of_scroll_index,
            scrollbar_detected=bool(scrollbar_info.get("detected", False)),
            scrollbar_state=str(scrollbar_info.get("state", "unknown")),
            scrollbar_thumb_top=scrollbar_info.get("thumb_top"),
            scrollbar_thumb_bottom=scrollbar_info.get("thumb_bottom"),
            needs_retry=needs_retry,
            retry_count=retry_count,
            success=True,
            status=getattr(screenshot, "status", "ready"),
            message=getattr(screenshot, "message", "科研页截图完成。"),
            warnings=tuple(getattr(screenshot, "warnings", ())),
        )

    def _with_frame_flags(
        self,
        artifact: ResearchPageCaptureArtifact,
        *,
        bottom_reached: bool,
        is_duplicate_frame: bool,
        duplicate_of_scroll_index: Optional[int],
    ) -> ResearchPageCaptureArtifact:
        """在不改动截图证据的前提下补充底部/重复帧标记。"""
        return ResearchPageCaptureArtifact(
            artifact.screenshot_path,
            artifact.session_id,
            artifact.frame_index,
            artifact.scroll_index,
            artifact.scroll_offset_px,
            page_name=artifact.page_name,
            page_state=artifact.page_state,
            filter_state=artifact.filter_state,
            rarity_state=artifact.rarity_state,
            sort_state=artifact.sort_state,
            scene=artifact.scene,
            action_name=artifact.action_name,
            action_result=artifact.action_result,
            action_message=artifact.action_message,
            sha1=artifact.sha1,
            resolution=artifact.resolution,
            scroll_direction=artifact.scroll_direction,
            scroll_pixels=artifact.scroll_pixels,
            overlap_ratio=artifact.overlap_ratio,
            device_serial=artifact.device_serial,
            adb_path=artifact.adb_path,
            adb_source=artifact.adb_source,
            timestamp=artifact.timestamp,
            bottom_reached=bottom_reached,
            is_duplicate_frame=is_duplicate_frame,
            duplicate_of_scroll_index=duplicate_of_scroll_index,
            scrollbar_detected=artifact.scrollbar_detected,
            scrollbar_state=artifact.scrollbar_state,
            scrollbar_thumb_top=artifact.scrollbar_thumb_top,
            scrollbar_thumb_bottom=artifact.scrollbar_thumb_bottom,
            needs_retry=artifact.needs_retry,
            retry_count=artifact.retry_count,
            success=artifact.success,
            status=artifact.status,
            message=artifact.message,
            warnings=artifact.warnings,
        )

    def _notify_device(
        self,
        controller: AdbController,
        message: str,
        *,
        serial: Optional[str],
        task_context: Optional[TaskExecutionContext],
    ) -> None:
        """在模拟器里显示短提示，便于人工观察当前步骤。"""
        controller.show_notification(
            message,
            title=DEFAULT_ACTION_NOTIFICATION_TITLE,
            tag="azurlane_research_capture",
            expand=False,
            serial=serial,
            task_context=task_context,
        )

    def _action_entry(
        self,
        *,
        action_name: str,
        result: str,
        message: str,
        page_name: str,
        page_state: str,
        scroll_index: int,
        scroll_offset_px: int,
        details: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构造 actions.log 中的一条 JSON 记录。"""
        return {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "action_name": action_name,
            "action_result": result,
            "message": message,
            "page_name": page_name,
            "page_state": page_state,
            "scroll_index": int(scroll_index),
            "scroll_offset_px": int(scroll_offset_px),
            "details": details,
        }

    def _base_payload(
        self,
        simulator: Dict[str, Any],
        controller: AdbController,
        *,
        adb_path: Optional[str] = None,
        adb_ready: bool = False,
        device_serial: Optional[str] = None,
    ) -> Dict[str, Any]:
        """构造研究页结果共享的 payload。"""
        return {
            "page_name": DEFAULT_PAGE_NAME,
            "page_state": DEFAULT_PAGE_STATE,
            "screenshot_path": None,
            "device_serial": device_serial or simulator.get("device_serial") or simulator.get("default_device_serial") or None,
            "resolution": list(controller.screen_size),
            "adb_path": adb_path,
            "adb_ready": adb_ready,
            "real_capture_enabled": bool(adb_path and adb_ready),
            "current_simulator_key": simulator.get("key", ""),
            "simulator_name": simulator.get("name", ""),
            "warnings": [],
        }

    def _get_simulator_context(self) -> Dict[str, Any]:
        """读取当前模拟器上下文。"""
        main_config = self.config_loader.get_main_config()
        simulator_key = str(main_config.get("current_simulator", "mumu") or "mumu")
        simulator_config = self.config_loader.get_simulator_config(simulator_key)
        adb_config = simulator_config.get("adb", {}) if isinstance(simulator_config, dict) else {}
        port = adb_config.get("port", 0)
        explicit_serial = adb_config.get("serial") or adb_config.get("device_serial")
        return {
            "key": simulator_key,
            "name": simulator_config.get("name", simulator_key) if isinstance(simulator_config, dict) else simulator_key,
            "adb": adb_config,
            "config": simulator_config if isinstance(simulator_config, dict) else {},
            "device_serial": str(explicit_serial) if explicit_serial else "",
            "default_device_serial": f"127.0.0.1:{port}" if port else "",
        }

    def _create_controller(self, simulator_context: Dict[str, Any]) -> AdbController:
        """按当前模拟器配置创建底层 ADB 控制器。"""
        return self._controller_factory(simulator_context.get("config", {}))

    def _capture_root_dir(self) -> Path:
        """返回科研页采集运行根目录。"""
        path = PathManager.get_work_dir() / "automation" / "adb_capture_runs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _normalize_session_id(session_id: str) -> str:
        """生成或清洗 session_id，避免路径中出现不安全字符。"""
        raw = str(session_id or "").strip()
        if not raw:
            raw = f"research_capture_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in raw)

    @staticmethod
    def _sha1_file(path: Path) -> str:
        """计算文件 sha1，供去重和底部判断使用。"""
        digest = hashlib.sha1()
        with open(path, "rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    @staticmethod
    def _design_content_signature(path: Path) -> Tuple[Any, ...]:
        """用设计图卡片布局生成稳定签名，避免背景动画干扰底部判定。"""
        try:
            detector = get_design_fragment_detector()
            image = detector.load_image(path)
            result = detector.detect(image)
        except Exception:
            return ("raw", ResearchPageAdbApi._sha1_file(path))

        if not result.success:
            if result.status == "empty":
                return ("empty",)
            return ("raw", ResearchPageAdbApi._sha1_file(path))
        return tuple(
            (
                int(candidate.index),
                int(candidate.row_index),
                int(candidate.column_index),
                str(candidate.visibility),
                int(candidate.bbox[0]),
                int(candidate.bbox[1]),
                int(candidate.bbox[2]),
                int(candidate.bbox[3]),
            )
            for candidate in result.candidates
        )

    @staticmethod
    def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
        """使用临时文件 + os.replace 写 JSON，避免半截文件。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    @staticmethod
    def _atomic_write_text_lines(path: Path, lines: Sequence[Dict[str, Any]]) -> None:
        """把动作日志按 JSONL 写入，便于逐行检查。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as file:
                for item in lines:
                    file.write(json.dumps(item, ensure_ascii=False))
                    file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    @staticmethod
    def _ensure_frame_filename(path: Path, scroll_index: int) -> Path:
        """把截图重命名成更便于 OCR 人工核查的 frame 序号文件。"""
        target = path.with_name(f"frame_{scroll_index:04d}.png")
        if path.resolve() != target.resolve():
            os.replace(path, target)
        return target

    @staticmethod
    def _sleep_with_cancel(delay_seconds: float, task_context: Optional[TaskExecutionContext]) -> None:
        """短等待前后都检查取消，避免后续步骤继续执行。"""
        if task_context is not None:
            task_context.raise_if_cancelled("科研页任务已取消。")
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        if task_context is not None:
            task_context.raise_if_cancelled("科研页任务已取消。")

    @staticmethod
    def _raise_if_cancelled(task_context: Optional[TaskExecutionContext], message: str) -> None:
        """安全点取消检查。"""
        if task_context is not None:
            task_context.raise_if_cancelled(message)

    @staticmethod
    def _effective_scroll_step_px(scroll_step_px: int, overlap_ratio: float) -> int:
        """把显式步长和重叠比例统一成实际滚动像素。"""
        if int(scroll_step_px) > 0:
            return int(scroll_step_px)
        calculated = max(1, int(round(BASE_RESOLUTION[1] * (1.0 - float(overlap_ratio)))))
        return min(calculated, DEFAULT_AUTO_SCROLL_STEP_CAP_PX)

    @staticmethod
    def _analyze_scrollbar_state(image_path: Path) -> Dict[str, Any]:
        """
        分析设计图页右侧滚动条位置。
        输入：
            image_path: 已保存的 viewport 截图。
        输出：
            包含 detected/state/thumb_top/thumb_bottom 的字典。
        """
        try:
            with Image.open(image_path) as image:
                rgb = image.convert("RGB")
                width, height = rgb.size
                x_start = max(0, width - 24)
                x_end = max(x_start + 1, width - 8)
                y_start = 20
                y_end = max(y_start + 1, height - 90)
                pixels = rgb.load()
                matched_rows: list[int] = []
                for y_pos in range(y_start, y_end):
                    hit_count = 0
                    for x_pos in range(x_start, x_end):
                        red, green, blue = pixels[x_pos, y_pos]
                        if red >= 180 and green >= 120 and blue <= 160 and (red + green) >= 360:
                            hit_count += 1
                    if hit_count >= 2:
                        matched_rows.append(y_pos)
                if not matched_rows:
                    return {"detected": False, "state": "unknown", "thumb_top": None, "thumb_bottom": None}

                best_start = matched_rows[0]
                best_end = matched_rows[0]
                current_start = matched_rows[0]
                current_end = matched_rows[0]
                for row_value in matched_rows[1:]:
                    if row_value == current_end + 1:
                        current_end = row_value
                    else:
                        if (current_end - current_start) > (best_end - best_start):
                            best_start, best_end = current_start, current_end
                        current_start = row_value
                        current_end = row_value
                if (current_end - current_start) > (best_end - best_start):
                    best_start, best_end = current_start, current_end

                thumb_height = max(1, best_end - best_start + 1)
                top_margin = max(8, int(round(thumb_height * 0.15)))
                bottom_margin = max(12, int(round(thumb_height * 0.20)))
                track_height = max(1, y_end - y_start)
                if thumb_height >= int(round(track_height * 0.75)):
                    return {
                        "detected": True,
                        "state": "single_page",
                        "thumb_top": int(best_start),
                        "thumb_bottom": int(best_end),
                        "thumb_height": int(thumb_height),
                    }
                at_top = best_start <= (y_start + 48 + top_margin)
                at_bottom = best_end >= (y_end - bottom_margin)
                state = "middle"
                if at_top:
                    state = "top"
                elif at_bottom:
                    state = "bottom"
                return {
                    "detected": True,
                    "state": state,
                    "thumb_top": int(best_start),
                    "thumb_bottom": int(best_end),
                    "thumb_height": int(thumb_height),
                }
        except (OSError, ValueError):
            return {"detected": False, "state": "unknown", "thumb_top": None, "thumb_bottom": None}

    def _resolution_detail(self, display_check: Any) -> str:
        """把显示环境检查结果转换成易读详情。"""
        resolution = getattr(display_check, "resolution", None)
        characteristics = getattr(display_check, "characteristics", "")
        density = getattr(display_check, "density", None)
        if resolution:
            resolution_text = f"{resolution[0]}x{resolution[1]}"
        else:
            resolution_text = "未知"
        return f"分辨率={resolution_text}；密度={density or '未知'}；特性={characteristics or '未知'}"

    @staticmethod
    def _navigation_result_payload(navigation: object) -> Dict[str, Any]:
        """兼容 controller.NavigationResult 与测试 fake 对象的 payload 提取。"""
        for method_name in ("to_payload", "to_dict"):
            method = getattr(navigation, method_name, None)
            if callable(method):
                payload = method()
                if isinstance(payload, dict):
                    return payload
        return {
            "sequence_name": getattr(navigation, "sequence_name", ""),
            "target_scene": getattr(getattr(navigation, "target_scene", None), "value", None),
            "target_screen_state": getattr(navigation, "target_screen_state", ""),
            "screen_state": getattr(navigation, "screen_state", ""),
            "scene_hint": getattr(navigation, "scene_hint", ""),
            "screenshot_path": getattr(navigation, "screenshot_path", None),
            "resolution": list(getattr(navigation, "resolution", ())) or None,
            "timestamp": getattr(navigation, "timestamp", ""),
            "confidence": getattr(navigation, "confidence", None),
            "attempts": getattr(navigation, "attempts", 0),
            "warnings": list(getattr(navigation, "warnings", ())),
        }

    def _invalid_session(
        self,
        message: str,
        *,
        session_id: str,
        page_name: str,
        page_state: str,
        resume_cursor: int,
        status: str,
    ) -> ResearchPageScrollSession:
        """把非法参数转换成结构化会话结果。"""
        safe_session_id = self._normalize_session_id(session_id)
        run_dir = self._capture_root_dir() / f"run_{safe_session_id}"
        frames_dir = run_dir / "frames"
        run_dir.mkdir(parents=True, exist_ok=True)
        frames_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = run_dir / "manifest.json"
        actions_log_path = run_dir / "actions.log"
        device_info_path = run_dir / "device_info.json"
        summary_path = run_dir / "summary.json"
        summary_payload = {
            "session_id": safe_session_id,
            "page_name": page_name,
            "page_state": page_state,
            "frame_count": 0,
            "duplicate_frame_count": 0,
            "bottom_reached": False,
            "cancelled": False,
            "resume_cursor": int(resume_cursor),
            "next_resume_cursor": int(resume_cursor),
            "scroll_step_px": 0,
            "overlap_ratio": DEFAULT_SCROLL_OVERLAP_RATIO,
            "warnings": [message],
            "action_count": 0,
            "device_serial": None,
            "adb_path": None,
            "display_status": "invalid",
            "resolution": list(BASE_RESOLUTION),
            "real_capture_enabled": False,
            "files": {
                "manifest": "manifest.json",
                "actions_log": "actions.log",
                "device_info": "device_info.json",
                "summary": "summary.json",
            },
        }
        self._atomic_write_json(device_info_path, {"status": status, "message": message, "real_capture_enabled": False})
        self._atomic_write_json(manifest_path, {
            "session_id": safe_session_id,
            "page_name": page_name,
            "page_state": page_state,
            "resume_cursor": int(resume_cursor),
            "next_resume_cursor": int(resume_cursor),
            "bottom_reached": False,
            "frames": [],
            "warnings": [message],
            "actions_log_path": str(actions_log_path.resolve()),
            "device_info_path": str(device_info_path.resolve()),
            "summary_path": str(summary_path.resolve()),
        })
        self._atomic_write_text_lines(actions_log_path, [])
        self._atomic_write_json(summary_path, summary_payload)
        return ResearchPageScrollSession(
            safe_session_id,
            page_name,
            page_state,
            (),
            str(run_dir.resolve()),
            str(frames_dir.resolve()),
            str(manifest_path.resolve()),
            str(actions_log_path.resolve()),
            str(device_info_path.resolve()),
            str(summary_path.resolve()),
            int(resume_cursor),
            False,
            warnings=(message,),
            success=False,
            status=status,
            message=message,
        )

    @staticmethod
    def _optimistic_scene_probe(scene: object = None) -> bool:
        """未注入识别层时的乐观探针：只让配置序列执行完成。"""
        return True

    @staticmethod
    def _optimistic_state_probe(candidate: object = None) -> Dict[str, object]:
        """未注入识别层时返回稳定 screen_state，便于底层状态化序列完成。"""
        return {
            "screen_state": DEFAULT_PAGE_STATE,
            "scene_hint": DEFAULT_PAGE_NAME,
            "confidence": 0.0,
        }


# ============================================================
# 🌐 第三部分：全局访问函数
# ============================================================

_research_page_adb_api: Optional[ResearchPageAdbApi] = None


def get_research_page_adb_api() -> ResearchPageAdbApi:
    """
    获取全局研究页 ADB API。
    输入：
        无。
    输出：
        ResearchPageAdbApi 单例。
    使用示例：
        api = get_research_page_adb_api()
    """
    global _research_page_adb_api
    if _research_page_adb_api is None:
        _research_page_adb_api = ResearchPageAdbApi()
    return _research_page_adb_api
