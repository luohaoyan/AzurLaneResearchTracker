#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""科研阶段图片整理入口。"""
from __future__ import annotations

import argparse
from pathlib import Path

from core.data.research_image_bundle import ResearchPhaseImageBundle


def main() -> int:
    """整理最新科研爬虫运行目录下的图片。"""
    parser = argparse.ArgumentParser(description="Azur Lane research phase image bundle")
    parser.add_argument("--run-dir", type=str, default=None, help="指定科研爬虫运行目录")
    parser.add_argument("--source-library-csv", type=str, default=None, help="指定源装备库 CSV")
    parser.add_argument("--source-images-csv", type=str, default=None, help="指定源图片映射 CSV")
    parser.add_argument("--output-folder-name", type=str, default="s", help="输出图片文件夹名")
    args = parser.parse_args()

    config_data = {
        "source": {
            "research_run_dir": args.run_dir,
            "source_library_csv": args.source_library_csv,
            "source_images_csv": args.source_images_csv,
        },
        "output": {
            "output_folder_name": args.output_folder_name,
        },
    }

    collector = ResearchPhaseImageBundle(config_data=config_data)
    result = collector.collect()
    print(f"copied: {result.copied_count}")
    print(f"workspace: {result.workspace_dir}")
    print(f"output: {result.output_dir}")
    print(f"manifest: {result.manifest_json_path}")
    if result.warnings:
        print(f"warnings: {len(result.warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
