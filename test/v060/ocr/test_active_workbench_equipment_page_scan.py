#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        active_workbench 装备页扫描脚本测试                   ║
║                                                              ║
║  【一句话解释】验证装备页分类、断点 key 和 raw/clean 汇总。     ║
║  【类比理解】像给扫描流水线的“标签纸”做抽查，防止贴错箱子。      ║
║  【数据流说明】文件名/识别行 → 页面元数据/汇总 CSV 字段。       ║
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

import pytest


# ============================================================
# 🧰 第二部分：测试工具
# ============================================================

def load_equipment_page_scan_module() -> Any:
    """
    加载 active_workbench 的装备页扫描脚本。

    输入：
        本项目工作树。
    输出：
        run_equipment_page_scan.py 模块对象。
    使用示例：
        module = load_equipment_page_scan_module()
    """
    project_root = Path(__file__).resolve().parents[3]
    script_path = project_root / "ocr_training_lab" / "equipment_icon_matcher_v2" / "active_workbench" / "scripts" / "run_equipment_page_scan.py"
    spec = importlib.util.spec_from_file_location("active_workbench_equipment_page_scan", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclass 在 Python 3.12 下会通过 sys.modules 解析字符串注解；
    # 动态加载脚本时先注册模块，避免测试环境和真实执行路径表现不一致。
    sys.modules[str(spec.name)] = module
    spec.loader.exec_module(module)
    return module


def load_common_icon_matching_module() -> Any:
    """
    加载 active_workbench 的共用 icon 匹配工具。

    输入：
        本项目工作树。
    输出：
        common_icon_matching.py 模块对象。
    使用示例：
        module = load_common_icon_matching_module()
    """
    project_root = Path(__file__).resolve().parents[3]
    script_path = project_root / "ocr_training_lab" / "equipment_icon_matcher_v2" / "active_workbench" / "scripts" / "common_icon_matching.py"
    spec = importlib.util.spec_from_file_location("active_workbench_common_icon_matching", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[str(spec.name)] = module
    spec.loader.exec_module(module)
    return module


# ============================================================
# ✅ 第三部分：测试用例
# ============================================================

def test_parse_equipment_page_meta_builds_rarity_page_key() -> None:
    """
    验证装备页文件名能解析为稀有度分类和断点 key。

    输入：
        equip_super_rare_scroll_012.png。
    输出：
        filter_rarity=super_rare 且 page_key 包含 scroll_012。
    使用示例：
        pytest test/v060/ocr/test_active_workbench_equipment_page_scan.py
    """
    module = load_equipment_page_scan_module()

    meta = module.parse_equipment_page_meta(Path("equip_super_rare_scroll_012.png"), "abc123")

    assert meta.page_type == "warehouse"
    assert meta.tab == "equipment"
    assert meta.filter_rarity == "super_rare"
    assert meta.filter_rarity_id == 4
    assert meta.scroll_index == 12
    assert meta.page_key == "warehouse:equipment:super_rare:sort_rarity:scroll_012"


def test_build_summary_by_mode_reports_raw_clean_rates() -> None:
    """
    验证 raw/clean 汇总不会再因缺函数导致装备页脚本崩溃。

    输入：
        raw 两行、clean 两行。
    输出：
        raw 成功率 50%，clean 成功率 100%。
    使用示例：
        pytest test/v060/ocr/test_active_workbench_equipment_page_scan.py
    """
    module = load_equipment_page_scan_module()
    rows = [
        {"match_mode": "raw", "status": "success"},
        {"match_mode": "raw", "status": "ambiguous"},
        {"match_mode": "clean", "status": "success"},
        {"match_mode": "clean", "status": "success"},
    ]

    summary = module.build_summary_by_mode(rows)

    assert summary["raw"]["success"] == 1
    assert summary["raw"]["ambiguous"] == 1
    assert summary["raw"]["success_rate"] == 0.5
    assert summary["clean"]["success"] == 2
    assert summary["clean"]["success_rate"] == 1.0


def test_raw_clean_change_marks_clean_improved() -> None:
    """
    验证 raw 失败而 clean 成功时，结果被标记为 clean_improved。

    输入：
        raw ambiguous、clean success。
    输出：
        clean_improved。
    使用示例：
        pytest test/v060/ocr/test_active_workbench_equipment_page_scan.py
    """
    module = load_equipment_page_scan_module()

    change = module.classify_raw_clean_change(
        {"status": "ambiguous", "equipment_name": ""},
        {"status": "success", "equipment_name": "四联装610mm鱼雷#T3"},
    )

    assert change == "clean_improved"


def test_make_equipment_overlay_variants_keeps_original_shape() -> None:
    """
    验证装备页合成遮挡图库会生成预期变体。

    输入：
        一张 128x128 合成 icon。
    输出：
        used_avatar/enhance_stack/组合遮挡，且尺寸不变。
    使用示例：
        pytest test/v060/ocr/test_active_workbench_equipment_page_scan.py
    """
    pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    module = load_common_icon_matching_module()
    image = numpy.full((128, 128, 3), 160, dtype=numpy.uint8)

    variants = module.make_equipment_overlay_variants(image)

    assert {"used_avatar", "enhance_stack", "used_enhance_stack", "heavy_occlusion"}.issubset(set(variants))
    assert all(item.shape == image.shape for item in variants.values())


def test_erase_equipment_dynamic_regions_returns_smaller_clean_icon() -> None:
    """
    验证装备页动态区域抹除会输出可用于匹配的 clean icon。

    输入：
        一张 128x128 合成 icon。
    输出：
        抹除并轻微裁边后的 icon，宽高不超过原图且不为空。
    使用示例：
        pytest test/v060/ocr/test_active_workbench_equipment_page_scan.py
    """
    pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    module = load_common_icon_matching_module()
    image = numpy.full((128, 128, 3), 160, dtype=numpy.uint8)
    image[0:40, 96:128] = 255
    image[80:120, 0:42] = 0

    clean = module.erase_equipment_dynamic_regions(image, crop_inset=True)

    assert clean.size > 0
    assert clean.shape[0] <= image.shape[0]
    assert clean.shape[1] <= image.shape[1]
