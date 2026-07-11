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
from typing import Any, Callable, Dict, Optional

from core.contracts import RecognitionScene, StructuredTaskResult, TaskExecutionContext
from core.automation.adb_controller import AdbController, NavigationResult, RECOMMENDED_SCREEN_SIZE
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
        self._controller_factory: Callable[[Dict[str, Any]], AdbController] = AdbController
        self._initialized = True

    def check_connection(
        self,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        strict_status: bool = False,
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
        simulator = self._get_simulator_context()
        controller = self._create_controller(simulator)
        if task_context is not None and not strict_status:
            adb_resolution = controller.find_adb()
            payload = {
                "simulator_key": simulator["key"],
                "simulator_name": simulator["name"],
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

        connection = controller.check_connection(serial=simulator["device_serial"] or None, task_context=task_context)
        payload = {
            "simulator_key": simulator["key"],
            "simulator_name": simulator["name"],
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

    def capture_screenshot(
        self,
        scene: RecognitionScene | str = RecognitionScene.HARBOR,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        real_capture: bool = False,
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
            serial=simulator["device_serial"] or None,
            task_context=task_context,
        )
        payload = result.to_payload()
        detail = result.detail or f"序列={sequence_name}；尝试={result.attempts}"
        self.logger.info(result.message)
        return AdbTaskResult(result.success, result.status, result.message, detail, payload, tuple(result.warnings))

    def _get_simulator_context(self) -> Dict[str, Any]:
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
        """按当前模拟器配置创建 ADB 控制器。"""
        return self._controller_factory(simulator_context.get("config", {}))


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
