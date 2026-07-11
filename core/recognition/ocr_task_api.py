#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🔎 OCR 识别任务接口 (ocr_task_api.py)            ║
║                                                              ║
║  【一句话解释】为 v0.6.0 装备与资源 OCR 预留稳定调用入口。     ║
║  【类比理解】它像港区识别镜架，镜片未装好前先固定好插槽。      ║
║  【数据流说明】截图路径 → OCR API → 标准识别结果 → GUI/数据层。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import importlib.util
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.utils.config_loader import get_config_loader
from core.utils.logger import get_logger


# ============================================================
# 🏗️ 第二部分：核心类
# ============================================================

@dataclass(frozen=True)
class OcrTaskResult:
    """
    OCR 任务执行结果。
    输入：
        success: 接口是否安全完成。
        status: reserved / ready / unavailable / error。
        message: 用户可见说明。
        detail: 给测试或开发者看的补充信息。
        payload: 后续真实 OCR 继续沿用的结构化数据。
    输出：
        不可变结果对象，可被 AutomationBridge 转成 GUI 结果。
    使用示例：
        result = get_ocr_task_api().scan_equipment_counts()
    """

    success: bool
    status: str
    message: str
    detail: str = ""
    payload: Optional[Dict[str, Any]] = None


class OcrTaskApi:
    """
    OCR 识别任务 API。
    输入：
        无，内部读取游戏识别区域配置。
    输出：
        当前阶段返回可测试的占位结果，不加载 PaddleOCR 模型。
    使用示例：
        api = OcrTaskApi()
        api.scan_resource_status()
    """

    _instance: Optional["OcrTaskApi"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "OcrTaskApi":
        """单例模式：避免未来重复加载 OCR 引擎。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化 OCR API，重复初始化时直接返回。"""
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        self.config_loader = get_config_loader()
        self._initialized = True

    def scan_equipment_counts(self, screenshot_path: Optional[str] = None) -> OcrTaskResult:
        """
        预检装备数量与碎片数量识别入口。
        输入：
            screenshot_path: 可选截图路径；当前阶段仅记录，不读取图片。
        输出：
            OcrTaskResult: 标准装备识别结果结构。
        使用示例：
            result = api.scan_equipment_counts("workdir/automation/screenshots/a.png")
        """
        recognition = self._recognition_config()
        payload = {
            "target": "equipment_counts",
            "screenshot_path": screenshot_path,
            "regions": {
                "equipment_region": recognition.get("equipment_region", []),
                "fragment_region": recognition.get("fragment_region", []),
            },
            "result_schema": self._equipment_result_schema(),
            "real_ocr_enabled": False,
        }
        detail = "字段=equipment_id, owned_quantity, fragment_quantity；真实 OCR=未启用"
        message = "装备 OCR 接口预检完成：已固定结果结构，等待 v0.6.0 接入截图识别。"
        self.logger.info(message)
        return OcrTaskResult(True, "reserved", message, detail, payload)

    def scan_resource_status(self, screenshot_path: Optional[str] = None) -> OcrTaskResult:
        """
        预检玩家资源识别入口。
        输入：
            screenshot_path: 可选截图路径；当前阶段仅记录，不读取图片。
        输出：
            OcrTaskResult: 标准玩家资源识别结果结构。
        使用示例：
            result = api.scan_resource_status()
        """
        payload = {
            "target": "resource_status",
            "screenshot_path": screenshot_path,
            "result_schema": self._resource_result_schema(),
            "real_ocr_enabled": False,
        }
        detail = "字段=player_name, oil, coins, gems；真实 OCR=未启用"
        message = "资源 OCR 接口预检完成：已固定玩家资源结构，后续可直接刷新港区实况。"
        self.logger.info(message)
        return OcrTaskResult(True, "reserved", message, detail, payload)

    def check_engine(self) -> OcrTaskResult:
        """
        检查 OCR 引擎依赖状态。
        输入：
            无。
        输出：
            OcrTaskResult: OpenCV/PaddleOCR 依赖是否可发现。
        使用示例：
            result = api.check_engine()
        """
        recognition = self._recognition_config()
        dependencies = {
            "opencv_cv2": importlib.util.find_spec("cv2") is not None,
            "paddleocr": importlib.util.find_spec("paddleocr") is not None,
        }
        threshold = recognition.get("confidence_threshold", 0.8)
        payload = {
            "dependencies": dependencies,
            "confidence_threshold": threshold,
            "real_ocr_enabled": False,
        }
        ready_count = sum(1 for available in dependencies.values() if available)
        detail = f"OCR依赖可用={ready_count}/{len(dependencies)}；置信度阈值={threshold}"
        message = "OCR 引擎预检完成：当前不加载模型，避免 GUI 启动变慢。"
        self.logger.info(message)
        return OcrTaskResult(True, "reserved", message, detail, payload)

    def _recognition_config(self) -> Dict[str, Any]:
        """
        读取游戏识别配置。
        输入：
            无。
        输出：
            dict: recognition 配置，缺失时返回空字典。
        使用示例：
            config = self._recognition_config()
        """
        game_config = self.config_loader.get_game_config()
        recognition = game_config.get("recognition", {}) if isinstance(game_config, dict) else {}
        return recognition if isinstance(recognition, dict) else {}

    @staticmethod
    def _equipment_result_schema() -> List[Dict[str, str]]:
        """返回装备识别结果的字段契约。"""
        return [
            {"name": "equipment_id", "type": "str", "description": "装备 ID，如 S9-001 或 G0001"},
            {"name": "owned_quantity", "type": "int", "description": "当前已拥有整装数量"},
            {"name": "fragment_quantity", "type": "int", "description": "当前装备碎片数量"},
            {"name": "confidence", "type": "float", "description": "OCR 或模板匹配置信度"},
        ]

    @staticmethod
    def _resource_result_schema() -> List[Dict[str, str]]:
        """返回玩家资源识别结果的字段契约。"""
        return [
            {"name": "player_name", "type": "str", "description": "玩家名称"},
            {"name": "oil", "type": "int", "description": "石油数量"},
            {"name": "coins", "type": "int", "description": "物资数量"},
            {"name": "gems", "type": "int", "description": "钻石数量"},
            {"name": "confidence", "type": "float", "description": "资源区域识别置信度"},
        ]


# ============================================================
# 🌐 第三部分：全局访问函数
# ============================================================

_ocr_task_api: Optional[OcrTaskApi] = None


def get_ocr_task_api() -> OcrTaskApi:
    """
    获取全局 OCR 任务 API。
    输入：
        无。
    输出：
        OcrTaskApi: 全局共享 API。
    使用示例：
        api = get_ocr_task_api()
    """
    global _ocr_task_api
    if _ocr_task_api is None:
        _ocr_task_api = OcrTaskApi()
    return _ocr_task_api
