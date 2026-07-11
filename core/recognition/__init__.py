"""OCR 识别相关核心接口。"""

from .ocr_task_api import OcrTaskApi, OcrTaskResult, get_ocr_task_api

__all__ = ["OcrTaskApi", "OcrTaskResult", "get_ocr_task_api"]
