# 碧蓝航线科研装备统计器 — 开发文档

## 项目概况

| 属性 | 值 |
|------|-----|
| 项目名称 | 碧蓝航线科研装备统计器 (AzurLaneResearchTracker) |
| 当前版本 | v0.2.0 |
| 开发语言 | Python 3.12 |
| IDE | PyCharm 2024 |
| 测试框架 | pytest / unittest |
| 测试状态 | 69 项测试，全部通过 |

---

## 版本历史

### v0.1.0 — 基础设施层（已完成）

**完成模块：**
- `core/utils/logger.py` — 日志系统，单例模式，RotatingFileHandler（10MB、5个备份），双文件输出（普通+错误）
- `core/utils/path_manager.py` — 路径管理器，基于 `Path(__file__)` 相对解析，提供 get_project_root/get_config_dir/get_log_dir/get_data_dir
- `core/utils/config_loader.py` — JSON 配置加载器，单例模式+缓存，支持主配置、模拟器配置、游戏配置的加载/保存/深度更新
- `config/*.json` — 主配置、MuMu/雷电模拟器配置、碧蓝航线游戏配置、自动化序列配置

### v0.2.0 — 数据层（已完成）★

**完成模块：**
- `core/data/rarity_manager.py` — 稀有度独立管理器，CSV 存储（rarity_id/name/color_hex/sort_order），完整 CRUD
- `core/data/equipment_manager.py` — 装备数据管理器，CSV 存储+图片映射分离，ID 编码/解析工具，延迟加载稀有度管理器
- `core/data/research_manager.py` — 科研期数管理器，跨管理器关联查询（查某期→所有装备详情+稀有度名称），延迟加载装备管理器
- `core/data/equipment_updater.py` — 批量添加整期科研装备（1行代码：1彩虹+5金色，自动生成ID+创建期数记录）

**数据文件：**
- `data/rarities.csv` — 5 种稀有度（普通/稀有/精锐/超稀有/海上传奇）
- `data/equipment_library.csv` — 12 件初始科研装备（S1-001 ~ S6-002），4 字段（equipment_id/name/rarity_id/type）
- `data/research_phases.csv` — 6 期科研（PR1~PR6），3 字段（phase_number/name/equipment_list）
- `data/equipment_images.csv` — 装备图片映射表，独立存储

**测试：**
- `test/test_all.py` — 69 项测试，覆盖所有管理器和方法，全部通过

---

## 核心设计决策

### 1. ID 编码方案

| 装备类型 | ID 格式 | 示例 |
|----------|---------|------|
| 科研装备 | S{期数}-{序号:03d} | S1-001, S7-003 |
| 通用装备 | 纯数字自增 | 1, 2, 3 |

- 期数信息完全编码在 ID 中，CSV 不存 research_phase 字段
- `EquipmentManager.parse_research_id("S1-001")` → (1, 1)
- `EquipmentManager.make_research_id(7, 3)` → "S7-003"

### 2. 稀有度独立管理

- 稀有度存在 `rarities.csv` 中，通过 `rarity_id` 关联
- 游戏更新稀有度等级时改 CSV 即可，无需改代码
- 装备管理器通过 `@property rarity_manager` 延迟加载

### 3. 图片映射分离

- `equipment_images.csv` 独立存储 `{equipment_id → image_path}`
- 和装备数据解耦，图片地址可以空缺
- 提供 `batch_set_images()` 批量设置

### 4. 欧非值剥离

- `research_phases.csv` 不包含 `luck_benchmark` 字段
- 欧非值计算公式待定，v0.3.0 单独处理

---

## 数据表结构

### rarities.csv

| rarity_id | name | color_hex | sort_order |
|-----------|------|-----------|------------|
| 1 | 普通 | #FFFFFF | 1 |
| 2 | 稀有 | #4169E1 | 2 |
| 3 | 精锐 | #800080 | 3 |
| 4 | 超稀有 | #FFD700 | 4 |
| 5 | 海上传奇 | #FF69B4 | 5 |

### equipment_library.csv

| equipment_id | name | rarity_id | type |
|-------------|------|-----------|------|
| S1-001 | 试作型三联装406mm主炮Mk6 | 5 | 战列炮 |
| S1-002 | 试作型三联装152mm主炮Mk17 | 4 | 轻巡炮 |
| S2-001 | 试作型双联装457mm主炮MkA | 5 | 战列炮 |
| ... | ... | ... | ... |
| S6-002 | 试作型四联装356mm主炮Mk7 | 4 | 战列炮 |

### research_phases.csv

| phase_number | name | equipment_list |
|-------------|------|----------------|
| 1 | 科研1期(PR1) | S1-001,S1-002 |
| 2 | 科研2期(PR2) | S2-001,S2-002 |
| ... | ... | ... |
| 6 | 科研6期(PR6) | S6-001,S6-002 |

### equipment_images.csv

| equipment_id | image_path |
|-------------|------------|
| S1-001 | (待填入) |
| S1-002 | (待填入) |
| ... | ... |

---

## 模块方法清单

### RarityManager (rarity_manager.py)

| 类别 | 方法 | 说明 |
|------|------|------|
| 查询 | get_all() | 全部稀有度列表 |
| 查询 | get_by_id(id) | 按 ID 查 |
| 查询 | get_by_name(name) | 按名称查 |
| 增删改 | add_rarity(dict) | 添加稀有度 |
| 增删改 | update_rarity(id, dict) | 更新稀有度 |
| 增删改 | delete_rarity(id) | 删除稀有度 |

### EquipmentManager (equipment_manager.py)

| 类别 | 方法 | 说明 |
|------|------|------|
| ID 工具 | parse_research_id(str) | 解析 S1-001 → (1, 1) |
| ID 工具 | make_research_id(phase, seq) | 生成 S1-001 格式 |
| 基础查询 | get_all() | 全部装备 |
| 基础查询 | get_by_id(id) | 按 ID 查 |
| 基础查询 | get_by_name(name) | 按名称查 |
| 基础查询 | search_by_name(keyword) | 关键词模糊搜索 |
| 分类筛选 | get_by_rarity_id(rid) | 按稀有度ID筛选 |
| 分类筛选 | get_by_type(type) | 按类型筛选 |
| 分类筛选 | get_by_phase(phase_number) | 按期数筛选 |
| 分类筛选 | get_research_equipment() | 所有科研装备 |
| 分类筛选 | get_general_equipment() | 所有通用装备 |
| 稀有度增强 | get_rarity_info() | 获取稀有度管理器 |
| 稀有度增强 | get_with_rarity_name(equipment) | 装备+稀有度名称 |
| 图片映射 | get_image_path(id) | 获取图片路径 |
| 图片映射 | set_image_path(id, path) | 设置图片路径 |
| 图片映射 | batch_set_images(dict) | 批量设置图片 |
| 图片映射 | get_all_images() | 全部图片映射 |
| 图片映射 | get_equipment_with_image() | 有图片的装备列表 |
| CRUD | add_equipment(dict) | 添加装备 |
| CRUD | update_equipment(id, dict) | 更新装备 |
| CRUD | delete_equipment(id) | 删除装备 |
| 批量 | import_equipment_batch(list) | 批量导入，返回统计 |
| 统计 | get_statistics() | 装备统计（总数/科研/通用/按稀有度） |

### ResearchManager (research_manager.py)

| 类别 | 方法 | 说明 |
|------|------|------|
| 查询 | get_all() | 全部科研期数 |
| 查询 | get_by_phase(phase_number) | 按期数查 |
| CRUD | add_phase(dict) | 添加期数 |
| CRUD | update_phase(id, dict) | 更新期数 |
| CRUD | delete_phase(id) | 删除期数 |
| 关联查询 | get_phase_equipment(phase_number) | 查某期→所有装备详情+稀有度 |
| 关联查询 | get_phase_equipment_count(phase_number) | 查某期装备数量 |
| 统计 | get_statistics() | 科研统计（总期数/总装备数） |

### EquipmentUpdater (equipment_updater.py)

| 方法 | 说明 |
|------|------|
| add_research_phase_equipment(phase_number, phase_name, gold_list, rainbow_tuple) | 一行代码添加整期科研（1彩+5金） |

---

## 项目架构

```
AzurLaneResearchTracker/
├── main.py                     # 程序入口
├── requirements.txt            # 依赖清单
├── AGENTS.md                   # Codex 开发规范
│
├── core/
│   ├── utils/                  # ✅ v0.1.0 — 基础设施
│   │   ├── logger.py           #   日志系统
│   │   ├── path_manager.py     #   路径管理器
│   │   └── config_loader.py    #   配置加载器
│   ├── data/                   # ✅ v0.2.0 — 数据层
│   │   ├── rarity_manager.py   #   稀有度管理器
│   │   ├── equipment_manager.py#   装备数据管理器
│   │   ├── research_manager.py #   科研期数管理器
│   │   └── equipment_updater.py#   批量更新工具
│   ├── calculation/            # 📋 v0.3.0 — 计算层
│   ├── automation/             # 📋 v0.6.0 — 自动化
│   └── recognition/            # 📋 v0.6.0 — 识别
│
├── ui/                         # 📋 v0.5.0 — PySide6 界面
├── config/                     # ✅ JSON 配置文件
├── data/                       # ✅ 4 个 CSV 数据文件
├── test/                       # ✅ 测试文件
└── Logs/                       # 自动生成
```

---

## 开发路线图

| 版本 | 内容 | 状态 |
|------|------|------|
| v0.1.0 | 基础设施（日志 + 配置 + 路径管理） | ✅ 已完成 |
| v0.2.0 | 数据层（装备/科研/稀有度管理 + 4个CSV + 69项测试） | ✅ 已完成 |
| v0.3.0 | 计算层（碎片计算 + 欧非值 + 公式管理） | 📋 下一步 |
| v0.4.0 | CLI 入口 + 数据导出 | 📋 待开发 |
| v0.5.0 | PySide6 GUI 界面（表格 + 图表 + 工具栏） | 📋 待开发 |
| v0.6.0 | ADB 自动化 + PaddleOCR 识别 | 📋 待开发 |
| v1.0.0 | 打包 & 发布 | 📋 待开发 |

---

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.12 |
| 数据存储 | CSV（utf-8-sig 编码） |
| 配置格式 | JSON |
| 图像处理 | OpenCV + Pillow |
| OCR | PaddleOCR 3.x |
| GUI | PySide6（LGPL 许可） |
| 模拟器控制 | ADB（雷电 LDPlayer 优先） |
| 测试 | pytest / unittest |
| 版本控制 | Git（main / develop 双主干 + feature 分支） |