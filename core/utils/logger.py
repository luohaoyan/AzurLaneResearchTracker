#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# core/utils/logger.py
# 整个系统的日志模块


import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from .path_manager import PathManager


class Logger:
    """日志管理类"""

    # 单例模式
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Logger, cls).__new__(cls)
        return cls._instance

    def __init__(self, name="AzurLaneResearchTracker", level=logging.DEBUG):
        """
        初始化日志器

        Args:
            name: 日志器名称
            log_dir: 日志目录
            level: 日志级别
        """
        # 避免重复初始化
        if hasattr(self, '_initialized'):
            return

        self.name = name
        self.log_dir = PathManager.get_log_dir()  # 将日志目录设置为程序目录/Logs文件夹
        self.level = level

        # 创建日志目录
        os.makedirs(self.log_dir, exist_ok=True)
        # 生成基于日期时间的文件名
        self.start_time = datetime.now().strftime("%Y%m%d") # 按照 name + 是否error + 日期进行存储

        # 初始化日志器
        self._setup_logger()
        self._initialized = True

    def _setup_logger(self):
        # 配置标准化日志器
        # 创建日志器
        self._std_logger = logging.getLogger(self.name)
        self._std_logger.setLevel(self.level)
        # 清楚已有标准化日志器
        self._std_logger.handlers.clear()

        # 设置日志格式
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)

        # 主日志文件处理器 - 使用日期时间文件名
        main_log_filename = f"{self.name}_{self.start_time}.log"
        main_log_path = os.path.join(self.log_dir, main_log_filename)
        main_file_handler = RotatingFileHandler(
            filename=main_log_path,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        main_file_handler.setLevel(logging.DEBUG)
        main_file_handler.setFormatter(formatter)
        # 错误日志文件处理器 - 单独记录ERROR及以上级别的日志
        error_log_filename = f"{self.name}_error_{self.start_time}.log"
        error_log_path = os.path.join(self.log_dir, error_log_filename)
        error_file_handler = RotatingFileHandler(
            filename=error_log_path,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        error_file_handler.setLevel(logging.ERROR)
        error_file_handler.setFormatter(formatter)

        # 添加处理器到日志器
        self._std_logger.addHandler(console_handler)
        self._std_logger.addHandler(main_file_handler)
        self._std_logger.addHandler(error_file_handler)

    # 不同日志器获取方法
    def get_std_logger(self):
        """获取标准日志器实例"""
        return self._std_logger

    # 标准日志方法 - 显示定义

    def debug(self, message, *args, **kwargs):
        """DEBUG级别日志"""
        self._std_logger.debug(message, *args, **kwargs)

    def info(self, message, *args, **kwargs):
        """INFO级别日志"""
        self._std_logger.info(message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        """WARNING级别日志"""
        self._std_logger.warning(message, *args, **kwargs)

    def error(self, message, *args, **kwargs):
        """ERROR级别日志"""
        self._std_logger.error(message, *args, **kwargs)

    def critical(self, message, *args, **kwargs):
        """CRITICAL级别日志"""
        self._std_logger.critical(message, *args, **kwargs)

    def exception(self, message, *args, **kwargs):
        """异常日志（自动包含堆栈信息）"""
        self._std_logger.exception(message, *args, **kwargs)

    # 自定义日志方法
    def log_performance(self, operation, execution_time):
        """记录性能日志"""
        self.info(f"性能统计 - 操作: {operation}, 耗时: {execution_time:.3f}秒")

    def log_automation_step(self, step_name, status="完成", details=""):
        """记录自动化步骤日志"""
        if details:
            self.info(f"自动化步骤 - {step_name} - {status} - {details}")
        else:
            self.info(f"自动化步骤 - {step_name} - {status}")

    def log_equipment_operation(self, operation, equipment_name, equipment_id, details=""):
        """记录装备操作日志"""
        if details:
            self.info(f"装备操作 - {operation} - {equipment_name}(ID:{equipment_id}) - {details}")
        else:
            self.info(f"装备操作 - {operation} - {equipment_name}(ID:{equipment_id})")


# 全局日志器实例
_logger_instance = None


def get_logger(name="AzurLaneResearchTracker"):
    """获取全局日志器实例"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = Logger(name=name)
    return _logger_instance


def get_std_logger(name="AzurLaneResearchTracker"):
    """获取全局日志器实例"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = Logger(name=name)
    return _logger_instance.get_std_logger()


def setup_logging(name="AzurLaneResearchTracker",  level=logging.DEBUG):
    """设置全局日志配置（便捷函数）"""
    global _logger_instance
    _logger_instance = Logger(name=name, level=level)
    return _logger_instance


# 便捷的日志函数
def debug(message, *args, **kwargs):
    get_std_logger().debug(message, *args, **kwargs)


def info(message, *args, **kwargs):
    get_std_logger().info(message, *args, **kwargs)


def warning(message, *args, **kwargs):
    get_std_logger().warning(message, *args, **kwargs)


def error(message, *args, **kwargs):
    get_std_logger().error(message, *args, **kwargs)


def critical(message, *args, **kwargs):
    get_std_logger().critical(message, *args, **kwargs)


def exception(message, *args, **kwargs):
    get_std_logger().exception(message, *args, **kwargs)
