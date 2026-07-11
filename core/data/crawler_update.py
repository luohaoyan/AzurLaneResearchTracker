#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔════════════════════════════════════════════════════════════╗
║           资料更新入口 (crawler_update)                   ║
║  装备爬虫 -> 科研爬虫 -> 正式 data/ 同步 的统一入口         ║
║  GUI/CLI 只需要调用 run_update() 就能完成整条更新链路      ║
╚════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 第一部分：导入依赖
# ============================================================

import inspect
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from ..utils.logger import get_logger
from .crawler_sync import get_crawler_data_synchronizer
from .equipment_crawler import get_equipment_crawler
from .research_crawler import get_research_crawler
from .special_equipment_manager import get_special_equipment_manager


# ============================================================
# 第二部分：核心函数
# ============================================================

def _build_success_message(equipment_count: int, image_count: int, phase_count: int) -> str:
    """把同步结果整理成 GUI 友好的单行提示。"""
    return (
        f"资料更新完成，装备 {equipment_count} 条、图片 {image_count} 张、"
        f"科研期数 {phase_count} 期，正式表已同步到 data/。"
    )


def _call_with_optional_progress(
    entry: Callable[..., Any],
    progress_callback: Callable[[int, str, str], None],
    **kwargs: Any,
) -> Any:
    """调用子模块入口，并在其支持时传入 progress_callback。"""
    try:
        signature = inspect.signature(entry)
    except (TypeError, ValueError):
        return entry(**kwargs)
    parameters = signature.parameters
    accepts_progress = "progress_callback" in parameters
    accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
    call_kwargs = dict(kwargs)
    if accepts_progress or accepts_kwargs:
        call_kwargs["progress_callback"] = progress_callback
    return entry(**call_kwargs)


def run_update(
    workspace_name: Optional[str] = None,
    progress_callback: Optional[Callable[[int, str, str], object]] = None,
) -> Dict[str, Any]:
    """执行装备爬虫、科研爬虫和正式数据同步的完整流程。"""
    logger = get_logger()
    run_name = workspace_name or datetime.now().strftime("%Y%m%d_%H%M%S")

    def report(progress: int, message: str, detail: str = "") -> None:
        """把 crawler 阶段进度转交给 GUI 任务清单。"""
        if progress_callback is not None:
            progress_callback(max(0, min(100, int(progress))), message, detail)

    def scale_progress(start: int, end: int) -> Callable[[int, str, str], None]:
        """把子任务 0-100 进度映射到总任务进度区间。"""
        def reporter(progress: int, message: str, detail: str = "") -> None:
            safe_progress = max(0, min(100, int(progress)))
            mapped_progress = start + round((end - start) * safe_progress / 100)
            report(mapped_progress, message, detail)

        return reporter

    report(8, "正在准备资料更新工作区。", f"workspace={run_name}")
    equipment_result = _call_with_optional_progress(
        get_equipment_crawler().crawl_all,
        scale_progress(10, 58),
        workspace_name=run_name,
    )
    report(60, "装备图鉴爬取完成，正在解析科研期数。", f"装备条目={equipment_result.selected_count}")
    research_result = _call_with_optional_progress(
        get_research_crawler().crawl_all,
        scale_progress(60, 75),
        workspace_name=run_name,
    )
    report(78, "科研资料解析完成，正在安全同步正式 CSV。", f"科研装备={research_result.total_equipment_count}")
    sync_result = _call_with_optional_progress(
        get_crawler_data_synchronizer().sync,
        scale_progress(78, 95),
        workspace_name=run_name,
        equipment_run_dir=equipment_result.workspace_dir,
        research_run_dir=research_result.workspace_dir,
    )
    report(97, "正式数据已同步，正在刷新特殊装备缓存。", f"备份目录={sync_result.backup_dir}")
    get_special_equipment_manager().reload()

    message = _build_success_message(
        len(sync_result.final_library_rows),
        len(sync_result.final_image_rows),
        len(sync_result.final_phase_rows),
    )
    logger.info(message)
    report(100, message, f"workspace={run_name}")

    warnings = list(equipment_result.warnings) + list(research_result.warnings) + list(sync_result.warnings)

    return {
        "message": message,
        "workspace_name": run_name,
        "equipment_workspace_dir": str(equipment_result.workspace_dir),
        "research_workspace_dir": str(research_result.workspace_dir),
        "sync_workspace_dir": str(sync_result.workspace_dir),
        "equipment_library_stage_path": str(equipment_result.library_csv_path),
        "equipment_images_stage_path": str(equipment_result.images_csv_path),
        "research_phase_stage_path": str(research_result.phase_stage_path),
        "research_equipment_stage_path": str(research_result.equipment_stage_path),
        "research_override_stage_path": str(research_result.override_stage_path),
        "equipment_library_path": str(sync_result.equipment_library_path),
        "equipment_images_path": str(sync_result.equipment_images_path),
        "research_phases_path": str(sync_result.research_phases_path),
        "data_images_dir": str(sync_result.data_images_dir),
        "backup_dir": str(sync_result.backup_dir),
        "sync_manifest_path": str(sync_result.workspace_dir / "crawler_sync_manifest.json"),
        "equipment_crawl_count": equipment_result.selected_count,
        "research_parsed_phase_count": research_result.parsed_phase_count,
        "research_common_count": research_result.common_equipment_count,
        "research_total_count": research_result.total_equipment_count,
        "equipment_count": len(sync_result.final_library_rows),
        "image_count": len(sync_result.final_image_rows),
        "phase_count": len(sync_result.final_phase_rows),
        "copied_image_count": len(sync_result.copied_image_paths),
        "warnings": warnings,
    }


def main() -> int:
    """命令行手动执行入口。"""
    payload = run_update()
    print(payload["message"])
    print(f"workspace: {payload['workspace_name']}")
    print(f"equipment workspace: {payload['equipment_workspace_dir']}")
    print(f"research workspace: {payload['research_workspace_dir']}")
    print(f"sync workspace: {payload['sync_workspace_dir']}")
    print(f"equipment_library: {payload['equipment_library_path']}")
    print(f"equipment_images: {payload['equipment_images_path']}")
    print(f"research_phases: {payload['research_phases_path']}")
    print(f"data_images: {payload['data_images_dir']}")
    if payload["warnings"]:
        print(f"warnings: {len(payload['warnings'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
