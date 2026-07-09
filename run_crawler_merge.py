#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""爬虫工作区整合入口。"""
from __future__ import annotations

import argparse

from core.data.crawler_integration import CrawlerWorkspaceMerger


def main() -> int:
    """把装备爬虫与科研爬虫结果整合到 workdir。"""
    parser = argparse.ArgumentParser(description="Azur Lane crawler workspace merger")
    parser.add_argument("--equipment-archive-dir", type=str, default=None, help="指定装备爬虫归档目录")
    parser.add_argument("--research-run-dir", type=str, default=None, help="指定科研爬虫运行目录")
    parser.add_argument("--workspace-name", type=str, default=None, help="手动指定输出目录名")
    args = parser.parse_args()

    config_data = {
        "source": {
            "equipment_archive_dir": args.equipment_archive_dir,
            "research_run_dir": args.research_run_dir,
        }
    }

    merger = CrawlerWorkspaceMerger(config_data=config_data)
    result = merger.merge(workspace_name=args.workspace_name)
    print(f"workspace: {result.workspace_dir}")
    print(f"equipment_library: {result.equipment_library_path}")
    print(f"research_phases: {result.research_phases_path}")
    print(f"equipment_images: {result.equipment_images_path}")
    print(f"overrides: {result.overrides_path}")
    print(f"manifest: {result.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
