#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        🎬 ADB 现场自动演示 (adb_live_full_demo.py)            ║
║                                                              ║
║  【一句话解释】自动连续演示当前 ADB 层已实现的主要模拟器操作。 ║
║  【类比理解】它像一段“试车动画”，不用按回车，会边提示边操作。  ║
║  【数据流说明】脚本步骤 → 模拟器通知提示 → ADB动作 → 结果日志。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import html
import http.server
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.automation.adb_controller import (  # noqa: E402
    AdbCommandResult,
    AdbController,
    AdbOperationSequenceResult,
)
from core.contracts import RecognitionScene  # noqa: E402
from core.utils.config_loader import get_config_loader  # noqa: E402
from core.utils.path_manager import PathManager  # noqa: E402


# ============================================================
# 🧱 第二部分：演示数据结构
# ============================================================

@dataclass(frozen=True)
class LiveDemoStep:
    """
    单个现场演示步骤。
    输入：
        title: 屏幕和终端显示的短标题。
        detail: 终端显示的说明。
        action: 真正执行的 ADB 调用。
    输出：
        run_live_demo 会按顺序执行这些步骤。
    使用示例：
        LiveDemoStep("中心点击", "点击 640,360", lambda: controller.tap(640, 360))
    """

    title: str
    detail: str
    action: Callable[[], object]


# ============================================================
# 🧰 第三部分：命令行与控制器辅助函数
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
    parser = argparse.ArgumentParser(description="AzurLaneResearchTracker ADB 现场自动演示")
    parser.add_argument("--serial", default="", help="指定 ADB 设备 serial；不填则单设备自动选择。")
    parser.add_argument("--simulator", default="", help="指定模拟器配置名，如 leidian/mumu；不填读取主配置。")
    parser.add_argument("--pause", type=float, default=1.2, help="每个动作后的观察等待秒数，默认 1.2。")
    parser.add_argument("--prompt-seconds", type=float, default=1.4, help="模拟器内提示停留秒数，默认 1.4。")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不执行真实 ADB 操作。")
    parser.add_argument(
        "--no-auto-connect",
        action="store_true",
        help="禁用无设备时的常见模拟器端口自动连接。",
    )
    parser.add_argument(
        "--connect-candidate",
        action="append",
        default=[],
        help="额外尝试 adb connect 的 serial，如 127.0.0.1:5555；可重复传入。",
    )
    parser.add_argument(
        "--device-message",
        choices=("auto", "notification", "browser", "none"),
        default="auto",
        help="模拟器内提示方式：auto 会先试通知栏，失败后用浏览器提示页。",
    )
    parser.add_argument(
        "--prompt-port",
        type=int,
        default=18765,
        help="browser 提示方式使用的本地 HTTP 端口，默认 18765。",
    )
    parser.add_argument(
        "--no-safe-home",
        action="store_true",
        help="默认会先回到安卓桌面以减少误触；加此参数则保持当前界面演示。",
    )
    parser.add_argument(
        "--include-game-navigation",
        action="store_true",
        help="额外执行 enter_research/enter_equipment 导航序列；需要游戏已在港区主页。",
    )
    parser.add_argument(
        "--no-settings-app",
        action="store_true",
        help="跳过安全的 Android 设置应用 start/stop 演示。",
    )
    return parser.parse_args()


def build_controller(simulator_name: str = "") -> AdbController:
    """
    根据项目模拟器配置创建 ADB 控制器。
    输入：
        simulator_name: 可选模拟器配置名。
    输出：
        AdbController。
    使用示例：
        controller = build_controller("leidian")
    """
    loader = get_config_loader()
    name = simulator_name or str(loader.get_main_config().get("current_simulator", "mumu") or "mumu")
    simulator_config = loader.get_simulator_config(name)
    return AdbController(simulator_config)


def choose_serial(controller: AdbController, args: argparse.Namespace) -> str:
    """
    选择一台可用 ADB 设备。
    输入：
        controller: ADB 控制器。
        args: 命令行参数。
    输出：
        选中的 serial。
    使用示例：
        serial = choose_serial(controller, args)
    """
    if args.dry_run:
        return args.serial or "DRY_RUN_DEVICE"

    connection = controller.check_connection(serial=args.serial or None)
    if connection.success and connection.selected_device is not None:
        return connection.selected_device.serial

    if not args.no_auto_connect:
        for candidate in build_connect_candidates(controller, args):
            print(f"[自动连接] 尝试 adb connect {candidate}")
            reconnect = controller.reconnect_device(candidate)
            print(f"[自动连接] {candidate}: {reconnect.status} {reconnect.stdout.strip() or reconnect.stderr.strip()}")
            connection = controller.check_connection(serial=candidate)
            if connection.success and connection.selected_device is not None:
                return connection.selected_device.serial

    print("\n[失败] 无法选择 ADB 设备")
    print(f"状态: {connection.status}")
    print(f"信息: {connection.message}")
    if connection.candidates:
        print("候选设备:")
        for device in connection.candidates:
            print(f"  - {device.serial} ({device.state})")
    raise SystemExit(2)


def build_connect_candidates(controller: AdbController, args: argparse.Namespace) -> list[str]:
    """
    构建模拟器 TCP 连接候选列表。
    输入：
        controller: ADB 控制器。
        args: 命令行参数。
    输出：
        去重后的 serial 列表。
    使用示例：
        candidates = build_connect_candidates(controller, args)
    """
    candidates: list[str] = []

    if args.serial and ":" in args.serial:
        candidates.append(args.serial)

    candidates.extend(str(item) for item in args.connect_candidate if item)

    port = controller.adb_config.get("port") if isinstance(controller.adb_config, dict) else None
    if port:
        candidates.append(f"127.0.0.1:{port}")

    simulator_type = str(controller.simulator_config.get("type", "") or "").lower()
    if simulator_type == "leidian":
        candidates.extend(("127.0.0.1:5555", "127.0.0.1:5554"))
    elif simulator_type == "mumu":
        candidates.extend(("127.0.0.1:7555", "127.0.0.1:7556"))

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


class BrowserPromptServer:
    """
    模拟器内浏览器提示页服务。
    输入：
        port: 本机 HTTP 端口。
    输出：
        通过 adb reverse 后，模拟器可访问当前步骤提示页。
    使用示例：
        server = BrowserPromptServer(18765)
        server.start()
    """

    def __init__(self, port: int) -> None:
        """初始化提示页服务。"""
        self.port = int(port)
        self.title = "ADB现场演示"
        self.detail = "准备开始"
        self.index = 0
        self.total = 0
        self._server: Optional[http.server.ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        """返回 HTTP 服务是否已启动。"""
        return self._server is not None

    def set_step(self, title: str, detail: str, index: int, total: int) -> None:
        """更新当前提示内容。"""
        self.title = title
        self.detail = detail
        self.index = index
        self.total = total

    def start(self) -> None:
        """启动本地 HTTP 服务。"""
        if self._server is not None:
            return

        owner = self

        class PromptHandler(http.server.BaseHTTPRequestHandler):
            """只返回当前步骤提示页的 HTTP handler。"""

            def do_GET(self) -> None:  # noqa: N802 - 标准库回调命名
                """返回当前步骤 HTML。"""
                content = owner.render_page().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, format: str, *args: object) -> None:
                """屏蔽 HTTP 访问日志，避免演示输出刷屏。"""
                return

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), PromptHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """关闭本地 HTTP 服务。"""
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None

    def render_page(self) -> str:
        """生成适合模拟器横屏观看的提示页。"""
        title = html.escape(self.title)
        detail = html.escape(self.detail)
        progress = f"{self.index}/{self.total}" if self.total else "ADB"
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ADB现场演示</title>
  <style>
    html, body {{
      margin: 0;
      width: 100%;
      height: 100%;
      background: linear-gradient(135deg, #101827, #243b6b);
      color: #f8fafc;
      font-family: sans-serif;
      overflow: hidden;
    }}
    .wrap {{
      box-sizing: border-box;
      width: 100%;
      height: 100%;
      padding: 72px 96px;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      text-align: center;
    }}
    .badge {{
      padding: 10px 28px;
      border-radius: 999px;
      background: rgba(34, 211, 238, 0.18);
      border: 2px solid rgba(125, 211, 252, 0.75);
      font-size: 34px;
      letter-spacing: 2px;
      margin-bottom: 34px;
    }}
    h1 {{
      margin: 0 0 28px;
      font-size: 64px;
      line-height: 1.18;
    }}
    p {{
      margin: 0;
      max-width: 980px;
      font-size: 34px;
      line-height: 1.45;
      color: #dbeafe;
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <div class="badge">AzurLaneResearchTracker · {progress}</div>
    <h1>{title}</h1>
    <p>{detail}</p>
  </main>
</body>
</html>"""


def print_result(result: object) -> None:
    """
    打印步骤结果摘要。
    输入：
        result: ADB 结果对象或普通对象。
    输出：
        终端日志。
    使用示例：
        print_result(controller.tap(640, 360))
    """
    if isinstance(result, AdbCommandResult):
        print(f"结果: success={result.success}, status={result.status}, returncode={result.returncode}")
        if result.stdout.strip():
            print(f"stdout: {result.stdout.strip()[:600]}")
        if result.stderr.strip():
            print(f"stderr: {result.stderr.strip()[:600]}")
        return

    if isinstance(result, AdbOperationSequenceResult):
        print(f"结果: success={result.success}, status={result.status}, steps={len(result.steps)}")
        for step in result.steps:
            print(f"  - {step.index}. {step.action}: success={step.success}, status={step.status}")
        return

    if hasattr(result, "success") and hasattr(result, "status"):
        print(f"结果: success={getattr(result, 'success')}, status={getattr(result, 'status')}")
        if hasattr(result, "message"):
            print(f"message: {getattr(result, 'message')}")
        artifact = getattr(result, "artifact", None)
        if artifact is not None:
            print(f"screenshot_path: {artifact.screenshot_path}")
        return

    print(f"结果: {result}")


# ============================================================
# 🔔 第四部分：模拟器内提示实现
# ============================================================

def show_step_on_device(
    controller: AdbController,
    serial: str,
    step: LiveDemoStep,
    *,
    index: int,
    total: int,
    args: argparse.Namespace,
    prompt_server: Optional[BrowserPromptServer],
) -> None:
    """
    在模拟器内提示当前步骤。
    输入：
        controller/serial/step/index/total/args/prompt_server。
    输出：
        尽量用系统通知栏显示；失败不阻塞主流程。
    使用示例：
        show_step_on_device(controller, serial, step, index=1, total=10, args=args, prompt_server=server)
    """
    if args.dry_run or args.device_message == "none":
        return

    method = str(args.device_message)
    notification_unavailable = bool(getattr(args, "_notification_unavailable", False))
    if method == "notification" or (method == "auto" and not notification_unavailable):
        message = f"{index}/{total} {step.title}"
        result = controller.show_notification(
            message,
            title="ADB现场演示",
            tag="azurlane_adb_live_demo",
            expand=True,
            serial=serial,
        )
        if result.success:
            time.sleep(max(0.0, float(args.prompt_seconds)))
            collapse_notification_panel(controller, serial)
            return
        setattr(args, "_notification_unavailable", True)
        if method == "notification":
            print(f"[提示] 模拟器通知显示失败，将只保留终端提示: {result.status}")
            return
        print(f"[提示] 当前系统不支持通知栏提示，切换到浏览器提示页: {result.status}")

    if method in {"auto", "browser"}:
        shown = show_browser_prompt(controller, serial, step, index=index, total=total, args=args, prompt_server=prompt_server)
        if not shown:
            print("[提示] 浏览器提示页显示失败，将只保留终端提示。")


def collapse_notification_panel(controller: AdbController, serial: str) -> None:
    """
    收起通知栏，避免后续点击落在通知面板上。
    输入：
        controller/serial。
    输出：
        不支持 collapse 命令时用返回键兜底。
    使用示例：
        collapse_notification_panel(controller, "emulator-5554")
    """
    result = controller.run_adb(["shell", "cmd", "statusbar", "collapse"], serial=serial, timeout=3)
    if not result.success:
        controller.press_back(serial=serial)


def show_browser_prompt(
    controller: AdbController,
    serial: str,
    step: LiveDemoStep,
    *,
    index: int,
    total: int,
    args: argparse.Namespace,
    prompt_server: Optional[BrowserPromptServer],
) -> bool:
    """
    用模拟器浏览器显示当前步骤提示。
    输入：
        controller/serial/step/index/total/args/prompt_server。
    输出：
        是否成功发起浏览器提示页。
    使用示例：
        show_browser_prompt(controller, serial, step, index=1, total=10, args=args, prompt_server=server)
    """
    if prompt_server is None:
        return False
    try:
        prompt_server.set_step(step.title, step.detail, index, total)
        prompt_server.start()
    except OSError as exc:
        print(f"[提示] 本地提示页服务启动失败: {exc}")
        return False

    reverse_result = controller.run_adb(
        ["reverse", f"tcp:{prompt_server.port}", f"tcp:{prompt_server.port}"],
        serial=serial,
        timeout=5,
    )
    if not reverse_result.success:
        print(f"[提示] adb reverse 失败: {reverse_result.status}")
        return False

    url = f"http://127.0.0.1:{prompt_server.port}/?step={index}&ts={int(time.time() * 1000)}"
    result = controller.run_adb(
        [
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            url,
            "-p",
            "com.android.browser",
        ],
        serial=serial,
        timeout=5,
    )
    if not result.success:
        result = controller.run_adb(
            ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url],
            serial=serial,
            timeout=5,
        )
    if not result.success:
        print(f"[提示] 浏览器启动失败: {result.status} {result.stderr.strip() or result.stdout.strip()}")
        return False

    time.sleep(max(0.0, float(args.prompt_seconds)))
    controller.press_home(serial=serial)
    return True


def announce_without_step_count(
    controller: AdbController,
    serial: str,
    message: str,
    *,
    args: argparse.Namespace,
) -> None:
    """
    在演示开始/结束时显示模拟器提示。
    输入：
        controller/serial/message/args。
    输出：
        通知栏提示。
    使用示例：
        announce_without_step_count(controller, serial, "演示完成", args=args)
    """
    if args.dry_run or args.device_message == "none":
        return
    controller.show_notification(message, title="ADB现场演示", tag="azurlane_adb_live_demo", expand=True, serial=serial)


# ============================================================
# 🧪 第五部分：具体 ADB 演示动作
# ============================================================

def run_corner_taps(controller: AdbController, serial: str) -> AdbCommandResult:
    """
    依次点击四角和中心点。
    输入：
        controller/serial。
    输出：
        最后一次点击结果；中途失败则立即返回失败。
    使用示例：
        result = run_corner_taps(controller, serial)
    """
    points = ((90, 90), (1190, 90), (1190, 630), (90, 630), (640, 360))
    last_result = AdbCommandResult(True, "ok", "尚未执行。")
    for x, y in points:
        last_result = controller.tap(x, y, serial=serial)
        time.sleep(0.45)
        if not last_result.success:
            return last_result
    return last_result


def push_marker_file(
    controller: AdbController,
    serial: str,
    local_marker: Path,
    remote_marker: str,
) -> AdbCommandResult:
    """
    创建本地标记文件并推送到模拟器。
    输入：
        controller/serial/local_marker/remote_marker。
    输出：
        adb push 结果。
    使用示例：
        push_marker_file(controller, serial, Path("a.txt"), "/sdcard/a.txt")
    """
    local_marker.parent.mkdir(parents=True, exist_ok=True)
    local_marker.write_text("AzurLaneResearchTracker ADB live demo marker\n", encoding="utf-8")
    return controller.transfer_to_device(local_marker, remote_marker, serial=serial)


def capture_remote_then_pull(
    controller: AdbController,
    serial: str,
    remote_screen: str,
    pulled_screen: Path,
) -> AdbCommandResult:
    """
    在模拟器端截图到 /sdcard，再拉回本地工作区。
    输入：
        controller/serial/remote_screen/pulled_screen。
    输出：
        adb pull 结果。
    使用示例：
        capture_remote_then_pull(controller, serial, "/sdcard/a.png", Path("a.png"))
    """
    capture = controller.run_adb(["shell", "screencap", "-p", remote_screen], serial=serial, timeout=10)
    if not capture.success:
        return capture
    return controller.transfer_from_device(remote_screen, pulled_screen, serial=serial)


def cleanup_remote_files(
    controller: AdbController,
    serial: str,
    *remote_paths: str,
) -> AdbCommandResult:
    """
    清理模拟器端演示文件。
    输入：
        controller/serial/remote_paths。
    输出：
        最后一个 rm 结果；中途失败会返回失败结果。
    使用示例：
        cleanup_remote_files(controller, serial, "/sdcard/a.txt")
    """
    last_result = AdbCommandResult(True, "ok", "没有需要清理的远端文件。")
    for remote_path in remote_paths:
        last_result = controller.remove_remote_file(remote_path, serial=serial)
        if not last_result.success:
            return last_result
    return last_result


def safe_text_input_probe(controller: AdbController, serial: str) -> AdbCommandResult:
    """
    尝试让文本输入有可见落点，再发送 input text。
    输入：
        controller/serial。
    输出：
        adb input text 结果。
    使用示例：
        safe_text_input_probe(controller, serial)
    """
    controller.press_home(serial=serial)
    time.sleep(0.6)
    controller.keyevent("KEYCODE_SEARCH", serial=serial)
    time.sleep(0.8)
    result = controller.input_text("Azur Lane OCR", serial=serial)
    time.sleep(0.6)
    controller.press_back(serial=serial)
    return result


def fake_scene_probe(target_scene: Optional[RecognitionScene] = None) -> bool:
    """
    演示用页面探针。
    输入：
        target_scene: 目标页面。
    输出：
        始终返回 True，仅验证导航序列执行接口，不依赖 OCR。
    使用示例：
        controller.run_sequence("go_harbor", fake_scene_probe)
    """
    return target_scene is not None


def build_steps(
    controller: AdbController,
    serial: str,
    args: argparse.Namespace,
    demo_dir: Path,
) -> list[LiveDemoStep]:
    """
    构建现场演示步骤列表。
    输入：
        controller/serial/args/demo_dir。
    输出：
        LiveDemoStep 列表。
    使用示例：
        steps = build_steps(controller, serial, args, demo_dir)
    """
    local_marker = demo_dir / "adb_live_marker.txt"
    pulled_marker = demo_dir / "adb_live_marker_from_device.txt"
    remote_marker = "/sdcard/AzurLaneResearchTracker/adb_live_marker.txt"
    remote_screen = "/sdcard/AzurLaneResearchTracker/adb_live_screen.png"
    pulled_screen = demo_dir / "adb_live_screen_pull.png"

    steps: list[LiveDemoStep] = [
        LiveDemoStep(
            "连接状态检查",
            "检查 ADB 路径、serial 和设备状态。",
            lambda: controller.check_connection(serial=serial),
        ),
        LiveDemoStep(
            "显示环境检查",
            "检查推荐分辨率 1280x720、density 和平板模式信息。",
            lambda: controller.check_display_environment(serial=serial),
        ),
        LiveDemoStep(
            "读取屏幕信息",
            "执行 wm size / wm density，确认坐标缩放基准。",
            lambda: controller.get_screen_info(serial=serial),
        ),
        LiveDemoStep(
            "查询当前前台窗口",
            "执行 dumpsys window windows，供后续 OCR/流程判断参考。",
            lambda: controller.get_foreground_activity(serial=serial),
        ),
        LiveDemoStep(
            "exec-out 截图保存",
            "优先使用 exec-out screencap -p，失败时控制器会走 pull fallback。",
            lambda: controller.capture_screenshot(RecognitionScene.HARBOR, serial=serial, output_dir=demo_dir),
        ),
        LiveDemoStep(
            "远端截图后 pull 回本地",
            "先把截图写到 /sdcard，再 adb pull 到工作区，验证截图传输链路。",
            lambda: capture_remote_then_pull(controller, serial, remote_screen, pulled_screen),
        ),
        LiveDemoStep(
            "推送文本文件到模拟器",
            "创建本地 marker 文件，并 push 到 /sdcard/AzurLaneResearchTracker。",
            lambda: push_marker_file(controller, serial, local_marker, remote_marker),
        ),
        LiveDemoStep(
            "从模拟器拉回文本文件",
            "把刚才的 marker 文件 pull 回工作区，验证文件回传。",
            lambda: controller.transfer_from_device(remote_marker, pulled_marker, serial=serial),
        ),
        LiveDemoStep(
            "Home 按键",
            "发送 KEYCODE_HOME，让后续大幅手势尽量落在安全桌面区域。",
            lambda: controller.press_home(serial=serial),
        ),
        LiveDemoStep(
            "返回按键",
            "发送 KEYCODE_BACK，验证基础按键输入。",
            lambda: controller.press_back(serial=serial),
        ),
        LiveDemoStep(
            "菜单按键",
            "发送 KEYCODE_MENU，部分模拟器可能无明显视觉反馈，但命令链路会记录。",
            lambda: controller.press_menu(serial=serial),
        ),
        LiveDemoStep(
            "四角与中心点击",
            "依次点击左上、右上、右下、左下、中心，验证坐标覆盖。",
            lambda: run_corner_taps(controller, serial),
        ),
        LiveDemoStep(
            "中心双击",
            "在 1280x720 基准下双击中心点 640,360。",
            lambda: controller.double_tap(640, 360, interval_seconds=0.25, serial=serial),
        ),
        LiveDemoStep(
            "中心长按",
            "用同点 swipe 模拟 1.6 秒长按。",
            lambda: controller.long_press(640, 360, 1600, serial=serial),
        ),
        LiveDemoStep(
            "右向左大幅滑动",
            "慢速横向滑动，适合观察页面/桌面翻页效果。",
            lambda: controller.swipe(1120, 360, 160, 360, 1800, serial=serial),
        ),
        LiveDemoStep(
            "左向右大幅滑动",
            "慢速横向滑动，返回上一页/桌面页。",
            lambda: controller.swipe(160, 360, 1120, 360, 1800, serial=serial),
        ),
        LiveDemoStep(
            "下向上大幅滑动",
            "慢速纵向滑动，验证竖向滚动。",
            lambda: controller.swipe(640, 630, 640, 120, 1800, serial=serial),
        ),
        LiveDemoStep(
            "上向下大幅滑动",
            "慢速纵向滑动，验证反向滚动。",
            lambda: controller.swipe(640, 120, 640, 630, 1800, serial=serial),
        ),
        LiveDemoStep(
            "对角拖拽",
            "从左上区域拖到右下区域，验证 drag 封装。",
            lambda: controller.drag(180, 150, 1100, 590, 2000, serial=serial),
        ),
        LiveDemoStep(
            "文本输入命令",
            "尝试触发搜索焦点后输入 Azur Lane OCR；若桌面不支持搜索，命令仍会被验证。",
            lambda: safe_text_input_probe(controller, serial),
        ),
        LiveDemoStep(
            "连续操作接口",
            "通过 run_operations 连续执行 wait、tap、swipe、screenshot，验证流水线能力。",
            lambda: controller.run_operations(
                [
                    {"action": "wait", "seconds": 0.4},
                    {"action": "tap", "x": 640, "y": 360, "post_delay": 0.5},
                    {
                        "action": "swipe",
                        "start_x": 1000,
                        "start_y": 580,
                        "end_x": 260,
                        "end_y": 180,
                        "duration_ms": 1500,
                        "post_delay": 0.5,
                    },
                    {"action": "screenshot", "scene": RecognitionScene.HARBOR.value, "output_dir": str(demo_dir)},
                ],
                serial=serial,
                default_delay=0.2,
            ),
        ),
        LiveDemoStep(
            "导航序列 go_harbor",
            "读取 config/automation/sequences.json 并执行 go_harbor；scene_probe 为演示注入。",
            lambda: controller.run_sequence("go_harbor", fake_scene_probe, serial=serial),
        ),
        LiveDemoStep(
            "导航序列 return_home",
            "读取配置并执行 return_home，验证返回主页序列接口。",
            lambda: controller.run_sequence("return_home", fake_scene_probe, serial=serial),
        ),
        LiveDemoStep(
            "清理模拟器端文件",
            "删除演示写入的 /sdcard 临时文件。",
            lambda: cleanup_remote_files(controller, serial, remote_marker, remote_screen),
        ),
    ]

    if not args.no_settings_app:
        settings_steps = [
            LiveDemoStep(
                "启动 Android 设置",
                "用 start_app 启动 com.android.settings，验证应用启动封装。",
                lambda: controller.start_app("com.android.settings", serial=serial),
            ),
            LiveDemoStep(
                "停止 Android 设置",
                "用 stop_app 停止 com.android.settings，验证应用停止封装。",
                lambda: controller.stop_app("com.android.settings", serial=serial),
            ),
        ]
        steps[9:9] = settings_steps

    if args.include_game_navigation:
        game_steps = [
            LiveDemoStep(
                "游戏导航 enter_research",
                "执行进入科研页序列；需要当前游戏在可识别港区主页，否则可能只是普通点击。",
                lambda: controller.run_sequence("enter_research", fake_scene_probe, serial=serial),
            ),
            LiveDemoStep(
                "游戏导航 enter_equipment",
                "执行进入装备仓库序列；需要当前游戏在可识别港区主页，否则可能只是普通点击。",
                lambda: controller.run_sequence("enter_equipment", fake_scene_probe, serial=serial),
            ),
        ]
        steps[-1:-1] = game_steps

    return steps


# ============================================================
# 🚀 第六部分：演示主流程
# ============================================================

def run_live_demo(args: argparse.Namespace) -> int:
    """
    执行完整现场演示。
    输入：
        args: 命令行参数。
    输出：
        进程退出码。
    使用示例：
        raise SystemExit(run_live_demo(parse_args()))
    """
    controller = build_controller(args.simulator)
    serial = choose_serial(controller, args)
    demo_dir = PathManager.get_work_dir() / "automation" / "adb_live_demo"
    demo_dir.mkdir(parents=True, exist_ok=True)

    print("AzurLaneResearchTracker ADB 现场自动演示")
    print(f"项目根目录: {PathManager.get_project_root()}")
    print(f"演示输出目录: {demo_dir}")
    print(f"设备 serial: {serial}")
    print("提示: 本脚本会自动连续执行，不需要按 Enter。当前步骤会尽量显示在模拟器内。")
    if args.device_message == "auto":
        print("模拟器内提示: auto（通知栏不可用时自动改用浏览器提示页）。")

    if not args.dry_run:
        controller.run_adb(["shell", "mkdir", "-p", "/sdcard/AzurLaneResearchTracker"], serial=serial, timeout=5)
        if not args.no_safe_home:
            controller.press_home(serial=serial)
            time.sleep(0.8)

    steps = build_steps(controller, serial, args, demo_dir)
    prompt_server = None if args.device_message in {"notification", "none"} else BrowserPromptServer(args.prompt_port)
    announce_without_step_count(controller, serial, "ADB 现场演示开始。请看模拟器通知栏和动作。", args=args)

    try:
        for index, step in enumerate(steps, start=1):
            print(f"\n===== {index}/{len(steps)} {step.title} =====")
            print(step.detail)
            show_step_on_device(
                controller,
                serial,
                step,
                index=index,
                total=len(steps),
                args=args,
                prompt_server=prompt_server,
            )
            if args.dry_run:
                print("[DRY-RUN] 已跳过真实 ADB 调用。")
                continue
            result = step.action()
            print_result(result)
            time.sleep(max(0.0, float(args.pause)))
    except KeyboardInterrupt:
        print("\n用户中止演示。")
        announce_without_step_count(controller, serial, "ADB 现场演示已中止。", args=args)
        return 130
    finally:
        if prompt_server is not None:
            if not args.dry_run and prompt_server.running:
                controller.run_adb(["reverse", "--remove", f"tcp:{prompt_server.port}"], serial=serial, timeout=5)
            prompt_server.stop()

    announce_without_step_count(controller, serial, "ADB 现场演示完成。截图和拉取文件已保存到工作区。", args=args)
    print("\n演示完成。")
    print(f"可检查输出目录: {demo_dir}")
    return 0


def main() -> int:
    """
    命令行入口。
    输入：
        无。
    输出：
        进程退出码。
    使用示例：
        python test/v060/adb/adb_live_full_demo.py
    """
    return run_live_demo(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
