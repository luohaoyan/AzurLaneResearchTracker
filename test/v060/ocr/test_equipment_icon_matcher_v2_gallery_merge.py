#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      🧪 equipment_icon_matcher_v2 图库累计测试               ║
║                                                              ║
║  【测试目标】确认多轮人工 reviewed 图库不会被最新一轮覆盖。   ║
║  【类比理解】像错题本只会追加新页，不会擦掉前面批改成果。      ║
║  【数据流说明】existing manifest + new rows → cumulative rows.║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import importlib.util
import sys
from pathlib import Path
from typing import Any


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ICON_SCRIPT = PROJECT_ROOT / "ocr_training_lab" / "equipment_icon_matcher_v2" / "build_reviewed_icon_gallery.py"
NAME_SCRIPT = PROJECT_ROOT / "ocr_training_lab" / "equipment_icon_matcher_v2" / "build_reviewed_name_gallery.py"


def _load_module(path: Path, module_name: str) -> Any:
    """按文件路径加载 lab 脚本，避免把实验目录改成正式包。"""
    script_dir = str(path.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_reviewed_icon_manifest_merges_old_rows_and_replaces_same_card() -> None:
    """图标 manifest 应累计历史样本，并用同截图同卡位的新行覆盖旧行。"""
    lab = _load_module(ICON_SCRIPT, "build_reviewed_icon_gallery_for_merge_test")
    existing = [
        {"source_filename": "shot_a.png", "card_no": "1", "equipment_name": "旧名称", "sample_id": "old-a"},
        {"source_filename": "shot_b.png", "card_no": "2", "equipment_name": "保留名称", "sample_id": "old-b"},
    ]
    new = [
        {"source_filename": "shot_a.png", "card_no": "1", "equipment_name": "新名称", "sample_id": "new-a"},
        {"source_filename": "shot_c.png", "card_no": "3", "equipment_name": "新增名称", "sample_id": "new-c"},
    ]

    merged = lab.merge_manifest_rows(existing, new)

    assert [row["source_filename"] for row in merged] == ["shot_a.png", "shot_b.png", "shot_c.png"]
    assert merged[0]["equipment_name"] == "新名称"
    assert merged[1]["equipment_name"] == "保留名称"
    assert merged[2]["equipment_name"] == "新增名称"


def test_reviewed_name_manifest_merges_old_rows_and_replaces_same_card() -> None:
    """名称 manifest 应累计历史样本，并用同截图同卡位的新行覆盖旧行。"""
    lab = _load_module(NAME_SCRIPT, "build_reviewed_name_gallery_for_merge_test")
    existing = [
        {"source_filename": "shot_a.png", "card_no": "1", "equipment_name": "旧名称", "sample_id": "old-a"},
    ]
    new = [
        {"source_filename": "shot_a.png", "card_no": "1", "equipment_name": "新名称", "sample_id": "new-a"},
        {"source_filename": "shot_b.png", "card_no": "2", "equipment_name": "新增名称", "sample_id": "new-b"},
    ]

    merged = lab.merge_manifest_rows(existing, new)

    assert len(merged) == 2
    assert merged[0]["equipment_name"] == "新名称"
    assert merged[1]["source_filename"] == "shot_b.png"
