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

## 当前版本：v0.4.0

已完成基础设施层、数据层、计算层和 CLI 入口，462 项测试全部通过。

下一步：v0.5.0 PySide6 GUI 界面。

## 项目架构

```
AzurLaneResearchTracker/
├── main.py                     # 程序入口壳（仅 sys.path + CLI 转发）
├── requirements.txt            # 依赖清单
├── AGENTS.md                   # Codex 开发规范
│
├── core/
│   ├── utils/                  # ✅ 日志 / 路径 / 配置
│   ├── data/                   # ✅ 装备 / 科研 / 稀有度 / 特殊装备 / 导出
│   ├── calculation/            # ✅ 公式 / 用户数据 / 碎片 / 欧非值
│   ├── cli/                    # ✅ CLI 主体逻辑
│   ├── automation/             # 📋 ADB 模拟器控制
│   └── recognition/            # 📋 OpenCV + PaddleOCR
│
├── ui/                         # 📋 PySide6 界面
├── data/                       # 6 个 CSV + user_records/ + exports/
├── config/                     # JSON 配置文件
├── test/                       # 225 项开发测试
├── qa_tests/                   # 237 项 QA 测试 + 报告
└── Logs/                       # 运行日志
```

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
