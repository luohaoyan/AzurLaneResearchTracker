#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🎮 ADB 交互式操作演示 (adb_interactive_demo.py)      ║
║                                                              ║
║  【一句话解释】逐步演示点击、滑动、截图和文件传输等 ADB 操作。 ║
║  【类比理解】它像手动试车清单，每按一次回车才执行下一项。      ║
║  【数据流说明】终端提示 → 回车确认 → ADB 操作 → 结果输出。     ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import sys
import time
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.automation.adb_controller import AdbCommandResult, AdbController
from core.contracts import RecognitionScene
from core.utils.config_loader import get_config_loader
from core.utils.path_manager import PathManager


# ============================================================
# 🧰 第二部分：演示辅助函数
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。
    输入：
        终端参数。
    输出：
        argparse.Namespace。
    使用示例：
        args = parse_args()
    """
    parser = argparse.ArgumentParser(description="AzurLaneResearchTracker ADB 交互式操作演示")
    parser.add_argument("--serial", default="", help="指定 ADB 设备 serial；不填则单设备自动选择。")
    parser.add_argument("--simulator", default="", help="指定模拟器配置名，如 mumu/leidian；不填读取 config.json。")
    parser.add_argument("--auto", action="store_true", help="自动继续每一步，用于快速自测。")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不执行真实 ADB 操作。")
    parser.add_argument("--pause", type=float, default=0.8, help="每个动作后的观察等待秒数，默认 0.8。")
    parser.add_argument(
        "--device-message",
        choices=("notification", "none"),
        default="notification",
        help="是否尝试在模拟器通知栏显示当前动作。",
    )
    return parser.parse_args()


def build_controller(simulator_name: str = "") -> AdbController:
    """
    根据配置创建 ADB 控制器。
    输入：
        simulator_name: 可选配置名。
    输出：
        AdbController。
    使用示例：
        controller = build_controller("leidian")
    """
    loader = get_config_loader()
    name = simulator_name or str(loader.get_main_config().get("current_simulator", "mumu") or "mumu")
    simulator_config = loader.get_simulator_config(name)
    return AdbController(simulator_config)


def choose_serial(controller: AdbController, requested_serial: str, dry_run: bool) -> str:
    """
    选择 ADB 设备。
    输入：
        controller: ADB 控制器。
        requested_serial: 用户指定 serial。
        dry_run: 是否演练模式。
    输出：
        选中的 serial。
    使用示例：
        serial = choose_serial(controller, "", False)
    """
    if dry_run:
        return requested_serial or "DRY_RUN_DEVICE"
    connection = controller.check_connection(serial=requested_serial or None)
    if not connection.success or connection.selected_device is None:
        print("\n[失败] 无法选择 ADB 设备")
        print(f"状态: {connection.status}")
        print(f"信息: {connection.message}")
        if connection.candidates:
            print("候选设备:")
            for device in connection.candidates:
                print(f"  - {device.serial} ({device.state})")
        raise SystemExit(2)
    return connection.selected_device.serial


def wait_for_enter(title: str, auto: bool) -> None:
    """
    等待用户确认。
    输入：
        title: 当前步骤标题；auto: 是否自动继续。
    输出：
        无。
    使用示例：
        wait_for_enter("准备点击", False)
    """
    if auto:
        print(f"[AUTO] {title}")
        return
    input(f"\n[下一步] {title}\n按 Enter 执行，或 Ctrl+C 停止...")


def show_device_message(
    controller: AdbController,
    serial: str,
    message: str,
    *,
    enabled: bool,
    dry_run: bool,
) -> None:
    """
    尝试在模拟器端显示当前动作。
    输入：
        controller/serial/message/enabled/dry_run。
    输出：
        通知栏显示失败不会中断演示。
    使用示例：
        show_device_message(controller, serial, "正在滑动", enabled=True, dry_run=False)
    """
    if not enabled or dry_run:
        return
    safe_message = message.replace('"', "'")
    result = controller.run_adb(
        [
            "shell",
            "cmd",
            "notification",
            "post",
            "-S",
            "bigtext",
            "-t",
            "ADB演示",
            "azurlane_adb_demo",
            safe_message,
        ],
        serial=serial,
        timeout=3,
    )
    if result.success:
        controller.run_adb(["shell", "cmd", "statusbar", "expand-notifications"], serial=serial, timeout=3)


def run_step(
    index: int,
    total: int,
    title: str,
    action: Callable[[], object],
    *,
    controller: AdbController,
    serial: str,
    args: argparse.Namespace,
    dry_description: str,
) -> object:
    """
    执行单个演示步骤。
    输入：
        index/total/title/action/controller/serial/args/dry_description。
    输出：
        action 返回值。
    使用示例：
        run_step(1, 10, "点击中心", lambda: controller.tap(640, 360), ...)
    """
    label = f"{index}/{total} {title}"
    print(f"\n===== {label} =====")
    print(f"工作区提示: {title}")
    show_device_message(
        controller,
        serial,
        label,
        enabled=args.device_message == "notification",
        dry_run=args.dry_run,
    )
    wait_for_enter(title, args.auto)
    if args.dry_run:
        print(f"[DRY-RUN] {dry_description}")
        return None
    result = action()
    print_result(result)
    time.sleep(max(0.0, float(args.pause)))
    return result


def print_result(result: object) -> None:
    """
    打印步骤结果。
    输入：
        result: ADB 命令结果或其他对象。
    输出：
        终端摘要。
    使用示例：
        print_result(controller.tap(640, 360))
    """
    if isinstance(result, AdbCommandResult):
        print(f"结果: success={result.success}, status={result.status}, returncode={result.returncode}")
        if result.stdout.strip():
            print(f"stdout: {result.stdout.strip()[:500]}")
        if result.stderr.strip():
            print(f"stderr: {result.stderr.strip()[:500]}")
        return
    if hasattr(result, "success") and hasattr(result, "status"):
        print(f"结果: success={getattr(result, 'success')}, status={getattr(result, 'status')}")
        if hasattr(result, "message"):
            print(f"message: {getattr(result, 'message')}")
        if hasattr(result, "artifact") and getattr(result, "artifact") is not None:
            print(f"screenshot_path: {getattr(result, 'artifact').screenshot_path}")
        return
    print(f"结果: {result}")


def ensure_remote_demo_dir(controller: AdbController, serial: str, dry_run: bool) -> None:
    """确保模拟器端演示目录存在。"""
    if dry_run:
        return
    controller.run_adb(["shell", "mkdir", "-p", "/sdcard/AzurLaneResearchTracker"], serial=serial, timeout=5)


# ============================================================
# 🚀 第三部分：演示主流程
# ============================================================

def main() -> int:
    """
    执行交互式 ADB 演示。
    输入：
        命令行参数。
    输出：
        进程退出码。
    使用示例：
        python test/v060/adb/adb_interactive_demo.py
    """
    args = parse_args()
    controller = build_controller(args.simulator)
    serial = choose_serial(controller, args.serial, args.dry_run)
    demo_dir = PathManager.get_work_dir() / "automation" / "adb_demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    local_marker = demo_dir / "adb_demo_marker.txt"
    pulled_marker = demo_dir / "adb_demo_marker_from_device.txt"
    remote_marker = "/sdcard/AzurLaneResearchTracker/adb_demo_marker.txt"
    remote_screen = "/sdcard/AzurLaneResearchTracker/adb_demo_screen.png"
    pulled_screen = demo_dir / "adb_demo_screen_pull.png"

    print("AzurLaneResearchTracker ADB 交互式演示")
    print(f"项目根目录: {PathManager.get_project_root()}")
    print(f"演示输出目录: {demo_dir}")
    print(f"设备 serial: {serial}")
    print("提示: 每一步会先说明动作，按 Enter 后才继续。请确认模拟器当前界面可以被安全点击/滑动。")

    ensure_remote_demo_dir(controller, serial, args.dry_run)

    steps: list[tuple[str, Callable[[], object], str]] = [
        (
            "读取屏幕信息，确认 1280x720 推荐环境",
            lambda: controller.get_screen_info(serial=serial),
            "adb shell wm size && adb shell wm density",
        ),
        (
            "截图并保存到 workdir/automation/adb_demo",
            lambda: controller.capture_screenshot(RecognitionScene.HARBOR, serial=serial, output_dir=demo_dir),
            "exec-out screencap -p，失败时 shell screencap + pull",
        ),
        (
            "大幅度横向滑动：从右向左",
            lambda: controller.swipe(1120, 360, 160, 360, 1500, serial=serial),
            "adb shell input swipe 1120 360 160 360 1500",
        ),
        (
            "大幅度横向滑动：从左向右",
            lambda: controller.swipe(160, 360, 1120, 360, 1500, serial=serial),
            "adb shell input swipe 160 360 1120 360 1500",
        ),
        (
            "大幅度纵向滑动：从下向上",
            lambda: controller.swipe(640, 620, 640, 120, 1500, serial=serial),
            "adb shell input swipe 640 620 640 120 1500",
        ),
        (
            "大幅度纵向滑动：从上向下",
            lambda: controller.swipe(640, 120, 640, 620, 1500, serial=serial),
            "adb shell input swipe 640 120 640 620 1500",
        ),
        (
            "中心长按 1.4 秒",
            lambda: controller.long_press(640, 360, 1400, serial=serial),
            "adb shell input swipe 640 360 640 360 1400",
        ),
        (
            "中心双击",
            lambda: controller.double_tap(640, 360, serial=serial),
            "adb shell input tap 640 360，两次",
        ),
        (
            "对角拖拽：左上到右下",
            lambda: controller.drag(160, 140, 1120, 600, 1800, serial=serial),
            "adb shell input swipe 160 140 1120 600 1800",
        ),
        (
            "四角点击，验证坐标覆盖范围",
            lambda: run_corner_taps(controller, serial),
            "依次 tap 左上/右上/右下/左下/中心",
        ),
        (
            "发送返回键 KEYCODE_BACK",
            lambda: controller.press_back(serial=serial),
            "adb shell input keyevent KEYCODE_BACK",
        ),
        (
            "创建并 push 文本文件到模拟器",
            lambda: push_marker_file(controller, serial, local_marker, remote_marker),
            f"adb push {local_marker} {remote_marker}",
        ),
        (
            "从模拟器 pull 文本文件回工作区",
            lambda: controller.transfer_from_device(remote_marker, pulled_marker, serial=serial),
            f"adb pull {remote_marker} {pulled_marker}",
        ),
        (
            "远端截图到 /sdcard 后 pull 回工作区",
            lambda: capture_remote_then_pull(controller, serial, remote_screen, pulled_screen),
            f"adb shell screencap -p {remote_screen} && adb pull {remote_screen} {pulled_screen}",
        ),
        (
            "清理模拟器端演示文件",
            lambda: cleanup_remote_files(controller, serial, remote_marker, remote_screen),
            "adb shell rm -f 演示文件",
        ),
    ]

    total = len(steps)
    try:
        for index, (title, action, dry_description) in enumerate(steps, start=1):
            run_step(
                index,
                total,
                title,
                action,
                controller=controller,
                serial=serial,
                args=args,
                dry_description=dry_description,
            )
    except KeyboardInterrupt:
        print("\n用户中止演示。")
        return 130

    print("\n演示完成。")
    print(f"可检查输出目录: {demo_dir}")
    return 0


def run_corner_taps(controller: AdbController, serial: str) -> AdbCommandResult:
    """依次点击四角和中心。"""
    points = ((80, 80), (1200, 80), (1200, 640), (80, 640), (640, 360))
    last_result = AdbCommandResult(True, "ok", "尚未执行。")
    for x, y in points:
        last_result = controller.tap(x, y, serial=serial)
        time.sleep(0.35)
        if not last_result.success:
            return last_result
    return last_result


def push_marker_file(
    controller: AdbController,
    serial: str,
    local_marker: Path,
    remote_marker: str,
) -> AdbCommandResult:
    """创建本地标记文件并推送到模拟器。"""
    local_marker.write_text("AzurLaneResearchTracker ADB demo marker\n", encoding="utf-8")
    return controller.transfer_to_device(local_marker, remote_marker, serial=serial)


def capture_remote_then_pull(
    controller: AdbController,
    serial: str,
    remote_screen: str,
    pulled_screen: Path,
) -> AdbCommandResult:
    """在模拟器端截图后拉回工作区。"""
    capture = controller.run_adb(["shell", "screencap", "-p", remote_screen], serial=serial, timeout=10)
    if not capture.success:
        return capture
    return controller.transfer_from_device(remote_screen, pulled_screen, serial=serial)


def cleanup_remote_files(
    controller: AdbController,
    serial: str,
    remote_marker: str,
    remote_screen: str,
) -> AdbCommandResult:
    """清理模拟器端演示文件。"""
    marker_result = controller.remove_remote_file(remote_marker, serial=serial)
    screen_result = controller.remove_remote_file(remote_screen, serial=serial)
    return screen_result if screen_result.success else marker_result


if __name__ == "__main__":
    raise SystemExit(main())
