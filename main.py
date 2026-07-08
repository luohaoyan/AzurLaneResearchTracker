#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║              🚪 main.py（项目启动瘦入口）                       ║
║                                                                  ║
║   【一句话解释】这里只负责启动程序，不承载具体业务逻辑。         ║
║   【类比理解】main.py 像大门，core.cli.app 才是前台接待员。      ║
║   【数据流说明】命令行参数 → main.py → core.cli.app.main()。     ║
╚══════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import sys
from pathlib import Path


# ============================================================
# 🧭 第二部分：准备项目路径
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent

# 先把项目根目录放到导入路径最前面，确保直接运行 main.py 时也能找到 core 包。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.cli.app import main as cli_main


# ============================================================
# 🚀 第三部分：全局运行入口
# ============================================================

def main() -> int:
    """
    启动碧蓝航线科研装备统计器。

    输入：
        无。命令行参数由 core.cli.app.main() 自行读取。

    输出：
        int：程序退出码，0 表示正常结束，非 0 表示命令执行失败。

    使用示例：
        python main.py status
        python main.py record --set S1-001 2 30 --dry-run
        python main.py export --kind equipment
    """
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
