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
from typing import Dict, List, Optional

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
    table_header: str = "#18314A"
    table_row: str = "#0D1C2B"
    table_row_alt: str = "#13283C"
    table_grid: str = "#23435E"
    table_selection: str = "#285C7C"
    table_selection_text: str = "#F4FBFF"
    nav_width: int = 236
    nav_collapsed_width: int = 60
    radius: int = 8
    font_family: str = '"Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Segoe UI"'
    utility_font_family: str = '"Consolas", "Cascadia Mono", "Microsoft YaHei UI"'


@dataclass(frozen=True)
class ThemeSkin:
    """
    GUI 皮肤定义。
    输入：
        key/name/description/tokens 等皮肤描述字段。
    输出：
        一个可被设置页展示、可被 MainWindow 应用的皮肤对象。
    使用示例：
        skin = get_theme_skin("harbor_night")
    """

    key: str
    name: str
    description: str
    accent_name: str
    preview_colors: List[str]
    tokens: ThemeTokens


THEME_SKINS: Dict[str, ThemeSkin] = {
    "harbor_night": ThemeSkin(
        key="harbor_night",
        name="港区夜航",
        description="低眩光深色控制台，适合长时间盯着表格和日志。",
        accent_name="蓝粉航迹",
        preview_colors=["#07131F", "#102337", "#58D7FF", "#FF8EC7"],
        tokens=ThemeTokens(),
    ),
    "sakura_mist": ThemeSkin(
        key="sakura_mist",
        name="樱雾晨间",
        description="偏柔和的明亮皮肤预留，后续可接入秘书舰立绘和节日素材。",
        accent_name="樱雾金边",
        preview_colors=["#F7FAFD", "#E9F1F8", "#D96BA8", "#4CA3C7"],
        tokens=ThemeTokens(
            background="#F7FAFD",
            surface="#E9F1F8",
            surface_soft="#D9E8F2",
            surface_glow="#C8E5F5",
            line="#A8C0D0",
            text="#18314A",
            text_muted="#5F7180",
            sakura="#D96BA8",
            azure="#4CA3C7",
            gold="#B98D24",
            success="#318C63",
            danger="#C84D61",
            table_header="#D8E7F0",
            table_row="#FDFEFF",
            table_row_alt="#EEF6FB",
            table_grid="#C8D7E2",
            table_selection="#B8DFF1",
            table_selection_text="#102337",
        ),
    ),
    "iron_blood": ThemeSkin(
        key="iron_blood",
        name="铁血机库",
        description="黑红钢铁机库风格，边框更锐利，适合自动化与调试场景。",
        accent_name="红轴警戒",
        preview_colors=["#08090D", "#181820", "#D7263D", "#C9B27C"],
        tokens=ThemeTokens(
            background="#08090D",
            surface="#181820",
            surface_soft="#24242E",
            surface_glow="#3A1E28",
            line="#4A3038",
            text="#F3F0EA",
            text_muted="#B7AEB2",
            sakura="#D7263D",
            azure="#A7B2C8",
            gold="#C9B27C",
            success="#75C48B",
            danger="#FF4D5E",
            table_header="#221B22",
            table_row="#101116",
            table_row_alt="#171820",
            table_grid="#3A3038",
            table_selection="#4B1F2B",
            table_selection_text="#F7FBFF",
            radius=5,
        ),
    ),
    "dragon_empery": ThemeSkin(
        key="dragon_empery",
        name="东煌庭院",
        description="红金与青玉色的温润阵营皮肤，适合明亮但不刺眼的日常统计。",
        accent_name="玉阶金纹",
        preview_colors=["#F7F2EA", "#E7D4B5", "#B83232", "#2F8F83"],
        tokens=ThemeTokens(
            background="#F7F2EA",
            surface="#EFE3D1",
            surface_soft="#E5D2B5",
            surface_glow="#DDBB7A",
            line="#C8A66A",
            text="#2A211A",
            text_muted="#6F5D4C",
            sakura="#B83232",
            azure="#2F8F83",
            gold="#A77C22",
            success="#2C8A58",
            danger="#B23A48",
            table_header="#E1C79D",
            table_row="#FBF8F1",
            table_row_alt="#F1E7D6",
            table_grid="#D1B88A",
            table_selection="#DDBB7A",
            table_selection_text="#2A211A",
        ),
    ),
    "eagle_union": ThemeSkin(
        key="eagle_union",
        name="白鹰船坞",
        description="海军蓝、星章白与高亮红的现代舰队感，本阶段先开放骨架。",
        accent_name="星海蓝白",
        preview_colors=["#0D2A4A", "#F5F7FA", "#C73542", "#4CA3FF"],
        tokens=ThemeTokens(
            background="#0D2A4A",
            surface="#14375D",
            surface_soft="#1E4B7A",
            surface_glow="#2A65A0",
            line="#477DAF",
            text="#F5F7FA",
            text_muted="#BCD2E8",
            sakura="#C73542",
            azure="#4CA3FF",
            gold="#F0C36A",
            table_header="#183D66",
            table_row="#0F2945",
            table_row_alt="#17375A",
            table_grid="#315F8C",
            table_selection="#245B91",
        ),
    ),
    "northern_parliament": ThemeSkin(
        key="northern_parliament",
        name="北联冰港",
        description="冰蓝、银白与冷灰的极地阵营皮肤，本阶段先开放骨架。",
        accent_name="极地冰辉",
        preview_colors=["#EAF4FA", "#CADBE6", "#5D88A8", "#FFFFFF"],
        tokens=ThemeTokens(
            background="#EAF4FA",
            surface="#DDEBF3",
            surface_soft="#CADBE6",
            surface_glow="#B1CAD9",
            line="#91AFC0",
            text="#1D3444",
            text_muted="#5D7180",
            sakura="#8C6FAE",
            azure="#3D88B5",
            gold="#9C7B38",
            table_header="#C9DDE9",
            table_row="#F8FCFE",
            table_row_alt="#EAF4FA",
            table_grid="#BCD0DD",
            table_selection="#B7D6E8",
            table_selection_text="#1D3444",
        ),
    ),
    "sakura_empire": ThemeSkin(
        key="sakura_empire",
        name="重樱夜港",
        description="深靛夜色与樱粉点缀的和风阵营皮肤，本阶段先开放骨架。",
        accent_name="夜樱绯影",
        preview_colors=["#17132A", "#2E244A", "#E986B8", "#D6B56D"],
        tokens=ThemeTokens(
            background="#17132A",
            surface="#211B38",
            surface_soft="#2E244A",
            surface_glow="#49355E",
            line="#5D4771",
            text="#F5EEF8",
            text_muted="#C7B6D0",
            sakura="#E986B8",
            azure="#8BBBE8",
            gold="#D6B56D",
            table_header="#2A2141",
            table_row="#1B1630",
            table_row_alt="#241D3B",
            table_grid="#4B3A61",
            table_selection="#5A3B61",
        ),
    ),
}


def list_theme_skins() -> List[ThemeSkin]:
    """
    返回所有可选 GUI 皮肤。
    输入：
        无。
    输出：
        List[ThemeSkin]: 按注册顺序排列的皮肤列表。
    使用示例：
        skins = list_theme_skins()
    """
    return list(THEME_SKINS.values())


def get_theme_skin(key: str) -> ThemeSkin:
    """
    按 key 获取皮肤，未知 key 自动回退到港区夜航。
    输入：
        key: 皮肤稳定键名。
    输出：
        ThemeSkin: 可直接应用的皮肤对象。
    使用示例：
        skin = get_theme_skin("harbor_night")
    """
    return THEME_SKINS.get(str(key or "").strip(), THEME_SKINS["harbor_night"])


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

    QWidget {{
        color: {t.text};
        font-family: {t.font_family};
    }}

    QLabel,
    QCheckBox {{
        color: {t.text};
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
        background: {t.surface};
        color: {t.text_muted};
        border: 1px solid {t.surface_glow};
        border-radius: {t.radius}px;
        font-weight: 700;
    }}

    QFrame#secretary_dialog {{
        background: {t.surface_soft};
        border: 1px solid {t.surface_glow};
        border-radius: {t.radius}px;
    }}

    QFrame#secretary_dialog[quiet="true"] {{
        background: transparent;
        border: 1px solid transparent;
    }}

    QLabel#secretary_dialog_text {{
        color: {t.text};
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
        background: {t.surface_soft};
        border: 1px solid {t.line};
        border-radius: {t.radius}px;
    }}

    QListWidget#navigation_list::item:selected {{
        color: {t.text};
        background: {t.surface_soft};
        border-left: 3px solid {t.sakura};
    }}

    QListWidget#navigation_list::item:hover {{
        color: {t.text};
        background: {t.surface_glow};
    }}

    QListWidget#selected_equipment_line_list {{
        background: {t.table_row};
        alternate-background-color: {t.table_row_alt};
        color: {t.text};
        border: 1px solid {t.table_grid};
        border-radius: {t.radius}px;
        padding: 3px;
        outline: none;
        selection-background-color: {t.table_selection};
        selection-color: {t.table_selection_text};
    }}

    QListWidget#selected_equipment_line_list::item {{
        background: transparent;
        color: {t.text};
        border: none;
        border-radius: {max(3, t.radius - 2)}px;
        padding: 7px 9px;
        min-height: 22px;
    }}

    QListWidget#selected_equipment_line_list::item:hover {{
        background: {t.surface_glow};
        color: {t.text};
    }}

    QListWidget#selected_equipment_line_list::item:selected {{
        background: {t.table_selection};
        color: {t.table_selection_text};
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

    QFrame#future_feature_row QLabel#panel_title {{
        color: {t.text};
        font-size: 16px;
        font-weight: 700;
        padding-bottom: 1px;
    }}

    QFrame#future_feature_row QLabel#panel_body {{
        color: {t.text_muted};
        font-size: 13px;
        padding-top: 1px;
        padding-bottom: 1px;
    }}

    QFrame#future_feature_row QLabel#future_status {{
        color: {t.azure};
        font-size: 12px;
        padding-top: 1px;
    }}

    QLabel#chart_axis_badge {{
        background: {t.surface_soft};
        color: {t.azure};
        border: 1px solid {t.line};
        border-radius: {t.radius}px;
        padding: 4px 10px;
        font-family: {t.utility_font_family};
        font-weight: 700;
    }}

    QScrollArea#future_scroll_area,
    QScrollArea#page_scroll_area {{
        background: transparent;
        border: none;
    }}

    QWidget#future_scroll_content,
    QWidget#page_scroll_content {{
        background: transparent;
    }}

    QScrollArea#page_scroll_area > QWidget > QWidget {{
        background: transparent;
    }}

    QTabWidget::pane {{
        background: {t.surface};
        border: 1px solid {t.line};
        border-radius: {t.radius}px;
        top: -1px;
    }}

    QTabBar::tab {{
        background: {t.surface_soft};
        color: {t.text_muted};
        border: 1px solid {t.line};
        border-bottom: none;
        padding: 8px 16px;
        min-width: 96px;
        min-height: 28px;
    }}

    QTabBar::tab:selected {{
        background: {t.surface};
        color: {t.text};
        border-color: {t.azure};
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
        min-width: 92px;
        max-width: 92px;
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

    QCalendarWidget {{
        background: {t.surface};
        color: {t.text};
        border: 1px solid {t.line};
        border-radius: {t.radius}px;
    }}

    QCalendarWidget QWidget#qt_calendar_navigationbar {{
        background: {t.surface_soft};
        border: none;
        border-bottom: 1px solid {t.line};
        min-height: 34px;
    }}

    QCalendarWidget QToolButton {{
        background: transparent;
        color: {t.text};
        border: none;
        border-radius: {max(3, t.radius - 2)}px;
        margin: 3px;
        padding: 5px 8px;
        font-weight: 700;
    }}

    QCalendarWidget QToolButton:hover {{
        background: {t.surface_glow};
        color: {t.text};
    }}

    QCalendarWidget QToolButton#qt_calendar_prevmonth,
    QCalendarWidget QToolButton#qt_calendar_nextmonth {{
        qproperty-icon: none;
        color: {t.azure};
        min-width: 28px;
        max-width: 28px;
    }}

    QCalendarWidget QMenu {{
        background: {t.surface};
        color: {t.text};
        border: 1px solid {t.line};
    }}

    QCalendarWidget QSpinBox {{
        background: {t.surface};
        color: {t.text};
        border: 1px solid {t.line};
        border-radius: {max(3, t.radius - 2)}px;
        padding: 4px 8px;
        selection-background-color: {t.table_selection};
        selection-color: {t.table_selection_text};
    }}

    QCalendarWidget QAbstractItemView {{
        background: {t.table_row};
        alternate-background-color: {t.table_row_alt};
        color: {t.text};
        selection-background-color: {t.azure};
        selection-color: {t.background};
        border: none;
        outline: none;
        gridline-color: {t.table_grid};
    }}

    QCalendarWidget QAbstractItemView:disabled {{
        background: {t.table_row};
        color: {t.line};
    }}

    QCalendarWidget QAbstractItemView::item:disabled {{
        background: {t.table_row};
        color: {t.line};
    }}

    QTableWidget {{
        background: {t.table_row};
        alternate-background-color: {t.table_row_alt};
        color: {t.text};
        border: 1px solid {t.table_grid};
        border-radius: {t.radius}px;
        gridline-color: {t.table_grid};
        selection-background-color: {t.table_selection};
        selection-color: {t.table_selection_text};
        outline: none;
        padding: 2px;
    }}

    QTableWidget::item {{
        border: none;
        padding: 7px 10px;
    }}

    QComboBox QAbstractItemView {{
        background: {t.surface};
        color: {t.text};
        border: 1px solid {t.line};
        selection-background-color: {t.surface_glow};
        selection-color: {t.text};
    }}

    QTableWidget::item:hover {{
        background: rgba(88, 215, 255, 0.10);
    }}

    QTableWidget::item:selected {{
        background: {t.table_selection};
        color: {t.table_selection_text};
    }}

    QHeaderView {{
        background: {t.table_header};
        border: none;
    }}

    QHeaderView::section {{
        background: {t.table_header};
        color: {t.text};
        border: none;
        border-right: 1px solid {t.table_grid};
        border-bottom: 1px solid {t.table_grid};
        padding: 9px 10px;
        font-weight: 700;
    }}

    QTableCornerButton::section {{
        background: {t.table_header};
        border: none;
        border-bottom: 1px solid {t.table_grid};
    }}

    QScrollBar:vertical {{
        background: {t.surface};
        width: 10px;
        margin: 2px;
        border-radius: 5px;
    }}

    QScrollBar::handle:vertical {{
        background: {t.surface_glow};
        border-radius: 5px;
        min-height: 32px;
    }}

    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QScrollBar:horizontal {{
        background: {t.surface};
        height: 10px;
        margin: 2px;
        border-radius: 5px;
    }}

    QScrollBar::handle:horizontal {{
        background: {t.surface_glow};
        border-radius: 5px;
        min-width: 32px;
    }}

    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {{
        width: 0px;
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
        background: {t.table_row};
        color: {t.text};
        border: none;
        font-family: {t.utility_font_family};
        font-size: 12px;
    }}

    QWidget#task_drawer {{
        background: transparent;
    }}

    QFrame#task_drawer_panel {{
        background: {t.surface_soft};
        border-left: 1px solid {t.line};
    }}

    QLabel#task_drawer_title {{
        color: {t.text};
        font-size: 15px;
        font-weight: 700;
    }}

    QPushButton#task_drawer_toggle_button {{
        background: {t.surface};
        color: {t.azure};
        border: 1px solid {t.line};
        border-radius: {t.radius}px;
        font-weight: 700;
    }}

    QPushButton#task_drawer_toggle_button:hover {{
        border-color: {t.azure};
        color: {t.text};
    }}

    QListWidget#task_list {{
        background: {t.table_row};
        color: {t.text};
        border: 1px solid {t.line};
        border-radius: {t.radius}px;
        padding: 4px;
    }}

    QListWidget#task_list::item {{
        padding: 6px 8px;
        border-bottom: 1px solid {t.line};
    }}

    QListWidget#task_list::item:selected {{
        background: {t.surface_soft};
        color: {t.text};
    }}

    QStatusBar {{
        background: {t.surface};
        color: {t.text_muted};
        border-top: 1px solid {t.line};
    }}

    QStatusBar[ironPulse="true"] {{
        border-top: 1px solid {t.sakura};
        color: {t.text};
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

    QToolTip {{
        background: {t.surface_soft};
        color: {t.text};
        border: 1px solid {t.line};
        border-radius: {t.radius}px;
        padding: 6px 8px;
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
