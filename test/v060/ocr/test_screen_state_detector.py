#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 登录/加载/港区状态识别测试                       ║
║                                                              ║
║  【测试目标】验证 ADB 截图路径进入 OCR 后能保守判断页面状态。  ║
║  【类比理解】像给自动化司机配一副只认房间门牌的眼镜。          ║
║  【数据流说明】合成截图 → ScreenStateDetector → unknown/harbor。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from pathlib import Path

import cv2
import numpy as np
import pytest

from core.contracts import RecognitionScene, TaskCancelledError, TaskExecutionContext
from core.recognition.screen_state_detector import ScreenStateDetector


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

def _base_config() -> dict:
    """构造开启状态探针的最小配置。"""
    return {
        "base_resolution": {"width": 1280, "height": 720},
        "capture_validation": {
            "allow_partial_image": False,
            "min_width_ratio": 0.85,
            "min_height_ratio": 0.85,
            "max_aspect_delta": 0.12,
        },
        "screen_state_detection": {
            "enabled": True,
            "confidence_threshold": 0.58,
            "ambiguous_margin": 0.06,
            "ocr_text_probe_enabled": False,
        },
    }


def _write(tmp_path: Path, image: np.ndarray, name: str = "screen.png") -> Path:
    """把合成 OpenCV 图像写入 pytest 临时目录。"""
    path = tmp_path / name
    assert cv2.imwrite(str(path), image)
    return path


def _blank(value: int = 35, width: int = 1280, height: int = 720) -> np.ndarray:
    """创建一张暗色横屏截图。"""
    return np.full((height, width, 3), value, dtype=np.uint8)


def _harbor_like() -> np.ndarray:
    """合成港区主界面：顶部资源栏、右上功能栏、底部导航和仓库按钮。"""
    image = _blank(70)
    image[18:56, 1008:1263] = (235, 235, 235)
    image[0:75, 470:1010] = (35, 90, 190)
    image[640:718, 10:1270] = (230, 230, 230)
    image[646:708, 324:480] = (248, 248, 248)
    cv2.rectangle(image, (8, 8), (80, 80), (220, 220, 220), 3)
    cv2.line(image, (90, 28), (315, 28), (240, 240, 240), 3)
    return image


def _login_like() -> np.ndarray:
    """合成登录页：中央/底部蓝色开始按钮和右上公告关闭候选。"""
    image = _blank(55)
    image[530:620, 430:850] = (225, 130, 35)
    cv2.rectangle(image, (1068, 28), (1232, 118), (235, 235, 235), 4)
    cv2.line(image, (1110, 48), (1190, 98), (235, 235, 235), 5)
    cv2.line(image, (1190, 48), (1110, 98), (235, 235, 235), 5)
    return image


def _loading_like() -> np.ndarray:
    """合成加载页：暗背景和底部蓝色 loading/progress 区域。"""
    image = _blank(25)
    image[642:700, 280:1000] = (210, 120, 30)
    image[665:674, 300:970] = (245, 245, 245)
    return image


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_harbor_screenshot_is_detected_as_harbor(tmp_path: Path) -> None:
    """港区截图应返回 scene=harbor，并报告 screen_state=harbor。"""
    detector = ScreenStateDetector(config=_base_config())

    result = detector.detect(_write(tmp_path, _harbor_like(), "harbor.png"))

    assert result.success is True
    assert result.screen_state == "harbor"
    assert result.scene is RecognitionScene.HARBOR
    assert result.confidence >= 0.58
    assert any(item.label == "harbor_warehouse_entry" for item in result.detections)


def test_login_screenshot_is_unknown_scene_not_equipment_or_research(tmp_path: Path) -> None:
    """登录页只应返回 screen_state=login 和 scene=unknown，不得误判为装备/科研。"""
    detector = ScreenStateDetector(config=_base_config())

    result = detector.detect(_write(tmp_path, _login_like(), "login.png"))

    assert result.success is True
    assert result.screen_state == "login"
    assert result.scene is RecognitionScene.UNKNOWN
    assert "ADB/Integration" in result.suggested_action


def test_loading_screenshot_is_unknown_scene_and_non_blocking(tmp_path: Path) -> None:
    """加载页应返回 unknown 场景，并把继续等待交给 ADB/Integration。"""
    detector = ScreenStateDetector(config=_base_config())

    result = detector.detect(_write(tmp_path, _loading_like(), "loading.png"))

    assert result.success is True
    assert result.screen_state == "loading"
    assert result.scene is RecognitionScene.UNKNOWN
    assert "继续等待" in result.suggested_action


def test_low_confidence_image_returns_unknown(tmp_path: Path) -> None:
    """低置信截图应保守返回 unknown。"""
    detector = ScreenStateDetector(config=_base_config())

    result = detector.detect(_write(tmp_path, _blank(0), "black.png"))

    assert result.success is True
    assert result.status == "unknown"
    assert result.screen_state == "unknown"
    assert result.scene is RecognitionScene.UNKNOWN


def test_invalid_path_returns_friendly_failure(tmp_path: Path) -> None:
    """损坏路径应返回失败结果，不抛普通异常。"""
    detector = ScreenStateDetector(config=_base_config())

    result = detector.detect(tmp_path / "missing.png")

    assert result.success is False
    assert result.status == "error"
    assert "截图文件不存在" in result.message


def test_cancelled_context_stops_state_detection(tmp_path: Path) -> None:
    """取消令牌传入后应在安全点停止，不继续分析下一特征。"""
    context = TaskExecutionContext()
    context.cancellation_token.request_cancel()
    detector = ScreenStateDetector(config=_base_config())

    with pytest.raises(TaskCancelledError):
        detector.detect(_write(tmp_path, _harbor_like(), "cancel.png"), task_context=context)


def test_partial_screenshot_returns_unknown_without_recognition(tmp_path: Path) -> None:
    """半截截图不进入页面判断，直接 unknown。"""
    detector = ScreenStateDetector(config=_base_config())

    result = detector.detect(_write(tmp_path, _harbor_like()[:, :640], "half.png"))

    assert result.success is True
    assert result.screen_state == "unknown"
    assert result.scene is RecognitionScene.UNKNOWN
    assert any("不完整" in warning for warning in result.warnings)
