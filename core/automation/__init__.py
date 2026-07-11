"""自动化相关核心接口。"""

from .adb_task_api import AdbTaskApi, AdbTaskResult, get_adb_task_api

__all__ = ["AdbTaskApi", "AdbTaskResult", "get_adb_task_api"]
