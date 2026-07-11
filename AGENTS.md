# AGENTS.md — 碧蓝航线科研装备统计器 开发指南

> 给 Codex Agent 的指令：请在每次对话中严格遵守本文档的所有规范。

---

## 一、项目概述

| 属性 | 值 |
|------|-----|
| 项目名称 | 碧蓝航线科研装备统计器 (AzurLaneResearchTracker) |
| 当前版本 | v0.5.1 |
| 核心目标 | 通过安卓模拟器自动化操作 + OCR图像识别，自动统计碧蓝航线科研装备数量并计算欧非值 |
| Python版本 | 3.12 |
| IDE | PyCharm 2024 |

### 核心功能
- Wiki装备爬虫（757件装备+754张图片+9期科研）
- 图像识别装备数量（OpenCV 模板匹配 + PaddleOCR 数字识别）
- 科研碎片等值计算 & 欧非值计算
- 用户数据按日管理 & 历史趋势查询（ASCII折线图）
- 特殊装备独立管理
- 公式可配置化 + 持久化
- CLI 命令行交互（交互菜单 + 子命令模式）
- CSV/Excel 数据导出
- PySide6 GUI（9页面+6套皮肤+matplotlib趋势图+日志抽屉+秘书舰）

### 项目架构

```
AzurLaneResearchTracker/
├── main.py                          # ✅ v0.4.0 瘦身入口
├── requirements.txt                 # 依赖清单
├── AGENTS.md                        # 本文件
│
├── crawler/                        # ✅ v0.5.0 — 装备爬虫+科研爬虫+同步器
│   ├── equipment_crawler.py
│   ├── research_crawler.py
│   ├── crawler_sync.py
│   └── crawler_integration.py
│
├── core/
│   ├── utils/                       # ✅ v0.1.0
│   │   ├── logger.py
│   │   ├── path_manager.py
│   │   └── config_loader.py
│   │
│   ├── data/                        # ✅ v0.2.0 + v0.3.0 + v0.4.0
│   │   ├── rarity_manager.py
│   │   ├── equipment_manager.py
│   │   ├── research_manager.py
│   │   ├── equipment_updater.py
│   │   ├── special_equipment_manager.py
│   │   └── export_manager.py
│   │
│   ├── calculation/                 # ✅ v0.3.0
│   │   ├── formula_manager.py
│   │   ├── user_data_manager.py
│   │   ├── fragment_calculator.py
│   │   └── luck_calculator.py
│   │
│   ├── cli/                         # ✅ v0.4.0
│   │   └── app.py
│   │
│   ├── automation/                  # 📋 v0.6.0
│   └── recognition/                 # 📋 v0.6.0
│
├── ui/                              # ✅ v0.5.0 — PySide6界面
├── config/                          # ✅ JSON配置文件
├── data/                            # ✅ 6个CSV + user_records/ + exports/
├── test/                            # ✅ 172项开发测试
├── qa_tests/                        # ✅ 632项QA测试 + 报告
└── Logs/                            # 自动生成
```

### 核心设计决策

1. ID编码：科研S{期数}-{序号:03d}，通用G{序号:04d}
2. 8种装备类别映射（等值分int整数运算）
3. 欧非值Decimal精确3位小数
4. 公式可配置+持久化写回JSON
5. 用户数据按日分文件
6. main.py纯入口壳，逻辑在core/cli/app.py
7. 导出层独立（core/data/export_manager.py）
8. CLI支持交互菜单+子命令两种模式
9. record支持非交互单条/批量录入（为后续OCR/自动化预留接口）
10. 爬虫同步安全：原子写入+旧行保留，防半成品覆盖正式表
11. GUI多线程：QThread+Worker+Signal，爬虫更新不阻塞主界面
12. 统一后台任务管理器（TaskManager），单长任务锁+任务取消预留
13. v0.6.0 ADB/OCR 接口已预留（5项），任务进度实时更新

### 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.12 |
| 数据存储 | CSV（utf-8-sig编码） |
| 配置格式 | JSON |
| 图像处理 | OpenCV + Pillow |
| OCR | PaddleOCR 3.x |
| GUI | PySide6（LGPL）+ matplotlib |
| 模拟器 | ADB（雷电LDPlayer优先） |
| CLI | argparse + prettytable |
| 测试 | pytest + unittest（593/595项，99.7%） |
| 版本控制 | Git（main/develop + feature分支） |

---

## 二、编码规范（必须遵守）

### 2.1 注释规范

核心原则：让一个不懂代码的人也能通过注释看懂每一行在做什么。

每个模块必须有：
1. 文件头ASCII艺术框：用╔═╗║╚╝画出功能概览、类比理解、数据流说明
2. 分区标题：用# =====分隔import/类定义/全局函数三个区域
3. 每个方法docstring：功能描述、输入输出说明、使用示例
4. 关键步骤行内注释：解释"为什么"而不仅仅是"是什么"

模板：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════╗
║        📦 模块名称 (功能概括)            ║
║   【一句话解释】                          ║
║   【类比理解】                            ║
║   【数据存储位置】                        ║
╚══════════════════════════════════════════╝
"""

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================
# ============================================================
# 🏗️ 第二部分：核心类
# ============================================================
# ============================================================
# 🌐 第三部分：全局访问函数
# ============================================================
```

### 2.2 代码风格

- 编码：UTF-8，文件头# -*- coding: utf-8 -*-，shebang #!/usr/bin/env python3
- 类型注解：所有函数参数和返回值必须有type hints
- 字符串格式化：统一使用f-string
- 路径处理：禁止硬编码，必须通过PathManager获取
- 日志记录：禁止print()调试日志，必须通过get_logger()记录
- 设计模式：核心管理器类统一使用单例模式（__new__ + _instance）
- 全局访问：每个管理器模块末尾提供get_xxx()便捷函数
- 防重复初始化：__init__中使用if hasattr(self, '_initialized'): return
- 延迟加载：依赖其他管理器的属性用@property延迟加载
- CLI输出：用户可见输出用print()，内部调试用logger

### 2.3 文件组织

- 模块文件：core/<domain>/<module>.py
- CLI逻辑：core/cli/app.py（main.py只做入口转发）
- 测试文件：test/test_<module>.py
- 数据文件：data/<name>.csv
- 配置文件：config/<type>/<name>.json
- 导出目录：data/exports/
- QA测试：qa_tests/（与test/隔离）

### 2.4 ID编码规范

- 科研装备：S{期数}-{序号:03d}，如S1-001、S7-003
- 通用装备：G{序号:04d}，如G0001、G0002

---

## 三、Git版本控制规范

### 3.1 分支策略

main（稳定发行） ← develop（开发主线） ← feature/vX.Y.Z-name（功能分支）

| 分支类型 | 用途 | 生命周期 |
|----------|------|----------|
| main | 稳定发布版本 | 永久 |
| develop | 功能集成&联调 | 永久 |
| feature/vX.Y.Z-name | 单个阶段开发 | 合并后删除 |
| fix/xxx | Bug修复 | 合并后删除 |

### 3.2 版本号规范

格式：v<主版本>.<次版本>.<修订号>

### 3.3 当前版本路线图

| 版本号 | 内容 | 状态 |
|--------|------|------|
| v0.1.0 | 基础设施（日志+配置+路径） | ✅ |
| v0.2.0 | 数据层（装备/科研/稀有度） | ✅ |
| v0.3.0 | 计算层（公式/碎片/欧非值） | ✅ |
| v0.4.0 | CLI入口+数据导出（462测试） | ✅ |
| v0.4.1 | 通用装备ID格式修复（G前缀统一，810测试） | ✅ |
| v0.4.2 | 代码审查Bug修复（3轻微Bug+3附带，786测试） | ✅ |
| v0.5.0 | PySide6 GUI + Wiki装备爬虫 + TaskManager（800/804测试，99.5%） | ✅ |
| v0.5.1 | 欧非公式排名制+4Bug修复+测试体系重组（593/595测试，99.7%） | ✅ |
| v0.6.0 | ADB自动化+OCR识别 | 📋 |
| v1.0.0 | 打包&发布 | 📋 |

### 3.4 Commit规范

- 语言：中文
- 格式：<类型>: <简要描述>
- 类型：feat / fix / refactor / docs / test

### 3.5 开发工作流

```
1. git checkout -b feature/v0.5.0-gui develop
2. 开发 + 测试
3. git checkout develop && git merge feature/v0.5.0-gui
4. git checkout main && git merge develop
5. git tag -a v0.5.0 -m "feat: 完成GUI界面"
6. git branch -d feature/v0.5.0-gui
```

### 3.6 Git操作安全守则（必须遵守）

禁止操作：
- 禁止将Git命令输出重定向到项目文件
- 禁止对.csv/.json/.md文件使用git reset或git restore
- 禁止在项目目录内执行git checkout -- <file>

---

## 四、开发阶段与依赖关系

```
[v0.1.0 基础设施] → [v0.2.0 数据层] → [v0.3.0 计算层] → [v0.4.0 CLI入口] → [v0.5.0 GUI+Crawler] → [v0.6.0 自动化+OCR] → [v1.0.0 打包发布]
```

---

## 五、新对话启动模板

```
【项目背景】
碧蓝航线科研装备统计器，Python 3.12 + PyCharm 2024
项目路径：G:\ALLPeoject\PythonProject\AzurLaneResearchTracker
当前版本：v0.5.1（欧非公式排名制+4Bug修复+测试重组，593/595测试，99.7%通过率）
请先阅读项目根目录的AGENTS.md了解完整开发规范。

已完成模块：
v0.1.0 基础设施：core/utils/logger.py, path_manager.py, config_loader.py
v0.2.0 数据层：core/data/rarity_manager.py, equipment_manager.py, research_manager.py, equipment_updater.py
v0.3.0 计算层：core/data/special_equipment_manager.py, core/calculation/formula_manager.py, user_data_manager.py, fragment_calculator.py, luck_calculator.py
v0.5.1 GUI+Crawler：ui/main_window.py（9页GUI）+ crawler/ + 欧非公式排名制 + 测试体系重组

测试：593/595项通过，99.7%（377开发 + 216 QA）
QA报告：qa_tests/reports/ 下有全部版本的测试报告

【本次任务】
[描述你要开发的功能]

【要求】
1. 遵循AGENTS.md的所有编码规范
2. 使用单例模式、延迟加载、类型注解
3. 每完成一个模块写对应单元测试
4. 代码完成后运行全部593+项测试验证
```

---

## 六、常见问题

Q: 为什么用CSV而不是SQLite？
A: 项目初期数据量小，CSV可Git追踪、可直接用Excel编辑。

Q: 为什么main.py只有几行？
A: v0.4.0将CLI逻辑全部拆分到core/cli/app.py，main.py只做入口转发。

Q: CLI支持哪些命令？
A: python main.py status / record / export / help，无参数进入交互菜单。