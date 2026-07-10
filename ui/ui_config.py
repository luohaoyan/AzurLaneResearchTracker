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
    "phase_settings": {
        "PR6": {"target": 2, "start_date": "2026-03-10"},
    },
    "phase_start_dates": {"6": "2026-03-10"},
    "phase_targets": {"6": 2},
    "fallback_start_date": "2026-03-10",
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


DEFAULT_RESEARCH_OFFICIAL_START_DATES_CONFIG: Dict[str, Any] = {
    "phase_start_dates": {
        "1": "2018-04-26",
        "2": "2019-04-18",
        "3": "2020-07-09",
        "4": "2021-07-08",
        "5": "2022-07-14",
        "6": "2023-07-13",
        "7": "2024-07-11",
        "8": "2025-07-10",
        "9": "2026-07-09",
    },
    "fallback_start_date": "2026-07-09",
}


DEFAULT_APPEARANCE_UI_CONFIG: Dict[str, Any] = {
    "active_skin": "harbor_night",
    "table_density": "comfortable",
    "custom_background": {
        "enabled": False,
        "path": "",
        "opacity": 0.18,
        "blur": 0,
    },
    "skin_notes": {
        "harbor_night": "默认低眩光深色皮肤，适合长时间统计。",
        "sakura_mist": "明亮皮肤预留，后续适合接入秘书舰和节日素材。",
        "iron_blood": "调试向深色皮肤预留，适合自动化实验室。",
        "eagle_union": "白鹰阵营皮肤预留，海军蓝与星章白的现代舰队感。",
        "dragon_empery": "东煌阵营皮肤，红金与青玉色构成温润中式界面。",
        "northern_parliament": "北联阵营皮肤预留，冰蓝银白的极地风格。",
        "sakura_empire": "重樱阵营皮肤预留，深靛与夜樱粉的和风氛围。",
    },
}


DEFAULT_SECRETARY_LINES_UI_CONFIG: Dict[str, Any] = {
    "active_secretary": "default",
    "dialog_duration_ms": 2400,
    "secretaries": {
        "default": {
            "name": "默认秘书舰",
            "avatar_path": "",
            "placeholder_text": "秘书舰",
            "lines": {
                "idle": [
                    "欢迎回来，指挥官。",
                    "今天也要全力以赴哦。",
                ],
                "target_changed": [
                    "指挥官，新的计划已经记录好了。",
                    "资料已经整理完毕，接下来就交给你了。",
                    "嗯，这个目标看起来很有挑战性。",
                ],
                "completed": [
                    "任务完成得很漂亮，指挥官。",
                    "这样一来，港区又向前推进了一步。",
                ],
                "history": [
                    "旧档案也需要认真整理。",
                    "慢慢来，过去的进度也很重要。",
                ],
            },
        }
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

    def get_research_official_start_dates_config(self) -> Dict[str, Any]:
        """
        读取科研官方开始时间固定配置。
        输入：
            无。
        输出：
            dict: 包含 phase_start_dates 与 fallback_start_date 的固定日期表。
        使用示例：
            cfg = manager.get_research_official_start_dates_config()
        """
        loaded = self.config_loader.get_config("ui", "research_official_start_dates")
        return self._merge_dicts(DEFAULT_RESEARCH_OFFICIAL_START_DATES_CONFIG, loaded)

    def get_official_research_start_date(self, phase_number: int) -> str:
        """
        获取指定科研期数的官方开始日期。
        输入：
            phase_number: 科研期数。
        输出：
            str: YYYY-MM-DD 日期字符串。
        使用示例：
            manager.get_official_research_start_date(9)
        """
        config = self.get_research_official_start_dates_config()
        phase_dates = config.get("phase_start_dates", {})
        return str(
            phase_dates.get(str(int(phase_number)))
            or config.get("fallback_start_date")
            or DEFAULT_RESEARCH_OFFICIAL_START_DATES_CONFIG["fallback_start_date"]
        )

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
        phase_settings = dict(config.get("phase_settings", {}))
        key = self._phase_key(phase_number)
        setting = dict(phase_settings.get(key, {}))
        setting["start_date"] = start_date
        setting.setdefault("target", int(config.get("phase_targets", {}).get(str(int(phase_number)), 2)))
        phase_settings[key] = setting
        config["phase_settings"] = phase_settings
        self.config_loader.save_config("ui", "research_progress", config)

    def get_phase_setting(self, phase_number: int) -> Dict[str, Any]:
        """
        获取某一期科研的用户配置。
        输入：
            phase_number: 科研期数。
        输出：
            dict: {"target": int, "start_date": "YYYY-MM-DD"}。
        使用示例：
            setting = manager.get_phase_setting(8)
        """
        config = self.get_research_progress_config()
        key = self._phase_key(phase_number)
        setting = dict(config.get("phase_settings", {}).get(key, {}))
        legacy_targets = config.get("phase_targets", {})
        legacy_dates = config.get("phase_start_dates", {})
        if "target" not in setting:
            setting["target"] = int(legacy_targets.get(str(int(phase_number)), 2))
        if "start_date" not in setting:
            setting["start_date"] = str(
                legacy_dates.get(str(int(phase_number)))
                or self.get_official_research_start_date(phase_number)
                or config.get("fallback_start_date")
            )
        return setting

    def save_phase_target_count(self, phase_number: int, target_count: int) -> None:
        """
        保存某一期科研的目标彩装数量。
        输入：
            phase_number: 科研期数。
            target_count: 目标彩装数量。
        输出：
            None。
        使用示例：
            manager.save_phase_target_count(8, 4)
        """
        config = self.get_research_progress_config()
        safe_target = max(1, min(20, int(target_count)))
        phase_targets = dict(config.get("phase_targets", {}))
        phase_targets[str(int(phase_number))] = safe_target
        config["phase_targets"] = phase_targets
        phase_settings = dict(config.get("phase_settings", {}))
        key = self._phase_key(phase_number)
        setting = dict(phase_settings.get(key, {}))
        setting["target"] = safe_target
        setting.setdefault(
            "start_date",
            self.get_phase_setting(phase_number).get("start_date", config.get("fallback_start_date", "")),
        )
        phase_settings[key] = setting
        config["phase_settings"] = phase_settings
        self.config_loader.save_config("ui", "research_progress", config)

    def get_appearance_config(self) -> Dict[str, Any]:
        """
        读取 GUI 外观配置。
        输入：
            无。
        输出：
            dict: 已合并默认值的外观配置。
        使用示例：
            config = manager.get_appearance_config()
        """
        loaded = self.config_loader.get_config("ui", "appearance")
        return self._merge_dicts(DEFAULT_APPEARANCE_UI_CONFIG, loaded)

    def get_secretary_lines_config(self) -> Dict[str, Any]:
        """
        读取秘书舰台词配置。
        输入：
            无。
        输出：
            dict: 已合并默认值的秘书舰台词配置。
        使用示例：
            config = manager.get_secretary_lines_config()
        """
        loaded = self.config_loader.get_config("ui", "secretary_lines")
        return self._merge_dicts(DEFAULT_SECRETARY_LINES_UI_CONFIG, loaded)

    def save_active_skin(self, skin_key: str) -> None:
        """
        保存当前 GUI 皮肤。
        输入：
            skin_key: 皮肤注册表中的稳定键名。
        输出：
            None。
        使用示例：
            manager.save_active_skin("harbor_night")
        """
        config = self.get_appearance_config()
        config["active_skin"] = str(skin_key or "harbor_night")
        self.config_loader.save_config("ui", "appearance", config)

    @staticmethod
    def _phase_key(phase_number: int) -> str:
        """把科研期数转换为配置键。"""
        return f"PR{int(phase_number)}"

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
