#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║                 📜 运行日志抽屉 (log_drawer.py)              ║
║                                                              ║
║  【一句话解释】在 GUI 底部展示本次运行日志，方便用户复制反馈。║
║  【类比理解】它像港区通讯记录，平时收起，需要时展开查看。     ║
║  【数据流说明】logging → GuiLogHandler → LogDrawer → 剪贴板。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import logging
import platform
import sys
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.state.runtime_state import get_runtime_state_manager
from core.utils.config_loader import get_config_loader
from core.utils.logger import get_std_logger


# ============================================================
# 🏗️ 第二部分：核心类
# ============================================================

class GuiLogHandler(logging.Handler):
    """
    GUI 日志处理器。
    输入：
        LogDrawer 实例。
    输出：
        logging.Handler，把标准日志推送给抽屉。
    使用示例：
        logger.addHandler(GuiLogHandler(drawer))
    """

    def __init__(self, drawer: "LogDrawer") -> None:
        """创建处理器并保存抽屉引用。"""
        super().__init__(logging.DEBUG)
        self.drawer = drawer

    def emit(self, record: logging.LogRecord) -> None:
        """
        接收 logging 记录并推送到 GUI。
        输入：
            record: 标准日志记录。
        输出：
            None。
        使用示例：
            logging 会自动调用。
        """
        try:
            self.drawer.append_record(record.levelname, self.format(record))
        except Exception:
            self.handleError(record)


class LogDrawer(QWidget):
    """
    底部可折叠运行日志抽屉。
    输入：
        parent: 可选父组件。
    输出：
        QWidget，包含过滤、复制、清空和诊断信息复制功能。
    使用示例：
        drawer = LogDrawer()
        drawer.install_logging_handler()
    """

    logAdded = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化日志抽屉，默认收起且只保存本次运行日志。"""
        super().__init__(parent)
        self.setObjectName("log_drawer")
        self._entries: List[dict[str, str]] = []
        self._handler: Optional[GuiLogHandler] = None
        self._expanded = False
        self._animation: Optional[QPropertyAnimation] = None
        self.collapsed_height = 48
        self.expanded_height = 260
        self.animation_duration_ms = 180

        self._build_ui()
        self.set_expanded(False, animate=False)
        self.logAdded.connect(self._on_log_added)

    def _build_ui(self) -> None:
        """构建日志抽屉界面。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("log_drawer_header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(8)

        self.toggle_button = QPushButton("展开日志")
        self.toggle_button.setToolTip("展开或收起运行日志")
        self.toggle_button.clicked.connect(self.toggle)
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["全部", "INFO", "WARNING", "ERROR"])
        self.filter_combo.currentTextChanged.connect(self.refresh_view)
        self.auto_scroll_check = QCheckBox("自动滚动")
        self.auto_scroll_check.setChecked(True)
        self.copy_button = QPushButton("复制全部")
        self.copy_button.clicked.connect(self.copy_all)
        self.copy_diagnostic_button = QPushButton("复制诊断信息")
        self.copy_diagnostic_button.clicked.connect(self.copy_diagnostic_info)
        self.clear_button = QPushButton("清空")
        self.clear_button.clicked.connect(self.clear)

        self.filter_label = QLabel("筛选")

        header_layout.addWidget(self.toggle_button)
        header_layout.addWidget(self.filter_label)
        header_layout.addWidget(self.filter_combo)
        header_layout.addWidget(self.auto_scroll_check)
        header_layout.addStretch(1)
        header_layout.addWidget(self.copy_button)
        header_layout.addWidget(self.copy_diagnostic_button)
        header_layout.addWidget(self.clear_button)

        self.log_text = QPlainTextEdit()
        self.log_text.setObjectName("log_text")
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_text.setPlaceholderText("本次运行日志会显示在这里。")

        root.addWidget(header)
        root.addWidget(self.log_text)

    def install_logging_handler(self) -> None:
        """
        将抽屉接入项目标准 logger。
        输入：
            无。
        输出：
            None。
        使用示例：
            drawer.install_logging_handler()
        """
        if self._handler is not None:
            return
        handler = GuiLogHandler(self)
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        get_std_logger().addHandler(handler)
        self._handler = handler

    def append_record(self, level: str, message: str) -> None:
        """
        追加一条日志。
        输入：
            level: 日志级别。
            message: 日志内容。
        输出：
            None。
        使用示例：
            drawer.append_record("INFO", "启动完成")
        """
        self.logAdded.emit(level, message)

    def append_message(self, level: str, message: str) -> None:
        """
        直接追加一条 GUI 日志。
        输入：
            level: 日志级别。
            message: 日志内容。
        输出：
            None。
        使用示例：
            drawer.append_message("INFO", "用户打开日志")
        """
        self._append_entry(level, message)

    def toggle(self) -> None:
        """
        展开或收起日志抽屉。
        输入：
            无。
        输出：
            None。
        使用示例：
            drawer.toggle()
        """
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool, animate: bool = True) -> None:
        """
        设置日志抽屉展开状态。
        输入：
            expanded: True 展开，False 收起。
            animate: 是否使用高度动画。
        输出：
            None。
        使用示例：
            drawer.set_expanded(True)
        """
        self._expanded = expanded
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.toggle_button.setText("收起日志" if expanded else "展开日志")

        detail_widgets = [
            self.log_text,
            self.filter_label,
            self.filter_combo,
            self.auto_scroll_check,
            self.copy_button,
            self.copy_diagnostic_button,
            self.clear_button,
        ]
        if expanded:
            for widget in detail_widgets:
                widget.setVisible(True)

        target_height = self.expanded_height if expanded else self.collapsed_height
        if not animate:
            self.setMinimumHeight(target_height)
            self.setMaximumHeight(target_height)
            if not expanded:
                for widget in detail_widgets:
                    widget.setVisible(False)
            return

        if self._animation is not None:
            self._animation.stop()
        self._animation = QPropertyAnimation(self, b"maximumHeight", self)
        self._animation.setDuration(self.animation_duration_ms)
        self._animation.setStartValue(self.height())
        self._animation.setEndValue(target_height)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animation.valueChanged.connect(lambda value: self.setMinimumHeight(int(value)))
        self._animation.finished.connect(lambda: self._finish_expand_animation(expanded, detail_widgets))
        self._animation.start()
        QTimer.singleShot(
            self.animation_duration_ms + 30,
            lambda: self._finish_expand_animation(expanded, detail_widgets),
        )

    def _finish_expand_animation(self, expanded: bool, detail_widgets: List[QWidget]) -> None:
        """动画结束后固定高度，并在收起时隐藏日志细节控件。"""
        if self._expanded != expanded:
            return
        target_height = self.expanded_height if expanded else self.collapsed_height
        self.setMinimumHeight(target_height)
        self.setMaximumHeight(target_height)
        if not expanded:
            for widget in detail_widgets:
                widget.setVisible(False)

    def refresh_view(self) -> None:
        """
        根据筛选条件刷新日志文本。
        输入：
            无。
        输出：
            None。
        使用示例：
            drawer.refresh_view()
        """
        selected = self.filter_combo.currentText()
        lines = []
        for entry in self._entries:
            if selected != "全部" and entry["level"] != selected:
                continue
            lines.append(entry["line"])
        self.log_text.setPlainText("\n".join(lines))
        if self.auto_scroll_check.isChecked():
            self._scroll_to_bottom()

    def copy_all(self) -> None:
        """
        复制当前全部运行日志。
        输入：
            无。
        输出：
            None。
        使用示例：
            drawer.copy_all()
        """
        QGuiApplication.clipboard().setText("\n".join(entry["line"] for entry in self._entries))

    def copy_diagnostic_info(self) -> None:
        """
        复制诊断信息。
        输入：
            无。
        输出：
            None。
        使用示例：
            drawer.copy_diagnostic_info()
        """
        app_config = get_config_loader().get_main_config().get("app", {})
        state = get_runtime_state_manager().get_full_state()
        lines = [
            "碧蓝航线科研装备统计器诊断信息",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"版本: {app_config.get('version', 'unknown')}",
            f"Python: {sys.version.split()[0]}",
            f"系统: {platform.platform()}",
            f"当前任务: {state['task'].get('kind_name', '未知')}",
            f"任务进度: {state['task'].get('progress', 0)}%",
            f"最近错误: {state['task'].get('last_error', '无')}",
            "",
            "本次运行日志:",
            "\n".join(entry["line"] for entry in self._entries[-200:]) or "无",
        ]
        QGuiApplication.clipboard().setText("\n".join(lines))

    def clear(self) -> None:
        """
        清空本次运行日志面板。
        输入：
            无。
        输出：
            None。
        使用示例：
            drawer.clear()
        """
        self._entries.clear()
        self.log_text.clear()

    def _on_log_added(self, level: str, message: str) -> None:
        """Qt 信号槽：把跨层日志写入 GUI 列表。"""
        self._append_entry(level, message)

    def _append_entry(self, level: str, message: str) -> None:
        """内部追加日志条目并刷新显示。"""
        normalized_level = level.upper()
        if normalized_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            normalized_level = "INFO"
        display_level = "ERROR" if normalized_level == "CRITICAL" else normalized_level
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] [{display_level}] {message}"
        self._entries.append({"level": display_level, "line": line})
        self.refresh_view()

    def _scroll_to_bottom(self) -> None:
        """把日志文本滚动到最底部。"""
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)
