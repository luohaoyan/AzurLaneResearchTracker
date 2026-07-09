#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🎛️ UI配置读取器 (ui_config.py)                 ║
║                                                              ║
║  【一句话解释】集中读取 GUI 专属 JSON 配置，减少窗口代码耦合。║
║  【类比理解】它像港区布告板，页面文案和日期先贴在这里再展示。║
║  【数据流说明】config/ui/*.json → UiConfigManager → GUI。     ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from copy import deepcopy
from typing import Any, Dict, Optional

from core.utils.config_loader import get_config_loader
from core.utils.logger import get_logger


# ============================================================
# 🏗️ 第二部分：默认配置与核心类
# ============================================================

DEFAULT_RESEARCH_PROGRESS_UI_CONFIG: Dict[str, Any] = {
    "phase_start_dates": {"6": "2026-03-10"},
    "official_start_dates": {"6": "2026-03-10"},
    "fallback_start_date": "2026-03-10",
    "official_fallback_start_date": "2026-03-10",
    "duration_messages": [
        {"min_day": 1, "max_day": 7, "text": "科研室刚开灯，先把每日委托稳稳拿下吧。"},
        {"min_day": 8, "max_day": 30, "text": "科研节奏进入巡航，秘书舰已经把进度表贴在墙上了。"},
        {"min_day": 31, "max_day": 90, "text": "漫长作战进行中，港区后勤建议保持补给和睡眠。"},
        {"min_day": 91, "max_day": None, "text": "这已经是长期工程了，旧账也会被认真清算。"},
    ],
    "secretary": {
        "name": "默认秘书舰",
        "image_path": "",
        "placeholder_text": "秘书舰",
        "dialog_duration_ms": 3600,
    },
    "target_dialogs": {
        "history": "补旧期属于港区档案整理任务，过期科研可不代表欧非程度哦，按自己的节奏推进就好。",
        "history_completed": "旧期目标已经补完啦，档案室盖章通过；不过过期科研可不代表欧非程度哦。",
        "completed": "目标已经突破啦，科研室建议立刻换个更闪亮的新目标。",
        "target_1": "秘书舰歪头：只锁定一件吗？稳是很稳，但港区烟花还没点燃呢。",
        "target_2_4": "标准指挥官路线，后勤妖精点头通过，肝度刚刚好。",
        "target_5_7": "勇者级科研计划启动，今晚科研室的灯大概要常亮了。",
        "target_8_plus": "指挥官，理智值还在线吗？这么多彩装连科研终端都开始冒蓝光了。",
    },
}


class UiConfigManager:
    """
    GUI 配置管理器。
    输入：
        无，内部从 config/ui 目录读取 JSON。
    输出：
        科研页等 GUI 专属配置字典。
    使用示例：
        config = get_ui_config_manager().get_research_progress_config()
    """

    _instance: Optional["UiConfigManager"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "UiConfigManager":
        """单例模式：全局共享一个 GUI 配置管理器。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化配置管理器，重复初始化时直接返回。"""
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        self.config_loader = get_config_loader()
        self._initialized = True

    def get_research_progress_config(self) -> Dict[str, Any]:
        """
        读取科研进度页 UI 配置。
        输入：
            无。
        输出：
            dict: 已合并默认值的配置。
        使用示例：
            cfg = manager.get_research_progress_config()
        """
        loaded = self.config_loader.get_config("ui", "research_progress")
        return self._merge_dicts(DEFAULT_RESEARCH_PROGRESS_UI_CONFIG, loaded)

    def save_phase_start_date(self, phase_number: int, start_date: str) -> None:
        """
        保存用户为某一期科研设置的开始日期。
        输入：
            phase_number: 科研期数。
            start_date: YYYY-MM-DD 日期字符串。
        输出：
            None。
        使用示例：
            manager.save_phase_start_date(6, "2026-03-10")
        """
        config = self.get_research_progress_config()
        phase_dates = dict(config.get("phase_start_dates", {}))
        phase_dates[str(int(phase_number))] = start_date
        config["phase_start_dates"] = phase_dates
        self.config_loader.save_config("ui", "research_progress", config)

    @classmethod
    def _merge_dicts(cls, defaults: Dict[str, Any], loaded: Dict[str, Any]) -> Dict[str, Any]:
        """深度合并配置，缺失字段使用默认值兜底。"""
        result = deepcopy(defaults)
        for key, value in loaded.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = cls._merge_dicts(result[key], value)
            else:
                result[key] = value
        return result


# ============================================================
# 🌐 第三部分：全局访问函数
# ============================================================

_ui_config_manager: Optional[UiConfigManager] = None


def get_ui_config_manager() -> UiConfigManager:
    """
    获取全局 GUI 配置管理器。
    输入：
        无。
    输出：
        UiConfigManager: 全局共享实例。
    使用示例：
        manager = get_ui_config_manager()
    """
    global _ui_config_manager
    if _ui_config_manager is None:
        _ui_config_manager = UiConfigManager()
    return _ui_config_manager
