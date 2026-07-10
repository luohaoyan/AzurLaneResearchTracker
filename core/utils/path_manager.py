#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# core/utils/path_manager.py
# 进行整个系统绝对路径的配置

import os
from pathlib import Path


class PathManager:
    """路径管理器，确保所有文件操作都基于项目根目录"""
    # 当前文件的路径
    _self_root = Path(__file__)
    # 获取项目根目录（AzurLaneResearchTacker/)
    _project_root = Path(__file__).parent.parent.parent.absolute()

    @classmethod
    def get_self_root(cls):
        """获取路径管理器文件的路径"""
        return cls._self_root

    @classmethod
    def get_project_root(cls):
        """获取项目根目录路径"""
        return cls._project_root

    @classmethod
    def get_config_dir(cls):
        """获取配置目录路径"""
        return cls._project_root / "config"

    @classmethod
    def get_config_path(cls, filename):
        """获取具体配置文件的完整路径"""
        config_dir = cls.get_config_dir()
        # 确保配置目录存在
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / filename

    @classmethod
    def get_log_dir(cls):
        """获取日志目录路径"""
        log_dir = cls._project_root / "Logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir




    @classmethod
    def get_data_dir(cls):
        """获取数据目录路径"""
        data_dir = cls._project_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    @classmethod
    def get_work_dir(cls):
        """获取通用工作目录路径"""
        work_dir = cls._project_root / "workdir"
        work_dir.mkdir(parents=True, exist_ok=True)
        return work_dir

    @classmethod
    def get_crawler_dir(cls):
        """获取爬虫专用工作目录路径"""
        crawler_dir = cls.get_work_dir() / "crawler"
        crawler_dir.mkdir(parents=True, exist_ok=True)
        return crawler_dir

    @classmethod
    def get_crawler_runs_dir(cls):
        """获取爬虫运行记录目录路径"""
        runs_dir = cls.get_crawler_dir() / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        return runs_dir
