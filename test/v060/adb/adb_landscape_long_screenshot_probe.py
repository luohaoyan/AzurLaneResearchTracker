#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║       🧪 横屏长截图能力探测 (adb_landscape_long_screenshot)  ║
║                                                              ║
║  【一句话解释】在雷电模拟器横屏环境下探测原生长截图和分帧采集。║
║  【类比理解】它像先找“全景相机”，找不到就用稳定连拍轨道。     ║
║  【数据流说明】ADB探测 → viewport截图 → 慢速滚动 → 采集报告。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.automation.adb_controller import AdbCommandResult, AdbController
from core.contracts import RecognitionScene
from core.utils.config_loader import get_config_loader
from core.utils.path_manager import PathManager


# ============================================================
# 🎛️ 第二部分：PyCharm 直接运行配置区
# ============================================================

# 说明：
# 1. 你在 PyCharm 里直接右键运行本脚本时，会读取下面这些默认值。
# 2. 默认会真实执行，但开始前会停在 input()，每一步也会停顿，方便你打断点和观察模拟器。
# 3. 如果只想看说明不操作模拟器，把 PYCHARM_EXECUTE 改成 False。

PYCHARM_EXECUTE = True
PYCHARM_SIMULATOR = "leidian"
PYCHARM_SERIAL = ""
PYCHARM_FRAMES = 6
PYCHARM_OVERLAP_RATIO = 0.35
PYCHARM_SCROLL_STEP_PX = 0
PYCHARM_DURATION_MS = 1800
PYCHARM_PAUSE_SECONDS = 1.0
PYCHARM_MANUAL_STEP = True
PYCHARM_START_CONFIRM = True
PYCHARM_SHOW_NOTICE = True
PYCHARM_STITCH_PREVIEW = True
PYCHARM_TRY_SYSRQ = False


# ============================================================
# 🧱 第三部分：命令行参数和基础工具
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析横屏长截图探测脚本参数。
    输入：
        终端命令行参数。
    输出：
        argparse.Namespace。
    使用示例：
        args = parse_args()
    """
    parser = argparse.ArgumentParser(description="雷电模拟器横屏长截图能力探测脚本")
    parser.add_argument("--execute", action="store_true", default=PYCHARM_EXECUTE, help="真实执行 ADB 探测、截图和滚动。")
    parser.add_argument("--dry-run", action="store_true", help="只打印说明，不操作模拟器。")
    parser.add_argument("--simulator", default=PYCHARM_SIMULATOR, help="模拟器配置名，默认读取脚本顶部 PYCHARM_SIMULATOR。")
    parser.add_argument("--serial", default=PYCHARM_SERIAL, help="指定 ADB serial；多设备时建议传入，如 127.0.0.1:5555。")
    parser.add_argument("--frames", type=int, default=PYCHARM_FRAMES, help="分帧采集帧数。")
    parser.add_argument("--overlap-ratio", type=float, default=PYCHARM_OVERLAP_RATIO, help="帧间重叠比例。")
    parser.add_argument("--scroll-step-px", type=int, default=PYCHARM_SCROLL_STEP_PX, help="显式滚动步长；0 表示按 720*(1-overlap) 计算。")
    parser.add_argument("--duration-ms", type=int, default=PYCHARM_DURATION_MS, help="每次滚动 duration，数值越大越慢。")
    parser.add_argument("--pause", type=float, default=PYCHARM_PAUSE_SECONDS, help="每帧动作后的观察等待秒数。")
    parser.add_argument("--manual-step", action="store_true", default=PYCHARM_MANUAL_STEP, help="每一步都按 Enter 才继续。")
    parser.add_argument("--auto-step", action="store_true", help="关闭逐步 Enter 确认，自动连续执行。")
    parser.add_argument("--no-start-confirm", action="store_true", default=not PYCHARM_START_CONFIRM, help="开始前不等待人工确认。")
    parser.add_argument("--no-notice", action="store_true", default=not PYCHARM_SHOW_NOTICE, help="不尝试在模拟器通知栏显示当前步骤。")
    parser.add_argument("--no-stitch-preview", action="store_true", default=not PYCHARM_STITCH_PREVIEW, help="不生成简单拼接预览图。")
    parser.add_argument("--try-sysrq", action="store_true", default=PYCHARM_TRY_SYSRQ, help="额外尝试 KEYCODE_SYSRQ 系统截图键；这会在模拟器系统相册留下截图。")
    args = parser.parse_args()
    if args.auto_step:
        args.manual_step = False
    if args.dry_run:
        args.execute = False
    return args


def build_controller(simulator_name: str) -> AdbController:
    """
    按项目配置创建 ADB 控制器。
    输入：
        simulator_name: config/simulators 下的配置名。
    输出：
        AdbController。
    使用示例：
        controller = build_controller("leidian")
    """
    loader = get_config_loader()
    simulator_config = loader.get_simulator_config(simulator_name)
    return AdbController(simulator_config)


def build_connect_candidates(controller: AdbController, requested_serial: str) -> list[str]:
    """
    构造雷电和其他常见模拟器 TCP serial 候选。
    输入：
        controller: ADB 控制器；requested_serial: 用户显式指定 serial。
    输出：
        去重后的候选 serial 列表。
    使用示例：
        for candidate in build_connect_candidates(controller, ""): ...
    """
    candidates: list[str] = []
    if requested_serial and ":" in requested_serial:
        candidates.append(requested_serial)

    port = controller.adb_config.get("port") if isinstance(controller.adb_config, dict) else None
    if port:
        candidates.append(f"127.0.0.1:{port}")

    # 雷电常见是 5555/5554；后面保留几种其他模拟器端口，便于用户临时切换。
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


def choose_serial(controller: AdbController, requested_serial: str) -> str:
    """
    选择一台 ready ADB 设备。
    输入：
        controller: ADB 控制器；requested_serial: 可选 serial。
    输出：
        选中的设备 serial。
    使用示例：
        serial = choose_serial(controller, "127.0.0.1:5555")
    """
    connection = controller.check_connection(serial=requested_serial or None, reconnect=True)
    if connection.success and connection.selected_device is not None:
        return connection.selected_device.serial

    for candidate in build_connect_candidates(controller, requested_serial):
        print(f"[自动连接] 尝试 adb connect {candidate}")
        reconnect = controller.reconnect_device(candidate)
        print(f"[自动连接] {candidate}: {reconnect.status} {reconnect.stdout.strip() or reconnect.stderr.strip()}")
        connection = controller.check_connection(serial=candidate)
        if connection.success and connection.selected_device is not None:
            return connection.selected_device.serial

    print("\n[失败] 没有找到 ready 的 ADB 设备。")
    print(f"状态: {connection.status}")
    print(f"信息: {connection.message}")
    if connection.candidates:
        print("候选设备:")
        for device in connection.candidates:
            print(f"  - {device.serial} ({device.state})")
    raise SystemExit(2)


def make_run_dir() -> Path:
    """
    创建本次探测输出目录。
    输入：
        无。
    输出：
        workdir/automation/landscape_long_screenshot_probe/run_时间戳。
    使用示例：
        run_dir = make_run_dir()
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = PathManager.get_work_dir() / "automation" / "landscape_long_screenshot_probe" / f"run_{timestamp}"
    (run_dir / "frames").mkdir(parents=True, exist_ok=True)
    return run_dir


def wait_step(title: str, manual_step: bool) -> None:
    """
    可选等待用户按 Enter。
    输入：
        title: 当前步骤标题；manual_step: 是否逐步确认。
    输出：
        无。
    使用示例：
        wait_step("准备滚动", True)
    """
    if manual_step:
        input(f"\n[下一步] {title}\n按 Enter 继续，或 Ctrl+C 停止...")


def show_notice(controller: AdbController, serial: str, message: str, *, enabled: bool) -> None:
    """
    尝试在模拟器通知栏提示当前步骤。
    输入：
        controller/serial/message/enabled。
    输出：
        通知失败不会中断探测。
    使用示例：
        show_notice(controller, serial, "正在截图", enabled=True)
    """
    if not enabled:
        return
    result = controller.show_notification(
        message,
        title="横屏长截图探测",
        tag="azurlane_landscape_longshot_probe",
        expand=False,
        serial=serial,
    )
    if not result.success:
        print(f"[提示] 模拟器通知不可用，继续仅使用终端提示: {result.status}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """
    写入 JSON 文件。
    输入：
        path: 输出路径；payload: 可序列化数据。
    输出：
        UTF-8 JSON 文件。
    使用示例：
        write_json(run_dir / "summary.json", payload)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def result_to_dict(result: object) -> dict[str, Any]:
    """
    把项目结果对象转成 JSON 友好的 dict。
    输入：
        result: ADB 结果对象或普通对象。
    输出：
        dict。
    使用示例：
        payload = result_to_dict(controller.get_foreground_activity())
    """
    for method_name in ("to_dict", "to_payload"):
        method = getattr(result, method_name, None)
        if callable(method):
            payload = method()
            if isinstance(payload, dict):
                return payload
    return {
        "success": bool(getattr(result, "success", True)),
        "status": str(getattr(result, "status", "ok")),
        "message": str(getattr(result, "message", repr(result))),
    }


# ============================================================
# 🔍 第四部分：原生长截图能力探测
# ============================================================

def probe_native_long_screenshot(controller: AdbController, serial: str, *, try_sysrq: bool) -> dict[str, Any]:
    """
    探测模拟器系统是否暴露原生长截图能力。
    输入：
        controller/serial/try_sysrq。
    输出：
        探测报告；这里只做能力判断，不做 OCR。
    使用示例：
        report = probe_native_long_screenshot(controller, serial, try_sysrq=False)
    """
    commands: list[tuple[str, list[object]]] = [
        ("cmd_services", ["shell", "cmd", "-l"]),
        ("statusbar_help", ["shell", "cmd", "statusbar", "help"]),
        ("window_help", ["shell", "cmd", "window", "help"]),
        ("wm_size", ["shell", "wm", "size"]),
        ("wm_density", ["shell", "wm", "density"]),
        ("display_dump", ["shell", "dumpsys", "display"]),
    ]
    command_payloads: dict[str, dict[str, Any]] = {}
    joined_text_parts: list[str] = []

    for name, command in commands:
        result = controller.run_adb(command, serial=serial, timeout=8)
        payload = result_to_dict(result)
        command_payloads[name] = payload
        joined_text_parts.append(str(payload.get("stdout", "")))
        joined_text_parts.append(str(payload.get("stderr", "")))

    sysrq_payload: Optional[dict[str, Any]] = None
    if try_sysrq:
        sysrq = controller.keyevent("KEYCODE_SYSRQ", serial=serial)
        sysrq_payload = result_to_dict(sysrq)
        joined_text_parts.append(str(sysrq_payload.get("stdout", "")))
        joined_text_parts.append(str(sysrq_payload.get("stderr", "")))

    joined_text = "\n".join(joined_text_parts).lower()
    has_screenshot_keyword = "screenshot" in joined_text or "screen shot" in joined_text
    has_long_keyword = any(keyword in joined_text for keyword in ("long screenshot", "scrollshot", "scrolling screenshot", "longshot", "capture more"))
    status = "possible" if has_screenshot_keyword and has_long_keyword else "not_detected"
    conclusion = (
        "系统命令输出中出现疑似长截图关键词，需要人工继续确认。"
        if status == "possible"
        else "未在 ADB 暴露的系统命令中发现稳定原生长截图入口；建议使用分帧重叠采集。"
    )

    return {
        "status": status,
        "conclusion": conclusion,
        "has_screenshot_keyword": has_screenshot_keyword,
        "has_long_screenshot_keyword": has_long_keyword,
        "sysrq_attempted": bool(try_sysrq),
        "sysrq_result": sysrq_payload,
        "commands": command_payloads,
    }


# ============================================================
# 📸 第五部分：分帧采集与简单拼接预览
# ============================================================

def effective_scroll_step_px(scroll_step_px: int, overlap_ratio: float) -> int:
    """
    计算本次实验滚动步长。
    输入：
        scroll_step_px: 显式步长；overlap_ratio: 重叠比例。
    输出：
        像素步长。
    使用示例：
        step = effective_scroll_step_px(0, 0.35)
    """
    if int(scroll_step_px) > 0:
        return int(scroll_step_px)
    return max(1, int(round(720 * (1.0 - float(overlap_ratio)))))


def capture_frame(
    controller: AdbController,
    serial: str,
    frames_dir: Path,
    *,
    frame_index: int,
    screen_state: str,
) -> dict[str, Any]:
    """
    采集一张 viewport 截图并重命名为 frame_XXXX.png。
    输入：
        controller/serial/frames_dir/frame_index/screen_state。
    输出：
        包含截图路径和 ADB 结果的 dict。
    使用示例：
        frame = capture_frame(controller, serial, frames_dir, frame_index=0, screen_state="before")
    """
    screenshot = controller.capture_screenshot(
        RecognitionScene.RESEARCH,
        serial=serial,
        output_dir=frames_dir,
        screen_state=screen_state,
        scene_hint="landscape_long_screenshot_probe",
    )
    payload = result_to_dict(screenshot)
    artifact = getattr(screenshot, "artifact", None)
    if screenshot.success and artifact is not None:
        source_path = Path(artifact.screenshot_path)
        target_path = frames_dir / f"frame_{frame_index:04d}.png"
        if source_path.resolve() != target_path.resolve():
            os.replace(source_path, target_path)
        payload["screenshot_path"] = str(target_path.resolve())
    return payload


def run_segmented_capture(
    controller: AdbController,
    serial: str,
    run_dir: Path,
    *,
    frames: int,
    overlap_ratio: float,
    scroll_step_px: int,
    duration_ms: int,
    pause: float,
    manual_step: bool,
    show_device_notice: bool,
) -> dict[str, Any]:
    """
    执行分帧重叠采集对照实验。
    输入：
        controller/serial/run_dir 和滚动参数。
    输出：
        frame manifest。
    使用示例：
        manifest = run_segmented_capture(controller, serial, run_dir, frames=6, ...)
    """
    safe_frames = max(1, int(frames))
    safe_overlap = min(0.9, max(0.0, float(overlap_ratio)))
    step_px = effective_scroll_step_px(scroll_step_px, safe_overlap)
    frames_dir = run_dir / "frames"
    frame_entries: list[dict[str, Any]] = []
    action_entries: list[dict[str, Any]] = []

    for frame_index in range(safe_frames):
        title = f"采集第 {frame_index + 1}/{safe_frames} 帧 viewport"
        print(f"\n===== {title} =====")
        show_notice(controller, serial, title, enabled=show_device_notice)
        wait_step(title, manual_step)
        capture_payload = capture_frame(
            controller,
            serial,
            frames_dir,
            frame_index=frame_index,
            screen_state=f"landscape_frame_{frame_index:04d}",
        )
        frame_entry = {
            "frame_index": frame_index,
            "scroll_index": frame_index,
            "scroll_offset_px": frame_index * step_px,
            "scroll_step_px": step_px,
            "overlap_ratio": safe_overlap,
            "screenshot_path": capture_payload.get("screenshot_path"),
            "capture_result": capture_payload,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        frame_entries.append(frame_entry)
        print(f"[截图] {capture_payload.get('status')} {capture_payload.get('message')}")
        if capture_payload.get("screenshot_path"):
            print(f"[截图] {capture_payload['screenshot_path']}")

        if frame_index >= safe_frames - 1:
            break

        title = f"慢速滚动到下一段，步长约 {step_px}px"
        print(f"\n----- {title} -----")
        show_notice(controller, serial, title, enabled=show_device_notice)
        wait_step(title, manual_step)
        # 这里用 1280x720 基准坐标：从下往上滑，页面内容向下推进。
        start_x, start_y = 640, 630
        end_x, end_y = 640, max(90, start_y - step_px)
        scroll = controller.swipe(start_x, start_y, end_x, end_y, int(duration_ms), serial=serial, base_resolution=(1280, 720))
        action_entries.append(
            {
                "action_name": "scroll_down",
                "frame_index": frame_index,
                "scroll_index": frame_index,
                "scroll_offset_px": frame_index * step_px,
                "scroll_step_px": step_px,
                "command_result": result_to_dict(scroll),
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
        )
        print(f"[滚动] {scroll.status} {scroll.message}")
        time.sleep(max(0.0, float(pause)))

    return {
        "frames": frame_entries,
        "actions": action_entries,
        "frame_count": len(frame_entries),
        "scroll_step_px": step_px,
        "overlap_ratio": safe_overlap,
        "frames_dir": str(frames_dir.resolve()),
    }


def build_stitch_preview(frame_paths: list[Path], output_path: Path, overlap_ratio: float) -> Optional[str]:
    """
    生成简单纵向拼接预览图，方便肉眼看分帧连贯性。
    输入：
        frame_paths: 已采集 PNG；output_path: 输出图；overlap_ratio: 重叠比例。
    输出：
        成功时返回输出路径，失败时返回 None。
    使用示例：
        preview = build_stitch_preview(paths, run_dir / "preview.png", 0.35)
    """
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - 本地环境可选能力
        print(f"[拼接预览] Pillow 不可用，跳过预览图: {exc}")
        return None

    images = [Image.open(path).convert("RGB") for path in frame_paths if path.exists()]
    if not images:
        return None

    width = max(image.width for image in images)
    height = images[0].height
    overlap_px = max(0, min(height - 1, int(round(height * float(overlap_ratio)))))
    total_height = height + sum(max(1, image.height - overlap_px) for image in images[1:])
    stitched = Image.new("RGB", (width, total_height), (0, 0, 0))

    y = 0
    for index, image in enumerate(images):
        if index == 0:
            stitched.paste(image, (0, y))
            y += image.height
            continue
        cropped = image.crop((0, overlap_px, image.width, image.height))
        stitched.paste(cropped, (0, y))
        y += cropped.height

    output_path.parent.mkdir(parents=True, exist_ok=True)
    stitched.save(output_path)
    for image in images:
        image.close()
    return str(output_path.resolve())


# ============================================================
# 🚀 第六部分：主流程
# ============================================================

def main() -> int:
    """
    执行横屏长截图探测。
    输入：
        命令行参数。
    输出：
        进程退出码。
    使用示例：
        python test/v060/adb/adb_landscape_long_screenshot_probe.py --execute
    """
    args = parse_args()
    if not args.execute:
        print("本脚本默认不真实操作模拟器。")
        print("请先在雷电模拟器里打开一个横屏、可上下滚动的页面，然后执行：")
        print("python test/v060/adb/adb_landscape_long_screenshot_probe.py --execute --simulator leidian")
        print("PyCharm 直接运行时默认已开启逐步观察；如需自动连续执行，可添加 --auto-step。")
        return 0

    controller = build_controller(args.simulator)
    serial = choose_serial(controller, args.serial)
    run_dir = make_run_dir()
    report_path = run_dir / "long_screenshot_probe_report.json"
    manifest_path = run_dir / "segmented_capture_manifest.json"

    print("AzurLaneResearchTracker 横屏长截图能力探测")
    print(f"项目根目录: {PathManager.get_project_root()}")
    print(f"输出目录: {run_dir}")
    print(f"模拟器配置: {args.simulator}")
    print(f"设备 serial: {serial}")
    print("\n请确认雷电模拟器当前是横屏，并打开了一个可以上下滚动的页面。")
    print("建议页面：游戏内设计图/装备列表、Android 设置列表、浏览器长网页。")
    if not args.no_start_confirm:
        input("确认无误后按 Enter 开始，或 Ctrl+C 停止...")

    screen_info = controller.get_screen_info(serial=serial)
    display_check = controller.check_display_environment(serial=serial)
    foreground = controller.get_foreground_activity(serial=serial)

    native_probe = probe_native_long_screenshot(controller, serial, try_sysrq=bool(args.try_sysrq))
    print("\n===== 原生长截图能力探测结论 =====")
    print(native_probe["conclusion"])

    segmented = run_segmented_capture(
        controller,
        serial,
        run_dir,
        frames=args.frames,
        overlap_ratio=args.overlap_ratio,
        scroll_step_px=args.scroll_step_px,
        duration_ms=args.duration_ms,
        pause=args.pause,
        manual_step=args.manual_step,
        show_device_notice=not args.no_notice,
    )
    write_json(manifest_path, segmented)

    preview_path: Optional[str] = None
    if not args.no_stitch_preview:
        frame_paths = [
            Path(str(frame.get("screenshot_path")))
            for frame in segmented["frames"]
            if frame.get("screenshot_path")
        ]
        preview_path = build_stitch_preview(frame_paths, run_dir / "stitched_preview_naive.png", segmented["overlap_ratio"])
        if preview_path:
            print(f"\n[拼接预览] 已生成: {preview_path}")

    report = {
        "script": Path(__file__).name,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "simulator": args.simulator,
        "serial": serial,
        "run_dir": str(run_dir.resolve()),
        "screen_info": screen_info,
        "display_environment": result_to_dict(display_check),
        "foreground_activity": result_to_dict(foreground),
        "native_long_screenshot_probe": native_probe,
        "segmented_capture_manifest_path": str(manifest_path.resolve()),
        "stitched_preview_path": preview_path,
        "recommendation": (
            "如果 native_long_screenshot_probe.status 不是 possible，后续 OCR 应继续采用 viewport 分帧 + 重叠滚动方案；"
            "即使预览图能拼接，也不要把它当 OCR 输入，OCR 输入仍建议使用 frames/ 下原始 PNG。"
        ),
    }
    write_json(report_path, report)

    print("\n===== 探测完成 =====")
    print(f"报告: {report_path}")
    print(f"分帧 manifest: {manifest_path}")
    print(f"原始帧目录: {segmented['frames_dir']}")
    if preview_path:
        print(f"简单拼接预览: {preview_path}")
    print("结论建议: ADB 标准 screencap 只能稳定截当前 viewport；长列表建议继续使用分帧重叠采集。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
