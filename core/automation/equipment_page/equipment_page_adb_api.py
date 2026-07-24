#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        🎮 装备页 ADB API (equipment_page_adb_api.py)          ║
║                                                              ║
║  【一句话解释】为 OCR 装备识别阶段提供装备仓库页自动化动作。  ║
║  【类比理解】它像只会操作装备页的助手，负责翻页和留证据。     ║
║  【数据流说明】GUI/OCR → 装备页动作 → 截图/manifest 元数据。   ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import csv
import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Sequence, Tuple

from core.automation.adb_controller import AdbCommandResult, AdbController
from core.contracts import RecognitionScene, TaskExecutionContext
from core.utils.config_loader import get_config_loader
from core.utils.logger import get_logger
from core.utils.path_manager import PathManager

from .equipment_page_constants import (
    BASE_RESOLUTION,
    DEFAULT_POST_ACTION_DELAY_MS,
    DEFAULT_SCROLL_DISTANCE_PX,
    DEFAULT_SCROLL_DURATION_MS,
    DEFAULT_SCROLL_OVERLAP_HINT,
    DEFAULT_SEARCH_CLEAR_DELETE_COUNT,
    EQUIPMENT_PAGE_POINTS,
    EQUIPMENT_TYPE_ALIASES,
    EQUIPMENT_TYPE_POINTS,
    RARITY_FILTER_POINTS,
    RARITY_FILTERS,
    SCENE_EQUIPMENT_LIST,
    SCROLL_ANCHORS,
)
from .equipment_page_models import (
    EquipmentPageAdbResult,
    EquipmentPageCaptureArtifact,
    EquipmentPageScrollFrame,
    EquipmentPageScrollSession,
)


# ============================================================
# 🏗️ 第二部分：装备页 ADB API
# ============================================================

class EquipmentPageAdbApi:
    """
    装备页专用 ADB 自动化门面。
    输入：
        通过 config/config.json 与 config/simulators/*.json 读取当前模拟器。
    输出：
        结构化结果、截图 artifact 和滚动采集 manifest。
    使用示例：
        api = get_equipment_page_adb_api()
        session = api.capture_scroll_sequence(frame_count=5)
    """

    _instance: Optional["EquipmentPageAdbApi"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "EquipmentPageAdbApi":
        """单例模式：装备页采集与 GUI 后台任务共享同一套配置读取逻辑。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化装备页 API，重复初始化时直接返回。"""
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        self.config_loader = get_config_loader()
        self._controller_factory: Callable[[Dict[str, Any]], AdbController] = AdbController
        self._scene_probe: Optional[Callable[..., object]] = None
        self._state_probe: Optional[Callable[..., object]] = None
        self._last_rarity_filter = "all"
        self._last_equipment_type = "全部"
        self._last_equipped_state = "unknown"
        self._last_search_text = ""
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
            scene_probe: 判断是否到装备列表页；state_probe: 返回 screen_state/equipped_state 等细分状态。
        输出：
            无；后续 ensure/capture 流程会复用这些探针。
        使用示例：
            api.configure_probes(state_probe=lambda shot: {"screen_state": "equipment_list"})
        """
        self._scene_probe = scene_probe
        self._state_probe = state_probe

    def check_connection(self, task_context: Optional[TaskExecutionContext] = None) -> EquipmentPageAdbResult:
        """
        检查装备页采集所需的 ADB、设备、分辨率和截图能力。
        输入：
            task_context: 可选任务上下文，用于响应 GUI 取消。
        输出：
            EquipmentPageAdbResult，payload 至少包含 adb_path/adb_ready/device_serial/resolution。
        使用示例：
            result = api.check_connection()
        """
        self._raise_if_cancelled(task_context, "装备页 ADB 连接检查已取消。")
        simulator = self._get_simulator_context()
        controller = self._create_controller(simulator)
        adb_resolution = controller.find_adb()
        if not adb_resolution.available:
            payload = self._base_payload(simulator, controller, adb_path=adb_resolution.adb_path, adb_ready=False)
            payload.update(adb_resolution.to_dict())
            return EquipmentPageAdbResult(
                False,
                "unavailable",
                "未找到可用 ADB，装备页采集不可用。",
                "请检查模拟器 ADB 路径或开启模拟器 ADB/Android 调试开关。",
                payload,
                tuple(adb_resolution.warnings),
            )

        connection = controller.check_connection(serial=simulator["device_serial"] or None, task_context=task_context)
        screen_info = controller.get_screen_info(
            serial=connection.selected_device.serial if connection.selected_device else simulator["device_serial"] or None,
            task_context=task_context,
        ) if connection.success else {"resolution": None, "density": None}
        payload = self._base_payload(
            simulator,
            controller,
            adb_path=connection.adb_path,
            adb_ready=connection.success,
            device_serial=connection.selected_device.serial if connection.selected_device else simulator["device_serial"],
            resolution=screen_info.get("resolution") or controller.screen_size,
        )
        payload.update(
            {
                "adb_source": connection.adb_source,
                "connection_status": connection.status,
                "device_state": connection.selected_device.state if connection.selected_device else None,
                "candidates": [device.to_dict() for device in connection.candidates],
                "density": screen_info.get("density"),
                "screen_info": screen_info,
                "screenshot_check": None,
            }
        )
        warnings = list(connection.warnings)
        if connection.success:
            screenshot = controller.capture_screenshot(
                RecognitionScene.EQUIPMENT_LIST,
                serial=payload["device_serial"],
                output_dir=self._runtime_dir(),
                screen_state=SCENE_EQUIPMENT_LIST,
                scene_hint="connection_check",
                task_context=task_context,
            )
            payload["screenshot_check"] = screenshot.to_payload()
            if screenshot.artifact:
                payload["screenshot_path"] = screenshot.artifact.screenshot_path
            warnings.extend(screenshot.warnings)
            if not screenshot.success:
                return EquipmentPageAdbResult(
                    False,
                    screenshot.status,
                    "ADB 已连接，但装备页截图能力检查失败。",
                    screenshot.detail,
                    payload,
                    tuple(warnings),
                )

        return EquipmentPageAdbResult(
            connection.success,
            "ready" if connection.success else connection.status,
            connection.message if connection.success else "ADB 设备未就绪，装备页采集不可用。",
            f"模拟器={simulator['name']}；ADB={payload['adb_path'] or '未找到'}；分辨率={payload['resolution']}",
            payload,
            tuple(warnings),
        )

    def get_device_info(self, task_context: Optional[TaskExecutionContext] = None) -> EquipmentPageAdbResult:
        """
        读取当前设备、游戏包、方向、密度和模拟器 key。
        输入：
            task_context: 可选取消上下文。
        输出：
            EquipmentPageAdbResult；拿不到真实值时返回 warning 而不是异常。
        使用示例：
            result = api.get_device_info()
        """
        self._raise_if_cancelled(task_context, "装备页设备信息查询已取消。")
        simulator = self._get_simulator_context()
        controller = self._create_controller(simulator)
        warnings: list[str] = []
        connection = controller.check_connection(serial=simulator["device_serial"] or None, task_context=task_context)
        screen_info = controller.get_screen_info(
            serial=connection.selected_device.serial if connection.selected_device else simulator["device_serial"] or None,
            task_context=task_context,
        ) if connection.success else {"resolution": None, "density": None}
        foreground = controller.get_foreground_package(
            serial=connection.selected_device.serial if connection.selected_device else simulator["device_serial"] or None,
            task_context=task_context,
        ) if connection.success else AdbCommandResult(False, "unavailable", "设备未连接，无法查询前台应用。")
        if not foreground.success:
            warnings.append(f"前台应用读取失败: {foreground.status}")
        game_config = self.config_loader.get_game_config()
        resolution = screen_info.get("resolution") or controller.screen_size
        orientation = "landscape" if resolution and int(resolution[0]) >= int(resolution[1]) else "portrait"
        payload = self._base_payload(
            simulator,
            controller,
            adb_path=connection.adb_path,
            adb_ready=connection.success,
            device_serial=connection.selected_device.serial if connection.selected_device else simulator["device_serial"],
            resolution=resolution,
        )
        payload.update(
            {
                "package_name": game_config.get("package_name", ""),
                "foreground_package": foreground.stdout if foreground.success else None,
                "serial": payload["device_serial"],
                "orientation": orientation,
                "density": screen_info.get("density"),
                "current_simulator_key": simulator["key"],
                "connection_status": connection.status,
                "screen_info": screen_info,
                "foreground_command": foreground.to_dict(),
            }
        )
        warnings.extend(connection.warnings)
        return EquipmentPageAdbResult(
            connection.success,
            "ready" if connection.success else connection.status,
            "装备页设备信息查询完成。" if connection.success else connection.message,
            f"模拟器={simulator['name']}；方向={orientation}；前台={payload['foreground_package'] or '未知'}",
            payload,
            tuple(warnings),
        )

    def ensure_equipment_page_ready(
        self,
        rarity: Optional[str] = None,
        equipment_type: Optional[str] = None,
        keep_on: bool = True,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        scene_probe: Optional[Callable[..., object]] = None,
        state_probe: Optional[Callable[..., object]] = None,
    ) -> EquipmentPageAdbResult:
        """
        进入装备页，确保装备中 ON，并按需应用稀有度/类型筛选。
        输入：
            rarity/equipment_type: 可选筛选条件；keep_on: 是否执行装备中 ON；
            scene_probe/state_probe: 可选页面探针，供 OCR 整合或测试注入。
        输出：
            EquipmentPageAdbResult，payload 中包含稳定截图和筛选元数据。
        使用示例：
            api.ensure_equipment_page_ready(rarity="super_rare", equipment_type="战列炮")
        """
        self._raise_if_cancelled(task_context, "装备页准备流程已取消。")
        simulator = self._get_simulator_context()
        controller = self._create_controller(simulator)
        effective_scene_probe = scene_probe or self._scene_probe or self._optimistic_scene_probe
        effective_state_probe = state_probe or self._state_probe or self._optimistic_equipment_state_probe
        warnings: list[str] = []
        if scene_probe is None and self._scene_probe is None:
            warnings.append("未注入 scene_probe，进入装备页只执行动作并保留截图证据。")
        if state_probe is None and self._state_probe is None:
            warnings.append("未注入 state_probe，装备页状态只能通过后续截图人工或 OCR 验证。")

        enter = controller.run_sequence(
            "enter_warehouse",
            effective_scene_probe,
            state_probe=effective_state_probe,
            serial=simulator["device_serial"] or None,
            task_context=task_context,
        )
        warnings.extend(enter.warnings)
        if not enter.success:
            return self._navigation_failure("进入仓库失败，无法继续装备页准备。", enter, simulator, controller, warnings)

        tab = controller.select_warehouse_tab(
            "equipment",
            effective_state_probe,
            serial=simulator["device_serial"] or None,
            task_context=task_context,
        )
        warnings.extend(tab.warnings)
        if not tab.success:
            return self._navigation_failure("切换装备页签失败。", tab, simulator, controller, warnings)

        step_payloads: list[Dict[str, Any]] = [enter.to_payload(), tab.to_payload()]
        if keep_on:
            equipped = self.ensure_equipped_on(task_context=task_context, state_probe=effective_state_probe)
            step_payloads.append(equipped.payload or {})
            warnings.extend(equipped.warnings)
            if not equipped.success:
                return equipped

        if rarity:
            rarity_result = self.set_rarity_filter(rarity, task_context=task_context)
            step_payloads.append(rarity_result.payload or {})
            warnings.extend(rarity_result.warnings)
            if not rarity_result.success:
                return rarity_result

        if equipment_type:
            type_result = self.set_type_filter(equipment_type, task_context=task_context)
            step_payloads.append(type_result.payload or {})
            warnings.extend(type_result.warnings)
            if not type_result.success:
                return type_result

        artifact = self.capture_viewport(task_context=task_context)
        warnings.extend(artifact.warnings)
        payload = artifact.to_dict()
        payload["steps"] = step_payloads
        payload["rarity_filter"] = self._last_rarity_filter
        payload["equipment_type"] = self._last_equipment_type
        payload["equipped_state"] = self._last_equipped_state
        return EquipmentPageAdbResult(
            artifact.success,
            artifact.status,
            "装备页已准备完成。" if artifact.success else artifact.message,
            f"rarity={self._last_rarity_filter}；type={self._last_equipment_type}；equipped={self._last_equipped_state}",
            payload,
            tuple(warnings),
        )

    def ensure_equipped_on(
        self,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        state_probe: Optional[Callable[..., object]] = None,
    ) -> EquipmentPageAdbResult:
        """
        执行“装备中 ON”动作并留下 post-action 截图。
        输入：
            state_probe: 可选状态探针，能返回 equipped_state/on 时可避免盲点。
        输出：
            EquipmentPageAdbResult；无法视觉确认时返回 warning 和截图证据。
        使用示例：
            result = api.ensure_equipped_on()
        """
        self._raise_if_cancelled(task_context, "装备中 ON 检查已取消。")
        effective_probe = state_probe or self._state_probe
        warnings: list[str] = []
        observed = self._probe_equipped_state(effective_probe)
        if observed == "on":
            self._last_equipped_state = "on"
            artifact = self.capture_viewport(task_context=task_context)
            payload = artifact.to_dict()
            payload["equipped_state"] = "on"
            return EquipmentPageAdbResult(True, "ready", "装备中已处于 ON 状态。", "state_probe 已确认。", payload, artifact.warnings)

        if observed not in {"off", ""}:
            warnings.append(f"装备中状态探针返回未知值: {observed}")
        if observed == "":
            warnings.append("未注入可读取装备中状态的探针，已执行 ON 按钮并保留截图证据。")

        action = self._tap_point("equipped_on", "装备中 ON", task_context=task_context)
        warnings.extend(action.warnings)
        if not action.success:
            return action
        self._post_action_delay(DEFAULT_POST_ACTION_DELAY_MS, task_context)
        observed_after = self._probe_equipped_state(effective_probe)
        self._last_equipped_state = "on" if observed_after in {"", "on"} else observed_after
        if observed_after == "":
            warnings.append("装备中 ON 点击后未能自动确认状态，请以后续截图/OCR 为准。")
        artifact = self.capture_viewport(task_context=task_context)
        warnings.extend(artifact.warnings)
        payload = artifact.to_dict()
        payload["action"] = "ensure_equipped_on"
        payload["command"] = (action.payload or {}).get("command")
        payload["equipped_state"] = self._last_equipped_state
        return EquipmentPageAdbResult(
            artifact.success,
            artifact.status,
            "装备中 ON 操作已执行。" if artifact.success else artifact.message,
            "已点击装备中 ON 并采集 post-action 截图。",
            payload,
            tuple(warnings),
        )

    def open_filter_panel(self, task_context: Optional[TaskExecutionContext] = None) -> EquipmentPageAdbResult:
        """
        打开装备页筛选面板。
        输入：
            task_context: 可选取消上下文。
        输出：
            EquipmentPageAdbResult，payload 保留点击命令和截图路径。
        使用示例：
            result = api.open_filter_panel()
        """
        return self._tap_and_capture("filter_button", "打开装备筛选面板", task_context=task_context, scene_hint="filter_panel")

    def set_rarity_filter(self, rarity: str, task_context: Optional[TaskExecutionContext] = None) -> EquipmentPageAdbResult:
        """
        设置装备稀有度筛选。
        输入：
            rarity: all/common/rare/elite/super_rare/ultra_rare。
        输出：
            EquipmentPageAdbResult，不做识别结论，只记录动作和截图。
        使用示例：
            api.set_rarity_filter("ultra_rare")
        """
        self._raise_if_cancelled(task_context, "装备稀有度筛选已取消。")
        normalized = str(rarity or "").strip().lower()
        if normalized not in RARITY_FILTERS:
            return self._error_result("invalid_filter", f"未知稀有度筛选: {rarity}", {"rarity_filter": rarity})
        open_result = self.open_filter_panel(task_context=task_context)
        if not open_result.success:
            return open_result
        command = self._tap_coordinate(RARITY_FILTER_POINTS[normalized], f"选择稀有度 {normalized}", task_context=task_context)
        if not command.success:
            return self._command_result(command, "set_rarity_filter", {"rarity_filter": normalized})
        self._last_rarity_filter = normalized
        self._post_action_delay(DEFAULT_POST_ACTION_DELAY_MS, task_context)
        artifact = self.capture_viewport(task_context=task_context)
        payload = artifact.to_dict()
        payload.update({"action": "set_rarity_filter", "rarity_filter": normalized, "command": command.to_dict()})
        return EquipmentPageAdbResult(artifact.success, artifact.status, "稀有度筛选动作已执行。", f"rarity={normalized}", payload, artifact.warnings)

    def set_type_filter(self, equipment_type: str, task_context: Optional[TaskExecutionContext] = None) -> EquipmentPageAdbResult:
        """
        设置装备类型筛选。
        输入：
            equipment_type: 游戏内按钮文本，如“战列炮”，也支持常见英文别名。
        输出：
            EquipmentPageAdbResult；不判断命中数量，只保留动作证据。
        使用示例：
            api.set_type_filter("战列炮")
        """
        self._raise_if_cancelled(task_context, "装备类型筛选已取消。")
        label = self._normalize_equipment_type(equipment_type)
        if label not in EQUIPMENT_TYPE_POINTS:
            return self._error_result("invalid_filter", f"未知装备类型筛选: {equipment_type}", {"equipment_type": equipment_type})
        open_result = self.open_filter_panel(task_context=task_context)
        if not open_result.success:
            return open_result
        command = self._tap_coordinate(EQUIPMENT_TYPE_POINTS[label], f"选择装备类型 {label}", task_context=task_context)
        if not command.success:
            return self._command_result(command, "set_type_filter", {"equipment_type": label})
        self._last_equipment_type = label
        self._post_action_delay(DEFAULT_POST_ACTION_DELAY_MS, task_context)
        artifact = self.capture_viewport(task_context=task_context)
        payload = artifact.to_dict()
        payload.update({"action": "set_type_filter", "equipment_type": label, "command": command.to_dict()})
        return EquipmentPageAdbResult(artifact.success, artifact.status, "装备类型筛选动作已执行。", f"type={label}", payload, artifact.warnings)

    def reset_filter_to_all(self, task_context: Optional[TaskExecutionContext] = None) -> EquipmentPageAdbResult:
        """
        将装备页筛选恢复为全部。
        输入：
            task_context: 可选取消上下文。
        输出：
            EquipmentPageAdbResult，payload 保留 reset/all 点击证据。
        使用示例：
            api.reset_filter_to_all()
        """
        self._raise_if_cancelled(task_context, "装备筛选重置已取消。")
        open_result = self.open_filter_panel(task_context=task_context)
        if not open_result.success:
            return open_result
        commands = [
            self._tap_coordinate(EQUIPMENT_PAGE_POINTS["filter_reset"], "筛选重置", task_context=task_context),
            self._tap_coordinate(RARITY_FILTER_POINTS["all"], "稀有度全部", task_context=task_context),
            self._tap_coordinate(EQUIPMENT_TYPE_POINTS["全部"], "类型全部", task_context=task_context),
        ]
        failed = next((item for item in commands if not item.success), None)
        if failed is not None:
            return self._command_result(failed, "reset_filter_to_all", {"commands": [item.to_dict() for item in commands]})
        self._last_rarity_filter = "all"
        self._last_equipment_type = "全部"
        self._post_action_delay(DEFAULT_POST_ACTION_DELAY_MS, task_context)
        artifact = self.capture_viewport(task_context=task_context)
        payload = artifact.to_dict()
        payload.update({"action": "reset_filter_to_all", "commands": [item.to_dict() for item in commands]})
        return EquipmentPageAdbResult(artifact.success, artifact.status, "装备筛选已恢复全部。", "rarity=all；type=全部", payload, artifact.warnings)

    def open_search_panel(self, task_context: Optional[TaskExecutionContext] = None) -> EquipmentPageAdbResult:
        """
        打开装备页搜索输入区域。
        输入：
            task_context: 可选取消上下文。
        输出：
            EquipmentPageAdbResult。
        使用示例：
            api.open_search_panel()
        """
        return self._tap_and_capture("search_button", "打开装备搜索", task_context=task_context, scene_hint="search_panel")

    def input_search_text(
        self,
        text: str,
        clear_before_input: bool = True,
        input_mode: str = "clipboard",
        task_context: Optional[TaskExecutionContext] = None,
    ) -> EquipmentPageAdbResult:
        """
        输入装备搜索文本，默认优先使用剪贴板以支持中文装备名。
        输入：
            text: 装备名称或关键词；clear_before_input: 输入前是否清空；input_mode: clipboard/input_text/auto。
        输出：
            EquipmentPageAdbResult，payload 中保留实际命令链和 search_text。
        使用示例：
            api.input_search_text("试作型三联装406mm主炮")
        """
        self._raise_if_cancelled(task_context, "装备搜索输入已取消。")
        search_text = str(text or "").strip()
        if not search_text:
            return self._error_result("invalid_text", "搜索文本不能为空。", {"search_text": text})
        mode = str(input_mode or "clipboard").strip().lower()
        if mode not in {"clipboard", "input_text", "auto"}:
            return self._error_result("invalid_input_mode", f"未知输入模式: {input_mode}", {"search_text": search_text, "input_mode": mode})

        commands: list[Dict[str, Any]] = []
        warnings: list[str] = []
        open_result = self.open_search_panel(task_context=task_context)
        if not open_result.success:
            return open_result
        if clear_before_input:
            clear_result = self.clear_search_text(task_context=task_context)
            commands.append({"clear": clear_result.to_dict()})
            warnings.extend(clear_result.warnings)
            if not clear_result.success:
                return clear_result
        self._tap_coordinate(EQUIPMENT_PAGE_POINTS["search_input"], "聚焦搜索输入框", task_context=task_context)

        command_result = self._input_text_with_mode(search_text, mode, commands, warnings, task_context)
        if not command_result.success:
            payload = self._common_operation_payload("input_search_text")
            payload.update({"search_text": search_text, "input_mode": mode, "commands": commands})
            return EquipmentPageAdbResult(False, command_result.status, command_result.message, "搜索文本输入失败。", payload, tuple(warnings))

        self._last_search_text = search_text
        self._post_action_delay(DEFAULT_POST_ACTION_DELAY_MS, task_context)
        artifact = self.capture_viewport(task_context=task_context)
        warnings.extend(artifact.warnings)
        payload = artifact.to_dict()
        payload.update({"action": "input_search_text", "search_text": search_text, "input_mode": mode, "commands": commands})
        return EquipmentPageAdbResult(artifact.success, artifact.status, "搜索文本输入完成。", f"search={search_text}", payload, tuple(warnings))

    def confirm_search(self, task_context: Optional[TaskExecutionContext] = None) -> EquipmentPageAdbResult:
        """
        确认搜索并等待结果页稳定。
        输入：
            task_context: 可选取消上下文。
        输出：
            EquipmentPageAdbResult；不判断是否唯一命中。
        使用示例：
            api.confirm_search()
        """
        return self._tap_and_capture("search_confirm", "确认装备搜索", task_context=task_context, scene_hint="search_result")

    def clear_search_text(self, task_context: Optional[TaskExecutionContext] = None) -> EquipmentPageAdbResult:
        """
        清空搜索框文本。
        输入：
            task_context: 可选取消上下文。
        输出：
            EquipmentPageAdbResult；优先点清空按钮，失败时用删除键兜底。
        使用示例：
            api.clear_search_text()
        """
        self._raise_if_cancelled(task_context, "清空装备搜索已取消。")
        warnings: list[str] = []
        clear_tap = self._tap_coordinate(EQUIPMENT_PAGE_POINTS["search_clear"], "清空搜索按钮", task_context=task_context)
        commands = [clear_tap.to_dict()]
        if not clear_tap.success:
            warnings.append("清空按钮点击失败，尝试使用删除键逐字清空。")
            for _index in range(DEFAULT_SEARCH_CLEAR_DELETE_COUNT):
                self._raise_if_cancelled(task_context, "清空装备搜索已取消。")
                delete_result = self._controller().keyevent("KEYCODE_DEL", serial=self._serial(), task_context=task_context)
                commands.append(delete_result.to_dict())
                if not delete_result.success:
                    return self._command_result(delete_result, "clear_search_text", {"commands": commands}, warnings=tuple(warnings))
        self._last_search_text = ""
        self._post_action_delay(DEFAULT_POST_ACTION_DELAY_MS, task_context)
        artifact = self.capture_viewport(task_context=task_context)
        warnings.extend(artifact.warnings)
        payload = artifact.to_dict()
        payload.update({"action": "clear_search_text", "search_text": "", "commands": commands})
        return EquipmentPageAdbResult(artifact.success, artifact.status, "搜索文本已清空。", "search_text=空", payload, tuple(warnings))

    def capture_viewport(
        self,
        session_id: str = "",
        frame_index: int = 0,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> EquipmentPageCaptureArtifact:
        """
        截取当前装备列表 viewport，不做拼接。
        输入：
            session_id: 采集会话 ID；frame_index: 本帧序号。
        输出：
            EquipmentPageCaptureArtifact，路径为绝对路径并附带 sha1。
        使用示例：
            artifact = api.capture_viewport("manual", 0)
        """
        self._raise_if_cancelled(task_context, "装备页 viewport 截图已取消。")
        safe_session_id = self._normalize_session_id(session_id)
        output_dir = self._session_dir(safe_session_id)
        controller = self._controller()
        screenshot = controller.capture_screenshot(
            RecognitionScene.EQUIPMENT_LIST,
            serial=self._serial(),
            output_dir=output_dir,
            screen_state=SCENE_EQUIPMENT_LIST,
            scene_hint="equipment_viewport",
            task_context=task_context,
        )
        if not screenshot.success or screenshot.artifact is None:
            return EquipmentPageCaptureArtifact(
                "",
                safe_session_id,
                int(frame_index),
                "",
                screenshot.resolution or controller.screen_size,
                int(frame_index),
                "",
                0,
                device_serial=self._serial(),
                rarity_filter=self._last_rarity_filter,
                equipment_type=self._last_equipment_type,
                equipped_state=self._last_equipped_state,
                search_text=self._last_search_text,
                timestamp=screenshot.timestamp,
                adb_path=screenshot.adb_path,
                adb_ready=False,
                success=False,
                status=screenshot.status,
                message=screenshot.message,
                warnings=screenshot.warnings,
            )
        screenshot_path = Path(screenshot.artifact.screenshot_path).resolve()
        return EquipmentPageCaptureArtifact(
            str(screenshot_path),
            safe_session_id,
            int(frame_index),
            self._sha1_file(screenshot_path),
            screenshot.resolution or controller.screen_size,
            int(frame_index),
            "",
            0,
            device_serial=screenshot.artifact.device_serial,
            rarity_filter=self._last_rarity_filter,
            equipment_type=self._last_equipment_type,
            equipped_state=self._last_equipped_state,
            search_text=self._last_search_text,
            timestamp=screenshot.timestamp,
            adb_path=screenshot.adb_path,
            adb_ready=True,
            success=True,
            status="ready",
            message="装备页 viewport 截图完成。",
            warnings=screenshot.warnings,
        )

    def scroll_list(
        self,
        direction: str,
        distance_px: Optional[int] = None,
        duration_ms: int = DEFAULT_SCROLL_DURATION_MS,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        wait_after_scroll_ms: int = DEFAULT_POST_ACTION_DELAY_MS,
    ) -> EquipmentPageAdbResult:
        """
        对装备列表执行一次滑动。
        输入：
            direction: up/down/left/right；distance_px: 基准分辨率下滑动像素；duration_ms: 滑动时长。
        输出：
            EquipmentPageAdbResult，包含滑动命令和后续截图。
        使用示例：
            api.scroll_list("down", distance_px=420)
        """
        self._raise_if_cancelled(task_context, "装备列表滑动已取消。")
        normalized = str(direction or "").strip().lower()
        if normalized not in SCROLL_ANCHORS:
            return self._error_result("invalid_direction", f"未知滑动方向: {direction}", {"scroll_direction": direction})
        pixels = int(distance_px or DEFAULT_SCROLL_DISTANCE_PX)
        if pixels <= 0:
            return self._error_result("invalid_distance", "滑动距离必须大于 0。", {"scroll_pixels": pixels})
        command = self._scroll_command(normalized, pixels, int(duration_ms), task_context)
        if not command.success:
            return self._command_result(command, "scroll_list", {"scroll_direction": normalized, "scroll_pixels": pixels})
        self._post_action_delay(wait_after_scroll_ms, task_context)
        artifact = self.capture_viewport(task_context=task_context)
        payload = artifact.to_dict()
        payload.update(
            {
                "action": "scroll_list",
                "scroll_direction": normalized,
                "scroll_pixels": pixels,
                "duration_ms": int(duration_ms),
                "command": command.to_dict(),
            }
        )
        return EquipmentPageAdbResult(artifact.success, artifact.status, "装备列表滑动完成。", f"{normalized}:{pixels}px", payload, artifact.warnings)

    def capture_scroll_sequence(
        self,
        frame_count: int,
        overlap_hint: float = DEFAULT_SCROLL_OVERLAP_HINT,
        stop_on_repeat: bool = True,
        resume_cursor: int = 0,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> EquipmentPageScrollSession:
        """
        连续采集装备页 viewport 序列，并写出 manifest。
        输入：
            frame_count: 本次采集帧数；overlap_hint: 帧间重叠比例；stop_on_repeat: 重复帧时停止。
        输出：
            EquipmentPageScrollSession，包含 CSV/JSON manifest 和断点 cursor。
        使用示例：
            session = api.capture_scroll_sequence(8, overlap_hint=0.35)
        """
        self._raise_if_cancelled(task_context, "装备页滚动采集已取消。")
        if int(frame_count) <= 0:
            return EquipmentPageScrollSession("", (), "", int(resume_cursor), False, ("frame_count 必须大于 0。",), success=False, status="invalid_frame_count", message="装备页滚动采集参数无效。")
        if not 0.0 <= float(overlap_hint) < 1.0:
            return EquipmentPageScrollSession("", (), "", int(resume_cursor), False, ("overlap_hint 必须位于 0.0 到 1.0 之间。",), success=False, status="invalid_overlap", message="装备页滚动采集参数无效。")

        session_id = self._normalize_session_id("")
        frames: list[EquipmentPageScrollFrame] = []
        artifacts: list[Dict[str, Any]] = []
        warnings: list[str] = []
        end_of_list_suspected = False
        previous_sha1 = ""
        scroll_pixels = max(1, int(round(DEFAULT_SCROLL_DISTANCE_PX * (1.0 - float(overlap_hint)))))

        for offset in range(int(frame_count)):
            self._raise_if_cancelled(task_context, "装备页滚动采集已取消。")
            frame_index = int(resume_cursor) + offset
            artifact = self.capture_viewport(session_id=session_id, frame_index=frame_index, task_context=task_context)
            artifact = self._artifact_with_scroll(artifact, frame_index, "down", scroll_pixels, float(overlap_hint))
            artifacts.append(artifact.to_dict())
            warnings.extend(artifact.warnings)
            if not artifact.success:
                warnings.append(f"第 {frame_index} 帧截图失败: {artifact.status}")
                break
            frames.append(
                EquipmentPageScrollFrame(
                    artifact.screenshot_path,
                    artifact.frame_index,
                    artifact.sha1,
                    artifact.scroll_index,
                    artifact.overlap_hint,
                    artifact.scroll_direction,
                    artifact.scroll_pixels,
                    artifact.timestamp,
                )
            )
            if previous_sha1 and previous_sha1 == artifact.sha1:
                end_of_list_suspected = True
                warnings.append("检测到连续两帧 sha1 相同，疑似到达列表底部。")
                if stop_on_repeat:
                    break
            previous_sha1 = artifact.sha1

            if offset < int(frame_count) - 1:
                scroll_command = self._scroll_command(
                    "down",
                    scroll_pixels,
                    DEFAULT_SCROLL_DURATION_MS,
                    task_context,
                )
                if not scroll_command.success:
                    warnings.append(f"第 {frame_index} 帧后的滑动失败: {scroll_command.status}")
                    break
                self._post_action_delay(DEFAULT_POST_ACTION_DELAY_MS, task_context)

        session_dir = self._session_dir(session_id)
        csv_manifest = session_dir / "capture_manifest.csv"
        json_manifest = session_dir / "capture_manifest.json"
        scroll_session_path = session_dir / "scroll_session.json"
        self._write_manifest_files(csv_manifest, json_manifest, scroll_session_path, session_id, artifacts, frames, int(resume_cursor), end_of_list_suspected, warnings)
        return EquipmentPageScrollSession(
            session_id,
            tuple(frames),
            str(csv_manifest.resolve()),
            int(resume_cursor) + len(frames),
            end_of_list_suspected,
            tuple(warnings),
            json_manifest_path=str(json_manifest.resolve()),
            scroll_session_path=str(scroll_session_path.resolve()),
            success=bool(frames) and not any("截图失败" in warning for warning in warnings),
            status="ready" if frames else "error",
            message="装备页滚动采集完成。" if frames else "装备页滚动采集失败。",
        )

    def return_to_equipment_list(self, task_context: Optional[TaskExecutionContext] = None) -> EquipmentPageAdbResult:
        """
        关闭搜索或筛选浮层，回到稳定装备列表页。
        输入：
            task_context: 可选取消上下文。
        输出：
            EquipmentPageAdbResult，包含返回动作和截图。
        使用示例：
            api.return_to_equipment_list()
        """
        self._raise_if_cancelled(task_context, "返回装备列表已取消。")
        commands = [
            self._controller().keyevent("KEYCODE_BACK", serial=self._serial(), task_context=task_context),
            self._controller().keyevent("KEYCODE_BACK", serial=self._serial(), task_context=task_context),
        ]
        failed = next((item for item in commands if not item.success), None)
        if failed is not None:
            return self._command_result(failed, "return_to_equipment_list", {"commands": [item.to_dict() for item in commands]})
        self._last_search_text = ""
        self._post_action_delay(DEFAULT_POST_ACTION_DELAY_MS, task_context)
        artifact = self.capture_viewport(task_context=task_context)
        payload = artifact.to_dict()
        payload.update({"action": "return_to_equipment_list", "commands": [item.to_dict() for item in commands]})
        return EquipmentPageAdbResult(artifact.success, artifact.status, "已返回装备列表。", "搜索/筛选浮层返回动作已执行。", payload, artifact.warnings)

    def tap(self, x: int | float, y: int | float, task_context: Optional[TaskExecutionContext] = None) -> EquipmentPageAdbResult:
        """
        装备页低层点击原语。
        输入：
            x/y: 1280x720 基准坐标。
        输出：
            EquipmentPageAdbResult，payload 包含 command/exit_code/stdout/stderr/elapsed_ms。
        使用示例：
            api.tap(640, 360)
        """
        started = time.perf_counter()
        command = self._controller().tap(x, y, serial=self._serial(), base_resolution=BASE_RESOLUTION, task_context=task_context)
        return self._primitive_result("tap", command, started)

    def swipe(
        self,
        x1: int | float,
        y1: int | float,
        x2: int | float,
        y2: int | float,
        duration_ms: int = DEFAULT_SCROLL_DURATION_MS,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> EquipmentPageAdbResult:
        """
        装备页低层滑动原语。
        输入：
            起止点为 1280x720 基准坐标，duration_ms 为毫秒。
        输出：
            EquipmentPageAdbResult。
        使用示例：
            api.swipe(640, 590, 640, 170, 650)
        """
        started = time.perf_counter()
        command = self._controller().swipe(x1, y1, x2, y2, duration_ms, serial=self._serial(), base_resolution=BASE_RESOLUTION, task_context=task_context)
        return self._primitive_result("swipe", command, started)

    def input_text(self, text: str, mode: str = "clipboard", task_context: Optional[TaskExecutionContext] = None) -> EquipmentPageAdbResult:
        """
        装备页低层文本输入原语。
        输入：
            text: 文本；mode: clipboard/input_text/auto。
        输出：
            EquipmentPageAdbResult，中文默认走剪贴板路径。
        使用示例：
            api.input_text("彩云", mode="clipboard")
        """
        commands: list[Dict[str, Any]] = []
        warnings: list[str] = []
        started = time.perf_counter()
        command = self._input_text_with_mode(str(text), str(mode), commands, warnings, task_context)
        result = self._primitive_result("input_text", command, started, warnings=tuple(warnings))
        if result.payload is not None:
            result.payload["commands"] = commands
            result.payload["input_mode"] = mode
        return result

    def keyevent(self, keycode: int | str, task_context: Optional[TaskExecutionContext] = None) -> EquipmentPageAdbResult:
        """
        装备页低层按键原语。
        输入：
            keycode: Android KEYCODE_* 或整数。
        输出：
            EquipmentPageAdbResult。
        使用示例：
            api.keyevent("KEYCODE_BACK")
        """
        started = time.perf_counter()
        command = self._controller().keyevent(keycode, serial=self._serial(), task_context=task_context)
        return self._primitive_result("keyevent", command, started)

    def screenshot(
        self,
        output_path: Optional[str | Path] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> EquipmentPageCaptureArtifact:
        """
        装备页低层截图原语。
        输入：
            output_path: 可选目标目录或文件路径；为空时写入装备页运行目录。
        输出：
            EquipmentPageCaptureArtifact。
        使用示例：
            artifact = api.screenshot()
        """
        if output_path is None:
            return self.capture_viewport(task_context=task_context)
        target = Path(output_path)
        output_dir = target if target.suffix == "" else target.parent
        artifact = self.capture_viewport(session_id=target.stem if target.suffix else "", task_context=task_context)
        if target.suffix and artifact.success and artifact.screenshot_path:
            final_path = target.resolve()
            final_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(artifact.screenshot_path, final_path)
            return EquipmentPageCaptureArtifact(
                str(final_path),
                artifact.session_id,
                artifact.frame_index,
                self._sha1_file(final_path),
                artifact.resolution,
                artifact.scroll_index,
                artifact.scroll_direction,
                artifact.scroll_pixels,
                scene=artifact.scene,
                device_serial=artifact.device_serial,
                rarity_filter=artifact.rarity_filter,
                equipment_type=artifact.equipment_type,
                equipped_state=artifact.equipped_state,
                search_text=artifact.search_text,
                overlap_hint=artifact.overlap_hint,
                timestamp=artifact.timestamp,
                adb_path=artifact.adb_path,
                adb_ready=artifact.adb_ready,
                real_command_enabled=artifact.real_command_enabled,
                success=artifact.success,
                status=artifact.status,
                message=artifact.message,
                warnings=artifact.warnings,
            )
        return artifact

    def wait(self, milliseconds: int, task_context: Optional[TaskExecutionContext] = None) -> EquipmentPageAdbResult:
        """
        装备页低层等待原语。
        输入：
            milliseconds: 等待毫秒数。
        输出：
            EquipmentPageAdbResult。
        使用示例：
            api.wait(500)
        """
        started = time.perf_counter()
        self._post_action_delay(int(milliseconds), task_context)
        payload = self._common_operation_payload("wait")
        payload.update({"elapsed_ms": int((time.perf_counter() - started) * 1000), "duration_ms": int(milliseconds)})
        return EquipmentPageAdbResult(True, "ready", "等待完成。", f"{milliseconds}ms", payload)

    def run_adb(self, args: Sequence[str], task_context: Optional[TaskExecutionContext] = None) -> EquipmentPageAdbResult:
        """
        装备页低层 ADB 命令原语。
        输入：
            args: 不包含 adb 可执行文件的参数列表。
        输出：
            EquipmentPageAdbResult，禁止 shell=True。
        使用示例：
            api.run_adb(["shell", "wm", "size"])
        """
        self._raise_if_cancelled(task_context, "装备页 ADB 命令已取消。")
        started = time.perf_counter()
        command = self._controller().run_adb(list(args), serial=self._serial())
        return self._primitive_result("run_adb", command, started)

    def wait_for_stable_screen(
        self,
        stable_frames: int = 2,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> EquipmentPageAdbResult:
        """
        简易等待屏幕稳定：连续截图 sha1 相同则认为稳定。
        输入：
            stable_frames: 需要连续相同的帧数。
        输出：
            EquipmentPageAdbResult，后续 OCR 可替换为更精细的视觉稳定判断。
        使用示例：
            api.wait_for_stable_screen(stable_frames=2)
        """
        self._raise_if_cancelled(task_context, "等待装备页稳定已取消。")
        target = max(1, int(stable_frames))
        previous_sha1 = ""
        hits = 0
        artifacts: list[Dict[str, Any]] = []
        warnings: list[str] = []
        for index in range(target + 2):
            artifact = self.capture_viewport(frame_index=index, task_context=task_context)
            artifacts.append(artifact.to_dict())
            warnings.extend(artifact.warnings)
            if not artifact.success:
                return EquipmentPageAdbResult(False, artifact.status, artifact.message, "稳定等待截图失败。", {"artifacts": artifacts}, tuple(warnings))
            hits = hits + 1 if previous_sha1 and previous_sha1 == artifact.sha1 else 1
            if hits >= target:
                payload = self._common_operation_payload("wait_for_stable_screen")
                payload.update({"stable_frames": hits, "artifacts": artifacts, "screenshot_path": artifact.screenshot_path})
                return EquipmentPageAdbResult(True, "ready", "装备页画面已稳定。", f"stable_frames={hits}", payload, tuple(warnings))
            previous_sha1 = artifact.sha1
            self._post_action_delay(150, task_context)
        payload = self._common_operation_payload("wait_for_stable_screen")
        payload.update({"stable_frames": hits, "artifacts": artifacts})
        return EquipmentPageAdbResult(True, "warning", "未观察到完全相同帧，已继续保留截图证据。", f"stable_frames={hits}", payload, tuple(warnings))

    # ============================================================
    # 🔧 第三部分：内部辅助函数
    # ============================================================

    def _get_simulator_context(self) -> Dict[str, Any]:
        """读取当前模拟器上下文，保持与 adb_task_api 的配置口径一致。"""
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

    def _controller(self) -> AdbController:
        """创建一次当前配置的底层控制器，避免装备页门面缓存过期配置。"""
        return self._create_controller(self._get_simulator_context())

    def _serial(self) -> Optional[str]:
        """返回显式设备串号，没有配置时交给底层单设备保护逻辑。"""
        simulator = self._get_simulator_context()
        return simulator["device_serial"] or None

    def _base_payload(
        self,
        simulator: Dict[str, Any],
        controller: AdbController,
        *,
        adb_path: Optional[str] = None,
        adb_ready: bool = False,
        device_serial: Optional[str] = None,
        resolution: Optional[Tuple[int, int]] = None,
    ) -> Dict[str, Any]:
        """构造所有装备页结果共享的 payload 字段。"""
        return {
            "scene": SCENE_EQUIPMENT_LIST,
            "screenshot_path": None,
            "device_serial": device_serial or simulator.get("device_serial") or simulator.get("default_device_serial") or None,
            "resolution": list(resolution or controller.screen_size),
            "rarity_filter": self._last_rarity_filter,
            "equipment_type": self._last_equipment_type,
            "equipped_state": self._last_equipped_state,
            "search_text": self._last_search_text,
            "session_id": "",
            "frame_index": 0,
            "scroll_index": 0,
            "scroll_direction": "",
            "scroll_pixels": 0,
            "overlap_hint": 0.0,
            "sha1": "",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "post_action_delay_ms": DEFAULT_POST_ACTION_DELAY_MS,
            "adb_path": adb_path,
            "adb_ready": adb_ready,
            "real_command_enabled": bool(adb_path),
            "current_simulator_key": simulator.get("key", ""),
            "simulator_name": simulator.get("name", ""),
            "warnings": [],
        }

    def _common_operation_payload(self, action: str) -> Dict[str, Any]:
        """构造单个装备页动作的基础 payload。"""
        simulator = self._get_simulator_context()
        controller = self._controller()
        adb = controller.find_adb()
        payload = self._base_payload(simulator, controller, adb_path=adb.adb_path, adb_ready=adb.available)
        payload["action"] = action
        return payload

    def _tap_point(self, point_name: str, action_name: str, task_context: Optional[TaskExecutionContext]) -> EquipmentPageAdbResult:
        """按语义点位执行一次点击，并返回结构化结果。"""
        point = EQUIPMENT_PAGE_POINTS[point_name]
        command = self._tap_coordinate(point, action_name, task_context=task_context)
        return self._command_result(command, action_name, {"point_name": point_name, "point": list(point)})

    def _tap_and_capture(
        self,
        point_name: str,
        action_name: str,
        *,
        task_context: Optional[TaskExecutionContext],
        scene_hint: str,
    ) -> EquipmentPageAdbResult:
        """点击语义点位后采集 post-action 截图。"""
        self._raise_if_cancelled(task_context, f"{action_name} 已取消。")
        command = self._tap_coordinate(EQUIPMENT_PAGE_POINTS[point_name], action_name, task_context=task_context)
        if not command.success:
            return self._command_result(command, action_name, {"point_name": point_name})
        self._post_action_delay(DEFAULT_POST_ACTION_DELAY_MS, task_context)
        artifact = self.capture_viewport(task_context=task_context)
        payload = artifact.to_dict()
        payload.update({"action": action_name, "point_name": point_name, "scene_hint": scene_hint, "command": command.to_dict()})
        return EquipmentPageAdbResult(artifact.success, artifact.status, f"{action_name}完成。", scene_hint, payload, artifact.warnings)

    def _tap_coordinate(
        self,
        point: Tuple[int, int],
        action_name: str,
        *,
        task_context: Optional[TaskExecutionContext],
    ) -> AdbCommandResult:
        """调用底层 tap，并固定使用装备页 1280x720 基准坐标。"""
        self._raise_if_cancelled(task_context, f"{action_name} 已取消。")
        return self._controller().tap(
            point[0],
            point[1],
            serial=self._serial(),
            base_resolution=BASE_RESOLUTION,
            task_context=task_context,
        )

    def _command_result(
        self,
        command: AdbCommandResult,
        action: str,
        extra_payload: Optional[Dict[str, Any]] = None,
        *,
        warnings: Tuple[str, ...] = (),
    ) -> EquipmentPageAdbResult:
        """把底层命令结果包装成装备页结果。"""
        payload = self._common_operation_payload(action)
        payload.update(extra_payload or {})
        payload["command"] = command.to_dict()
        payload["exit_code"] = command.returncode
        payload["stdout"] = command.stdout
        payload["stderr"] = command.stderr
        payload["elapsed_ms"] = 0
        return EquipmentPageAdbResult(command.success, "ready" if command.success else command.status, command.message, action, payload, warnings)

    def _primitive_result(
        self,
        action: str,
        command: AdbCommandResult,
        started: float,
        *,
        warnings: Tuple[str, ...] = (),
    ) -> EquipmentPageAdbResult:
        """包装低层原语命令日志，补充 elapsed_ms 字段。"""
        payload = self._common_operation_payload(action)
        payload.update(
            {
                "command": command.to_dict(),
                "exit_code": command.returncode,
                "stdout": command.stdout,
                "stderr": command.stderr,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        return EquipmentPageAdbResult(command.success, "ready" if command.success else command.status, command.message, action, payload, warnings)

    def _input_text_with_mode(
        self,
        text: str,
        mode: str,
        commands: list[Dict[str, Any]],
        warnings: list[str],
        task_context: Optional[TaskExecutionContext],
    ) -> AdbCommandResult:
        """按 clipboard/input_text/auto 策略输入文本，中文优先剪贴板。"""
        self._raise_if_cancelled(task_context, "装备页文本输入已取消。")
        normalized_mode = str(mode or "clipboard").strip().lower()
        if normalized_mode in {"clipboard", "auto"}:
            clipboard = self._controller().run_adb(
                ["shell", "cmd", "clipboard", "set", "text", text],
                serial=self._serial(),
            )
            commands.append({"clipboard_set": clipboard.to_dict()})
            if clipboard.success:
                paste = self._controller().keyevent("KEYCODE_PASTE", serial=self._serial(), task_context=task_context)
                commands.append({"paste": paste.to_dict()})
                if paste.success:
                    return paste
                warnings.append(f"剪贴板已设置但粘贴失败: {paste.status}")
            else:
                warnings.append(f"系统剪贴板写入失败: {clipboard.status}")

            clipper = self._controller().run_adb(
                ["shell", "am", "broadcast", "-a", "clipper.set", "-e", "text", text],
                serial=self._serial(),
            )
            commands.append({"clipper_set": clipper.to_dict()})
            if clipper.success:
                paste = self._controller().keyevent("KEYCODE_PASTE", serial=self._serial(), task_context=task_context)
                commands.append({"paste_after_clipper": paste.to_dict()})
                if paste.success:
                    return paste
                warnings.append(f"Clipper 写入后粘贴失败: {paste.status}")

        if normalized_mode in {"input_text", "auto", "clipboard"}:
            if any(ord(char) > 127 for char in text):
                warnings.append("已回退到 adb input text；中文可能需要 ADB Keyboard/剪贴板服务支持。")
            typed = self._controller().input_text(text, serial=self._serial(), task_context=task_context)
            commands.append({"input_text": typed.to_dict()})
            return typed
        return AdbCommandResult(False, "invalid_input_mode", f"未知输入模式: {mode}")

    def _scroll_points(self, direction: str, distance_px: int) -> Tuple[int, int, int, int]:
        """按方向和距离计算一次列表滑动的基准坐标。"""
        start_x, start_y, end_x, end_y = SCROLL_ANCHORS[direction]
        if direction == "down":
            end_y = max(80, start_y - int(distance_px))
        elif direction == "up":
            end_y = min(BASE_RESOLUTION[1] - 80, start_y + int(distance_px))
        elif direction == "left":
            end_x = max(80, start_x - int(distance_px))
        elif direction == "right":
            end_x = min(BASE_RESOLUTION[0] - 80, start_x + int(distance_px))
        return start_x, start_y, end_x, end_y

    def _scroll_command(
        self,
        direction: str,
        distance_px: int,
        duration_ms: int,
        task_context: Optional[TaskExecutionContext],
    ) -> AdbCommandResult:
        """执行一次不附带截图的列表滑动，供 scroll_list 和滚动采集复用。"""
        self._raise_if_cancelled(task_context, "装备列表滑动已取消。")
        start_x, start_y, end_x, end_y = self._scroll_points(direction, distance_px)
        return self._controller().swipe(
            start_x,
            start_y,
            end_x,
            end_y,
            int(duration_ms),
            serial=self._serial(),
            base_resolution=BASE_RESOLUTION,
            task_context=task_context,
        )

    def _probe_equipped_state(self, state_probe: Optional[Callable[..., object]]) -> str:
        """调用注入探针读取装备中状态，失败时返回空字符串。"""
        if state_probe is None:
            return ""
        try:
            probe_result = state_probe()
        except TypeError:
            try:
                probe_result = state_probe({"scene": SCENE_EQUIPMENT_LIST})
            except Exception:
                return ""
        except Exception:
            return ""
        if isinstance(probe_result, dict):
            value = probe_result.get("equipped_state", probe_result.get("equipped", ""))
            if isinstance(value, bool):
                return "on" if value else "off"
            return str(value).strip().lower()
        if isinstance(probe_result, bool):
            return "on" if probe_result else "off"
        return str(probe_result).strip().lower() if probe_result is not None else ""

    @staticmethod
    def _optimistic_scene_probe(scene: object = None) -> bool:
        """未注入识别层时的乐观探针：只让配置序列执行完成，不假装做 OCR。"""
        return True

    @staticmethod
    def _optimistic_equipment_state_probe(candidate: object = None) -> Dict[str, object]:
        """未注入识别层时返回装备页状态，便于底层状态化序列完成。"""
        return {"screen_state": "warehouse_equipment", "scene_hint": "equipment_tab", "confidence": 0.0}

    def _navigation_failure(
        self,
        message: str,
        navigation: Any,
        simulator: Dict[str, Any],
        controller: AdbController,
        warnings: Sequence[str],
    ) -> EquipmentPageAdbResult:
        """把导航失败转换为装备页结构化结果。"""
        payload = self._base_payload(simulator, controller, adb_ready=False)
        payload.update(navigation.to_payload())
        return EquipmentPageAdbResult(False, navigation.status, message, navigation.detail, payload, tuple(warnings))

    def _error_result(self, status: str, message: str, payload_extra: Optional[Dict[str, Any]] = None) -> EquipmentPageAdbResult:
        """创建装备页参数错误结果。"""
        payload = self._common_operation_payload(status)
        payload.update(payload_extra or {})
        return EquipmentPageAdbResult(False, status, message, message, payload)

    @staticmethod
    def _normalize_equipment_type(equipment_type: str) -> str:
        """规范化装备类型，保留中文真实按钮文本并兼容英文 key。"""
        raw = str(equipment_type or "").strip()
        if raw in EQUIPMENT_TYPE_POINTS:
            return raw
        return EQUIPMENT_TYPE_ALIASES.get(raw.lower(), raw)

    def _runtime_dir(self) -> Path:
        """返回装备页运行时截图目录。"""
        path = PathManager.get_work_dir() / "automation" / "equipment_page"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _session_dir(self, session_id: str) -> Path:
        """返回单次滚动采集会话目录。"""
        path = self._runtime_dir() / self._normalize_session_id(session_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _normalize_session_id(session_id: str) -> str:
        """生成或清洗 session_id，避免路径中出现不安全字符。"""
        raw = str(session_id or "").strip()
        if not raw:
            raw = f"equipment_page_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in raw)

    @staticmethod
    def _sha1_file(path: Path) -> str:
        """计算文件 sha1，作为滚动去重和 manifest 元数据。"""
        digest = hashlib.sha1()
        with open(path, "rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _artifact_with_scroll(
        artifact: EquipmentPageCaptureArtifact,
        frame_index: int,
        direction: str,
        scroll_pixels: int,
        overlap_hint: float,
    ) -> EquipmentPageCaptureArtifact:
        """给截图 artifact 补充滚动序列字段。"""
        return EquipmentPageCaptureArtifact(
            artifact.screenshot_path,
            artifact.session_id,
            artifact.frame_index,
            artifact.sha1,
            artifact.resolution,
            frame_index,
            direction,
            scroll_pixels,
            scene=artifact.scene,
            device_serial=artifact.device_serial,
            rarity_filter=artifact.rarity_filter,
            equipment_type=artifact.equipment_type,
            equipped_state=artifact.equipped_state,
            search_text=artifact.search_text,
            overlap_hint=overlap_hint,
            timestamp=artifact.timestamp,
            adb_path=artifact.adb_path,
            adb_ready=artifact.adb_ready,
            real_command_enabled=artifact.real_command_enabled,
            success=artifact.success,
            status=artifact.status,
            message=artifact.message,
            warnings=artifact.warnings,
        )

    def _write_manifest_files(
        self,
        csv_manifest: Path,
        json_manifest: Path,
        scroll_session_path: Path,
        session_id: str,
        artifacts: Sequence[Dict[str, Any]],
        frames: Sequence[EquipmentPageScrollFrame],
        resume_cursor: int,
        end_of_list_suspected: bool,
        warnings: Sequence[str],
    ) -> None:
        """写出 CSV/JSON manifest，方便后续 OCR 拼接层断点续接。"""
        csv_manifest.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "session_id",
            "frame_index",
            "screenshot_path",
            "sha1",
            "resolution",
            "scroll_index",
            "scroll_direction",
            "scroll_pixels",
            "overlap_hint",
            "timestamp",
            "rarity_filter",
            "equipment_type",
            "equipped_state",
            "search_text",
        ]
        with open(csv_manifest, "w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            for artifact in artifacts:
                writer.writerow({field: artifact.get(field, "") for field in fieldnames})
        session_payload = {
            "session_id": session_id,
            "frames": [frame.to_dict() for frame in frames],
            "resume_cursor": int(resume_cursor) + len(frames),
            "end_of_list_suspected": bool(end_of_list_suspected),
            "warnings": list(warnings),
            "artifacts": list(artifacts),
        }
        self._atomic_write_json(json_manifest, {"session_id": session_id, "artifacts": list(artifacts)})
        self._atomic_write_json(scroll_session_path, session_payload)

    @staticmethod
    def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
        """用临时文件 + os.replace 写 JSON，避免中途失败产生半截 manifest。"""
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

    def _post_action_delay(self, milliseconds: int, task_context: Optional[TaskExecutionContext]) -> None:
        """动作后短等待并响应取消，避免 UI 动画未停就截图。"""
        self._raise_if_cancelled(task_context, "装备页动作后等待已取消。")
        delay_seconds = max(0.0, int(milliseconds) / 1000.0)
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        self._raise_if_cancelled(task_context, "装备页动作后等待已取消。")

    @staticmethod
    def _raise_if_cancelled(task_context: Optional[TaskExecutionContext], message: str) -> None:
        """安全点取消检查。"""
        if task_context is not None:
            task_context.raise_if_cancelled(message)


# ============================================================
# 🌐 第四部分：全局访问函数
# ============================================================

_equipment_page_adb_api: Optional[EquipmentPageAdbApi] = None


def get_equipment_page_adb_api() -> EquipmentPageAdbApi:
    """
    获取全局装备页 ADB API。
    输入：
        无。
    输出：
        EquipmentPageAdbApi 单例。
    使用示例：
        api = get_equipment_page_adb_api()
    """
    global _equipment_page_adb_api
    if _equipment_page_adb_api is None:
        _equipment_page_adb_api = EquipmentPageAdbApi()
    return _equipment_page_adb_api
