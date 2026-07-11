#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║             🤖 ADB 控制器 (adb_controller.py)               ║
║                                                              ║
║  【一句话解释】封装真实 ADB 路径发现、设备检测、截图和输入。  ║
║  【类比理解】它像自动化层的驾驶台，先确认设备，再执行动作。   ║
║  【数据流说明】配置 → ADB 命令 → 截图/点击/导航结构化结果。   ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import inspect
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Sequence, Tuple

from core.contracts import RecognitionScene, ScreenshotArtifact, TaskExecutionContext
from core.utils.logger import get_logger
from core.utils.path_manager import PathManager


# ============================================================
# 🧱 第二部分：基础数据结构
# ============================================================

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
DEFAULT_COMMAND_TIMEOUT_SECONDS = 10.0
DEFAULT_SCREEN_SIZE = (1280, 720)
DEFAULT_MAX_SWIPE_DURATION_MS = 60000
ADB_TEMP_SCREENSHOT = "/sdcard/azurlane_tracker_screenshot.png"
RECOMMENDED_SCREEN_SIZE = (1280, 720)
RECOMMENDED_ORIENTATION_MODE = "tablet"

COMMON_ADB_PATHS: Tuple[str, ...] = (
    "C:/LDPlayer/LDPlayer9/adb.exe",
    "C:/LDPlayer/LDPlayer4.0/adb.exe",
    "D:/LDPlayer/LDPlayer9/adb.exe",
    "D:/LDPlayer/LDPlayer4.0/adb.exe",
    "C:/Program Files/LDPlayer/LDPlayer9/adb.exe",
    "D:/MuMuPlayer-12.0/shell/adb.exe",
    "C:/Program Files/Netease/MuMuPlayer-12.0/shell/adb.exe",
    "C:/Program Files/Netease/MuMuPlayerGlobal-12.0/shell/adb.exe",
)


@dataclass(frozen=True)
class AdbPathResolution:
    """
    ADB 可执行文件解析结果。
    输入：
        adb_path/source/searched_paths/warnings。
    输出：
        上层可判断 ADB 是否可用以及来自哪个来源。
    使用示例：
        resolution = controller.find_adb()
    """

    adb_path: Optional[str]
    source: str
    searched_paths: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        """返回是否找到可执行的 ADB。"""
        return bool(self.adb_path)

    def to_dict(self) -> Dict[str, Any]:
        """转换为 API payload 可直接使用的字典。"""
        return {
            "adb_path": self.adb_path,
            "adb_source": self.source,
            "adb_path_exists": self.available,
            "searched_paths": list(self.searched_paths),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AdbCommandResult:
    """
    单条 ADB 命令执行结果。
    输入：
        success/status/message/stdout/stderr/returncode。
    输出：
        不向 GUI 抛 subprocess 异常的统一结果。
    使用示例：
        result = controller.run_adb(["devices", "-l"])
    """

    success: bool
    status: str
    message: str
    stdout: str = ""
    stderr: str = ""
    stdout_bytes: bytes = b""
    returncode: Optional[int] = None
    command: Tuple[str, ...] = ()
    timed_out: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """转换为可序列化字典，避免泄露 bytes 到 GUI 层。"""
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "command": list(self.command),
            "timed_out": self.timed_out,
        }


@dataclass(frozen=True)
class AdbDevice:
    """
    adb devices -l 的单台设备记录。
    输入：
        serial/state/detail/properties。
    输出：
        可区分 device/offline/unauthorized 的候选设备。
    使用示例：
        device = AdbDevice("127.0.0.1:7555", "device")
    """

    serial: str
    state: str
    detail: str = ""
    properties: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为 payload 中的候选设备字典。"""
        return {
            "serial": self.serial,
            "state": self.state,
            "detail": self.detail,
            "properties": dict(self.properties),
        }


@dataclass(frozen=True)
class AdbDeviceListResult:
    """
    设备列表查询结果。
    输入：
        devices 和执行命令的上下文。
    输出：
        上层可据此选择设备或返回错误。
    使用示例：
        result = controller.list_devices()
    """

    success: bool
    status: str
    message: str
    devices: Tuple[AdbDevice, ...] = ()
    adb_path: Optional[str] = None
    adb_source: str = "missing"
    command_result: Optional[AdbCommandResult] = None
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AdbConnectionResult:
    """
    ADB 连接选择结果。
    输入：
        设备列表和可选 serial。
    输出：
        明确表示 ready/offline/unauthorized/multiple_devices/unavailable。
    使用示例：
        result = controller.check_connection(serial="127.0.0.1:7555")
    """

    success: bool
    status: str
    message: str
    selected_device: Optional[AdbDevice] = None
    candidates: Tuple[AdbDevice, ...] = ()
    adb_path: Optional[str] = None
    adb_source: str = "missing"
    warnings: Tuple[str, ...] = ()
    command_result: Optional[AdbCommandResult] = None

    def to_payload(self) -> Dict[str, Any]:
        """转换为 adb_task_api 的结构化 payload。"""
        return {
            "adb_path": self.adb_path,
            "adb_source": self.adb_source,
            "device_serial": self.selected_device.serial if self.selected_device else None,
            "device_state": self.selected_device.state if self.selected_device else None,
            "candidates": [device.to_dict() for device in self.candidates],
            "connection_status": self.status,
            "command": self.command_result.to_dict() if self.command_result else None,
        }


@dataclass(frozen=True)
class AdbDisplayCheckResult:
    """
    模拟器截图环境检查结果。
    输入：
        分辨率、密度、平板模式和用户提示。
    输出：
        OCR 前可展示的推荐环境状态。
    使用示例：
        result = controller.check_display_environment()
    """

    success: bool
    status: str
    message: str
    resolution: Optional[Tuple[int, int]] = None
    density: Optional[int] = None
    characteristics: str = ""
    recommended_resolution: Tuple[int, int] = RECOMMENDED_SCREEN_SIZE
    required_mode: str = RECOMMENDED_ORIENTATION_MODE
    warnings: Tuple[str, ...] = ()
    suggestions: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """转换为环境检查 payload。"""
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "resolution": list(self.resolution) if self.resolution else None,
            "density": self.density,
            "characteristics": self.characteristics,
            "recommended_resolution": list(self.recommended_resolution),
            "required_mode": self.required_mode,
            "warnings": list(self.warnings),
            "suggestions": list(self.suggestions),
        }


@dataclass(frozen=True)
class AdbScreenshotResult:
    """
    截图采集结果。
    输入：
        ScreenshotArtifact、采集方式和警告。
    输出：
        screenshot_path 始终是绝对路径，失败时为 None。
    使用示例：
        result = controller.capture_screenshot(RecognitionScene.HARBOR)
    """

    success: bool
    status: str
    message: str
    artifact: Optional[ScreenshotArtifact] = None
    method: str = ""
    adb_path: Optional[str] = None
    adb_source: str = "missing"
    warnings: Tuple[str, ...] = ()
    detail: str = ""

    def to_payload(self) -> Dict[str, Any]:
        """转换为 API payload。"""
        artifact_payload = self.artifact.to_dict() if self.artifact else {}
        return {
            "screenshot_path": artifact_payload.get("screenshot_path"),
            "scene": artifact_payload.get("scene"),
            "device_serial": artifact_payload.get("device_serial"),
            "capture_method": self.method,
            "adb_path": self.adb_path,
            "adb_source": self.adb_source,
        }


@dataclass(frozen=True)
class NavigationResult:
    """
    导航序列执行结果。
    输入：
        sequence_name/target_scene/warnings。
    输出：
        表示导航是否经 scene_probe 到达目标页面。
    使用示例：
        result = controller.run_sequence("enter_research", scene_probe)
    """

    success: bool
    status: str
    message: str
    sequence_name: str
    target_scene: Optional[RecognitionScene] = None
    attempts: int = 0
    warnings: Tuple[str, ...] = ()
    detail: str = ""

    def to_payload(self) -> Dict[str, Any]:
        """转换为结构化 payload。"""
        return {
            "sequence_name": self.sequence_name,
            "target_scene": self.target_scene.value if self.target_scene else None,
            "attempts": self.attempts,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AdbOperationStepResult:
    """
    连续 ADB 操作中的单步结果。
    输入：
        index/action/success/status/message/payload。
    输出：
        可定位失败步骤的结构化记录。
    使用示例：
        step = result.steps[0]
    """

    index: int
    action: str
    success: bool
    status: str
    message: str
    payload: Dict[str, Any] = field(default_factory=dict)
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """转换为可序列化字典。"""
        return {
            "index": self.index,
            "action": self.action,
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "payload": dict(self.payload),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AdbOperationSequenceResult:
    """
    连续 ADB 操作结果。
    输入：
        steps/failure_index/warnings。
    输出：
        OCR 自动化流水线可直接判断整体是否成功。
    使用示例：
        result = controller.run_operations([...])
    """

    success: bool
    status: str
    message: str
    steps: Tuple[AdbOperationStepResult, ...] = ()
    failure_index: Optional[int] = None
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """转换为 API 或日志可用的基础字典。"""
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "steps": [step.to_dict() for step in self.steps],
            "failure_index": self.failure_index,
            "warnings": list(self.warnings),
        }


# ============================================================
# 🏗️ 第三部分：ADB 控制器
# ============================================================

class AdbController:
    """
    真实 ADB 自动化控制器。
    输入：
        simulator_config: 模拟器 JSON 配置。
        runner: 可注入 subprocess.run 替身，便于单元测试。
    输出：
        设备、截图、输入、导航的结构化结果。
    使用示例：
        controller = AdbController(simulator_config)
        controller.tap(100, 200)
    """

    def __init__(
        self,
        simulator_config: Optional[Dict[str, Any]] = None,
        *,
        runner: Optional[Callable[..., subprocess.CompletedProcess[Any]]] = None,
        path_exists: Optional[Callable[[str], bool]] = None,
        which: Optional[Callable[[str], Optional[str]]] = None,
        sleeper: Optional[Callable[[float], object]] = None,
        time_provider: Optional[Callable[[], float]] = None,
    ) -> None:
        """初始化控制器，测试可注入 runner/路径探测/时间函数。"""
        self.simulator_config = simulator_config or {}
        self.adb_config = self.simulator_config.get("adb", {}) if isinstance(self.simulator_config, dict) else {}
        self.screen_config = self.simulator_config.get("screen", {}) if isinstance(self.simulator_config, dict) else {}
        self.performance_config = (
            self.simulator_config.get("performance", {}) if isinstance(self.simulator_config, dict) else {}
        )
        self.runner = runner or subprocess.run
        self.path_exists = path_exists or (lambda item: Path(item).exists())
        self.which = which or shutil.which
        self.sleeper = sleeper or time.sleep
        self.time_provider = time_provider or time.monotonic
        self.logger = get_logger()

    @property
    def configured_serial(self) -> Optional[str]:
        """从配置中读取设备 serial；未显式配置时不擅自推导设备。"""
        explicit_serial = self.adb_config.get("serial") or self.adb_config.get("device_serial")
        if explicit_serial:
            return str(explicit_serial)
        return None

    @property
    def command_timeout(self) -> float:
        """读取统一命令超时，缺省 10 秒。"""
        return float(self.adb_config.get("connect_timeout", DEFAULT_COMMAND_TIMEOUT_SECONDS) or DEFAULT_COMMAND_TIMEOUT_SECONDS)

    @property
    def base_resolution(self) -> Tuple[int, int]:
        """读取坐标基准分辨率，未配置时默认 1920x1080。"""
        base = self.adb_config.get("base_resolution", {}) if isinstance(self.adb_config, dict) else {}
        width = int(base.get("width", DEFAULT_SCREEN_SIZE[0]) or DEFAULT_SCREEN_SIZE[0])
        height = int(base.get("height", DEFAULT_SCREEN_SIZE[1]) or DEFAULT_SCREEN_SIZE[1])
        return width, height

    @property
    def screen_size(self) -> Tuple[int, int]:
        """读取目标屏幕分辨率，未配置时默认 1920x1080。"""
        width = int(self.screen_config.get("width", DEFAULT_SCREEN_SIZE[0]) or DEFAULT_SCREEN_SIZE[0])
        height = int(self.screen_config.get("height", DEFAULT_SCREEN_SIZE[1]) or DEFAULT_SCREEN_SIZE[1])
        return width, height

    def find_adb(self) -> AdbPathResolution:
        """
        查找 ADB 可执行文件。
        输入：
            无。
        输出：
            优先有效显式配置，然后 PATH，最后雷电/MuMu 常见目录。
        使用示例：
            resolution = controller.find_adb()
        """
        searched: list[str] = []
        warnings: list[str] = []
        explicit_path = str(self.adb_config.get("path", "") or "").strip()

        if explicit_path:
            searched.append(explicit_path)
            explicit_resolved = self._resolve_existing_adb(explicit_path)
            if explicit_resolved:
                return AdbPathResolution(explicit_resolved, "config", tuple(searched), tuple(warnings))
            warnings.append(f"显式 ADB 路径不可用: {explicit_path}")

        path_adb = self.which("adb")
        searched.append("PATH:adb")
        if path_adb:
            return AdbPathResolution(str(Path(path_adb)), "path", tuple(searched), tuple(warnings))

        common_paths = self._common_adb_paths()
        for candidate in common_paths:
            searched.append(candidate)
            resolved = self._resolve_existing_adb(candidate)
            if resolved:
                return AdbPathResolution(resolved, "common", tuple(searched), tuple(warnings))

        return AdbPathResolution(None, "missing", tuple(searched), tuple(warnings))

    def run_adb(
        self,
        args: Sequence[object],
        *,
        serial: Optional[str] = None,
        timeout: Optional[float] = None,
        binary: bool = False,
        adb_path: Optional[str] = None,
    ) -> AdbCommandResult:
        """
        执行 ADB 命令。
        输入：
            args: adb 后续参数；serial: 可选设备串号；binary: 是否保留 stdout bytes。
        输出：
            超时、非零退出码和缺失 ADB 均转为 AdbCommandResult。
        使用示例：
            result = controller.run_adb(["devices", "-l"])
        """
        resolution = self.find_adb() if adb_path is None else AdbPathResolution(adb_path, "provided")
        if not resolution.adb_path:
            return AdbCommandResult(False, "unavailable", "未找到可用 ADB。")

        command = [resolution.adb_path]
        if serial:
            command.extend(["-s", serial])
        command.extend(str(item) for item in args)

        run_kwargs: Dict[str, Any] = {
            "capture_output": True,
            "timeout": timeout or self.command_timeout,
            "shell": False,
        }
        if not binary:
            run_kwargs.update({"text": True, "encoding": "utf-8", "errors": "replace"})

        try:
            completed = self.runner(command, **run_kwargs)
        except subprocess.TimeoutExpired as exc:
            stderr = self._decode_output(exc.stderr)
            stdout = self._decode_output(exc.stdout)
            return AdbCommandResult(
                False,
                "timeout",
                "ADB 命令执行超时。",
                stdout=stdout,
                stderr=stderr,
                command=tuple(command),
                timed_out=True,
            )
        except FileNotFoundError as exc:
            return AdbCommandResult(
                False,
                "unavailable",
                f"ADB 可执行文件不可用: {exc}",
                command=tuple(command),
            )
        except OSError as exc:
            return AdbCommandResult(False, "error", f"ADB 命令启动失败: {exc}", command=tuple(command))

        stdout_bytes = completed.stdout if isinstance(completed.stdout, bytes) else b""
        stdout_text = self._decode_output(completed.stdout)
        stderr_text = self._decode_output(completed.stderr)
        returncode = int(completed.returncode)
        if returncode != 0:
            status = self._classify_adb_error(stderr_text or stdout_text)
            return AdbCommandResult(
                False,
                status,
                f"ADB 命令失败，退出码 {returncode}。",
                stdout=stdout_text,
                stderr=stderr_text,
                stdout_bytes=stdout_bytes,
                returncode=returncode,
                command=tuple(command),
            )

        return AdbCommandResult(
            True,
            "ok",
            "ADB 命令执行成功。",
            stdout=stdout_text,
            stderr=stderr_text,
            stdout_bytes=stdout_bytes,
            returncode=returncode,
            command=tuple(command),
        )

    @staticmethod
    def parse_devices(output: str) -> Tuple[AdbDevice, ...]:
        """
        解析 adb devices -l 输出。
        输入：
            adb devices -l 的 stdout。
        输出：
            保留 serial/state/detail/properties 的设备列表。
        使用示例：
            devices = AdbController.parse_devices(stdout)
        """
        devices: list[AdbDevice] = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("List of devices") or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial, state = parts[0], parts[1]
            properties: Dict[str, str] = {}
            for item in parts[2:]:
                if ":" in item:
                    key, value = item.split(":", 1)
                    properties[key] = value
            devices.append(AdbDevice(serial=serial, state=state, detail=" ".join(parts[2:]), properties=properties))
        return tuple(devices)

    def list_devices(self, task_context: Optional[TaskExecutionContext] = None) -> AdbDeviceListResult:
        """
        查询 ADB 设备列表。
        输入：
            task_context: 可选取消上下文。
        输出：
            区分缺少 ADB、命令失败和正常设备列表。
        使用示例：
            result = controller.list_devices()
        """
        self._raise_if_cancelled(task_context, "ADB 设备列表查询已取消。")
        resolution = self.find_adb()
        if not resolution.adb_path:
            return AdbDeviceListResult(
                False,
                "unavailable",
                "未找到可用 ADB，无法查询设备。",
                adb_source=resolution.source,
                warnings=resolution.warnings,
            )

        command_result = self.run_adb(["devices", "-l"], adb_path=resolution.adb_path)
        if not command_result.success:
            return AdbDeviceListResult(
                False,
                command_result.status,
                command_result.message,
                adb_path=resolution.adb_path,
                adb_source=resolution.source,
                command_result=command_result,
                warnings=resolution.warnings,
            )
        devices = self.parse_devices(command_result.stdout)
        return AdbDeviceListResult(
            True,
            "ok",
            f"发现 {len(devices)} 台 ADB 设备。",
            devices=devices,
            adb_path=resolution.adb_path,
            adb_source=resolution.source,
            command_result=command_result,
            warnings=resolution.warnings,
        )

    def check_connection(
        self,
        serial: Optional[str] = None,
        task_context: Optional[TaskExecutionContext] = None,
        *,
        reconnect: bool = False,
    ) -> AdbConnectionResult:
        """
        检查并选择 ADB 设备。
        输入：
            serial: 指定设备；未指定且多设备时返回候选列表。
        输出：
            ready/offline/unauthorized/multiple_devices/unavailable/error。
        使用示例：
            result = controller.check_connection()
        """
        self._raise_if_cancelled(task_context, "ADB 连接检查已取消。")
        target_serial = serial or self.configured_serial
        device_list = self.list_devices(task_context)

        if reconnect and target_serial and not device_list.devices:
            self.reconnect_device(target_serial)
            device_list = self.list_devices(task_context)

        if not device_list.success:
            return AdbConnectionResult(
                False,
                device_list.status,
                device_list.message,
                candidates=device_list.devices,
                adb_path=device_list.adb_path,
                adb_source=device_list.adb_source,
                warnings=device_list.warnings,
                command_result=device_list.command_result,
            )

        devices = device_list.devices
        selected = self._select_device(devices, target_serial)
        return AdbConnectionResult(
            selected["success"],
            selected["status"],
            selected["message"],
            selected_device=selected.get("device"),
            candidates=devices,
            adb_path=device_list.adb_path,
            adb_source=device_list.adb_source,
            warnings=device_list.warnings,
            command_result=device_list.command_result,
        )

    def check_display_environment(
        self,
        serial: Optional[str] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbDisplayCheckResult:
        """
        检查模拟器截图环境。
        输入：
            serial: 可选设备串号；未指定时沿用连接选择逻辑。
            task_context: 可选取消上下文。
        输出：
            推荐 1280x720 与平板模式检查结果，ADB 不可用时返回用户提示。
        使用示例：
            result = controller.check_display_environment()
        """
        self._raise_if_cancelled(task_context, "ADB 显示环境检查已取消。")
        connection = self.check_connection(serial=serial, task_context=task_context)
        simulator_type = str(self.simulator_config.get("type", "") or "").lower()
        suggestions = list(self._adb_setup_suggestions(simulator_type))
        if not connection.success or connection.selected_device is None:
            warnings = list(connection.warnings)
            warnings.append(connection.message)
            return AdbDisplayCheckResult(
                False,
                connection.status,
                "无法读取模拟器显示环境，请先确认 ADB 可用。",
                warnings=tuple(warnings),
                suggestions=tuple(suggestions),
            )

        device_serial = connection.selected_device.serial
        size_result = self.run_adb(
            ["shell", "wm", "size"],
            serial=device_serial,
            adb_path=connection.adb_path,
            timeout=self.command_timeout,
        )
        density_result = self.run_adb(
            ["shell", "wm", "density"],
            serial=device_serial,
            adb_path=connection.adb_path,
            timeout=self.command_timeout,
        )
        characteristics_result = self.run_adb(
            ["shell", "getprop", "ro.build.characteristics"],
            serial=device_serial,
            adb_path=connection.adb_path,
            timeout=self.command_timeout,
        )

        resolution = self.parse_wm_size(size_result.stdout) if size_result.success else None
        density = self.parse_wm_density(density_result.stdout) if density_result.success else None
        characteristics = characteristics_result.stdout.strip() if characteristics_result.success else ""
        warnings: list[str] = []
        if resolution != RECOMMENDED_SCREEN_SIZE:
            warnings.append("建议将模拟器分辨率设置为 1280x720，避免 OCR ROI 和点击坐标偏移。")
        if simulator_type == "mumu" and RECOMMENDED_ORIENTATION_MODE not in characteristics.lower():
            warnings.append("MuMu 模拟器建议切换为平板模式。")
        if not size_result.success:
            warnings.append("无法通过 ADB 读取分辨率，请确认模拟器已开启 ADB 调试开关。")
        if not characteristics_result.success:
            warnings.append("无法读取模拟器模式，后续 OCR 可能需要人工确认。")

        success = not warnings
        status = "ready" if success else "warning"
        message = "模拟器显示环境符合 OCR 推荐设置。" if success else "模拟器显示环境需要调整。"
        return AdbDisplayCheckResult(
            success,
            status,
            message,
            resolution=resolution,
            density=density,
            characteristics=characteristics,
            warnings=tuple(warnings),
            suggestions=tuple(suggestions),
        )

    def reconnect_device(self, serial: str) -> AdbCommandResult:
        """
        通过 adb connect 尝试重连 TCP 设备。
        输入：
            serial: 形如 127.0.0.1:7555 的串号。
        输出：
            ADB connect 命令结果；非 TCP serial 直接返回 error。
        使用示例：
            controller.reconnect_device("127.0.0.1:7555")
        """
        if ":" not in serial:
            return AdbCommandResult(False, "error", f"非 TCP 设备不支持 adb connect: {serial}")
        return self.run_adb(["connect", serial], timeout=self.command_timeout)

    def capture_screenshot(
        self,
        scene: RecognitionScene | str = RecognitionScene.HARBOR,
        *,
        serial: Optional[str] = None,
        output_dir: Optional[Path] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbScreenshotResult:
        """
        采集截图并原子保存 PNG。
        输入：
            scene: 截图场景；serial: 可选设备串号；output_dir: 可选输出目录。
        输出：
            成功时 screenshot_path 为绝对路径，优先 exec-out，失败后 pull 回退。
        使用示例：
            result = controller.capture_screenshot(RecognitionScene.RESEARCH)
        """
        self._raise_if_cancelled(task_context, "ADB 截图任务已取消。")
        normalized_scene = RecognitionScene.normalize(scene)
        screenshot_dir = output_dir or (PathManager.get_work_dir() / "automation" / "screenshots")
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        connection = self.check_connection(serial=serial, task_context=task_context)
        if not connection.success or connection.selected_device is None:
            return AdbScreenshotResult(
                False,
                connection.status,
                connection.message,
                adb_path=connection.adb_path,
                adb_source=connection.adb_source,
                warnings=connection.warnings,
                detail="设备未 ready，截图未执行。",
            )

        warnings = list(connection.warnings)
        device_serial = connection.selected_device.serial
        final_path = self._build_screenshot_path(screenshot_dir, normalized_scene)
        reconnect_enabled = bool(self.adb_config.get("reconnect_on_failure", True))

        for attempt in range(2):
            self._raise_if_cancelled(task_context, "ADB 截图任务已取消。")
            exec_result = self.run_adb(
                ["exec-out", "screencap", "-p"],
                serial=device_serial,
                binary=True,
                timeout=self.command_timeout,
                adb_path=connection.adb_path,
            )
            if exec_result.success and self._looks_like_png(exec_result.stdout_bytes):
                self._atomic_write_bytes(final_path, exec_result.stdout_bytes)
                artifact = ScreenshotArtifact(str(final_path.resolve()), normalized_scene, device_serial)
                return AdbScreenshotResult(
                    True,
                    "ready",
                    "ADB 截图完成。",
                    artifact=artifact,
                    method="exec-out",
                    adb_path=connection.adb_path,
                    adb_source=connection.adb_source,
                    warnings=tuple(warnings),
                )
            warnings.append(f"exec-out 截图失败: {exec_result.status}")

            pull_result = self._capture_via_pull(
                final_path,
                device_serial,
                connection.adb_path,
                task_context,
            )
            if pull_result.success:
                artifact = ScreenshotArtifact(str(final_path.resolve()), normalized_scene, device_serial)
                return AdbScreenshotResult(
                    True,
                    "ready",
                    "ADB 截图完成。",
                    artifact=artifact,
                    method="pull",
                    adb_path=connection.adb_path,
                    adb_source=connection.adb_source,
                    warnings=tuple(warnings),
                )
            warnings.append(f"pull 截图失败: {pull_result.status}")

            if attempt == 0 and reconnect_enabled:
                reconnect_result = self.reconnect_device(device_serial)
                warnings.append(f"ADB 重连结果: {reconnect_result.status}")

        return AdbScreenshotResult(
            False,
            "error",
            "ADB 截图失败，exec-out 与 pull 回退均未成功。",
            adb_path=connection.adb_path,
            adb_source=connection.adb_source,
            warnings=tuple(warnings),
            detail="已重试一次。",
        )

    def scale_point(
        self,
        x: int | float,
        y: int | float,
        *,
        base_resolution: Optional[Tuple[int, int]] = None,
        screen_size: Optional[Tuple[int, int]] = None,
    ) -> Tuple[int, int]:
        """
        按基准分辨率缩放坐标。
        输入：
            原始 x/y，基准分辨率和目标分辨率。
        输出：
            缩放后的整数坐标；越界时抛 ValueError。
        使用示例：
            x, y = controller.scale_point(960, 540)
        """
        base_width, base_height = base_resolution or self.base_resolution
        screen_width, screen_height = screen_size or self.screen_size
        if base_width <= 0 or base_height <= 0 or screen_width <= 0 or screen_height <= 0:
            raise ValueError("分辨率必须为正整数。")
        scaled_x = int(round(float(x) * screen_width / base_width))
        scaled_y = int(round(float(y) * screen_height / base_height))
        if not 0 <= scaled_x < screen_width or not 0 <= scaled_y < screen_height:
            raise ValueError(f"坐标越界: ({scaled_x}, {scaled_y}) 不在 {screen_width}x{screen_height} 内。")
        return scaled_x, scaled_y

    def tap(
        self,
        x: int | float,
        y: int | float,
        *,
        serial: Optional[str] = None,
        base_resolution: Optional[Tuple[int, int]] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbCommandResult:
        """
        执行 tap 输入。
        输入：
            x/y 为基准分辨率坐标。
        输出：
            ADB input tap 命令结果；坐标越界返回 invalid_coordinate。
        使用示例：
            controller.tap(500, 600)
        """
        self._raise_if_cancelled(task_context, "ADB 点击任务已取消。")
        try:
            scaled_x, scaled_y = self.scale_point(x, y, base_resolution=base_resolution)
        except ValueError as exc:
            return AdbCommandResult(False, "invalid_coordinate", str(exc))
        return self.run_adb(
            ["shell", "input", "tap", scaled_x, scaled_y],
            serial=serial or self.configured_serial,
            timeout=self.command_timeout,
        )

    def swipe(
        self,
        start_x: int | float,
        start_y: int | float,
        end_x: int | float,
        end_y: int | float,
        duration_ms: int = 300,
        *,
        serial: Optional[str] = None,
        base_resolution: Optional[Tuple[int, int]] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbCommandResult:
        """
        执行 swipe 输入。
        输入：
            起止坐标和毫秒 duration。
        输出：
            ADB input swipe 命令结果；越界或 duration 非法返回错误。
        使用示例：
            controller.swipe(1000, 800, 1000, 200, 500)
        """
        self._raise_if_cancelled(task_context, "ADB 滑动任务已取消。")
        if not 0 <= int(duration_ms) <= DEFAULT_MAX_SWIPE_DURATION_MS:
            return AdbCommandResult(False, "invalid_duration", "swipe duration 必须位于 0 到 60000 毫秒。")
        try:
            scaled_start = self.scale_point(start_x, start_y, base_resolution=base_resolution)
            scaled_end = self.scale_point(end_x, end_y, base_resolution=base_resolution)
        except ValueError as exc:
            return AdbCommandResult(False, "invalid_coordinate", str(exc))
        return self.run_adb(
            ["shell", "input", "swipe", scaled_start[0], scaled_start[1], scaled_end[0], scaled_end[1], int(duration_ms)],
            serial=serial or self.configured_serial,
            timeout=self.command_timeout,
        )

    def long_press(
        self,
        x: int | float,
        y: int | float,
        duration_ms: int = 800,
        *,
        serial: Optional[str] = None,
        base_resolution: Optional[Tuple[int, int]] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbCommandResult:
        """
        执行长按输入。
        输入：
            x/y 为基准分辨率坐标；duration_ms 为长按时长。
        输出：
            ADB input swipe 同点位命令结果。
        使用示例：
            controller.long_press(640, 360, 1000)
        """
        self._raise_if_cancelled(task_context, "ADB 长按任务已取消。")
        return self.swipe(
            x,
            y,
            x,
            y,
            duration_ms,
            serial=serial,
            base_resolution=base_resolution,
            task_context=task_context,
        )

    def double_tap(
        self,
        x: int | float,
        y: int | float,
        *,
        interval_seconds: float = 0.08,
        serial: Optional[str] = None,
        base_resolution: Optional[Tuple[int, int]] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbCommandResult:
        """
        执行双击输入。
        输入：
            x/y 为基准分辨率坐标；interval_seconds 为两次点击间隔。
        输出：
            任一点击失败时返回失败结果。
        使用示例：
            controller.double_tap(640, 360)
        """
        self._raise_if_cancelled(task_context, "ADB 双击任务已取消。")
        first = self.tap(x, y, serial=serial, base_resolution=base_resolution, task_context=task_context)
        if not first.success:
            return first
        self._sleep_with_cancel(max(0.0, float(interval_seconds)), task_context)
        return self.tap(x, y, serial=serial, base_resolution=base_resolution, task_context=task_context)

    def drag(
        self,
        start_x: int | float,
        start_y: int | float,
        end_x: int | float,
        end_y: int | float,
        duration_ms: int = 800,
        *,
        serial: Optional[str] = None,
        base_resolution: Optional[Tuple[int, int]] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbCommandResult:
        """
        执行拖拽输入。
        输入：
            起止坐标和较长 duration。
        输出：
            ADB input swipe 命令结果。
        使用示例：
            controller.drag(200, 500, 900, 500, 1200)
        """
        self._raise_if_cancelled(task_context, "ADB 拖拽任务已取消。")
        return self.swipe(
            start_x,
            start_y,
            end_x,
            end_y,
            duration_ms,
            serial=serial,
            base_resolution=base_resolution,
            task_context=task_context,
        )

    def input_text(
        self,
        text: str,
        *,
        serial: Optional[str] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbCommandResult:
        """
        输入文本。
        输入：
            text: 适合 ADB input text 的短文本；空格会转义为 %s。
        输出：
            ADB input text 命令结果。
        使用示例：
            controller.input_text("Azur Lane")
        """
        self._raise_if_cancelled(task_context, "ADB 文本输入任务已取消。")
        encoded_text = self._encode_input_text(text)
        if not encoded_text:
            return AdbCommandResult(False, "invalid_text", "输入文本不能为空。")
        return self.run_adb(
            ["shell", "input", "text", encoded_text],
            serial=serial or self.configured_serial,
            timeout=self.command_timeout,
        )

    def keyevent(
        self,
        keycode: int | str,
        *,
        serial: Optional[str] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbCommandResult:
        """
        执行 keyevent 输入。
        输入：
            keycode 可为整数或 Android KEYCODE_* 字符串。
        输出：
            ADB input keyevent 命令结果。
        使用示例：
            controller.keyevent("KEYCODE_BACK")
        """
        self._raise_if_cancelled(task_context, "ADB 按键任务已取消。")
        value = str(keycode).strip()
        if not value:
            return AdbCommandResult(False, "invalid_keyevent", "keyevent 不能为空。")
        return self.run_adb(
            ["shell", "input", "keyevent", value],
            serial=serial or self.configured_serial,
            timeout=self.command_timeout,
        )

    def show_notification(
        self,
        message: str,
        *,
        title: str = "ADB提示",
        tag: str = "azurlane_adb_notice",
        expand: bool = True,
        serial: Optional[str] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbCommandResult:
        """
        在模拟器端显示通知提示。
        输入：
            message: 通知正文；title: 通知标题；expand: 是否展开通知栏。
        输出：
            adb cmd notification 结果；不支持该命令时返回 error。
        使用示例：
            controller.show_notification("正在截图")
        """
        self._raise_if_cancelled(task_context, "ADB 通知提示任务已取消。")
        safe_message = str(message).strip()
        safe_title = str(title).strip() or "ADB提示"
        safe_tag = str(tag).strip() or "azurlane_adb_notice"
        if not safe_message:
            return AdbCommandResult(False, "invalid_text", "通知正文不能为空。")
        result = self.run_adb(
            ["shell", "cmd", "notification", "post", "-S", "bigtext", "-t", safe_title, safe_tag, safe_message],
            serial=serial or self.configured_serial,
            timeout=self.command_timeout,
        )
        if result.success and expand:
            self.expand_notifications(serial=serial, task_context=task_context)
        return result

    def expand_notifications(
        self,
        *,
        serial: Optional[str] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbCommandResult:
        """
        展开通知栏。
        输入：
            可选 serial 与取消上下文。
        输出：
            adb cmd statusbar expand-notifications 结果。
        使用示例：
            controller.expand_notifications()
        """
        self._raise_if_cancelled(task_context, "ADB 通知栏展开任务已取消。")
        return self.run_adb(
            ["shell", "cmd", "statusbar", "expand-notifications"],
            serial=serial or self.configured_serial,
            timeout=self.command_timeout,
        )

    def press_back(self, *, serial: Optional[str] = None, task_context: Optional[TaskExecutionContext] = None) -> AdbCommandResult:
        """发送返回键。"""
        return self.keyevent("KEYCODE_BACK", serial=serial, task_context=task_context)

    def press_home(self, *, serial: Optional[str] = None, task_context: Optional[TaskExecutionContext] = None) -> AdbCommandResult:
        """发送 Home 键。"""
        return self.keyevent("KEYCODE_HOME", serial=serial, task_context=task_context)

    def press_menu(self, *, serial: Optional[str] = None, task_context: Optional[TaskExecutionContext] = None) -> AdbCommandResult:
        """发送菜单/最近任务键。"""
        return self.keyevent("KEYCODE_MENU", serial=serial, task_context=task_context)

    def transfer_to_device(
        self,
        local_path: str | Path,
        remote_path: str,
        *,
        serial: Optional[str] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbCommandResult:
        """
        推送本地文件到模拟器。
        输入：
            local_path: 本地文件路径；remote_path: 设备路径。
        输出：
            adb push 命令结果。
        使用示例：
            controller.transfer_to_device("a.png", "/sdcard/a.png")
        """
        self._raise_if_cancelled(task_context, "ADB 文件推送任务已取消。")
        path = Path(local_path)
        if not path.exists() or not path.is_file():
            return AdbCommandResult(False, "invalid_path", f"本地文件不存在: {path}")
        if not remote_path.strip():
            return AdbCommandResult(False, "invalid_path", "远端路径不能为空。")
        return self.run_adb(
            ["push", str(path), remote_path],
            serial=serial or self.configured_serial,
            timeout=self.command_timeout,
        )

    def transfer_from_device(
        self,
        remote_path: str,
        local_path: str | Path,
        *,
        serial: Optional[str] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbCommandResult:
        """
        从模拟器拉取文件。
        输入：
            remote_path: 设备路径；local_path: 本地目标路径。
        输出：
            adb pull 命令结果。
        使用示例：
            controller.transfer_from_device("/sdcard/a.png", "a.png")
        """
        self._raise_if_cancelled(task_context, "ADB 文件拉取任务已取消。")
        if not remote_path.strip():
            return AdbCommandResult(False, "invalid_path", "远端路径不能为空。")
        path = Path(local_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return self.run_adb(
            ["pull", remote_path, str(path)],
            serial=serial or self.configured_serial,
            timeout=self.command_timeout,
        )

    def remove_remote_file(
        self,
        remote_path: str,
        *,
        serial: Optional[str] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbCommandResult:
        """
        删除模拟器端文件。
        输入：
            remote_path: 设备路径。
        输出：
            adb shell rm -f 命令结果。
        使用示例：
            controller.remove_remote_file("/sdcard/tmp.png")
        """
        self._raise_if_cancelled(task_context, "ADB 远端文件删除任务已取消。")
        if not remote_path.strip():
            return AdbCommandResult(False, "invalid_path", "远端路径不能为空。")
        return self.run_adb(
            ["shell", "rm", "-f", remote_path],
            serial=serial or self.configured_serial,
            timeout=self.command_timeout,
        )

    def start_app(
        self,
        package_name: str,
        activity_name: Optional[str] = None,
        *,
        serial: Optional[str] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbCommandResult:
        """
        启动应用。
        输入：
            package_name: 包名；activity_name: 可选 Activity。
        输出：
            指定 Activity 时使用 am start，否则使用 monkey 启动主入口。
        使用示例：
            controller.start_app("com.bilibili.azurlane")
        """
        self._raise_if_cancelled(task_context, "ADB 应用启动任务已取消。")
        package = package_name.strip()
        if not package:
            return AdbCommandResult(False, "invalid_package", "应用包名不能为空。")
        if activity_name:
            component = f"{package}/{activity_name.strip()}"
            args: list[object] = ["shell", "am", "start", "-n", component]
        else:
            args = ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"]
        return self.run_adb(args, serial=serial or self.configured_serial, timeout=self.command_timeout)

    def stop_app(
        self,
        package_name: str,
        *,
        serial: Optional[str] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbCommandResult:
        """
        强制停止应用。
        输入：
            package_name: 应用包名。
        输出：
            adb shell am force-stop 命令结果。
        使用示例：
            controller.stop_app("com.bilibili.azurlane")
        """
        self._raise_if_cancelled(task_context, "ADB 应用停止任务已取消。")
        package = package_name.strip()
        if not package:
            return AdbCommandResult(False, "invalid_package", "应用包名不能为空。")
        return self.run_adb(
            ["shell", "am", "force-stop", package],
            serial=serial or self.configured_serial,
            timeout=self.command_timeout,
        )

    def get_foreground_activity(
        self,
        *,
        serial: Optional[str] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbCommandResult:
        """
        查询当前前台窗口/Activity。
        输入：
            可选 serial 与取消上下文。
        输出：
            adb shell dumpsys window 命令结果。
        使用示例：
            result = controller.get_foreground_activity()
        """
        self._raise_if_cancelled(task_context, "ADB 前台应用查询已取消。")
        return self.run_adb(
            ["shell", "dumpsys", "window", "windows"],
            serial=serial or self.configured_serial,
            timeout=self.command_timeout,
        )

    def get_screen_info(
        self,
        *,
        serial: Optional[str] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> Dict[str, Any]:
        """
        查询屏幕信息。
        输入：
            可选 serial 与取消上下文。
        输出：
            包含 size/density 原始命令与解析值的字典。
        使用示例：
            info = controller.get_screen_info()
        """
        self._raise_if_cancelled(task_context, "ADB 屏幕信息查询已取消。")
        size_result = self.run_adb(["shell", "wm", "size"], serial=serial or self.configured_serial, timeout=self.command_timeout)
        density_result = self.run_adb(["shell", "wm", "density"], serial=serial or self.configured_serial, timeout=self.command_timeout)
        return {
            "resolution": self.parse_wm_size(size_result.stdout) if size_result.success else None,
            "density": self.parse_wm_density(density_result.stdout) if density_result.success else None,
            "size_command": size_result.to_dict(),
            "density_command": density_result.to_dict(),
        }

    def run_operations(
        self,
        operations: Sequence[Dict[str, Any]],
        *,
        serial: Optional[str] = None,
        continue_on_error: bool = False,
        default_delay: float = 0.0,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> AdbOperationSequenceResult:
        """
        连续执行 ADB 操作步骤。
        输入：
            operations: 步骤列表；每步包含 action 和对应参数。
            serial: 可选设备串号。
            continue_on_error: 失败后是否继续后续步骤。
            default_delay: 每步默认后置等待秒数。
            task_context: 可选取消上下文。
        输出：
            AdbOperationSequenceResult: 包含每一步结构化结果。
        使用示例：
            controller.run_operations([{"action": "tap", "x": 640, "y": 360}])
        """
        self._raise_if_cancelled(task_context, "ADB 连续操作已取消。")
        if not operations:
            return AdbOperationSequenceResult(False, "error", "连续操作步骤不能为空。")

        step_results: list[AdbOperationStepResult] = []
        warnings: list[str] = []
        target_serial = serial or self.configured_serial
        for index, raw_step in enumerate(operations, start=1):
            self._raise_if_cancelled(task_context, "ADB 连续操作已取消。")
            if not isinstance(raw_step, dict):
                step_result = AdbOperationStepResult(index, "invalid", False, "error", "操作步骤必须是 dict。")
            else:
                step_result = self._run_operation_step(index, raw_step, target_serial, task_context)
            step_results.append(step_result)
            warnings.extend(step_result.warnings)

            step_continue = bool(raw_step.get("continue_on_error", False)) if isinstance(raw_step, dict) else False
            if not step_result.success and not (continue_on_error or step_continue):
                return AdbOperationSequenceResult(
                    False,
                    step_result.status,
                    f"连续操作在第 {index} 步失败: {step_result.message}",
                    tuple(step_results),
                    failure_index=index,
                    warnings=tuple(warnings),
                )

            delay_seconds = self._step_delay(raw_step, default_delay)
            self._sleep_with_cancel(delay_seconds, task_context)

        return AdbOperationSequenceResult(
            all(step.success for step in step_results),
            "ready" if all(step.success for step in step_results) else "warning",
            "连续 ADB 操作执行完成。",
            tuple(step_results),
            warnings=tuple(warnings),
        )

    def run_sequence(
        self,
        sequence_name: str,
        scene_probe: Callable[..., object],
        *,
        serial: Optional[str] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> NavigationResult:
        """
        执行配置化导航序列。
        输入：
            sequence_name: config/automation/sequences.json 中的序列名。
            scene_probe: 注入的页面判断函数，不依赖 OCR 实现模块。
        输出：
            到达目标页面则 success=True；超时后最多重试两次。
        使用示例：
            controller.run_sequence("enter_research", lambda scene: current == scene)
        """
        self._raise_if_cancelled(task_context, "ADB 导航任务已取消。")
        try:
            root_config = self._load_sequence_config()
            sequence_config = self._get_sequence_config(root_config, sequence_name)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            return NavigationResult(False, "error", str(exc), sequence_name)

        target_scene = self._target_scene_for_sequence(sequence_name, sequence_config)
        defaults = root_config.get("defaults", {}) if isinstance(root_config.get("defaults"), dict) else {}
        max_retries = min(2, int(sequence_config.get("max_retries", defaults.get("max_retries", 2)) or 0))
        timeout_seconds = float(sequence_config.get("timeout_seconds", defaults.get("timeout_seconds", 8.0)) or 0.0)
        base_resolution = self._sequence_base_resolution(root_config, sequence_config)
        warnings: list[str] = []

        for attempt in range(max_retries + 1):
            self._raise_if_cancelled(task_context, "ADB 导航任务已取消。")
            for step in sequence_config.get("steps", ()):
                step_result = self._run_navigation_step(
                    step,
                    serial=serial,
                    base_resolution=base_resolution,
                    task_context=task_context,
                )
                if not step_result.success:
                    warnings.append(f"第 {attempt + 1} 次导航步骤失败: {step_result.status}")
                    break
                delay_seconds = float(step.get("delay", defaults.get("step_delay", 0.0)) or 0.0)
                self._sleep_with_cancel(delay_seconds, task_context)

            if self._wait_for_scene(scene_probe, target_scene, timeout_seconds, task_context):
                return NavigationResult(
                    True,
                    "ready",
                    f"导航序列 {sequence_name} 已到达目标页面。",
                    sequence_name,
                    target_scene=target_scene,
                    attempts=attempt + 1,
                    warnings=tuple(warnings),
                )
            warnings.append(f"第 {attempt + 1} 次导航未到达 {target_scene.value}。")

        return NavigationResult(
            False,
            "timeout",
            f"导航序列 {sequence_name} 超时，未到达 {target_scene.value}。",
            sequence_name,
            target_scene=target_scene,
            attempts=max_retries + 1,
            warnings=tuple(warnings),
        )

    # ========================================================
    # 🔧 第四部分：内部辅助方法
    # ========================================================

    def _common_adb_paths(self) -> Tuple[str, ...]:
        """合并配置里的常见路径和内置雷电/MuMu路径。"""
        configured = self.adb_config.get("common_paths", ())
        if not isinstance(configured, Iterable) or isinstance(configured, (str, bytes)):
            configured = ()
        paths = [str(item) for item in configured]
        paths.extend(COMMON_ADB_PATHS)
        return tuple(dict.fromkeys(paths))

    def _resolve_existing_adb(self, candidate: str) -> Optional[str]:
        """把候选 ADB 路径解析为真实可用路径。"""
        if not candidate:
            return None
        if any(separator in candidate for separator in ("/", "\\")) or candidate.lower().endswith(".exe"):
            return str(Path(candidate)) if self.path_exists(candidate) else None
        resolved = self.which(candidate)
        return str(Path(resolved)) if resolved else None

    @staticmethod
    def _decode_output(value: object) -> str:
        """把 subprocess 的 bytes/str/None 输出统一成字符串。"""
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    @staticmethod
    def _encode_input_text(text: str) -> str:
        """
        编码 adb shell input text 参数。
        输入：
            用户要输入的短文本。
        输出：
            空格转为 %s，常见 shell 敏感字符用反斜杠保护。
        使用示例：
            encoded = AdbController._encode_input_text("Azur Lane")
        """
        safe_text = str(text).strip()
        replacements = {
            " ": "%s",
            "\\": "\\\\",
            "&": "\\&",
            "|": "\\|",
            "<": "\\<",
            ">": "\\>",
            ";": "\\;",
            "(": "\\(",
            ")": "\\)",
            "$": "\\$",
            "*": "\\*",
            "'": "\\'",
            '"': '\\"',
        }
        return "".join(replacements.get(char, char) for char in safe_text)

    @staticmethod
    def _classify_adb_error(text: str) -> str:
        """根据 stderr/stdout 对常见 ADB 错误分类。"""
        lowered = text.lower()
        if "unauthorized" in lowered:
            return "unauthorized"
        if "offline" in lowered:
            return "offline"
        if "not found" in lowered or "no devices" in lowered or "no device" in lowered:
            return "unavailable"
        if "more than one device" in lowered:
            return "multiple_devices"
        if "timeout" in lowered:
            return "timeout"
        return "error"

    @staticmethod
    def parse_wm_size(output: str) -> Optional[Tuple[int, int]]:
        """
        解析 adb shell wm size 输出。
        输入：
            Physical size: 1280x720。
        输出：
            (1280, 720)，无法解析时返回 None。
        使用示例：
            size = AdbController.parse_wm_size("Physical size: 1280x720")
        """
        for token in output.replace("\r", "\n").split():
            if "x" not in token:
                continue
            width_text, height_text = token.strip().split("x", 1)
            if width_text.isdigit() and height_text.isdigit():
                return int(width_text), int(height_text)
        return None

    @staticmethod
    def parse_wm_density(output: str) -> Optional[int]:
        """
        解析 adb shell wm density 输出。
        输入：
            Physical density: 240。
        输出：
            240，无法解析时返回 None。
        使用示例：
            density = AdbController.parse_wm_density("Physical density: 240")
        """
        for token in output.replace("\r", "\n").split():
            if token.isdigit():
                return int(token)
        return None

    @staticmethod
    def _adb_setup_suggestions(simulator_type: str) -> Tuple[str, ...]:
        """按模拟器类型给出 ADB 与显示设置提示。"""
        common = "请在模拟器设置中开启 ADB/Android 调试开关，并重启模拟器后重试。"
        if simulator_type == "mumu":
            return (
                "MuMu 模拟器请设置分辨率为 1280x720，并选择平板模式。",
                common,
            )
        if simulator_type == "leidian":
            return (
                "雷电模拟器请在性能/显示设置中将分辨率设置为 1280x720。",
                common,
            )
        return (
            "建议将模拟器分辨率设置为 1280x720。",
            common,
        )

    def _run_operation_step(
        self,
        index: int,
        step: Dict[str, Any],
        serial: Optional[str],
        task_context: Optional[TaskExecutionContext],
    ) -> AdbOperationStepResult:
        """执行连续操作中的单个步骤。"""
        action = str(step.get("action", "")).strip().lower()
        try:
            if action in {"tap", "click"}:
                result: object = self.tap(step.get("x", 0), step.get("y", 0), serial=serial, task_context=task_context)
            elif action == "swipe":
                result = self.swipe(
                    step.get("start_x", step.get("x1", 0)),
                    step.get("start_y", step.get("y1", 0)),
                    step.get("end_x", step.get("x2", 0)),
                    step.get("end_y", step.get("y2", 0)),
                    int(step.get("duration_ms", step.get("duration", 300))),
                    serial=serial,
                    task_context=task_context,
                )
            elif action == "long_press":
                result = self.long_press(
                    step.get("x", 0),
                    step.get("y", 0),
                    int(step.get("duration_ms", step.get("duration", 800))),
                    serial=serial,
                    task_context=task_context,
                )
            elif action == "double_tap":
                result = self.double_tap(
                    step.get("x", 0),
                    step.get("y", 0),
                    interval_seconds=float(step.get("interval_seconds", 0.08)),
                    serial=serial,
                    task_context=task_context,
                )
            elif action == "drag":
                result = self.drag(
                    step.get("start_x", step.get("x1", 0)),
                    step.get("start_y", step.get("y1", 0)),
                    step.get("end_x", step.get("x2", 0)),
                    step.get("end_y", step.get("y2", 0)),
                    int(step.get("duration_ms", step.get("duration", 800))),
                    serial=serial,
                    task_context=task_context,
                )
            elif action == "keyevent":
                result = self.keyevent(step.get("keycode", ""), serial=serial, task_context=task_context)
            elif action in {"text", "input_text"}:
                result = self.input_text(str(step.get("text", "")), serial=serial, task_context=task_context)
            elif action in {"notify", "notification"}:
                result = self.show_notification(
                    str(step.get("message", "")),
                    title=str(step.get("title", "ADB提示")),
                    tag=str(step.get("tag", "azurlane_adb_notice")),
                    expand=bool(step.get("expand", True)),
                    serial=serial,
                    task_context=task_context,
                )
            elif action == "wait":
                self._sleep_with_cancel(float(step.get("seconds", step.get("delay", 0.0)) or 0.0), task_context)
                result = AdbCommandResult(True, "ok", "等待步骤完成。")
            elif action == "screenshot":
                result = self.capture_screenshot(
                    RecognitionScene.normalize(step.get("scene", RecognitionScene.HARBOR.value)),
                    serial=serial,
                    output_dir=Path(step["output_dir"]) if step.get("output_dir") else None,
                    task_context=task_context,
                )
            elif action == "push":
                result = self.transfer_to_device(step.get("local_path", ""), str(step.get("remote_path", "")), serial=serial, task_context=task_context)
            elif action == "pull":
                result = self.transfer_from_device(str(step.get("remote_path", "")), step.get("local_path", ""), serial=serial, task_context=task_context)
            elif action in {"remove", "rm"}:
                result = self.remove_remote_file(str(step.get("remote_path", "")), serial=serial, task_context=task_context)
            elif action == "start_app":
                result = self.start_app(str(step.get("package_name", "")), step.get("activity_name"), serial=serial, task_context=task_context)
            elif action == "stop_app":
                result = self.stop_app(str(step.get("package_name", "")), serial=serial, task_context=task_context)
            elif action == "screen_info":
                result = self.get_screen_info(serial=serial, task_context=task_context)
            else:
                return AdbOperationStepResult(index, action or "unknown", False, "error", f"未知连续操作动作: {action}")
        except Exception as exc:
            return AdbOperationStepResult(index, action or "unknown", False, "error", f"{type(exc).__name__}: {exc}")
        return self._operation_result_from_raw(index, action, result)

    @staticmethod
    def _operation_result_from_raw(index: int, action: str, result: object) -> AdbOperationStepResult:
        """把单步原始结果转换为统一步骤结果。"""
        if isinstance(result, AdbCommandResult):
            return AdbOperationStepResult(
                index,
                action,
                result.success,
                result.status,
                result.message,
                {"command": result.to_dict()},
            )
        if isinstance(result, AdbScreenshotResult):
            return AdbOperationStepResult(
                index,
                action,
                result.success,
                result.status,
                result.message,
                result.to_payload(),
                result.warnings,
            )
        if isinstance(result, dict):
            return AdbOperationStepResult(index, action, True, "ok", "步骤执行完成。", result)
        return AdbOperationStepResult(index, action, True, "ok", str(result), {"result": str(result)})

    @staticmethod
    def _step_delay(step: object, default_delay: float) -> float:
        """读取单步后置延迟。"""
        if isinstance(step, dict) and "post_delay" in step:
            return max(0.0, float(step.get("post_delay") or 0.0))
        if isinstance(step, dict) and step.get("action") == "wait":
            return 0.0
        return max(0.0, float(default_delay or 0.0))

    @staticmethod
    def _select_device(devices: Tuple[AdbDevice, ...], serial: Optional[str]) -> Dict[str, Any]:
        """根据 serial 或单设备规则选择设备。"""
        if not devices:
            return {"success": False, "status": "unavailable", "message": "未发现 ADB 设备，请确认模拟器已启动。"}

        if serial:
            matched = next((device for device in devices if device.serial == serial), None)
            if matched is None:
                return {
                    "success": False,
                    "status": "unavailable",
                    "message": f"未发现指定设备: {serial}",
                }
            return AdbController._device_state_result(matched)

        if len(devices) > 1:
            return {
                "success": False,
                "status": "multiple_devices",
                "message": "发现多台 ADB 设备，请在配置中指定 serial。",
            }
        return AdbController._device_state_result(devices[0])

    @staticmethod
    def _device_state_result(device: AdbDevice) -> Dict[str, Any]:
        """把单台设备 state 转成连接结果。"""
        if device.state == "device":
            return {"success": True, "status": "ready", "message": "ADB 设备连接正常。", "device": device}
        if device.state == "offline":
            return {"success": False, "status": "offline", "message": f"设备离线: {device.serial}", "device": device}
        if device.state == "unauthorized":
            return {
                "success": False,
                "status": "unauthorized",
                "message": f"设备未授权: {device.serial}",
                "device": device,
            }
        return {
            "success": False,
            "status": "error",
            "message": f"设备状态不可用: {device.serial} ({device.state})",
            "device": device,
        }

    def _capture_via_pull(
        self,
        final_path: Path,
        device_serial: str,
        adb_path: Optional[str],
        task_context: Optional[TaskExecutionContext],
    ) -> AdbCommandResult:
        """使用 shell screencap + pull 回退截图，并保持本地原子替换。"""
        self._raise_if_cancelled(task_context, "ADB 截图回退任务已取消。")
        remote_result = self.run_adb(
            ["shell", "screencap", "-p", ADB_TEMP_SCREENSHOT],
            serial=device_serial,
            adb_path=adb_path,
            timeout=self.command_timeout,
        )
        if not remote_result.success:
            return remote_result

        temp_path = final_path.with_name(f".{final_path.name}.{os.getpid()}.pull.tmp")
        pull_result = self.run_adb(
            ["pull", ADB_TEMP_SCREENSHOT, str(temp_path)],
            serial=device_serial,
            adb_path=adb_path,
            timeout=self.command_timeout,
        )
        self.run_adb(["shell", "rm", "-f", ADB_TEMP_SCREENSHOT], serial=device_serial, adb_path=adb_path)
        if not pull_result.success:
            if temp_path.exists():
                temp_path.unlink()
            return pull_result
        if not temp_path.exists() or not self._looks_like_png(temp_path.read_bytes()):
            if temp_path.exists():
                temp_path.unlink()
            return AdbCommandResult(False, "error", "pull 回退得到的文件不是有效 PNG。")
        final_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp_path, final_path)
        return pull_result

    @staticmethod
    def _looks_like_png(data: bytes) -> bool:
        """检查截图 bytes 是否为 PNG。"""
        return data.startswith(PNG_SIGNATURE)

    @staticmethod
    def _build_screenshot_path(screenshot_dir: Path, scene: RecognitionScene) -> Path:
        """生成唯一截图文件名。"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return screenshot_dir / f"azurlane_{scene.value}_{timestamp}.png"

    @staticmethod
    def _atomic_write_bytes(path: Path, data: bytes) -> None:
        """先写临时文件再 os.replace，保证截图保存原子性。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with open(temp_path, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def _load_sequence_config(self) -> Dict[str, Any]:
        """读取导航序列配置文件。"""
        sequence_path = PathManager.get_config_dir() / "automation" / "sequences.json"
        if not sequence_path.exists():
            raise FileNotFoundError(f"导航序列配置不存在: {sequence_path}")
        with open(sequence_path, "r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            raise ValueError("导航序列配置必须是 JSON 对象。")
        return data

    @staticmethod
    def _get_sequence_config(root_config: Dict[str, Any], sequence_name: str) -> Dict[str, Any]:
        """兼容新版 sequences 字段和旧版顶层 list 配置。"""
        sequences = root_config.get("sequences", root_config)
        if sequence_name not in sequences:
            raise KeyError(f"未找到导航序列: {sequence_name}")
        raw_config = sequences[sequence_name]
        if isinstance(raw_config, list):
            return {"steps": raw_config}
        if not isinstance(raw_config, dict):
            raise ValueError(f"导航序列必须是对象或步骤列表: {sequence_name}")
        steps = raw_config.get("steps", ())
        if not isinstance(steps, list):
            raise ValueError(f"导航序列 steps 必须是列表: {sequence_name}")
        return raw_config

    @staticmethod
    def _target_scene_for_sequence(sequence_name: str, sequence_config: Dict[str, Any]) -> RecognitionScene:
        """从配置或常用序列名推断目标场景。"""
        scene_name = sequence_config.get("target_scene")
        fallback = {
            "enter_research": RecognitionScene.RESEARCH.value,
            "enter_equipment": RecognitionScene.EQUIPMENT_LIST.value,
            "go_harbor": RecognitionScene.HARBOR.value,
            "return_home": RecognitionScene.HARBOR.value,
            "equipment": RecognitionScene.EQUIPMENT_LIST.value,
        }
        return RecognitionScene.normalize(scene_name or fallback.get(sequence_name, RecognitionScene.HARBOR.value))

    @staticmethod
    def _sequence_base_resolution(root_config: Dict[str, Any], sequence_config: Dict[str, Any]) -> Tuple[int, int]:
        """读取导航序列坐标基准分辨率。"""
        base = sequence_config.get("base_resolution") or root_config.get("base_resolution") or {}
        if isinstance(base, dict):
            width = int(base.get("width", DEFAULT_SCREEN_SIZE[0]) or DEFAULT_SCREEN_SIZE[0])
            height = int(base.get("height", DEFAULT_SCREEN_SIZE[1]) or DEFAULT_SCREEN_SIZE[1])
            return width, height
        if isinstance(base, list) and len(base) == 2:
            return int(base[0]), int(base[1])
        return DEFAULT_SCREEN_SIZE

    def _run_navigation_step(
        self,
        step: Dict[str, Any],
        *,
        serial: Optional[str],
        base_resolution: Tuple[int, int],
        task_context: Optional[TaskExecutionContext],
    ) -> AdbCommandResult:
        """执行单个导航步骤。"""
        self._raise_if_cancelled(task_context, "ADB 导航步骤已取消。")
        action = str(step.get("action", "")).strip().lower()
        if action in {"tap", "click"}:
            return self.tap(step.get("x", 0), step.get("y", 0), serial=serial, base_resolution=base_resolution, task_context=task_context)
        if action == "swipe":
            return self.swipe(
                step.get("start_x", step.get("x1", 0)),
                step.get("start_y", step.get("y1", 0)),
                step.get("end_x", step.get("x2", 0)),
                step.get("end_y", step.get("y2", 0)),
                int(step.get("duration_ms", step.get("duration", 300))),
                serial=serial,
                base_resolution=base_resolution,
                task_context=task_context,
            )
        if action == "keyevent":
            return self.keyevent(step.get("keycode", ""), serial=serial, task_context=task_context)
        if action == "wait":
            self._sleep_with_cancel(float(step.get("seconds", step.get("delay", 0.0)) or 0.0), task_context)
            return AdbCommandResult(True, "ok", "等待步骤完成。")
        return AdbCommandResult(False, "error", f"未知导航动作: {action}")

    def _wait_for_scene(
        self,
        scene_probe: Callable[..., object],
        target_scene: RecognitionScene,
        timeout_seconds: float,
        task_context: Optional[TaskExecutionContext],
    ) -> bool:
        """轮询 scene_probe，直到到达目标场景或超时。"""
        deadline = self.time_provider() + max(0.0, timeout_seconds)
        while True:
            self._raise_if_cancelled(task_context, "ADB 导航页面判断已取消。")
            if self._call_scene_probe(scene_probe, target_scene):
                return True
            if self.time_provider() >= deadline:
                return False
            self._sleep_with_cancel(0.2, task_context)

    @staticmethod
    def _call_scene_probe(scene_probe: Callable[..., object], target_scene: RecognitionScene) -> bool:
        """兼容 scene_probe(target_scene) 和 scene_probe() 两种注入方式。"""
        try:
            signature = inspect.signature(scene_probe)
            result = scene_probe(target_scene) if len(signature.parameters) else scene_probe()
        except (TypeError, ValueError):
            try:
                result = scene_probe(target_scene)
            except TypeError:
                result = scene_probe()
        if isinstance(result, RecognitionScene):
            return result is target_scene
        if isinstance(result, str):
            try:
                return RecognitionScene.normalize(result) is target_scene
            except ValueError:
                return False
        return bool(result)

    def _sleep_with_cancel(self, delay_seconds: float, task_context: Optional[TaskExecutionContext]) -> None:
        """短延迟前后都检查取消，避免长步骤继续点击。"""
        self._raise_if_cancelled(task_context, "ADB 自动化任务已取消。")
        if delay_seconds > 0:
            self.sleeper(delay_seconds)
        self._raise_if_cancelled(task_context, "ADB 自动化任务已取消。")

    @staticmethod
    def _raise_if_cancelled(task_context: Optional[TaskExecutionContext], message: str) -> None:
        """安全点取消检查。"""
        if task_context is not None:
            task_context.raise_if_cancelled(message)


# ============================================================
# 🌐 第五部分：便捷函数
# ============================================================

def create_adb_controller(simulator_config: Optional[Dict[str, Any]] = None) -> AdbController:
    """
    创建 ADB 控制器。
    输入：
        simulator_config: 可选模拟器配置。
    输出：
        AdbController 实例。
    使用示例：
        controller = create_adb_controller(config)
    """
    return AdbController(simulator_config)
