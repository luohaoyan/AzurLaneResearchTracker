#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# core/utils/config_loader.py
# 整个系统的配置模块

import json
import os
import shutil
from typing import Any, Dict, List, Optional
from .logger import get_logger
from .path_manager import PathManager


class ConfigLoader:
    """配置加载器 - 管理所有配置文件"""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(ConfigLoader, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        # 常用属性初始化
        self.config_dir = PathManager.get_config_dir() # 存储地址
        self.cache = {}

        self.logger = get_logger() # 日志单例

        # 确保配置目录存在
        os.makedirs(self.config_dir, exist_ok=True)

        # 获得配置/进行初始化默认配置
        self._init_default_configs()

        self._initialized = True


    def _init_default_configs(self):
        """初始化默认配置文件"""
        # 主配置文件配置目录
        main_config_path = os.path.join(self.config_dir, "config.json")
        flag = False  # 用来判断是否进行初始化
        if not os.path.exists(main_config_path):
            default_main_config = {
                "app": {
                    "name": "碧蓝航线科研装备统计器",
                    "version": "0.5.0",
                    "author": "Your Name"
                },
                "current_simulator": "mumu",
                "current_game": "azur_lane",
                "data_storage": {
                    "format": "csv",
                    "backup_enabled": True,
                    "backup_interval_days": 7
                },
                "automation": {
                    "enabled": True,
                    "default_delay": 1.0,
                    "retry_count": 3,
                    "screenshot_quality": "high"
                },
                "ui": {
                    "theme": "default",
                    "language": "zh_CN",
                    "auto_save_layout": True
                }
            }
            flag = True
            self.logger.debug(f"初始化主配置文件配置目录, 文件地址:{main_config_path}")
            self._save_config_file("config.json",main_config_path, default_main_config)

        # 模拟器配置目录
        simulators_dir = os.path.join(self.config_dir, "simulators")
        os.makedirs(simulators_dir, exist_ok=True)
        # MuMu模拟器配置
        mumu_config_path = os.path.join(simulators_dir, "mumu.json")
        if not os.path.exists(mumu_config_path):
            default_mumu_config = {
                "name": "MuMu模拟器",
                "type": "mumu",
                "window_class": "MuMuPlayer",
                "window_title": "MuMu",
                "control_method": "adb",
                "adb": {
                    "path": "D:/MuMuPlayer-12.0/shell/adb.exe",
                    "port": 7555,
                    "connect_timeout": 10
                },
                "screen": {
                    "width": 1920,
                    "height": 1080,
                    "dpi": 320
                },
                "performance": {
                    "click_delay": 0.5,
                    "screenshot_delay": 0.3,
                    "template_scale": 1.0
                },
                "custom_commands": {
                    "start_simulator": "D:/MuMuPlayer-12.0/MuMuPlayer.exe",
                    "stop_simulator": "taskkill /f /im MuMuPlayer.exe"
                }
            }
            flag = True
            self.logger.debug(f"初始化MuMu模拟器配置目录, 文件地址:{mumu_config_path}")
            self._save_config_file("mumu.json",mumu_config_path, default_mumu_config)


        # 雷电模拟器配置
        leidian_config_path = os.path.join(simulators_dir, "leidian.json")
        if not os.path.exists(leidian_config_path):
            default_leidian_config = {
                "name": "雷电模拟器",
                "type": "leidian",
                "window_class": "LDPlayerMainFrame",
                "window_title": "雷电模拟器",
                "control_method": "adb",
                "adb": {
                    "path": "C:/LDPlayer/LDPlayer4.0/adb.exe",
                    "port": 5555,
                    "connect_timeout": 10
                },
                "screen": {
                    "width": 1600,
                    "height": 900,
                    "dpi": 240
                },
                "performance": {
                    "click_delay": 0.5,
                    "screenshot_delay": 0.3,
                    "template_scale": 1.0
                },
                "custom_commands": {
                    "start_simulator": "C:/LDPlayer/LDPlayer4.0/LDPlayer.exe",
                    "stop_simulator": "taskkill /f /im LdBoxHeadless.exe"
                }
            }
            flag = True
            self.logger.debug(f"初始化雷电模拟器配置目录, 文件地址:{leidian_config_path}")
            self._save_config_file("leidian.json",leidian_config_path, default_leidian_config)

        # 游戏配置目录
        games_dir = os.path.join(self.config_dir, "games")
        os.makedirs(games_dir, exist_ok=True)

        # 碧蓝航线配置
        azur_lane_config_path = os.path.join(games_dir, "azur_lane.json")
        if not os.path.exists(azur_lane_config_path):
            default_azur_lane_config = {
                "name": "碧蓝航线",
                "package_name": "com.bilibili.azurlane",
                "activity_name": "com.unity3d.player.UnityPlayerActivity",
                "ui_elements": {
                    "game_icon": "resources/templates/azur_lane/ui_elements/game_icon.png",
                    "equipment_button": "resources/templates/azur_lane/ui_elements/equipment_button.png",
                    "research_button": "resources/templates/azur_lane/ui_elements/research_button.png"
                },
                "recognition": {
                    "equipment_region": [100, 200, 800, 600],
                    "fragment_region": [900, 200, 400, 600],
                    "confidence_threshold": 0.8
                },
                "calculations": {
                    "fragment_formulas": {
                        "gold_research": "equipment_count * 25 + fragment_count",
                        "rainbow": "equipment_count * 50 + fragment_count",
                        "gold_normal": "equipment_count * 15 + fragment_count"
                    },
                    "luck_formula": "rainbow_fragments / sum(gold_fragments)"
                }
            }
            flag = True
            self.logger.debug(f"初始化游戏配置目录, 文件地址:{azur_lane_config_path}")
            self._save_config_file("azur_lane.json",azur_lane_config_path, default_azur_lane_config)

        # 自动化配置目录
        automation_dir = os.path.join(self.config_dir, "automation")
        os.makedirs(automation_dir, exist_ok=True)

        # 点击序列配置
        sequences_config_path = os.path.join(automation_dir, "sequences.json")
        if not os.path.exists(sequences_config_path):
            default_sequences_config = {
                "login": [
                    {"action": "click", "x": 100, "y": 200, "delay": 2.0},
                    {"action": "click", "x": 300, "y": 400, "delay": 1.0}
                ],
                "equipment": [
                    {"action": "click", "x": 500, "y": 600, "delay": 1.5}
                ]
            }
            flag = True
            self.logger.debug(f"初始化点击序列配置, 文件地址:{sequences_config_path}")
            self._save_config_file("sequences.json",sequences_config_path, default_sequences_config)

        # 判断是否进行初始化
        if flag:
            self.logger.debug(f"配置加载器已初始化，配置目录: {os.path.abspath(self.config_dir)}")

    def _save_config_file(self, file_name, file_path: str, config_data: Dict[str, Any]):
        """保存配置文件"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
            self.logger.debug(f"已保存配置文件{file_name}, 文件路径:{file_path}")
        except Exception as e:
            self.logger.error(f"保存配置文件{file_name}失败, 文件失败路径: {file_path}: {e}")


    def get_config(self, config_type: str, config_name: str = None) -> Dict[str, Any]:
        """
        获取配置

        Args:
            config_type: 配置类型，如 'simulators', 'games', 'automation'
            config_name: 配置名称，如 'mumu', 'azur_lane'

        Returns:
            配置字典
        """
        cache_key = f"{config_type}/{config_name}" if config_name else config_type

        # 检查缓存
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            if config_name:
                # 获取特定配置
                config_path = os.path.join(self.config_dir, config_type, f"{config_name}.json")
            else:
                # 获取主配置
                config_path = os.path.join(self.config_dir, f"{config_type}.json")

            if not os.path.exists(config_path):
                self.logger.warning(f"配置文件不存在: {config_path}")
                return {}

            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)

            # 缓存配置
            self.cache[cache_key] = config_data
            self.logger.debug(f"已加载配置: {cache_key}")

            return config_data

        except Exception as e:
            self.logger.error(f"加载配置失败 {cache_key}: {e}")
            return {}

    def save_config(self, config_type: str, config_name: str, config_data: Dict[str, Any]):
        """
        保存配置

        Args:
            config_type: 配置类型
            config_name: 配置名称
            config_data: 配置数据
        """
        try:
            config_dir = os.path.join(self.config_dir, config_type)
            os.makedirs(config_dir, exist_ok=True)

            config_path = os.path.join(config_dir, f"{config_name}.json")

            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)

            # 更新缓存
            cache_key = f"{config_type}/{config_name}"
            self.cache[cache_key] = config_data

            self.logger.info(f"已保存配置: {cache_key}")

        except Exception as e:
            self.logger.error(f"保存配置失败 {config_type}/{config_name}: {e}")

    def get_simulator_config(self, simulator_name: str = None) -> Dict[str, Any]:
        """
        获取模拟器配置

        Args:
            simulator_name: 模拟器名称，如果为None则使用当前模拟器

        Returns:
            模拟器配置
        """
        if simulator_name is None:
            main_config = self.get_config("config")
            simulator_name = main_config.get("current_simulator", "mumu")

        return self.get_config("simulators", simulator_name)

    def get_game_config(self, game_name: str = None) -> Dict[str, Any]:
        """
        获取游戏配置

        Args:
            game_name: 游戏名称，如果为None则使用当前游戏

        Returns:
            游戏配置
        """
        if game_name is None:
            main_config = self.get_config("config")
            game_name = main_config.get("current_game", "azur_lane")

        return self.get_config("games", game_name)

    def get_automation_config(self, config_name: str) -> Dict[str, Any]:
        """
        获取自动化配置

        Args:
            config_name: 自动化配置名称

        Returns:
            自动化配置
        """
        return self.get_config("automation", config_name)

    def get_main_config(self) -> Dict[str, Any]:
        """
        获取主配置

        Returns:
            主配置
        """
        return self.get_config("config")

    def _deep_update(self, original: Dict[str, Any], updates: Dict[str, Any]):
        """
        深度更新字典

        Args:
            original: 原始字典
            updates: 更新字典
        """
        for key, value in updates.items():
            if isinstance(value, dict) and key in original and isinstance(original[key], dict):
                self._deep_update(original[key], value)
            else:
                original[key] = value

    def update_main_config(self, updates: Dict[str, Any]):
        """
        更新主配置

        Args:
            updates: 要更新的配置项
        """
        main_config = self.get_main_config()

        # 深度更新配置
        self._deep_update(main_config, updates)

        # 保存更新后的配置
        self.save_config("", "config", main_config)



    def list_available_configs(self, config_type: str) -> List[str]:
        """
        列出可用的配置

        Args:
            config_type: 配置类型

        Returns:
            配置名称列表
        """
        config_dir = os.path.join(self.config_dir, config_type)

        if not os.path.exists(config_dir):
            return []

        config_files = [f for f in os.listdir(config_dir) if f.endswith('.json')]
        config_names = [os.path.splitext(f)[0] for f in config_files]

        return config_names

    def list_available_simulators(self) -> List[str]:
        """
        列出可用的模拟器

        Returns:
            模拟器名称列表
        """
        return self.list_available_configs("simulators")

    def list_available_games(self) -> List[str]:
        """
        列出可用的游戏

        Returns:
            游戏名称列表
        """
        return self.list_available_configs("games")


# 全局配置加载器实例
_config_loader_instance = None


def get_config_loader() -> ConfigLoader:
    """获取全局配置加载器实例"""
    global _config_loader_instance
    if _config_loader_instance is None:
        _config_loader_instance = ConfigLoader()
    return _config_loader_instance
