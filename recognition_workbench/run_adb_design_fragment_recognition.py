#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        🛰️ ADB 设计图截图识别工作台                          ║
║                                                              ║
║  【一句话解释】把 ADB 分帧采集产物接到设计图装备识别流水线。  ║
║  【类比理解】ADB 像摄影师，本脚本像整理相册再交给识别员。     ║
║  【数据流说明】manifest/实时采集 → frame 列表 → OCR 输出。    ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.automation.research_page import get_research_page_adb_api
from core.automation.research_page.research_page_constants import DEFAULT_SCROLL_SETTLE_DELAY_MS
from core.recognition.adb_frame_order import load_adb_manifest, order_manifest_frames


# ============================================================
# 🏗️ 第二部分：manifest 读取与 ADB 采集
# ============================================================

def load_manifest(manifest_path: Path) -> Dict[str, Any]:
    """
    读取 ADB 采集层输出的 manifest.json。
    输入：
        manifest_path: ADB run_xxx/manifest.json 路径。
    输出：
        dict: 原始 manifest 内容。
    使用示例：
        payload = load_manifest(Path("workdir/automation/adb_capture_runs/run_x/manifest.json"))
    """
    return load_adb_manifest(Path(manifest_path))


def collect_frame_paths(
    manifest: Mapping[str, Any],
    *,
    include_duplicates: bool = False,
    include_failed_frames: bool = False,
) -> Tuple[List[Path], List[Dict[str, Any]]]:
    """
    从 manifest 中筛选可交给 OCR 的截图帧。
    输入：
        manifest: ADB manifest 字典；include_duplicates/include_failed_frames 控制是否保留重复/失败帧。
    输出：
        (图片路径列表, 帧元数据列表)，顺序与 ADB frame_index 一致。
    使用示例：
        paths, frames = collect_frame_paths(manifest)
    """
    order = order_manifest_frames(
        manifest,
        include_duplicates=include_duplicates,
        include_failed_frames=include_failed_frames,
    )
    selected_paths = list(order.image_paths)
    frame_records = [selection.to_dict() for selection in order.selections if selection.selected]
    return selected_paths, frame_records


def detect_empty_design_page(image_paths: Sequence[Path]) -> bool:
    """
    用轻量卡片几何检测判断当前稀有度是否没有设计图卡片。

    这里只做“有没有卡片”的预检，不启动 OCR、OpenCV 图标匹配或 NN；
    需要至少两张可用帧时，所有被检查帧都必须返回 empty 才会短路。
    """
    if not image_paths:
        return False
    from core.recognition.design_fragment_detector import DesignFragmentDetector

    detector = DesignFragmentDetector()
    probe_paths = tuple(Path(item) for item in image_paths[: min(2, len(image_paths))])
    results = [detector.detect(path, image_mode="viewport_full") for path in probe_paths]
    return bool(results) and all(result.status == "empty" and not result.candidates for result in results)


def capture_adb_design_frames(args: argparse.Namespace) -> Tuple[Optional[Path], Optional[Dict[str, Any]]]:
    """
    调用 ADB 层采集设计图 viewport 序列。
    输入：
        args: CLI 参数，包含 frame_count、overlap_ratio、筛选状态等。
    输出：
        (manifest_path, session_dict)；采集失败时 manifest 可能仍存在但 frames 为空。
    使用示例：
        manifest_path, session = capture_adb_design_frames(args)
    """
    api = get_research_page_adb_api()
    session = api.capture_design_chart_sequence(
        frame_count=args.frame_count,
        overlap_ratio=args.overlap_ratio,
        scroll_step_px=args.scroll_step_px,
        scroll_settle_delay_ms=args.scroll_settle_ms,
        resume_cursor=args.resume_cursor,
        prepare_page=bool(getattr(args, "prepare_page", False)),
        stop_on_repeat=not bool(args.no_stop_on_repeat),
        ensure_top=bool(args.ensure_top),
        capture_until_bottom=bool(getattr(args, "until_bottom", False)),
        page_name="research_design_chart",
        page_state="research_design_chart",
        filter_state=args.filter_state,
        rarity_state=args.rarity_state,
        sort_state=args.sort_state,
        notify_actions=bool(args.notify_actions),
        device_message_mode=args.device_message_mode,
        session_id=args.capture_session_id,
    )
    return Path(session.manifest_path).resolve(), session.to_dict()


def run_recognition_for_images(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Lazily import the full recognition workbench so pytest collection stays light."""
    from recognition_workbench.run_recognition import run_recognition_for_images as _run_recognition_for_images

    return _run_recognition_for_images(*args, **kwargs)


def write_adb_context(
    output_dir: Path,
    *,
    manifest_path: Optional[Path],
    manifest: Mapping[str, Any],
    selected_frames: Sequence[Mapping[str, Any]],
    capture_session: Optional[Mapping[str, Any]],
    recognition_summary: Mapping[str, Any],
) -> None:
    """
    写出 ADB 与 OCR 的对接上下文，方便整合层和测试工程师追踪。
    输入：
        output_dir: 本次识别输出目录；manifest/selected_frames/capture_session/recognition_summary。
    输出：
        adb_capture_context.json。
    使用示例：
        write_adb_context(run_dir, manifest_path=path, manifest=payload, ...)
    """
    payload = {
        "source_manifest_path": str(manifest_path) if manifest_path else "",
        "source_session_id": manifest.get("session_id", ""),
        "source_page_name": manifest.get("page_name", ""),
        "source_page_state": manifest.get("page_state", ""),
        "source_filter_state": manifest.get("filter_state", ""),
        "source_rarity_state": manifest.get("rarity_state", ""),
        "source_sort_state": manifest.get("sort_state", ""),
        "source_bottom_reached": bool(manifest.get("bottom_reached", False)),
        "source_next_resume_cursor": manifest.get("next_resume_cursor", None),
        "selected_frame_count": len(selected_frames),
        "selected_frames": list(selected_frames),
        "capture_session": dict(capture_session or {}),
        "recognition_summary": dict(recognition_summary),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "adb_capture_context.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ============================================================
# 🌐 第三部分：CLI 入口
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析 ADB 设计图识别工作台参数。
    输入：
        命令行参数。
    输出：
        argparse.Namespace。
    使用示例：
        python recognition_workbench/run_adb_design_fragment_recognition.py --manifest workdir/.../manifest.json
    """
    parser = argparse.ArgumentParser(description="Run OCR recognition from an ADB design-fragment capture manifest.")
    parser.add_argument("--manifest", type=Path, default=None, help="Existing ADB manifest.json to consume.")
    parser.add_argument("--capture", action="store_true", help="Capture frames through ADB before recognition.")
    parser.add_argument("--frame-count", type=int, default=8)
    parser.add_argument("--overlap-ratio", type=float, default=0.35)
    parser.add_argument("--scroll-step-px", type=int, default=0, help="Explicit vertical swipe distance in pixels.")
    parser.add_argument(
        "--scroll-settle-ms",
        type=int,
        default=DEFAULT_SCROLL_SETTLE_DELAY_MS,
        help="Wait time after each swipe before the next screenshot; increase if the emulator still has inertia.",
    )
    parser.add_argument("--resume-cursor", type=int, default=0)
    parser.set_defaults(prepare_page=False)
    parser.add_argument("--prepare-page", dest="prepare_page", action="store_true", help="Navigate before capture when you want the workbench to enter the page first.")
    parser.add_argument("--no-prepare-page", dest="prepare_page", action="store_false", help="Skip navigation and use the current viewport directly.")
    parser.add_argument("--no-stop-on-repeat", action="store_true", help="Keep capturing even if duplicate frames appear.")
    parser.set_defaults(ensure_top=True)
    parser.add_argument("--ensure-top", dest="ensure_top", action="store_true", help="Rewind the list to the top before capturing.")
    parser.add_argument("--no-ensure-top", dest="ensure_top", action="store_false", help="Keep the current viewport and skip top rewind.")
    parser.set_defaults(until_bottom=False)
    parser.add_argument("--until-bottom", dest="until_bottom", action="store_true", help="Keep capturing until the design list bottom is confirmed.")
    parser.add_argument("--notify-actions", action="store_true", help="Show device notifications during capture.")
    parser.add_argument("--device-message-mode", choices=("none", "notification", "auto"), default="none")
    parser.add_argument("--capture-session-id", default="", help="Optional ADB capture session id.")
    parser.add_argument("--filter-state", default="all")
    parser.add_argument("--rarity-state", default="all")
    parser.add_argument("--enforce-rarity-filter", action="store_true", help="仅在已确认稀有度筛选正确时限制 OpenCV/NN 候选。")
    parser.add_argument("--sort-state", default="default")
    parser.add_argument("--include-duplicates", action="store_true")
    parser.add_argument("--include-failed-frames", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "recognition_workbench" / "adb_test_out")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--image-mode", choices=("viewport_full", "long_screenshot"), default="viewport_full")
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--onnx-dir", type=Path, default=None)
    parser.add_argument("--onnx-model", default="equipment_icon_resnet18_fp16.onnx")
    parser.add_argument("--nn-backend", choices=("auto", "onnx", "pytorch", "off"), default="auto")
    parser.add_argument("--nn-mode", choices=("fallback", "assist", "always"), default="assist")
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--skip-icons", action="store_true")
    parser.add_argument("--disable-nn", action="store_true")
    parser.add_argument("--nn-min-confidence", type=float, default=0.55)
    parser.add_argument("--nn-min-margin", type=float, default=0.08)
    parser.add_argument("--nn-trigger-threshold", type=float, default=0.82)
    parser.add_argument("--no-preview", action="store_true")
    return parser.parse_args()


def main() -> int:
    """执行 ADB manifest 消费或实时采集后识别。"""
    args = parse_args()
    capture_session: Optional[Dict[str, Any]] = None
    manifest_path = args.manifest.resolve() if args.manifest else None
    if args.capture:
        manifest_path, capture_session = capture_adb_design_frames(args)
    if manifest_path is None:
        print("请提供 --manifest，或使用 --capture 先执行 ADB 分帧采集。")
        return 2

    manifest = load_manifest(manifest_path)
    manifest_rarity_state = str(manifest.get("rarity_state", "") or "").strip()
    effective_rarity_state = (
        args.rarity_state
        if str(args.rarity_state or "").strip().lower() not in {"", "all", "unknown"}
        else manifest_rarity_state
    )
    image_paths, frame_records = collect_frame_paths(
        manifest,
        include_duplicates=bool(args.include_duplicates),
        include_failed_frames=bool(args.include_failed_frames),
    )
    run_name = args.run_name.strip() or f"adb_design_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = args.output_dir.resolve() / run_name
    if not image_paths:
        empty_summary = {
            "images": 0,
            "detected_cards": 0,
            "final_success": 0,
            "needs_review": 0,
            "warning": "No usable ADB frames were selected for OCR.",
        }
        write_adb_context(
            run_dir,
            manifest_path=manifest_path,
            manifest=manifest,
            selected_frames=frame_records,
            capture_session=capture_session,
            recognition_summary=empty_summary,
        )
        print(json.dumps({"output_dir": str(run_dir), **empty_summary}, ensure_ascii=False, indent=2))
        return 1

    if detect_empty_design_page(image_paths):
        from nn_training_lab.scripts.run_screenshot_pipeline import write_outputs

        run_dir.mkdir(parents=True, exist_ok=True)
        empty_summary = write_outputs(run_dir, [])
        empty_summary.update(
            {
                "empty_page": True,
                "recognition_skipped": True,
                "rarity_state": effective_rarity_state,
                "rarity_filter_enabled": False,
                "rarity_candidate_count": 0,
                "warning": "当前稀有度页面未检测到设计图卡片，已跳过 OCR/OpenCV/NN 识别。",
            }
        )
        (run_dir / "empty_page.json").write_text(
            json.dumps(
                {
                    "empty_page": True,
                    "rarity_state": effective_rarity_state,
                    "checked_frames": [str(path) for path in image_paths[:2]],
                    "message": "未检测到设计图卡片，按空页面处理。",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (run_dir / "screenshot_pipeline_summary.json").write_text(
            json.dumps(empty_summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        write_adb_context(
            run_dir,
            manifest_path=manifest_path,
            manifest=manifest,
            selected_frames=frame_records,
            capture_session=capture_session,
            recognition_summary=empty_summary,
        )
        print(json.dumps({"output_dir": str(run_dir), **empty_summary}, ensure_ascii=False, indent=2))
        return 0

    summary = run_recognition_for_images(
        image_paths,
        run_dir,
        image_mode=args.image_mode,
        model=args.model,
        onnx_dir=args.onnx_dir,
        onnx_model=args.onnx_model,
        nn_backend=args.nn_backend,
        nn_mode=args.nn_mode,
        skip_ocr=bool(args.skip_ocr),
        skip_icons=bool(args.skip_icons),
        disable_nn=bool(args.disable_nn),
        nn_min_confidence=float(args.nn_min_confidence),
        nn_min_margin=float(args.nn_min_margin),
        nn_trigger_threshold=float(args.nn_trigger_threshold),
        rarity_state=effective_rarity_state,
        enforce_rarity_filter=bool(args.enforce_rarity_filter),
        no_preview=bool(args.no_preview),
    )
    write_adb_context(
        run_dir,
        manifest_path=manifest_path,
        manifest=manifest,
        selected_frames=frame_records,
        capture_session=capture_session,
        recognition_summary=summary,
    )
    print(json.dumps({"output_dir": str(run_dir), **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
