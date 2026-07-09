#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""装备爬虫独立运行入口。"""
from __future__ import annotations

import argparse

from core.data.equipment_crawler import get_equipment_crawler
from core.utils.path_manager import PathManager


def main() -> int:
    """支持抽样和全量两种运行模式。"""
    parser = argparse.ArgumentParser(description="Azur Lane equipment crawler")
    parser.add_argument("--all", action="store_true", help="crawl all equipment entries")
    args = parser.parse_args()

    crawler = get_equipment_crawler()
    result = crawler.crawl_all() if args.all else crawler.crawl_sample()
    print(f"crawl done: {result.selected_count} items")
    print(f"workspace: {result.workspace_dir}")
    if args.all:
        print(f"all_imgs: {PathManager.get_work_dir() / 'all_imgs'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
