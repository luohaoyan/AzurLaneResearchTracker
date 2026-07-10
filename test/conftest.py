"""pytest 配置：统一导入路径，并忽略手工 smoke 脚本。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

collect_ignore = [
    "test_calculation.py",
    "test_data_layer.py",
]
