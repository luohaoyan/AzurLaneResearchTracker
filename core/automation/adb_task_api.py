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
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from core.utils.config_loader import get_config_loader
from core.utils.logger import get_logger
from core.utils.path_manager import PathManager


# ============================================================
# 🏗️ 第二部分：核心类
# ============================================================

@dataclass(frozen=True)
class AdbTaskResult:
    """
    ADB 自动化任务执行结果。
    输入：
        success: 接口是否安全完成。
        status: reserved / ready / unavailable / error。
        message: 用户可见说明。
        detail: 给测试或开发者看的补充信息。
        payload: 结构化结果，后续真实实现继续沿用。
    输出：
        不可变结果对象，可被 AutomationBridge 转成 GUI 结果。
    使用示例：
        result = get_adb_task_api().check_connection()
    """

    success: bool
    status: str
    message: str
    detail: str = ""
    payload: Optional[Dict[str, Any]] = None


class AdbTaskApi:
    """
    ADB 自动化任务 API。
    输入：
        无，内部读取 config/config.json 和 config/simulators/*.json。
    输出：
        结构化预检结果；当前阶段不执行真实 ADB 命令。
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
        self._initialized = True

    def check_connection(self) -> AdbTaskResult:
        """
        检查 ADB 连接配置。
        输入：
            无。
        输出：
            AdbTaskResult: 当前仅校验配置和 adb 路径，不连接真实设备。
        使用示例：
            result = api.check_connection()
        """
        simulator = self._get_simulator_context()
        adb_path = str(simulator["adb"].get("path", "")).strip()
        adb_path_exists = self._adb_path_exists(adb_path)
        payload = {
            "simulator_key": simulator["key"],
            "simulator_name": simulator["name"],
            "adb_path": adb_path,
            "adb_path_exists": adb_path_exists,
            "port": simulator["adb"].get("port"),
            "device_serial": simulator["device_serial"],
            "real_command_enabled": False,
        }
        detail = (
            f"模拟器={payload['simulator_name']}；ADB={adb_path or '未配置'}；"
            f"端口={payload['port']}；路径存在={adb_path_exists}"
        )
        message = "ADB 连接预检完成：已保留真实连接入口，当前阶段不启动模拟器。"
        self.logger.info(message)
        return AdbTaskResult(True, "reserved", message, detail, payload)

    def capture_screenshot(self) -> AdbTaskResult:
        """
        预检截图采集工作目录。
        输入：
            无。
        输出：
            AdbTaskResult: 返回未来截图输出目录和命名规则。
        使用示例：
            result = api.capture_screenshot()
        """
        screenshot_dir = PathManager.get_work_dir() / "automation" / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        simulator = self._get_simulator_context()
        payload = {
            "screenshot_dir": str(screenshot_dir),
            "filename_pattern": "azurlane_{timestamp}.png",
            "device_serial": simulator["device_serial"],
            "real_capture_enabled": False,
        }
        detail = f"截图目录={screenshot_dir}；设备={simulator['device_serial']}；真实截图=未启用"
        message = "截图采集接口预检完成：已准备输出目录，真实 ADB 截图将在 v0.6.0 接入。"
        self.logger.info(message)
        return AdbTaskResult(True, "reserved", message, detail, payload)

    def run_environment_check(self) -> AdbTaskResult:
        """
        检查自动化和识别相关环境。
        输入：
            无。
        输出：
            AdbTaskResult: 汇总配置、目录和可选依赖状态。
        使用示例：
            result = api.run_environment_check()
        """
        simulator = self._get_simulator_context()
        game_config = self.config_loader.get_game_config()
        work_dir = PathManager.get_work_dir()
        data_dir = PathManager.get_data_dir()
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
            "dependencies": dependency_status,
            "real_automation_enabled": False,
        }
        ready_count = sum(1 for available in dependency_status.values() if available)
        detail = f"依赖可用={ready_count}/{len(dependency_status)}；工作目录={work_dir}；数据目录={data_dir}"
        message = "基础环境预检完成：配置与目录可读取，缺失依赖会在真实 OCR 接入前继续补齐。"
        self.logger.info(message)
        return AdbTaskResult(True, "reserved", message, detail, payload)

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
        return {
            "key": simulator_key,
            "name": simulator_config.get("name", simulator_key) if isinstance(simulator_config, dict) else simulator_key,
            "adb": adb_config,
            "device_serial": f"127.0.0.1:{port}" if port else "未配置",
        }

    @staticmethod
    def _adb_path_exists(adb_path: str) -> bool:
        """判断 ADB 路径或命令是否存在。"""
        if not adb_path:
            return False
        return Path(adb_path).exists() or shutil.which(adb_path) is not None


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
