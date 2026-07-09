#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""科研爬虫独立运行入口。"""
from __future__ import annotations

import argparse

from core.data.research_crawler import get_research_crawler


def main() -> int:
    """支持全量和小规模两种运行模式。"""
    parser = argparse.ArgumentParser(description="Azur Lane research crawler")
    parser.add_argument("--phase-limit", type=int, default=None, help="只导出前 N 期科研数据")
    parser.add_argument("--common-limit", type=int, default=None, help="只导出前 N 条通用科研装备")
    parser.add_argument("--workspace-name", type=str, default=None, help="手动指定工作区名称")
    args = parser.parse_args()

    crawler = get_research_crawler()
    result = crawler.crawl_sample(
        phase_limit=args.phase_limit,
        common_limit=args.common_limit,
        workspace_name=args.workspace_name,
    )
    print(f"crawl done: {result.parsed_phase_count} phases")
    print(f"workspace: {result.workspace_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
