#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🤖 ADB 自动化任务接口 (adb_task_api.py)          ║
║                                                              ║
║  【一句话解释】为 v0.6.0 模拟器自动化预留可被 GUI 调用的入口。 ║
║  【类比理解】它像港区设备检测台，先检查线路，不擅自启动机器。 ║
║  【数据流说明】GUI按钮 → Bridge → ADB API → 结构化结果。       ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import importlib.util
import re
from copy import deepcopy
from typing import Any, Callable, Dict, Optional

from core.contracts import RecognitionScene, StructuredTaskResult, TaskExecutionContext
from core.automation.adb_controller import (
    AdbController,
    AdbAutoConnectResult,
    AdbLoginResult,
    NavigationResult,
    AdbStateWaitResult,
    RECOMMENDED_SCREEN_SIZE,
)
from core.automation.simulator_preferences import get_simulator_preferences
from core.automation.simulator_registry import get_simulator_profile, normalize_serial
from core.utils.config_loader import get_config_loader
from core.utils.logger import get_logger
from core.utils.path_manager import PathManager


# ============================================================
# 🏗️ 第二部分：核心类
# ============================================================

class AdbTaskResult(StructuredTaskResult):
    """
    ADB 自动化任务执行结果。
    输入：
        success: 接口是否安全完成。
        status: reserved / ready / unavailable / error。
        message: 用户可见说明。
        detail: 给测试或开发者看的补充信息。
        payload: 结构化结果，后续真实实现继续沿用。
        warnings: 不阻塞任务完成的警告列表。
    输出：
        不可变结果对象，可被 AutomationBridge 转成 GUI 结果。
    使用示例：
        result = get_adb_task_api().check_connection()
    """

class AdbTaskApi:
    """
    ADB 自动化任务 API。
    输入：
        无，内部读取 config/config.json 和 config/simulators/*.json。
    输出：
        结构化预检结果；真实 ADB 执行由 AdbController 负责。
    使用示例：
        api = AdbTaskApi()
        api.capture_screenshot()
    """

    _instance: Optional["AdbTaskApi"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "AdbTaskApi":
        """单例模式：所有 GUI 入口共享一套自动化配置读取逻辑。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化 ADB API，重复初始化时直接返回。"""
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        self.config_loader = get_config_loader()
        self.simulator_preferences = get_simulator_preferences()
        self._controller_factory: Callable[[Dict[str, Any]], AdbController] = AdbController
        self._initialized = True

    def check_connection(
        self,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        strict_status: bool = False,
        simulator_key: Optional[str] = None,
        serial: Optional[str] = None,
        port: Optional[str | int] = None,
    ) -> AdbTaskResult:
        """
        检查 ADB 连接配置。
        输入：
            task_context: 可选任务上下文，用于在安全点响应取消。
            strict_status: True 时顶层 status 使用真实 ADB 状态；False 保留旧 GUI 预检兼容状态。
        输出：
            AdbTaskResult: payload 中包含真实设备检测结果；缺失 ADB 不向 GUI 抛异常。
        使用示例：
            result = api.check_connection()
        """
        if task_context is not None:
            task_context.raise_if_cancelled("ADB 连接检查已取消。")
        simulator = self._get_simulator_context(simulator_key=simulator_key, serial=serial, port=port)
        controller = self._create_controller(simulator)
        if task_context is not None and not strict_status:
            adb_resolution = controller.find_adb()
            payload = {
                "simulator_key": simulator["key"],
                "simulator_name": simulator["name"],
                "selection": simulator["selection"],
                "auto_selected": simulator["auto_selected"],
                "adb_path": adb_resolution.adb_path or str(simulator["adb"].get("path", "")).strip(),
                "adb_path_exists": adb_resolution.available,
                "adb_source": adb_resolution.source,
                "port": simulator["adb"].get("port"),
                "device_serial": simulator["device_serial"] or simulator["default_device_serial"],
                "configured_device_serial": simulator["device_serial"],
                "device_state": None,
                "connection_status": "not_checked",
                "candidates": [],
                "recommended_resolution": list(RECOMMENDED_SCREEN_SIZE),
                "real_command_enabled": False,
                "command": None,
            }
            detail = (
                f"模拟器={payload['simulator_name']}；ADB={payload['adb_path'] or '未配置'}；"
                f"端口={payload['port']}；后台快速预检=启用"
            )
            message = "ADB 连接预检完成：已完成轻量配置检查，真实设备检测可在环境检查中查看。"
            self.logger.info(message)
            return AdbTaskResult(True, "reserved", message, detail, payload, tuple(adb_resolution.warnings))

        target_serial = simulator["device_serial"] or simulator["default_device_serial"] or None
        connection = controller.check_connection(serial=target_serial, task_context=task_context)
        payload = {
            "simulator_key": simulator["key"],
            "simulator_name": simulator["name"],
            "selection": simulator["selection"],
            "auto_selected": simulator["auto_selected"],
            "adb_path": connection.adb_path or str(simulator["adb"].get("path", "")).strip(),
            "adb_path_exists": bool(connection.adb_path),
            "adb_source": connection.adb_source,
            "port": simulator["adb"].get("port"),
            "device_serial": connection.selected_device.serial if connection.selected_device else simulator["device_serial"],
            "configured_device_serial": simulator["device_serial"],
            "device_state": connection.selected_device.state if connection.selected_device else None,
            "connection_status": connection.status,
            "candidates": [device.to_dict() for device in connection.candidates],
            "recommended_resolution": list(RECOMMENDED_SCREEN_SIZE),
            "real_command_enabled": True,
            "command": connection.command_result.to_dict() if connection.command_result else None,
        }
        detail = (
            f"模拟器={payload['simulator_name']}；ADB={payload['adb_path'] or '未配置'}；"
            f"端口={payload['port']}；真实状态={connection.status}"
        )
        message = connection.message if strict_status else "ADB 连接预检完成：已接入真实设备检测，结果已写入 payload。"
        self.logger.info(message)
        return AdbTaskResult(
            connection.success if strict_status else True,
            connection.status if strict_status else "reserved",
            message,
            detail,
            payload,
            tuple(connection.warnings),
        )

    def auto_connect_simulator(
        self,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        include_all_profiles: bool = True,
        max_candidates: Optional[int] = None,
        simulator_key: Optional[str] = None,
        serial: Optional[str] = None,
        port: Optional[str | int] = None,
    ) -> AdbTaskResult:
        """
        自动探测并连接当前配置对应的模拟器 ADB。
        输入：
            task_context: 可选任务上下文，用于在安全点响应取消。
            include_all_profiles: 是否追加其他模拟器端口族兜底。
            max_candidates: 最大尝试数量，避免 UI 长时间等待。
        输出：
            AdbTaskResult: payload 包含连接状态、候选 serial、显示环境和前台应用。
        使用示例：
            result = api.auto_connect_simulator()
        """
        if task_context is not None:
            task_context.raise_if_cancelled("模拟器自动连接任务已取消。")
            task_context.report_progress(18, "正在解析当前模拟器配置。", "")
        simulator = self._get_simulator_context(simulator_key=simulator_key, serial=serial, port=port)
        controller = self._create_controller(simulator)
        target_serial = simulator["device_serial"] or simulator["default_device_serial"] or None
        if task_context is not None:
            task_context.report_progress(32, "正在尝试 ADB 自动连接。", str(target_serial or "自动候选"))
        connected: AdbAutoConnectResult = controller.auto_connect_simulator(
            simulator["key"],
            task_context=task_context,
            include_all_profiles=include_all_profiles,
            serial=target_serial,
            max_candidates=max_candidates,
        )

        payload: Dict[str, Any] = {
            "simulator_key": simulator["key"],
            "simulator_name": simulator["name"],
            "selection": simulator["selection"],
            "auto_selected": simulator["auto_selected"],
            "configured_device_serial": simulator["device_serial"],
            "default_device_serial": simulator["default_device_serial"],
            "port": simulator["adb"].get("port"),
            "real_command_enabled": True,
            **connected.to_payload(),
        }
        detected_profile = next(
            (
                profile
                for profile in connected.simulator_profiles
                if connected.selected_device is not None and profile.serial == connected.selected_device.serial
            ),
            None,
        )
        payload["detected_simulator_type"] = detected_profile.simulator_type if detected_profile is not None else ""
        payload["detected_simulator_confidence"] = detected_profile.confidence if detected_profile is not None else 0.0
        if detected_profile is not None and simulator["auto_selected"]:
            detected_key = detected_profile.simulator_type.split("_or_", 1)[0]
            detected_config = self.config_loader.get_simulator_config(detected_key)
            payload["simulator_key"] = detected_key
            payload["simulator_name"] = (
                detected_config.get("name")
                if isinstance(detected_config, dict) and detected_config.get("name")
                else detected_key
            )
        warnings = list(connected.warnings)
        display_payload: Optional[Dict[str, Any]] = None
        foreground_payload: Optional[Dict[str, Any]] = None

        if connected.success and connected.selected_device is not None:
            device_serial = connected.selected_device.serial
            if task_context is not None:
                task_context.report_progress(70, "连接成功，正在读取模拟器显示环境。", device_serial)
            display_check = controller.check_display_environment(serial=device_serial, task_context=task_context)
            display_payload = display_check.to_dict()
            warnings.extend(display_check.warnings)
            if task_context is not None:
                task_context.report_progress(86, "正在读取当前前台应用。", device_serial)
            foreground = controller.get_foreground_package(serial=device_serial, task_context=task_context)
            foreground_payload = {
                "success": foreground.success,
                "status": foreground.status,
                "message": foreground.message,
                "package_name": foreground.stdout.strip() if foreground.success else "",
                "command": foreground.to_dict(),
            }
            if not foreground.success:
                warnings.append("已连接模拟器，但暂时无法解析当前前台应用包名。")

        payload["display_environment"] = display_payload
        payload["foreground_app"] = foreground_payload
        selected_serial = payload.get("device_serial") or target_serial or "未知设备"
        detail = (
            f"模拟器={payload['simulator_name']}；设备={selected_serial}；"
            f"ADB来源={payload.get('adb_source') or 'missing'}；尝试={len(payload.get('attempted_serials') or [])}"
        )
        message = connected.message
        record_serial = str(payload.get("device_serial") or target_serial or "")
        record_port = self._port_from_serial(record_serial) or str(payload.get("port") or "")
        record_key = str(payload.get("simulator_key") or simulator["key"] or "auto")
        self._persist_connection_preferences(
            controller=controller,
            simulator=simulator,
            record_key=record_key,
            record_serial=record_serial,
            record_port=record_port,
            payload=payload,
            status=connected.status,
            success=connected.success,
            message=message,
        )
        self.logger.info(message)
        return AdbTaskResult(
            connected.success,
            connected.status,
            message,
            detail,
            payload,
            tuple(dict.fromkeys(warnings)),
        )

    def list_packages(
        self,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        include_system: bool = False,
    ) -> AdbTaskResult:
        """
        读取当前模拟器中已安装的应用包列表。
        输入：
            task_context: 可选取消上下文；include_system: 是否包含系统应用。
        输出：
            AdbTaskResult，payload 中含 packages/package_names/source。
        使用示例：
            result = get_adb_task_api().list_packages()
        """
        if task_context is not None:
            task_context.raise_if_cancelled("ADB 应用列表查询已取消。")
        simulator = self._get_simulator_context()
        controller = self._create_controller(simulator)
        package_result = controller.list_packages(
            serial=simulator["device_serial"] or None,
            include_system=include_system,
            task_context=task_context,
        )
        payload = {
            "simulator_key": simulator["key"],
            "simulator_name": simulator["name"],
            **package_result.to_payload(),
        }
        detail = f"模拟器={simulator['name']}；应用数量={len(package_result.packages)}；来源={package_result.source or '无'}"
        self.logger.info(package_result.message)
        return AdbTaskResult(
            package_result.success,
            package_result.status,
            package_result.message,
            detail,
            payload,
            tuple(package_result.warnings),
        )

    def detect_simulators(
        self,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbTaskResult:
        """
        识别所有当前 ADB 设备的模拟器家族。
        输入：
            task_context: 可选取消上下文。
        输出：
            AdbTaskResult，payload 中保留全部候选，不在多设备时擅自选择。
        使用示例：
            result = get_adb_task_api().detect_simulators()
        """
        if task_context is not None:
            task_context.raise_if_cancelled("模拟器识别已取消。")
        simulator = self._get_simulator_context()
        controller = self._create_controller(simulator)
        detected = controller.detect_simulators(task_context=task_context)
        payload = {
            "simulator_key": simulator["key"],
            "simulator_name": simulator["name"],
            **detected.to_payload(),
        }
        detail = f"模拟器候选数={len(detected.simulators)}；ADB来源={detected.adb_source}"
        self.logger.info(detected.message)
        return AdbTaskResult(detected.success, detected.status, detected.message, detail, payload, detected.warnings)

    def run_game_login(
        self,
        scene_probe: Optional[Callable[..., object]] = None,
        state_probe: Optional[Callable[..., object]] = None,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        login_steps: Optional[list[Dict[str, Any]]] = None,
    ) -> AdbTaskResult:
        """
        启动当前游戏并等待 OCR/模板探针确认进入港区。
        输入：
            scene_probe: 可注入的港区判断函数；不传时只验证应用已启动；
            timeout_seconds/max_retries: 等待和重试控制；login_steps: 可选确认弹窗步骤。
        输出：
            AdbTaskResult，保留旧顶层字段并在 payload 中写入登录详情。
        使用示例：
            result = get_adb_task_api().run_game_login(lambda scene: scene.value == "harbor")
        """
        if task_context is not None:
            task_context.raise_if_cancelled("ADB 游戏登录任务已取消。")
        simulator = self._get_simulator_context()
        game_config = self.config_loader.get_game_config()
        package_name = str(game_config.get("package_name", "") or "").strip()
        activity_name = str(game_config.get("activity_name", "") or "").strip() or None
        controller = self._create_controller(simulator)
        login: AdbLoginResult = controller.login_game(
            package_name,
            activity_name=activity_name,
            scene_probe=scene_probe,
            state_probe=state_probe,
            serial=simulator["device_serial"] or None,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            login_steps=login_steps,
            task_context=task_context,
        )
        payload = {
            "simulator_key": simulator["key"],
            "simulator_name": simulator["name"],
            **login.to_payload(),
        }
        detail = f"游戏包={package_name or '未配置'}；尝试={login.attempts}；前台={login.foreground_package or '未知'}"
        self.logger.info(login.message)
        return AdbTaskResult(login.success, login.status, login.message, detail, payload, login.warnings)

    def launch_game(
        self,
        package_name: Optional[str] = None,
        activity_name: Optional[str] = None,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        serial: Optional[str] = None,
    ) -> AdbTaskResult:
        """
        启动游戏但不等待登录完成。
        输入：
            package_name/activity_name: 可覆盖配置中的游戏入口。
        输出：
            AdbTaskResult，payload 中保留底层 ADB 命令详情。
        使用示例：
            result = api.launch_game()
        """
        if task_context is not None:
            task_context.raise_if_cancelled("游戏启动任务已取消。")
        simulator = self._get_simulator_context()
        game_config = self.config_loader.get_game_config()
        package = str(package_name or game_config.get("package_name", "") or "").strip()
        activity = str(activity_name or game_config.get("activity_name", "") or "").strip() or None
        controller = self._create_controller(simulator)
        command = controller.launch_game(
            package,
            activity_name=activity,
            serial=serial or simulator["device_serial"] or None,
            task_context=task_context,
        )
        payload = {
            "simulator_key": simulator["key"],
            "simulator_name": simulator["name"],
            "package_name": package,
            "activity_name": activity,
            "serial": serial or simulator["device_serial"] or None,
            "command": command.to_dict(),
        }
        detail = f"游戏包={package or '未配置'}；Activity={activity or '主入口'}"
        self.logger.info(command.message)
        return AdbTaskResult(command.success, command.status, command.message, detail, payload, tuple(getattr(command, "warnings", ())))

    def wait_for_state(
        self,
        expected_state: RecognitionScene | str,
        state_probe: Callable[..., object],
        task_context: Optional[TaskExecutionContext] = None,
        *,
        timeout_seconds: float = 8.0,
        stable_frames: int = 2,
        skip_first_sample: bool = True,
        screenshot_scene: RecognitionScene | str | None = None,
        serial: Optional[str] = None,
    ) -> AdbTaskResult:
        """
        等待页面或屏幕状态稳定。
        输入：
            expected_state: 目标 scene 或 screen_state。
            state_probe: 注入的状态探针。
        输出：
            AdbTaskResult，payload 中保留截图路径、resolution 和状态信息。
        使用示例：
            result = api.wait_for_state("warehouse_equipment", probe)
        """
        if task_context is not None:
            task_context.raise_if_cancelled("状态等待任务已取消。")
        simulator = self._get_simulator_context()
        controller = self._create_controller(simulator)
        wait_result: AdbStateWaitResult = controller.wait_for_state(
            expected_state,
            state_probe,
            serial=serial or simulator["device_serial"] or None,
            timeout_seconds=timeout_seconds,
            stable_frames=stable_frames,
            skip_first_sample=skip_first_sample,
            screenshot_scene=screenshot_scene,
            task_context=task_context,
        )
        payload = {
            "simulator_key": simulator["key"],
            "simulator_name": simulator["name"],
            **wait_result.to_payload(),
        }
        detail = wait_result.detail or f"期待状态={wait_result.expected_state}；稳定帧={wait_result.stable_frames}"
        self.logger.info(wait_result.message)
        return AdbTaskResult(wait_result.success, wait_result.status, wait_result.message, detail, payload, wait_result.warnings)

    def capture_screenshot(
        self,
        scene: RecognitionScene | str = RecognitionScene.HARBOR,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        real_capture: bool = False,
        screen_state: Optional[str] = None,
        scene_hint: Optional[str] = None,
    ) -> AdbTaskResult:
        """
        预检截图采集工作目录。
        输入：
            scene: 截图所属的稳定游戏场景。
            task_context: 可选任务上下文，用于在安全点响应取消。
            real_capture: True 时执行真实 ADB 截图；False 保持旧 GUI 预检调用兼容。
        输出：
            AdbTaskResult: 真实执行时返回绝对 screenshot_path。
        使用示例：
            result = api.capture_screenshot()
        """
        if task_context is not None:
            task_context.raise_if_cancelled("ADB 截图任务已取消。")
        normalized_scene = RecognitionScene.normalize(scene)
        screenshot_dir = PathManager.get_work_dir() / "automation" / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        simulator = self._get_simulator_context()
        controller = self._create_controller(simulator)

        if real_capture:
            screenshot = controller.capture_screenshot(
                normalized_scene,
                serial=simulator["device_serial"] or None,
                output_dir=screenshot_dir,
                screen_state=screen_state,
                scene_hint=scene_hint,
                task_context=task_context,
            )
            payload = {
                "screenshot_dir": str(screenshot_dir),
                "filename_pattern": "azurlane_{scene}_{timestamp}.png",
                "real_capture_enabled": True,
                **screenshot.to_payload(),
            }
            detail = screenshot.detail or f"截图目录={screenshot_dir}；采集方式={screenshot.method or '未完成'}"
            self.logger.info(screenshot.message)
            return AdbTaskResult(
                screenshot.success,
                screenshot.status,
                screenshot.message,
                detail,
                payload,
                tuple(screenshot.warnings),
            )

        adb_resolution = controller.find_adb()
        payload = {
            "screenshot_dir": str(screenshot_dir),
            "filename_pattern": "azurlane_{timestamp}.png",
            "screenshot_path": None,
            "scene": normalized_scene.value,
            "device_serial": simulator["device_serial"],
            "adb_path": adb_resolution.adb_path or str(simulator["adb"].get("path", "")).strip(),
            "adb_source": adb_resolution.source,
            "adb_path_exists": adb_resolution.available,
            "real_capture_enabled": False,
            "screen_state": screen_state or normalized_scene.value,
            "scene_hint": scene_hint or normalized_scene.value,
        }
        detail = f"截图目录={screenshot_dir}；设备={simulator['device_serial']}；ADB来源={adb_resolution.source}"
        message = "截图采集接口预检完成：真实截图能力已接入，可通过 real_capture=True 执行。"
        self.logger.info(message)
        return AdbTaskResult(True, "reserved", message, detail, payload, tuple(adb_resolution.warnings))

    def run_environment_check(
        self,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        strict_status: bool = False,
    ) -> AdbTaskResult:
        """
        检查自动化和识别相关环境。
        输入：
            task_context: 可选任务上下文，用于在安全点响应取消。
            strict_status: True 时缺少 ADB 返回 unavailable；False 保留旧 GUI 预检兼容状态。
        输出：
            AdbTaskResult: 汇总配置、目录和可选依赖状态。
        使用示例：
            result = api.run_environment_check()
        """
        if task_context is not None:
            task_context.raise_if_cancelled("自动化环境检查已取消。")
        simulator = self._get_simulator_context()
        game_config = self.config_loader.get_game_config()
        work_dir = PathManager.get_work_dir()
        data_dir = PathManager.get_data_dir()
        screenshot_dir = work_dir / "automation" / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        sequence_path = PathManager.get_config_dir() / "automation" / "sequences.json"
        controller = self._create_controller(simulator)
        adb_resolution = controller.find_adb()
        display_check = controller.check_display_environment(serial=simulator["device_serial"] or None, task_context=task_context)
        dependency_status = {
            "opencv_cv2": importlib.util.find_spec("cv2") is not None,
            "paddleocr": importlib.util.find_spec("paddleocr") is not None,
            "pillow": importlib.util.find_spec("PIL") is not None,
            "pyside6": importlib.util.find_spec("PySide6") is not None,
        }
        payload = {
            "simulator_key": simulator["key"],
            "simulator_name": simulator["name"],
            "game_package": game_config.get("package_name", ""),
            "work_dir": str(work_dir),
            "data_dir": str(data_dir),
            "screenshot_dir": str(screenshot_dir),
            "sequence_config_path": str(sequence_path),
            "sequence_config_exists": sequence_path.exists(),
            **adb_resolution.to_dict(),
            "display_environment": display_check.to_dict(),
            "dependencies": dependency_status,
            "real_automation_enabled": adb_resolution.available and display_check.status in {"ready", "warning"},
        }
        warnings = list(adb_resolution.warnings)
        warnings.extend(display_check.warnings)
        if not adb_resolution.available:
            warnings.extend(display_check.suggestions)
        ready_count = sum(1 for available in dependency_status.values() if available)
        detail = (
            f"依赖可用={ready_count}/{len(dependency_status)}；工作目录={work_dir}；"
            f"ADB来源={adb_resolution.source}；显示环境={display_check.status}"
        )
        status = "ready" if adb_resolution.available and display_check.status == "ready" else "unavailable"
        if adb_resolution.available and display_check.status == "warning":
            status = "warning"
        message = "基础环境预检完成：已汇总配置、ADB 和目录状态。"
        self.logger.info(message)
        return AdbTaskResult(
            status == "ready" if strict_status else True,
            status if strict_status else "reserved",
            message,
            detail,
            payload,
            tuple(warnings),
        )

    def run_navigation_sequence(
        self,
        sequence_name: str,
        scene_probe: Callable[..., object],
        state_probe: Optional[Callable[..., object]] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbTaskResult:
        """
        执行 ADB 导航序列。
        输入：
            sequence_name: config/automation/sequences.json 中的序列名。
            scene_probe: 页面到达判断函数，由测试或后续 OCR 整合层注入。
            task_context: 可选任务上下文，用于在安全点响应取消。
        输出：
            AdbTaskResult: 导航状态、尝试次数和 warning 汇总。
        使用示例：
            api.run_navigation_sequence("enter_research", lambda scene: True)
        """
        if task_context is not None:
            task_context.raise_if_cancelled("ADB 导航任务已取消。")
        simulator = self._get_simulator_context()
        controller = self._create_controller(simulator)
        result: NavigationResult = controller.run_sequence(
            sequence_name,
            scene_probe,
            state_probe=state_probe,
            serial=simulator["device_serial"] or None,
            task_context=task_context,
        )
        payload = result.to_payload()
        detail = result.detail or f"序列={sequence_name}；尝试={result.attempts}"
        self.logger.info(result.message)
        return AdbTaskResult(result.success, result.status, result.message, detail, payload, tuple(result.warnings))

    def return_to_harbor(
        self,
        scene_probe: Callable[..., object],
        task_context: Optional[TaskExecutionContext] = None,
        *,
        serial: Optional[str] = None,
    ) -> AdbTaskResult:
        """
        返回港区主页。
        输入：
            scene_probe: 港区识别探针。
        输出：
            AdbTaskResult，payload 中包含目标场景与截图信息。
        使用示例：
            result = api.return_to_harbor(probe)
        """
        if task_context is not None:
            task_context.raise_if_cancelled("返回港区任务已取消。")
        simulator = self._get_simulator_context()
        controller = self._create_controller(simulator)
        result = controller.return_to_harbor(
            scene_probe,
            serial=serial or simulator["device_serial"] or None,
            task_context=task_context,
        )
        payload = {
            "simulator_key": simulator["key"],
            "simulator_name": simulator["name"],
            **result.to_payload(),
        }
        detail = result.detail or f"序列={result.sequence_name}；尝试={result.attempts}"
        self.logger.info(result.message)
        return AdbTaskResult(result.success, result.status, result.message, detail, payload, tuple(result.warnings))

    def enter_warehouse(
        self,
        scene_probe: Callable[..., object],
        task_context: Optional[TaskExecutionContext] = None,
        *,
        serial: Optional[str] = None,
    ) -> AdbTaskResult:
        """
        进入仓库入口页。
        输入：
            scene_probe: 页面识别探针。
        输出：
            AdbTaskResult，payload 中包含截图与状态。
        使用示例：
            result = api.enter_warehouse(probe)
        """
        if task_context is not None:
            task_context.raise_if_cancelled("进入仓库任务已取消。")
        simulator = self._get_simulator_context()
        controller = self._create_controller(simulator)
        result = controller.enter_warehouse(
            scene_probe,
            serial=serial or simulator["device_serial"] or None,
            task_context=task_context,
        )
        payload = {
            "simulator_key": simulator["key"],
            "simulator_name": simulator["name"],
            **result.to_payload(),
        }
        detail = result.detail or f"序列={result.sequence_name}；尝试={result.attempts}"
        self.logger.info(result.message)
        return AdbTaskResult(result.success, result.status, result.message, detail, payload, tuple(result.warnings))

    def select_warehouse_tab(
        self,
        tab: str,
        state_probe: Callable[..., object],
        task_context: Optional[TaskExecutionContext] = None,
        *,
        serial: Optional[str] = None,
    ) -> AdbTaskResult:
        """
        切换仓库标签页。
        输入：
            tab: design / equipment / material。
            state_probe: 支持 screen_state 的状态探针。
        输出：
            AdbTaskResult，payload 中包含目标 screen_state。
        使用示例：
            result = api.select_warehouse_tab("material", probe)
        """
        if task_context is not None:
            task_context.raise_if_cancelled("切换仓库标签任务已取消。")
        simulator = self._get_simulator_context()
        controller = self._create_controller(simulator)
        result = controller.select_warehouse_tab(
            tab,
            state_probe,
            serial=serial or simulator["device_serial"] or None,
            task_context=task_context,
        )
        payload = {
            "simulator_key": simulator["key"],
            "simulator_name": simulator["name"],
            **result.to_payload(),
        }
        detail = result.detail or f"标签={tab}；尝试={result.attempts}"
        self.logger.info(result.message)
        return AdbTaskResult(result.success, result.status, result.message, detail, payload, tuple(result.warnings))

    def close_popup(
        self,
        state_probe: Optional[Callable[..., object]] = None,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        policy: str = "auto",
        serial: Optional[str] = None,
    ) -> AdbTaskResult:
        """
        关闭弹窗或覆盖层。
        输入：
            policy: auto / back / home / double_back。
            state_probe: 可选确认探针。
        输出：
            AdbTaskResult，payload 中保留动作与确认信息。
        使用示例：
            result = api.close_popup(probe)
        """
        if task_context is not None:
            task_context.raise_if_cancelled("关闭弹窗任务已取消。")
        simulator = self._get_simulator_context()
        controller = self._create_controller(simulator)
        result = controller.close_popup(
            policy=policy,
            state_probe=state_probe,
            serial=serial or simulator["device_serial"] or None,
            task_context=task_context,
        )
        payload = {
            "simulator_key": simulator["key"],
            "simulator_name": simulator["name"],
            **result.to_payload(),
        }
        detail = result.detail or f"策略={policy}；尝试={result.attempts}"
        self.logger.info(result.message)
        return AdbTaskResult(result.success, result.status, result.message, detail, payload, tuple(result.warnings))

    def _get_simulator_context(
        self,
        *,
        simulator_key: Optional[str] = None,
        serial: Optional[str] = None,
        port: Optional[str | int] = None,
    ) -> Dict[str, Any]:
        """
        读取当前模拟器上下文。
        输入：
            无。
        输出：
            dict: 当前模拟器 key、名称、ADB 配置和设备串号。
        使用示例：
            context = self._get_simulator_context()
        """
        main_config = self.config_loader.get_main_config()
        current_key = str(main_config.get("current_simulator", "mumu") or "mumu")
        saved_selection = self.simulator_preferences.get_selection() if self.simulator_preferences.path.exists() else {}
        requested_key = simulator_key if simulator_key is not None else saved_selection.get("selection") or current_key
        selection = str(requested_key or current_key).strip() or current_key
        auto_selected = selection.lower() in {"auto", "automatic", "自动选择"}
        config_key = current_key if auto_selected else selection
        simulator_config = self.config_loader.get_simulator_config(config_key)
        if not isinstance(simulator_config, dict) or not simulator_config:
            profile = get_simulator_profile(config_key)
            simulator_config = {
                "name": profile.display_name if profile is not None else config_key,
                "type": config_key,
                "adb": {},
            }
        simulator_config = deepcopy(simulator_config)
        adb_config = dict(simulator_config.get("adb", {}) if isinstance(simulator_config, dict) else {})
        saved_serial = saved_selection.get("serial", "") if simulator_key is None else ""
        saved_port = saved_selection.get("port", "") if simulator_key is None else ""
        explicit_serial = serial if serial is not None else (
            saved_serial or adb_config.get("serial") or adb_config.get("device_serial")
        )
        if port is not None and str(port).strip():
            # 用户明确填写端口时，端口优先于历史 serial，避免连接到旧实例。
            explicit_serial = ""
        requested_port = port if port is not None else (
            self._port_from_serial(explicit_serial) or saved_port or adb_config.get("port", 0)
        )
        normalized_serial = normalize_serial(explicit_serial) if explicit_serial else ""
        safe_port = self._safe_port(requested_port)
        if normalized_serial:
            adb_config["serial"] = normalized_serial
        if safe_port:
            adb_config["port"] = safe_port
        simulator_config["adb"] = adb_config
        return {
            "key": config_key,
            "selection": selection,
            "auto_selected": auto_selected,
            "name": simulator_config.get("name", config_key) if isinstance(simulator_config, dict) else config_key,
            "adb": adb_config,
            "config": simulator_config,
            "device_serial": normalized_serial,
            "default_device_serial": f"127.0.0.1:{safe_port}" if safe_port else "",
        }

    @staticmethod
    def _safe_port(value: object) -> int:
        """把 UI 端口输入转换成合法 TCP 端口。"""
        try:
            port = int(str(value or "").strip())
        except (TypeError, ValueError):
            return 0
        return port if 0 < port < 65536 else 0

    @staticmethod
    def _port_from_serial(serial: object) -> str:
        """从 127.0.0.1:port 形式 serial 提取端口。"""
        match = re.search(r":(\d+)$", str(serial or "").strip())
        return match.group(1) if match else ""

    def _create_controller(self, simulator_context: Dict[str, Any]) -> AdbController:
        """按当前模拟器配置创建 ADB 控制器。"""
        return self._controller_factory(simulator_context.get("config", {}))

    def _persist_connection_preferences(
        self,
        *,
        controller: object,
        simulator: Dict[str, Any],
        record_key: str,
        record_serial: str,
        record_port: str,
        payload: Dict[str, Any],
        status: str,
        success: bool,
        message: str,
    ) -> None:
        """保存连接偏好；单元测试 fake 控制器不会污染正式 config.json。"""
        default_path = self.config_loader.config_dir / "config.json"
        if not isinstance(controller, AdbController) and self.simulator_preferences.path == default_path:
            self.logger.debug("检测到 fake ADB 控制器，跳过正式用户配置写入。")
            return
        self.simulator_preferences.save_selection(
            simulator["selection"],
            serial=simulator["device_serial"],
            port=simulator["adb"].get("port") or "",
            auto_select=bool(simulator["auto_selected"]),
        )
        self.simulator_preferences.record_connection(
            simulator_key=record_key,
            simulator_name=str(payload.get("simulator_name") or simulator["name"]),
            serial=record_serial,
            port=record_port,
            status=status,
            success=success,
            auto_selected=bool(simulator["auto_selected"]),
            message=message,
        )


# ============================================================
# 🌐 第三部分：全局访问函数
# ============================================================

_adb_task_api: Optional[AdbTaskApi] = None


def get_adb_task_api() -> AdbTaskApi:
    """
    获取全局 ADB 任务 API。
    输入：
        无。
    输出：
        AdbTaskApi: 全局共享 API。
    使用示例：
        api = get_adb_task_api()
    """
    global _adb_task_api
    if _adb_task_api is None:
        _adb_task_api = AdbTaskApi()
    return _adb_task_api
