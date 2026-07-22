#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      🧪 equipment_icon_matcher_v2 test_img 入口测试          ║
║                                                              ║
║  【测试目标】确认独立测试图默认使用高准确率优先的保守阈值。   ║
║  【类比理解】训练像刷题，test_img 像考试，宁可标疑问也别乱猜。 ║
║  【数据流说明】runner args → run_v2_prelabel command。        ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNNER_SCRIPT = PROJECT_ROOT / "ocr_training_lab" / "equipment_icon_matcher_v2" / "run_test_img_detection.py"


def _load_runner() -> Any:
    """按文件路径加载 test_img runner，避免把实验目录改成正式包。"""
    spec = importlib.util.spec_from_file_location("run_test_img_detection_for_test", RUNNER_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_test_img_runner_passes_conservative_review_confidence(tmp_path: Path) -> None:
    """test_img 默认应把较高 review-confidence 传给底层识别，避免低分错认直接放行。"""
    runner = _load_runner()
    args = Namespace(
        input_dir=tmp_path / "test_img",
        output_root=tmp_path / "test_out",
        output_name="run_test",
        pattern="*.png",
        read_quantity=False,
        no_name_ocr=False,
        top_n=10,
        review_confidence=0.90,
        name_global_assist_score=0.90,
        name_override_icon_confidence=0.86,
    )

    command = runner.build_command(args, tmp_path / "test_out" / "run_test")

    assert "--review-confidence" in command
    assert command[command.index("--review-confidence") + 1] == "0.9"
    assert "--skip-ocr" in command
    assert "--enable-name-ocr" in command
