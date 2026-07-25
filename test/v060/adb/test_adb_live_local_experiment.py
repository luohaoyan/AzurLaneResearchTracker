#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║       🧪 ADB 本地实机控制实验 (test_adb_live_local_experiment) ║
║                                                              ║
║  【一句话解释】在真实模拟器上慢速演示截图、点击、长按和滑动。  ║
║  【类比理解】它像一条带护栏的试车跑道，默认跳过，显式开启才跑。║
║  【数据流说明】pytest → ADB 控制器 → 模拟器动作 → 截图与JSON记录║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import pytest

from core.automation.adb_controller import AdbCommandResult, AdbController
from core.contracts import RecognitionScene
from core.utils.config_loader import get_config_loader
from core.utils.path_manager import PathManager


# ============================================================
# 🧱 第二部分：实验配置与辅助数据结构
# ============================================================

LIVE_FLAG_ENV = "ALRT_ADB_LIVE"
DEFAULT_SIMULATOR = "leidian"
TARGET_RESOLUTION = (1280, 720)


@dataclass(frozen=True)
class LiveExperimentSettings:
    """
    ADB 本地实验设置。
    输入：
        环境变量中的 serial、模拟器名、暂停秒数和显示开关。
    输出：
        测试运行时使用的只读配置。
    使用示例：
        settings = LiveExperimentSettings.from_env()
    """

    simulator_name: str
    serial: str
    pause_seconds: float
    prompt_seconds: float
    confirm_each_step: bool
    show_device_notice: bool
    safe_home: bool
    auto_connect: bool
    include_text_input: bool

    @classmethod
    def from_env(cls) -> "LiveExperimentSettings":
        """
        从环境变量读取本地实验参数。
        输入：
            PowerShell / CMD 环境变量。
        输出：
            LiveExperimentSettings。
        使用示例：
            settings = LiveExperimentSettings.from_env()
        """
        return cls(
            simulator_name=os.getenv("ALRT_ADB_SIMULATOR", DEFAULT_SIMULATOR).strip() or DEFAULT_SIMULATOR,
            serial=os.getenv("ALRT_ADB_SERIAL", "").strip(),
            pause_seconds=_float_env("ALRT_ADB_STEP_PAUSE", 1.2),
            prompt_seconds=_float_env("ALRT_ADB_PROMPT_SECONDS", 0.9),
            confirm_each_step=_truthy_env("ALRT_ADB_CONFIRM"),
            show_device_notice=not _truthy_env("ALRT_ADB_NO_NOTICE"),
            safe_home=not _truthy_env("ALRT_ADB_KEEP_CURRENT"),
            auto_connect=not _truthy_env("ALRT_ADB_NO_AUTO_CONNECT"),
            include_text_input=_truthy_env("ALRT_ADB_INCLUDE_TEXT"),
        )


@dataclass(frozen=True)
class ExperimentStep:
    """
    单个可观察 ADB 实验步骤。
    输入：
        title/detail/action/required。
    输出：
        test_live_adb_control_experiment 会按顺序执行这些步骤。
    使用示例：
        ExperimentStep("中心点击", "点击 640,360", lambda: controller.tap(640, 360))
    """

    title: str
    detail: str
    action: Callable[[], object]
    required: bool = True


# ============================================================
# 🧰 第三部分：通用辅助函数
# ============================================================

def _truthy_env(name: str) -> bool:
    """
    判断环境变量是否表示启用。
    输入：
        name: 环境变量名称。
    输出：
        True 表示 1/true/yes/on/y。
    使用示例：
        if _truthy_env("ALRT_ADB_LIVE"): ...
    """
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on", "y"}


def _float_env(name: str, default: float) -> float:
    """
    读取浮点环境变量。
    输入：
        name/default。
    输出：
        解析失败时回落 default。
    使用示例：
        pause = _float_env("ALRT_ADB_STEP_PAUSE", 1.2)
    """
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return max(0.0, float(raw_value))
    except ValueError:
        return default


def _build_controller(simulator_name: str) -> AdbController:
    """
    创建真实 ADB 控制器。
    输入：
        simulator_name: config/simulators 下的配置名，如 leidian/mumu。
    输出：
        AdbController。
    使用示例：
        controller = _build_controller("leidian")
    """
    loader = get_config_loader()
    simulator_config = loader.get_simulator_config(simulator_name)
    return AdbController(simulator_config)


def _build_connect_candidates(controller: AdbController, settings: LiveExperimentSettings) -> list[str]:
    """
    构建常见模拟器 serial 候选。
    输入：
        controller/settings。
    输出：
        去重后的 adb connect 候选列表。
    使用示例：
        for serial in _build_connect_candidates(controller, settings): ...
    """
    candidates: list[str] = []
    if settings.serial and ":" in settings.serial:
        candidates.append(settings.serial)

    port = controller.adb_config.get("port") if isinstance(controller.adb_config, dict) else None
    if port:
        candidates.append(f"127.0.0.1:{port}")

    # 这里刻意放入主流端口：本地实验时经常是模拟器已开、ADB 还没 connect。
    candidates.extend(
        (
            "127.0.0.1:5555",
            "127.0.0.1:5554",
            "127.0.0.1:7555",
            "127.0.0.1:7556",
            "127.0.0.1:62001",
            "127.0.0.1:21503",
        )
    )

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def _select_serial(controller: AdbController, settings: LiveExperimentSettings) -> str:
    """
    选择真实设备 serial。
    输入：
        controller/settings。
    输出：
        成功连接的设备 serial；失败时 pytest.fail。
    使用示例：
        serial = _select_serial(controller, settings)
    """
    connection = controller.check_connection(serial=settings.serial or None, reconnect=True)
    if connection.success and connection.selected_device is not None:
        return connection.selected_device.serial

    if settings.auto_connect:
        for candidate in _build_connect_candidates(controller, settings):
            print(f"[ADB实验] 尝试自动连接: adb connect {candidate}")
            reconnect = controller.reconnect_device(candidate)
            print(f"[ADB实验] connect 结果: {reconnect.status} {reconnect.stdout.strip() or reconnect.stderr.strip()}")
            connection = controller.check_connection(serial=candidate)
            if connection.success and connection.selected_device is not None:
                return connection.selected_device.serial

    candidates = ", ".join(f"{item.serial}({item.state})" for item in connection.candidates) or "无"
    pytest.fail(f"无法选择可用 ADB 设备：{connection.status}，{connection.message}；候选设备：{candidates}")


def _make_run_dir() -> Path:
    """
    创建本地实验输出目录。
    输入：
        无。
    输出：
        workdir/automation/adb_live_local_experiment/run_时间戳。
    使用示例：
        run_dir = _make_run_dir()
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = PathManager.get_work_dir() / "automation" / "adb_live_local_experiment" / f"run_{timestamp}"
    (run_dir / "frames").mkdir(parents=True, exist_ok=True)
    return run_dir


def _serialize_result(result: object) -> dict[str, Any]:
    """
    将 ADB 结果转为 JSON 可记录结构。
    输入：
        ADB dataclass、dict 或普通对象。
    输出：
        JSON 友好的 dict。
    使用示例：
        trace.append(_serialize_result(result))
    """
    if hasattr(result, "to_dict"):
        return getattr(result, "to_dict")()
    if hasattr(result, "to_payload"):
        payload = getattr(result, "to_payload")()
        return {"success": getattr(result, "success", True), "status": getattr(result, "status", "ok"), "payload": payload}
    if isinstance(result, dict):
        return _json_safe(result)
    return {"success": getattr(result, "success", True), "status": getattr(result, "status", "ok"), "repr": repr(result)}


def _json_safe(value: Any) -> Any:
    """
    递归转换 JSON 不认识的对象。
    输入：
        任意 Python 值。
    输出：
        可被 json.dumps 处理的值。
    使用示例：
        json.dumps(_json_safe(data))
    """
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if hasattr(value, "to_dict"):
        return _json_safe(getattr(value, "to_dict")())
    if hasattr(value, "to_payload"):
        return _json_safe(getattr(value, "to_payload")())
    return repr(value)


def _result_success(result: object) -> bool:
    """
    判断步骤结果是否成功。
    输入：
        ADB 结果或普通对象。
    输出：
        True 表示该步骤可以继续。
    使用示例：
        if not _result_success(result): pytest.fail(...)
    """
    if hasattr(result, "success"):
        return bool(getattr(result, "success"))
    if isinstance(result, dict) and "success" in result:
        return bool(result["success"])
    return True


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """
    写入 JSON 文件。
    输入：
        path/data。
    输出：
        UTF-8 JSON 文件。
    使用示例：
        _write_json(run_dir / "trace.json", trace)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(data), ensure_ascii=False, indent=2), encoding="utf-8")


def _show_device_notice(
    controller: AdbController,
    serial: str,
    title: str,
    *,
    settings: LiveExperimentSettings,
) -> None:
    """
    尝试在模拟器通知栏显示当前步骤。
    输入：
        controller/serial/title/settings。
    输出：
        通知失败只打印提示，不影响真正动作测试。
    使用示例：
        _show_device_notice(controller, serial, "准备截图", settings=settings)
    """
    if not settings.show_device_notice:
        return

    notice = controller.show_notification(
        title,
        title="ADB本地实验",
        tag="azurlane_adb_local_experiment",
        expand=True,
        serial=serial,
    )
    if not notice.success:
        print(f"[ADB实验] 模拟器通知不可用，继续使用终端提示：{notice.status} {notice.message}")
        return

    time.sleep(max(0.0, settings.prompt_seconds))
    # 展开通知栏后先收起，避免后续点击落在通知面板上。
    collapse = controller.run_adb(["shell", "cmd", "statusbar", "collapse"], serial=serial, timeout=3)
    if not collapse.success:
        controller.press_back(serial=serial)


def _run_step(
    index: int,
    total: int,
    step: ExperimentStep,
    *,
    controller: AdbController,
    serial: str,
    settings: LiveExperimentSettings,
    trace: list[dict[str, Any]],
) -> object:
    """
    执行单个本地实验步骤。
    输入：
        index/total/step/controller/serial/settings/trace。
    输出：
        原始步骤结果。
    使用示例：
        _run_step(1, 10, step, controller=controller, ...)
    """
    print(f"\n===== ADB 本地实验 {index}/{total}: {step.title} =====")
    print(step.detail)
    _show_device_notice(controller, serial, f"{index}/{total} {step.title}", settings=settings)

    if settings.confirm_each_step:
        input("[ADB实验] 按 Enter 执行此步骤，或 Ctrl+C 停止...")

    started = time.time()
    result = step.action()
    elapsed_ms = int((time.time() - started) * 1000)
    record = {
        "index": index,
        "title": step.title,
        "detail": step.detail,
        "elapsed_ms": elapsed_ms,
        "required": step.required,
        "result": _serialize_result(result),
    }
    trace.append(record)
    print(json.dumps(_json_safe(record["result"]), ensure_ascii=False, indent=2)[:1200])

    if step.required and not _result_success(result):
        pytest.fail(f"ADB 本地实验步骤失败：{step.title}；结果：{record['result']}")

    time.sleep(max(0.0, settings.pause_seconds))
    return result


def _assert_target_resolution(controller: AdbController, serial: str) -> dict[str, Any]:
    """
    校验模拟器分辨率是否为 1280x720。
    输入：
        controller/serial。
    输出：
        get_screen_info 的结果。
    使用示例：
        info = _assert_target_resolution(controller, serial)
    """
    info = controller.get_screen_info(serial=serial)
    resolution = info.get("resolution")
    if resolution != TARGET_RESOLUTION:
        pytest.fail(
            "ADB 本地实验要求模拟器为 1280x720。"
            f"当前读取到：{resolution}。请在模拟器设置中改为 1280x720 后重试。"
        )
    return info


def _capture_named(controller: AdbController, serial: str, run_dir: Path, scene_hint: str) -> object:
    """
    采集一张带场景提示的实验截图。
    输入：
        controller/serial/run_dir/scene_hint。
    输出：
        AdbScreenshotResult。
    使用示例：
        _capture_named(controller, serial, run_dir, "before")
    """
    return controller.capture_screenshot(
        RecognitionScene.HARBOR,
        serial=serial,
        output_dir=run_dir / "frames",
        screen_state=scene_hint,
        scene_hint=scene_hint,
    )


def _make_marker_file(run_dir: Path) -> Path:
    """
    创建用于 push/pull 验证的本地标记文件。
    输入：
        run_dir。
    输出：
        marker 文件路径。
    使用示例：
        marker = _make_marker_file(run_dir)
    """
    marker = run_dir / "adb_local_marker.txt"
    marker.write_text("AzurLaneResearchTracker ADB local live experiment\n", encoding="utf-8")
    return marker


def _build_steps(controller: AdbController, serial: str, run_dir: Path, settings: LiveExperimentSettings) -> list[ExperimentStep]:
    """
    构建本地实验步骤。
    输入：
        controller/serial/run_dir/settings。
    输出：
        ExperimentStep 列表。
    使用示例：
        steps = _build_steps(controller, serial, run_dir, settings)
    """
    remote_dir = "/sdcard/AzurLaneResearchTracker"
    remote_marker = f"{remote_dir}/adb_local_marker.txt"
    local_marker = _make_marker_file(run_dir)
    pulled_marker = run_dir / "adb_local_marker_from_device.txt"

    steps: list[ExperimentStep] = [
        ExperimentStep(
            "设备连接检查",
            "确认 ADB 路径、serial 和设备状态。失败时不会继续做真实点击。",
            lambda: controller.check_connection(serial=serial),
        ),
        ExperimentStep(
            "分辨率校验",
            "读取 wm size / wm density，并要求当前分辨率为 1280x720。",
            lambda: _assert_target_resolution(controller, serial),
        ),
        ExperimentStep(
            "显示环境检查",
            "检查 OCR 推荐环境；雷电重点看 1280x720，MuMu 还应使用平板模式。",
            lambda: controller.check_display_environment(serial=serial),
        ),
        ExperimentStep(
            "读取用户应用列表",
            "读取模拟器已安装第三方程序包，用于观察 ADB 包管理能力。",
            lambda: controller.list_packages(serial=serial, include_system=False),
            required=False,
        ),
        ExperimentStep(
            "读取当前前台窗口",
            "查询当前前台 Activity，后续登录/页面判断可复用这个能力。",
            lambda: controller.get_foreground_activity(serial=serial),
            required=False,
        ),
        ExperimentStep(
            "实验前截图",
            "优先 exec-out screencap -p 截图，失败时控制器会自动尝试 pull fallback。",
            lambda: _capture_named(controller, serial, run_dir, "before_actions"),
        ),
    ]

    if settings.safe_home:
        steps.append(
            ExperimentStep(
                "切回安卓桌面",
                "发送 Home 键，让后续大幅动作尽量落在安全桌面区域。",
                lambda: controller.press_home(serial=serial),
            )
        )

    steps.extend(
        [
            ExperimentStep(
                "中心点击",
                "点击 1280x720 基准坐标 (640, 360)，验证 tap。",
                lambda: controller.tap(640, 360, serial=serial),
            ),
            ExperimentStep(
                "中心双击",
                "慢速双击中心点，验证 double_tap 的连续输入。",
                lambda: controller.double_tap(640, 360, interval_seconds=0.3, serial=serial),
            ),
            ExperimentStep(
                "中心长按",
                "在中心点长按 1.6 秒，验证 long_press。",
                lambda: controller.long_press(640, 360, 1600, serial=serial),
            ),
            ExperimentStep(
                "右向左慢速大滑动",
                "从屏幕右侧滑到左侧，duration=2000ms，方便肉眼观察。",
                lambda: controller.swipe(1120, 360, 160, 360, 2000, serial=serial),
            ),
            ExperimentStep(
                "左向右慢速大滑动",
                "从屏幕左侧滑到右侧，duration=2000ms，验证反向滑动。",
                lambda: controller.swipe(160, 360, 1120, 360, 2000, serial=serial),
            ),
            ExperimentStep(
                "下向上慢速滚动",
                "从屏幕下方滑到上方，duration=2000ms，用于模拟列表向下翻页。",
                lambda: controller.swipe(640, 630, 640, 120, 2000, serial=serial),
            ),
            ExperimentStep(
                "上向下慢速滚动",
                "从屏幕上方滑到下方，duration=2000ms，用于模拟列表回滚。",
                lambda: controller.swipe(640, 120, 640, 630, 2000, serial=serial),
            ),
            ExperimentStep(
                "对角拖拽",
                "从左上区域拖拽到右下区域，验证 drag 封装。",
                lambda: controller.drag(180, 150, 1100, 590, 2200, serial=serial),
            ),
            ExperimentStep(
                "返回键",
                "发送 KEYCODE_BACK，观察系统返回动作。",
                lambda: controller.press_back(serial=serial),
            ),
            ExperimentStep(
                "创建模拟器端目录",
                "在 /sdcard/AzurLaneResearchTracker 下创建实验目录。",
                lambda: controller.run_adb(["shell", "mkdir", "-p", remote_dir], serial=serial, timeout=5),
            ),
            ExperimentStep(
                "Push 文件到模拟器",
                "把本地 marker 文件推送到 /sdcard，验证截图以外的文件传输链路。",
                lambda: controller.transfer_to_device(local_marker, remote_marker, serial=serial),
            ),
            ExperimentStep(
                "Pull 文件回工作区",
                "把刚推送的 marker 拉回本地，验证回传链路。",
                lambda: controller.transfer_from_device(remote_marker, pulled_marker, serial=serial),
            ),
            ExperimentStep(
                "连续操作接口",
                "一次性执行 wait → tap → swipe → screenshot，验证连续编排能力。",
                lambda: controller.run_operations(
                    [
                        {"action": "wait", "seconds": 0.4},
                        {"action": "tap", "x": 640, "y": 360, "post_delay": 0.5},
                        {
                            "action": "swipe",
                            "start_x": 1000,
                            "start_y": 580,
                            "end_x": 280,
                            "end_y": 180,
                            "duration_ms": 1800,
                            "post_delay": 0.5,
                        },
                        {"action": "screenshot", "scene": RecognitionScene.HARBOR.value, "output_dir": str(run_dir / "frames")},
                    ],
                    serial=serial,
                    default_delay=0.2,
                ),
            ),
            ExperimentStep(
                "实验后截图",
                "保存动作完成后的屏幕，用于和实验前截图对比。",
                lambda: _capture_named(controller, serial, run_dir, "after_actions"),
            ),
            ExperimentStep(
                "清理模拟器端临时文件",
                "删除 /sdcard/AzurLaneResearchTracker/adb_local_marker.txt。",
                lambda: controller.remove_remote_file(remote_marker, serial=serial),
                required=False,
            ),
        ]
    )

    if settings.include_text_input:
        steps.insert(
            -2,
            ExperimentStep(
                "可选文本输入",
                "输入 ASCII 文本 Azur Lane OCR；仅在 ALRT_ADB_INCLUDE_TEXT=1 时执行。",
                lambda: controller.input_text("Azur Lane OCR", serial=serial),
            ),
        )

    return steps


# ============================================================
# 🧪 第四部分：真实模拟器实验用例
# ============================================================

def test_live_adb_control_experiment() -> None:
    """
    在真实模拟器上执行可观察 ADB 控制实验。
    输入：
        需要显式设置 ALRT_ADB_LIVE=1，否则默认 skip。
    输出：
        pytest 结果 + workdir/automation/adb_live_local_experiment/run_*/trace.json。
    使用示例：
        PowerShell:
        $env:ALRT_ADB_LIVE="1"; $env:ALRT_ADB_SIMULATOR="leidian"
        python -m pytest test/v060/adb/test_adb_live_local_experiment.py -s -q
    """
    if not _truthy_env(LIVE_FLAG_ENV):
        pytest.skip(f"真实模拟器实验默认跳过；设置 {LIVE_FLAG_ENV}=1 后才会执行 ADB 点击/滑动。")

    settings = LiveExperimentSettings.from_env()
    controller = _build_controller(settings.simulator_name)
    serial = _select_serial(controller, settings)
    run_dir = _make_run_dir()
    trace: list[dict[str, Any]] = []

    print("\nAzurLaneResearchTracker ADB 本地实机控制实验")
    print(f"项目根目录: {PathManager.get_project_root()}")
    print(f"实验输出目录: {run_dir}")
    print(f"模拟器配置: {settings.simulator_name}")
    print(f"设备 serial: {serial}")
    print("提示: 本测试会真实操作当前模拟器；请先确认模拟器界面处于可安全点击/滑动的状态。")

    steps = _build_steps(controller, serial, run_dir, settings)
    try:
        for index, step in enumerate(steps, start=1):
            _run_step(
                index,
                len(steps),
                step,
                controller=controller,
                serial=serial,
                settings=settings,
                trace=trace,
            )
    finally:
        summary = {
            "success": all(bool(item["result"].get("success", True)) or not item["required"] for item in trace),
            "simulator_name": settings.simulator_name,
            "serial": serial,
            "target_resolution": TARGET_RESOLUTION,
            "run_dir": str(run_dir.resolve()),
            "step_count": len(trace),
            "steps": trace,
        }
        _write_json(run_dir / "trace.json", summary)
        print(f"\n[ADB实验] trace 已保存: {run_dir / 'trace.json'}")
