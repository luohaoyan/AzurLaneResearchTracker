# test_config_loader.py
from copy import deepcopy
import json
import os
import sys
from pathlib import Path
from typing import Generator

import pytest

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.utils import config_loader as config_loader_module
from core.utils.config_loader import ConfigSaveError, get_config_loader


@pytest.fixture(autouse=True)
def isolate_config_directory(tmp_path: Path) -> Generator[None, None, None]:
    """把配置写入统一隔离到临时目录，禁止测试改写项目正式 JSON。"""
    config_loader = get_config_loader()
    original_dir = config_loader.config_dir
    original_cache = deepcopy(config_loader.cache)
    config_loader.config_dir = tmp_path
    config_loader.cache = deepcopy(original_cache)
    try:
        yield
    finally:
        config_loader.config_dir = original_dir
        config_loader.cache = original_cache


def test_save_config_persists_to_disk_and_cache(tmp_path):
    """save_config 应在磁盘写入成功并校验后再更新缓存。"""
    config_loader = get_config_loader()
    original_dir = config_loader.config_dir
    original_cache = dict(config_loader.cache)
    config_loader.config_dir = tmp_path
    config_loader.cache = {}

    try:
        payload = {"active_skin": "sakura_mist", "nested": {"target": 5}}

        assert config_loader.save_config("ui", "appearance", payload) is True

        saved_path = tmp_path / "ui" / "appearance.json"
        assert saved_path.exists()
        assert json.loads(saved_path.read_text(encoding="utf-8")) == payload
        assert config_loader.cache["ui/appearance"] == payload
    finally:
        config_loader.config_dir = original_dir
        config_loader.cache = original_cache


def test_save_config_failure_keeps_old_disk_file_and_cache(tmp_path, monkeypatch):
    """磁盘替换失败时应抛出异常，并保持旧文件与旧缓存不被污染。"""
    config_loader = get_config_loader()
    original_dir = config_loader.config_dir
    original_cache = dict(config_loader.cache)
    config_loader.config_dir = tmp_path
    config_loader.cache = {}

    try:
        old_payload = {"active_skin": "harbor_night"}
        new_payload = {"active_skin": "sakura_mist"}
        config_loader.save_config("ui", "appearance", old_payload)
        cache_before = dict(config_loader.cache)
        saved_path = tmp_path / "ui" / "appearance.json"

        def fail_replace(_source, _target):
            raise PermissionError("locked by test")

        monkeypatch.setattr(config_loader_module.os, "replace", fail_replace)

        with pytest.raises(ConfigSaveError):
            config_loader.save_config("ui", "appearance", new_payload)

        assert json.loads(saved_path.read_text(encoding="utf-8")) == old_payload
        assert config_loader.cache == cache_before
        assert not saved_path.with_suffix(".json.tmp").exists()
    finally:
        config_loader.config_dir = original_dir
        config_loader.cache = original_cache

def test_config_init():
    # 测试配置初始化
    print("=====配置初始化=======")
    config_loader = get_config_loader()


def test_config_loader():
    """测试配置加载器"""
    print("=== 测试配置加载器 ===")

    # 获取配置加载器实例
    config_loader = get_config_loader()

    # 测试获取主配置
    print("\n1. 获取主配置:")
    main_config = config_loader.get_main_config()
    print(f"应用名称: {main_config.get('app', {}).get('name')}")
    print(f"当前模拟器: {main_config.get('current_simulator')}")
    print(f"当前游戏: {main_config.get('current_game')}")

    # 测试获取模拟器配置
    print("\n2. 获取模拟器配置:")
    mumu_config = config_loader.get_simulator_config("mumu")
    print(f"模拟器名称: {mumu_config.get('name')}")
    print(f"ADB路径: {mumu_config.get('adb', {}).get('path')}")
    print(f"屏幕分辨率: {mumu_config.get('screen', {}).get('width')}x{mumu_config.get('screen', {}).get('height')}")

    # 测试获取游戏配置
    print("\n3. 获取游戏配置:")
    azur_lane_config = config_loader.get_game_config("azur_lane")
    print(f"游戏名称: {azur_lane_config.get('name')}")
    print(f"包名: {azur_lane_config.get('package_name')}")

    # 测试列出可用配置
    print("\n4. 列出可用模拟器:")
    simulators = config_loader.list_available_simulators()
    print(f"可用模拟器: {simulators}")

    print("\n5. 列出可用游戏:")
    games = config_loader.list_available_games()
    print(f"可用游戏: {games}")

    # 测试更新配置
    print("\n6. 测试更新配置:")
    updates = {
        "ui": {
            "theme": "dark",
            "language": "zh_CN"
        }
    }
    config_loader.update_main_config(updates)
    print("配置已更新")

    # 验证更新
    updated_config = config_loader.get_main_config()
    print(f"更新后的主题: {updated_config.get('ui', {}).get('theme')}")

    print("\n=== 配置加载器测试完成 ===")
    print("请检查 config/ 目录，确认配置文件已正确创建")


def test_config_files():
    """测试配置文件"""
    print("\n=== 测试配置文件 ===")

    config_dir = "config"

    # 检查配置文件是否存在
    config_files = []
    for root, dirs, files in os.walk(config_dir):
        for file in files:
            if file.endswith('.json'):
                full_path = os.path.join(root, file)
                config_files.append(full_path)

    print(f"找到 {len(config_files)} 个配置文件:")
    for file_path in config_files:
        file_size = os.path.getsize(file_path)
        print(f"  - {file_path} ({file_size} 字节)")

    print("配置文件测试完成")


if __name__ == "__main__":
    # test_config_init()
    test_config_loader()
    # test_config_files()



    print("\n=== 所有测试完成 ===")
