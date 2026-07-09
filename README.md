# 碧蓝航线科研装备统计器

自动统计碧蓝航线科研装备数量和欧非值的桌面工具。

## 功能特点

- 安卓模拟器自动化操作（雷电 / MuMu）
- OpenCV 图像识别 + PaddleOCR 数字识别
- 装备库管理（增删改查 / 批量导入 / 图片映射）
- 科研期数管理（跨管理器关联查询）
- 碎片等值自动计算（8 种装备类别，int 整数运算）
- 欧非值计算（按期汇总 + 期数范围均值 + 历史趋势，Decimal 精确 3 位小数）
- 用户数据按日管理 + ASCII 折线图展示
- 特殊装备独立管理
- 公式可配置化（等值映射 + 欧非阈值，修改后持久化）
- CLI 命令行交互（交互菜单 + 子命令模式）
- CSV / Excel 数据导出（一键全套报告）
- PySide6 数据可视化（表格 / 折线图 / 柱状图）

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.12 |
| 数据存储 | CSV |
| 配置格式 | JSON |
| 图像处理 | OpenCV + Pillow |
| OCR | PaddleOCR |
| GUI | PySide6 |
| CLI | argparse + prettytable |
| Excel 导出 | openpyxl |
| 测试 | pytest |
| 模拟器控制 | ADB |

## 当前版本：v0.4.2

已完成基础设施层、数据层、计算层和 CLI 入口，786 项测试全部通过。

下一步：v0.5.0 PySide6 GUI 界面。

## 项目架构

| 目录 | 模块 | 状态 | 说明 |
|------|------|------|------|
| core/utils/ | logger / path_manager / config_loader | ✅ | 日志 / 路径 / 配置加载 |
| core/data/ | rarity / equipment / research manager | ✅ | 稀有度 / 装备 / 科研期数 |
| core/data/ | special_equipment / equipment_updater | ✅ | 特殊装备 / 批量导入 |
| core/data/ | export_manager | ✅ | CSV / Excel 数据导出 |
| core/calculation/ | formula / user_data manager | ✅ | 公式配置 / 用户数据 |
| core/calculation/ | fragment / luck calculator | ✅ | 碎片等值 / 欧非值 |
| core/cli/ | app | ✅ | CLI 交互菜单 + 子命令 |
| core/automation/ | — | 📋 | ADB 模拟器控制 |
| core/recognition/ | — | 📋 | OpenCV + PaddleOCR 识别 |
| ui/ | — | 📋 | PySide6 界面 |
| config/ | games / simulators / automation | ✅ | 配置文件 |
| data/ | CSV + user_records + exports | ✅ | 装备库 + 用户记录 + 导出 |
| test/ + qa_tests/ | 786 项测试 | ✅ | 开发 + QA 测试 |

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# CLI 交互模式
python main.py

# CLI 子命令
python main.py status
python main.py record
python main.py export

# 运行全部测试
python -m pytest test/ -q
```