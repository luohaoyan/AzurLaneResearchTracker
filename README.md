# 碧蓝航线科研装备统计器

自动统计碧蓝航线科研装备数量和欧非值的桌面工具。

## 功能特点

- **PySide6 GUI 界面**（9 页导航 + 阵营皮肤系统 + 日志抽屉 + 趋势图）
  - 港区总览 / 装备库 / 科研进度 / 历史趋势 / 自动化实验室 / 小游戏 / 设置 / 关于
  - 铁血/东煌等多套阵营皮肤 + 可折叠日志抽屉（筛选/复制诊断）
- **Wiki 装备爬虫**（装备图鉴 + 研究室双线解析 + 自动同步 + 备份机制）
- 安卓模拟器自动化操作（雷电 / MuMu，接口就绪）
- OpenCV + PaddleOCR 图像识别（v0.6.0）（接口就绪）
- 装备库管理（增删改查 / 批量导入 / 图片映射）
- 科研期数管理（跨管理器关联查询）
- 碎片等值自动计算（8 种装备类别，int 整数运算）
- 欧非值计算（按期汇总 + 期数范围均值 + 历史趋势，Decimal 精确 3 位小数）
- 用户数据按日管理 + ASCII 折线图展示
- 特殊装备独立管理
- 公式可配置化（等值映射 + 欧非阈值，修改后持久化）
- CLI 命令行交互（交互菜单 + 子命令模式）
- CSV / Excel 数据导出（一键全套报告）
- PySide6 数据可视化（表格 / matplotlib 折线图 / 柱状图）

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
| Wiki 爬虫 | requests + BeautifulSoup |
| 测试 | pytest |
| 模拟器控制 | ADB |

## 当前版本：v0.5.1

已完成 GUI 界面 + Wiki 装备爬虫，543/546 项测试通过（99.5%）。

下一步：v0.6.0 ADB 自动化 + PaddleOCR 识别。

## 项目架构

| 目录 | 模块 | 状态 | 说明 |
|------|------|------|------|
| `core/utils/` | logger / path_manager / config_loader | ✅ | 日志 / 路径 / 配置加载 |
| `core/data/` | rarity / equipment / research manager | ✅ | 稀有度 / 装备 / 科研期数 |
| `core/data/` | special_equipment / equipment_updater | ✅ | 特殊装备 / 批量导入 |
| `core/data/` | export_manager | ✅ | CSV / Excel 数据导出 |
| `core/calculation/` | formula / user_data manager | ✅ | 公式配置 / 用户数据 |
| `core/calculation/` | fragment / luck calculator | ✅ | 碎片等值 / 欧非值 |
| `core/cli/` | app | ✅ | CLI 交互菜单 + 子命令 |
| `ui/` | main_window / theme / widgets | ✅ | 9 页 GUI + 阵营皮肤 + 日志抽屉 |
| `crawler/` | equipment / research / sync / integration | ✅ | Wiki 爬虫 + 自动同步 + 备份 |
| `core/automation/` | — | 📋 | ADB 模拟器控制（v0.6.0） |
| `core/recognition/` | — | 📋 | OpenCV + PaddleOCR 识别（v0.6.0） |
| `config/` | games / simulators / ui / crawler | ✅ | 全局 + UI + 爬虫配置 |
| `data/` | CSV + user_records + exports | ✅ | 装备库 + 用户记录 + 导出 |
| `test/` + `qa_tests/` | 543/546 项测试 | ✅ | 99.5% 通过率 |

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

# 启动 GUI 界面
python -m ui.main_window

# Wiki 装备爬虫
python -m crawler.equipment_crawler

# 运行全部测试
python -m pytest test/ -q
```
