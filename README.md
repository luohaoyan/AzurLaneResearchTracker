# 碧蓝航线科研装备统计器

自动统计碧蓝航线科研装备数量和欧非值的桌面工具。

## 功能特点

- PySide6 桌面 GUI（9 页面 + 6 套阵营皮肤 + matplotlib 趋势图 + 日志抽屉 + 秘书舰）
- Wiki 装备爬虫（757 件装备 + 754 张图片 + 9 期科研，自动同步至正式表）
- 装备库管理（增删改查 / 批量导入 / 图片映射 / 稀有度筛选 / 科研期筛选）
- 科研进度追踪（按期保存目标彩装数 + 开始时间 + 官方日期 PR1-PR9 + 金彩比 + 欧非评价）
- 历史趋势分析（matplotlib 折线图 / 金彩比趋势 / 装备碎片趋势 / 多装备叠加 / 悬停提示）
- 碎片等值自动计算（8 种装备类别，int 整数运算）
- 欧非值计算（按期汇总 + 期数范围均值 + 历史趋势，Decimal 精确 3 位小数）
- 用户数据按日管理 + 日期范围查询
- 特殊装备独立管理
- 公式可配置化（等值映射 + 欧非阈值，修改后持久化）
- CLI 命令行交互（交互菜单 + 子命令模式）
- CSV / Excel 数据导出（一键全套报告）
- 统一后台任务管理器（QThread + 单长任务锁 + 任务取消预留 + 独立任务抽屉）
- 爬虫同步安全（原子写入 + 旧行保留，防半成品覆盖正式表）
- v0.6.0 ADB / OCR 接口预留

## 当前版本：v0.5.1

已完成基础设施层、数据层、计算层、CLI 入口、GUI 界面和 Wiki 装备爬虫，
593/595 项测试通过（99.7%）。

新特性：Wiki统计学排名制欧非公式 + 测试体系版本化重组。

下一步：v0.6.0 ADB 自动化 + PaddleOCR 识别。

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.12 |
| 数据存储 | CSV（utf-8-sig） |
| 配置格式 | JSON |
| GUI | PySide6（LGPL）+ matplotlib |
| 爬虫 | requests + BeautifulSoup4 |
| 图像处理 | OpenCV + Pillow |
| OCR | PaddleOCR 3.x（v0.6.0） |
| CLI | argparse + prettytable |
| Excel 导出 | openpyxl |
| 测试 | pytest + unittest |
| 模拟器控制 | ADB（雷电优先，v0.6.0） |

## 项目架构

| 目录 | 模块 | 状态 | 说明 |
|------|------|------|------|
| core/utils/ | logger / path_manager / config_loader | ✅ | 日志 / 路径 / 配置 |
| core/data/ | rarity / equipment / research manager | ✅ | 稀有度 / 装备 / 科研期数 |
| core/data/ | special_equipment / equipment_updater | ✅ | 特殊装备 / 批量导入 |
| core/data/ | export_manager | ✅ | CSV / Excel 导出 |
| core/calculation/ | formula / user_data manager | ✅ | 公式配置 / 用户数据 |
| core/calculation/ | fragment / luck calculator | ✅ | 碎片等值 / 欧非值 |
| core/calculation/ | trend_analyzer / research_progress | ✅ | 趋势分析 / 科研进度 |
| core/cli/ | app | ✅ | CLI 交互菜单 + 子命令 |
| crawler/ | equipment / research / sync / integration | ✅ | Wiki 爬虫 + 同步器 |
| ui/ | main_window / theme / widgets / pages | ✅ | PySide6 桌面界面 |
| ui/ | automation_bridge / secretary_pack | ✅ | 自动化桥接 / 秘书舰 |
| core/state/ | runtime_state / task_manager | ✅ | 运行状态 / 任务管理 |
| core/automation/ | — | 📋 | ADB 模拟器控制 |
| core/recognition/ | — | 📋 | OpenCV + PaddleOCR |
| config/ | games / simulators / ui / crawler | ✅ | 全部配置文件 |
| data/ | CSV + user_records + exports + images | ✅ | 装备库 + 用户记录 + 导出 |
| test/ + qa_tests/ | 593/595 项测试 | ✅ | 99.7% 通过率 |

## 快速开始

```bash
pip install -r requirements.txt

python -m ui.main_window          # 启动 GUI
python main.py                    # CLI 交互模式
python main.py status             # CLI 子命令
python main.py record             # 数据录入
python main.py export             # 数据导出
python -m core.data.crawler_update  # 更新装备库

python -m pytest test/ -q         # 运行全部测试
```
