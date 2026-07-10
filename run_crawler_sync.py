#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""爬虫结果同步到正式 data/ 的入口。"""
from __future__ import annotations

import argparse

from core.data.crawler_sync import CrawlerDataSynchronizer


def main() -> int:
    """把最新的装备爬虫与科研爬虫结果同步到项目数据目录。"""
    parser = argparse.ArgumentParser(description="Azur Lane crawler data synchronizer")
    parser.add_argument("--equipment-run-dir", type=str, default=None, help="指定装备爬虫运行目录")
    parser.add_argument("--research-run-dir", type=str, default=None, help="指定科研爬虫运行目录")
    parser.add_argument("--workspace-name", type=str, default=None, help="手动指定同步工作区名称")
    args = parser.parse_args()

    config_data = {
        "source": {
            "equipment_run_dir": args.equipment_run_dir,
            "research_run_dir": args.research_run_dir,
        }
    }

    synchronizer = CrawlerDataSynchronizer(config_data=config_data)
    result = synchronizer.sync(workspace_name=args.workspace_name)

    print(f"workspace: {result.workspace_dir}")
    print(f"backup: {result.backup_dir}")
    print(f"equipment_library: {result.equipment_library_path}")
    print(f"equipment_images: {result.equipment_images_path}")
    print(f"research_phases: {result.research_phases_path}")
    print(f"data_images: {result.data_images_dir}")
    print(f"copied_images: {len(result.copied_image_paths)}")
    if result.warnings:
        print(f"warnings: {len(result.warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
