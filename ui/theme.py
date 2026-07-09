#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║                 🎨 GUI 主题系统 (theme.py)                   ║
║                                                              ║
║  【一句话解释】集中管理 PySide6 界面的颜色、字体和控件样式。   ║
║  【类比理解】主题系统像港区装修手册，所有窗口都按同一套审美。 ║
║  【数据流说明】ThemeTokens → build_stylesheet() → QApplication。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from core.utils.path_manager import PathManager


# ============================================================
# 🏗️ 第二部分：主题数据结构
# ============================================================

@dataclass(frozen=True)
class ThemeTokens:
    """
    GUI 主题令牌。
    输入：
        无，使用默认字段即可。
    输出：
        一个不可变对象，保存颜色、字体和圆角等基础设计值。
    使用示例：
        tokens = ThemeTokens()
        qss = build_stylesheet(tokens)
    """

    background: str = "#07131F"
    surface: str = "#102337"
    surface_soft: str = "#193A56"
    surface_glow: str = "#214E72"
    line: str = "#2C607D"
    text: str = "#EAF7FF"
    text_muted: str = "#A5BDCB"
    sakura: str = "#FF8EC7"
    azure: str = "#58D7FF"
    gold: str = "#FFD36A"
    success: str = "#7EE0A7"
    danger: str = "#FF7A8A"
    nav_width: int = 236
    nav_collapsed_width: int = 60
    radius: int = 8
    font_family: str = '"Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Segoe UI"'
    utility_font_family: str = '"Consolas", "Cascadia Mono", "Microsoft YaHei UI"'


# ============================================================
# 🌐 第三部分：全局样式函数
# ============================================================

def build_stylesheet(tokens: ThemeTokens | None = None) -> str:
    """
    构建 QApplication 可直接使用的 QSS 样式表。
    输入：
        tokens: 可选主题令牌；不传则使用默认港区控制台主题。
    输出：
        str: QSS 文本。
    使用示例：
        app.setStyleSheet(build_stylesheet())
    """
    t = tokens or ThemeTokens()
    return f"""
    QMainWindow {{
        background: {t.background};
        color: {t.text};
        font-family: {t.font_family};
        font-size: 14px;
    }}

    QWidget#central_shell,
    QWidget#page_stack {{
        background: {t.background};
    }}

    QWidget#navigation_panel {{
        background: {t.surface};
        border-right: 1px solid {t.line};
    }}

    QLabel#app_title {{
        color: {t.text};
        font-size: 18px;
        font-weight: 700;
    }}

    QLabel#app_subtitle,
    QLabel#page_summary,
    QLabel#card_caption,
    QLabel#future_status,
    QLabel#muted_text {{
        color: {t.text_muted};
    }}

    QLabel#page_title {{
        color: {t.text};
        font-size: 26px;
        font-weight: 700;
    }}

    QLabel#section_title {{
        color: {t.text};
        font-size: 17px;
        font-weight: 700;
    }}

    QLabel#page_marker {{
        color: {t.gold};
        font-family: {t.utility_font_family};
        font-size: 12px;
        letter-spacing: 0px;
    }}

    QLabel#stat_value {{
        color: {t.text};
        font-size: 22px;
        font-weight: 700;
    }}

    QLabel#stat_label {{
        color: {t.text_muted};
        font-size: 12px;
    }}

    QLabel#prompt_text {{
        color: {t.sakura};
        font-size: 15px;
        font-weight: 700;
    }}

    QLabel#research_day_value {{
        color: {t.text};
        font-size: 30px;
        font-weight: 800;
    }}

    QLabel#secretary_avatar {{
        background: {t.surface_soft};
        color: {t.text_muted};
        border: 1px solid {t.line};
        border-radius: {t.radius}px;
        font-weight: 700;
    }}

    QFrame#secretary_dialog {{
        background: #F5F8FC;
        border: 1px solid rgba(88, 215, 255, 0.45);
        border-radius: {t.radius}px;
    }}

    QLabel#secretary_dialog_text {{
        color: #102337;
        font-size: 13px;
        font-weight: 700;
    }}

    QListWidget#navigation_list {{
        background: transparent;
        border: none;
        outline: none;
        color: {t.text_muted};
    }}

    QListWidget#navigation_list::item {{
        min-height: 42px;
        padding: 8px 10px;
        margin: 3px 4px;
        background: rgba(25, 58, 86, 0.38);
        border: 1px solid rgba(44, 96, 125, 0.46);
        border-radius: {t.radius}px;
    }}

    QListWidget#navigation_list::item:selected {{
        color: {t.text};
        background: {t.surface_soft};
        border-left: 3px solid {t.sakura};
    }}

    QListWidget#navigation_list::item:hover {{
        color: {t.text};
        background: rgba(88, 215, 255, 0.12);
    }}

    QFrame#content_panel,
    QFrame#stat_card,
    QFrame#future_feature_row,
    QFrame#mascot_panel,
    QFrame#chart_panel {{
        background: {t.surface};
        border: 1px solid {t.line};
        border-radius: {t.radius}px;
    }}

    QLabel#panel_title {{
        color: {t.text};
        font-size: 16px;
        font-weight: 700;
    }}

    QLabel#panel_body {{
        color: {t.text_muted};
        line-height: 150%;
    }}

    QPushButton {{
        background: {t.surface_soft};
        color: {t.text};
        border: 1px solid {t.line};
        border-radius: {t.radius}px;
        padding: 8px 12px;
    }}

    QPushButton:hover {{
        border-color: {t.azure};
        background: {t.surface_glow};
    }}

    QPushButton#nav_toggle_button {{
        min-height: 32px;
        padding: 4px 8px;
    }}

    QPushButton#reset_start_date_button {{
        padding: 6px 8px;
    }}

    QComboBox#target_combo {{
        min-width: 108px;
        max-width: 108px;
    }}

    QDateEdit#research_start_date {{
        min-width: 0px;
    }}

    QComboBox,
    QLineEdit,
    QDateEdit {{
        background: {t.surface};
        color: {t.text};
        border: 1px solid {t.line};
        border-radius: {t.radius}px;
        padding: 7px 10px;
    }}

    QTableWidget {{
        background: {t.surface};
        color: {t.text};
        border: 1px solid {t.line};
        border-radius: {t.radius}px;
        gridline-color: {t.line};
        selection-background-color: {t.surface_glow};
    }}

    QHeaderView::section {{
        background: {t.surface_soft};
        color: {t.text};
        border: none;
        padding: 8px;
    }}

    QProgressBar {{
        background: {t.surface};
        color: {t.text};
        border: 1px solid {t.line};
        border-radius: {t.radius}px;
        text-align: center;
        min-height: 18px;
    }}

    QProgressBar::chunk {{
        background: {t.azure};
        border-radius: {t.radius}px;
    }}

    QWidget#log_drawer {{
        background: {t.surface};
        border-top: 1px solid {t.line};
    }}

    QFrame#log_drawer_header {{
        background: {t.surface};
    }}

    QPlainTextEdit#log_text {{
        background: #06111B;
        color: {t.text};
        border: none;
        font-family: {t.utility_font_family};
        font-size: 12px;
    }}

    QStatusBar {{
        background: {t.surface};
        color: {t.text_muted};
        border-top: 1px solid {t.line};
    }}

    QMenuBar {{
        background: {t.surface};
        color: {t.text};
    }}

    QMenuBar::item:selected,
    QMenu::item:selected {{
        background: {t.surface_soft};
    }}

    QMenu {{
        background: {t.surface};
        color: {t.text};
        border: 1px solid {t.line};
    }}
    """


def install_application_fonts(app: QApplication) -> Optional[str]:
    """
    为 QApplication 注册中文字体，并设置默认字体。
    输入：
        app: 当前 QApplication 实例。
    输出：
        Optional[str]: 成功选中的字体族；没有找到时返回 None。
    使用示例：
        family = install_application_fonts(app)
    """
    font_files = _candidate_font_files()
    for font_file in font_files:
        if font_file.exists():
            QFontDatabase.addApplicationFont(str(font_file))

    families = set(QFontDatabase.families())
    for family in [
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Segoe UI",
    ]:
        if family in families:
            app.setFont(QFont(family, 10))
            return family
    return None


def _candidate_font_files() -> List[Path]:
    """返回可主动注册的常见中文字体文件路径。"""
    project_fonts = PathManager.get_project_root() / "resources" / "fonts"
    return [
        project_fonts / "NotoSansSC-Regular.otf",
        project_fonts / "SourceHanSansSC-Regular.otf",
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttc"),
    ]
