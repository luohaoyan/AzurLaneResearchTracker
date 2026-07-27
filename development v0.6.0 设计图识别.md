# 碧蓝航线科研装备统计器 — v0.6.0 设计图识别开发文档

## 1. 这份文档是做什么的

这份文档用于记录 v0.6.0 阶段「仓库页 / 设计图识别」相关工作的开发顺序、当前进度、已完成内容、测试方式和后续扩展方向。

它的目标不是讲原理课，而是让后续开发时可以直接照着做：

1. 先确认仓库页能稳定切到设计图页。
2. 再按稀有度逐步扫图。
3. 再把 ADB 的分帧结果交给 OCR。
4. 最后再把识别结果接入正式数据写入链路。

当前建议默认流程：

```text
仓库页已打开
→ 切到“设计图”
→ 确认已进入设计图页
→ 按稀有度扫图（白 → 蓝 → 紫 → 金 → 彩）
→ 生成 manifest / actions / summary
→ OCR 消费 ADB 产物
→ 识别结果先进入草稿层
→ Integration 层再写入正式数据表
```

---

## 2. 当前版本状态

日期：2026-07-27

最近一次识别链路修正：2026-07-26

当前工作重点：

- ADB 层：让“仓库页 → 设计图页”的切换动作稳定、可确认、可回退。
- ADB 层：让“设计图页 → 白/蓝/紫/金/彩”稀有度切换可断点、可复跑、可留证据。
- OCR 层：消费 ADB 的分帧输出，不直接做点击和滑动。
- 识别策略：先保守，先确认页面，再扫图，再识别，再写入。

已经完成的最小闭环：

- `EquipmentPageAdbApi.ensure_warehouse_design_page_ready()`
  - 从仓库页切到设计图页
  - 调用仓库标签识别器进行确认
  - 返回结构化结果

- `recognition_workbench/run_warehouse_design_tab_check.py`
  - 一键运行检查脚本
  - 方便直接测试“仓库页 → 设计图页”

- `recognition_workbench/RUN_WAREHOUSE_DESIGN_TAB_CHECK.bat`
  - 双击即可执行

- `core/automation/equipment_page/EquipmentPageRaritySweepSession`
  - 记录设计图页稀有度切换会话
  - 带 `resume_cursor / next_resume_cursor`
  - 可保存 `manifest.json / actions.log / device_info.json / summary.json`

- `recognition_workbench/run_warehouse_design_rarity_sweep.py`
  - 一键运行白/蓝/紫/金/彩稀有度切换

- `recognition_workbench/RUN_WAREHOUSE_DESIGN_RARITY_SWEEP.bat`
  - 双击即可执行稀有度切换流程

- 测试覆盖：
  - 设计图页切换确认成功
  - 设计图页切换后识别失败时返回 `not_confirmed`

---

## 3. 目前已经接上的代码

### 3.1 ADB 页面的最小闭环

文件：

- `G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\core\automation\equipment_page\equipment_page_adb_api.py`
- `G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\core\automation\equipment_page\equipment_page_models.py`
- `G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\core\automation\equipment_page\equipment_page_constants.py`

新增能力：

- 进入仓库页后切换到“设计图”
- 使用仓库标签识别器确认当前页确实是 design
- 识别结果不确定时，不强行假装成功
- 识别依赖不可用时，保留切页动作结果，不阻塞整个流程

### 3.2 仓库标签识别

文件：

- `G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\core\recognition\warehouse_label_detector.py`

它负责的内容：

- 左下角仓库标签页识别
- 顶部房子按钮识别
- 筛选按钮识别
- 排序状态识别
- 设计图 / 装备 / 材料标签识别

在当前流程里的作用：

- 不负责点击
- 不负责滚动
- 只负责看图确认“现在是不是 design 页”

### 3.3 识别工作台

文件：

- `G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\recognition_workbench\run_warehouse_design_tab_check.py`
- `G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\recognition_workbench\RUN_WAREHOUSE_DESIGN_TAB_CHECK.bat`

作用：

- 让你在模拟器已经打开仓库页时，直接一键测试切换到设计图页
- 不需要先进 PyCharm
- 不需要先跑完整识别链路

---

## 4. 推荐开发顺序

### 第 1 步：仓库页 → 设计图页切换确认

目标：

- 当前已经在仓库页时，稳定切到设计图页
- 切过去以后能确认当前页面确实是设计图页

输出：

- 结构化 ADB 结果
- `design_tab_confirmed`
- 切页截图证据

这一步的意义：

- 后面所有稀有度分桶扫图，都依赖它
- 如果这里不稳，后面再准的 OCR 也没用

### 第 2 步：设计图页稀有度扫图

目标：

- 白 → 蓝 → 紫 → 金 → 彩
- 每个稀有度单独一个 session 或一个可断点的 sweep session
- 每个 session 都有 checkpoint / resume cursor
- 每次切换都保留截图证据和 actions.log

建议规则：

- 每个稀有度都是独立运行
- 同一次 sweep 统一写自己的 `manifest.json / actions.log / device_info.json / summary.json`
- 断点靠 `summary.json` 的 `next_resume_cursor`
- 不要把不同稀有度的结果混在别的版本目录里

### 第 3 步：把 ADB 分帧交给 OCR

目标：

- OCR 只消费 ADB 输出
- OCR 不负责点击
- OCR 不负责滑动
- OCR 不直接写正式日表

### 第 4 步：识别结果先进入草稿层

目标：

- OCR 先输出草稿结果
- Integration 层再把草稿映射到 `equipment_id`
- 如果有歧义，不直接写入

### 第 5 步：稳定后再扩展自动写入

目标：

- 在确认完整性和准确率足够后，再考虑自动更新正式表

---

## 5. 当前已经完成到什么程度

### 已完成

- 仓库页标签识别器
- 仓库页 → 设计图页切换检查入口
- 设计图页切换确认测试
- ADB 端输出结构化结果
- OCR 端已有科研设计图读取器和 ADB manifest 消费链路

### 仍在推进

- 设计图页按稀有度扫图后，接入 OCR 识别和最终标注
- checkpoint / resume 的更细粒度控制
- 稀有度切换后的重复帧去重策略
- 草稿层和正式表之间的整合层

### 2026-07-26 已补充

- `recognition_workbench/run_adb_design_fragment_recognition.py`
  - ADB 识别工作台默认使用 `--nn-mode assist`
  - 每张完整卡片都会调用当前最新 ONNX 模型（ONNX 模型由 PyTorch 训练模型导出）
  - 默认 `--nn-trigger-threshold 0.82` 仍保留给 `fallback` 模式
  - 如果命令没有显式传 `--rarity-state`，会自动读取 manifest 中的稀有度
  - 可选 `--enforce-rarity-filter`，仅在已经人工确认筛选状态正确时启用

- `recognition_workbench/run_recognition.py`
  - 识别结果现在会记录 `nn_backend`、`onnx_model_dir`、`pytorch_model`
  - `recognition_model.json` 记录 `backend=opencv+ocr+onnx`、NN 模式、稀有度过滤状态和 OCR 本地模型状态
  - 输出汇总增加 `ocr_status`，便于判断是否真正加载了本地 PaddleOCR 模型

- `nn_training_lab/scripts/run_screenshot_pipeline.py`
  - OpenCV matcher 支持传入稀有度候选 ID 集合
  - NN 输出支持按稀有度候选集合过滤
  - 每张卡片 CSV 增加 `nn_provider`

- `core/recognition/equipment_icon_matcher.py`
  - `match_icon(..., allowed_equipment_ids=...)` 支持按 `rarity_id` 限制候选图库

- 本机 OCR 运行环境
  - 移除了会触发缺失 cuDNN DLL 的 `paddlepaddle-gpu`
  - 保留并重装 CPU 版 `paddlepaddle==3.3.1`
  - 当前 PaddleOCR 本地中文模型已通过真实截图 ROI 冒烟验证
  - `python -m pip check`：无损坏依赖

## 5.1 当前设计图识别推荐命令

仅消费已经采集好的 manifest，默认使用 OpenCV + OCR + 最新 ONNX（PyTorch 导出）辅助：

```cmd
python recognition_workbench\run_adb_design_fragment_recognition.py ^
  --manifest "G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\workdir\automation\adb_capture_runs\run_xxx\manifest.json" ^
  --nn-mode assist ^
  --no-preview
```

如果已经确认当前模拟器确实只显示某一个稀有度，可以额外启用候选过滤。例如“超稀有（金色）”使用 `super_rare`：

```cmd
python recognition_workbench\run_adb_design_fragment_recognition.py ^
  --manifest "G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\workdir\automation\adb_capture_runs\run_xxx\manifest.json" ^
  --rarity-state super_rare ^
  --enforce-rarity-filter ^
  --nn-mode assist ^
  --no-preview
```

注意：`ultra_rare` 在本项目中表示“海上传奇/彩色”，`super_rare` 表示“超稀有/金色”。如果只是给采集过程写元数据但尚未确认筛选按钮，先不要加 `--enforce-rarity-filter`，避免把错误的稀有度元数据当成硬过滤条件。

结果目录中重点查看：

- `recognition_model.json`：确认使用的模型、ONNX provider、OCR 本地模型状态。
- `screenshot_pipeline_results.csv`：逐卡查看 `opencv_*`、`name_ocr_*`、`nn_*`、`final_*`。
- `screenshot_pipeline_summary.json`：查看 `nn_backend`、`nn_mode`、`nn_invoked`、`name_ocr_success` 和 `rarity_filter_enabled`。

---

## 6. 当前测试方式

### 6.1 你现在人在“仓库”页面时，怎么测试切到设计图页

最简单的方法：

1. 保持模拟器已经打开，并停留在“仓库”页面。
2. 双击：

   `G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\recognition_workbench\RUN_WAREHOUSE_DESIGN_TAB_CHECK.bat`

3. 等待窗口输出 JSON。

如果结果里出现：

- `design_tab_confirmed: true`

说明：

- 点击“设计图”成功了
- 并且识别器也确认了当前页是设计图页

### 6.2 如果你只想看“动作能不能执行”，不想做识别确认

运行：

```bash
python recognition_workbench\run_warehouse_design_tab_check.py --no-confirm
```

这时会：

- 只执行切页动作
- 不强制做截图识别确认

适合：

- 先排查按钮坐标
- 先排查 ADB 是否能点到位
- 先排查页面是否真的能切换

### 6.3 如果你想保存一份结果文件

运行：

```bash
python recognition_workbench\run_warehouse_design_tab_check.py --json-out "G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\recognition_workbench\test_out\warehouse_design_check.json"
```

这样会把当前 JSON 结果落到指定路径。

---

## 7. 这一步测试时你要准备什么

你现在只需要准备这几件事：

1. 模拟器已经打开。
2. 你已经停在“仓库”页面。
3. 分辨率是 `1280x720`。
4. 模拟器里不要先把弹窗挡住仓库标签。

如果页面上有弹窗、遮挡、加载中的遮罩，建议先关掉。

---

## 8. 切换测试时如何判断结果

你运行脚本后，重点看这几个字段：

- `success`
- `status`
- `message`
- `target_tab`
- `design_tab_confirmed`
- `design_tab_state`
- `warehouse_label_result`

判断规则：

- `design_tab_confirmed = true`
  - 已经进入设计图页

- `design_tab_confirmed = false`
  - 可能切页失败
  - 也可能切页成功但确认失败
  - 需要看 `status` 和 `warehouse_label_result`

- `status = not_confirmed`
  - 切页动作执行了，但识别器没有确认是 design 页

- `status = unavailable`
  - 仓库标签识别依赖不可用
  - 这时保留切页动作结果，后续再补环境

### 8.1 设计图入口位置

设计图入口已经和“模拟器连接”区域彻底分开：

- “模拟器连接”只保留 `刷新状态` 和 `自动连接`。
- “设计图功能测试”区域包含：
  - `测试筛选`：切换/确认设计图稀有度筛选。
  - `扫图识别`：按当前稀有度执行 ADB 分帧截图和 OpenCV + OCR + ONNX/PyTorch assist 识别。

扫图所需的稀有度、断点、滚动步长和开关都在“设计图功能测试”区域内填写，不需要再到模拟器连接区域寻找入口。

2026-07-26 修复：补回 `adb_auto_connect` 任务规格，确保“自动连接”按钮调用真实 ADB 自动发现流程，不会因为设计图入口拆分而落到空任务定义。

### 8.2 设计图扫图识别参数

| 控件 | 默认值 | 说明 |
|---|---:|---|
| 稀有度 | `super_rare` | 只填写一个值；也支持白/蓝/紫/金/彩 |
| 断点 | `0` | 从第几个采集游标继续 |
| 步长(px) | `0` | `0` 使用采集层默认步长，通常为 280px |
| 扫到底部 | 勾选 | 持续采集直到底部确认 |
| 稀有度硬过滤 | 不勾选 | 仅在模拟器筛选已确认正确时勾选 |
| 生成预览 | 不勾选 | 需要人工验图时再勾选；正式整合建议关闭 |

扫图默认从当前已经打开的设计图页开始，不会重复点击筛选或改变稀有度。建议先点击 `测试筛选` 确认状态，再点击 `扫图识别`。

### 8.3 断点 JSON 该看什么

设计图稀有度扫图会写自己的 session 目录，里面最关键的是：

- `manifest.json`
  - 记录每一帧截图和对应的动作信息
- `actions.log`
  - 记录实际做了哪些切换、点了什么、是否重试
- `device_info.json`
  - 记录当前设备、分辨率、ADB 信息
- `summary.json`
  - 这是最重要的断点文件

其中 `summary.json` 里最值得看的字段是：

- `resume_cursor`
  - 本次扫描是从第几个稀有度步骤开始的
- `next_resume_cursor`
  - 下次可以从哪里继续
- `rarity_state`
  - 当前处在哪个稀有度
- `filter_state`
  - 当前筛选状态
- `sort_state`
  - 当前排序状态
- `frame_count`
  - 本次一共抓了多少帧
- `bottom_reached`
  - 是否已经滚到最后

### 8.4 断点续跑怎么用

如果你想手动续跑，最直接的方式是：

```cmd
python recognition_workbench\run_warehouse_design_rarity_sweep.py --rarities rare elite super_rare ultra_rare --resume-cursor 1
```

意思是：

- `--rarities`
  - 你这次要跑哪些稀有度
- `--resume-cursor`
  - 从第几个稀有度开始续跑

如果你不手动传 `--resume-cursor`，GUI 和后端会尝试读取最近一次 `summary.json` 里的断点信息，自动往后接。

### 8.5 不打开 PyCharm 的 CMD 扫图命令

在项目根目录 `G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR` 打开 CMD 或 PowerShell，确认模拟器已经停在目标稀有度的设计图页后执行：

```cmd
python recognition_workbench\run_adb_design_fragment_recognition.py ^
  --capture ^
  --until-bottom ^
  --rarity-state super_rare ^
  --nn-mode assist ^
  --overlap-ratio 0.35 ^
  --scroll-step-px 0 ^
  --no-preview
```

如果当前页面已经正确定位、只想从当前画面开始，不回到顶部，可加上：

```cmd
--no-ensure-top --no-prepare-page
```

输出目录默认是：

```text
G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\recognition_workbench\adb_test_out\adb_design_YYYYMMDD_HHMMSS\
```

其中 `adb_capture_context.json` 记录本次 ADB manifest、选中的帧和识别摘要；`csv/json` 识别结果位于同一运行目录。

---

## 9. 后续我会继续做什么

按当前顺序，接下来建议继续做：

1. 把设计图页的稀有度切换封装成一个独立流程。
2. 每次切换稀有度后都保留一个 checkpoint。
3. 让 OCR 只消费 ADB 的 manifest，不再碰 ADB 动作。
4. 把识别结果先写到草稿层目录。
5. 最后再把草稿层接到正式数据表。

---

## 10. 文件清单

### 新增

- `G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\recognition_workbench\run_warehouse_design_tab_check.py`
- `G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\recognition_workbench\RUN_WAREHOUSE_DESIGN_TAB_CHECK.bat`
- `G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\development v0.6.0 设计图识别.md`

### 修改

- `G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\core\automation\equipment_page\equipment_page_adb_api.py`
- `G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\test\v060\adb\test_equipment_page_adb_api.py`
- `G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\recognition_workbench\use.txt`

---

## 11. 备注

这一步我们刻意做得很保守：

- 先确认页面
- 再确认识别
- 再做扫图
- 再做 OCR

这样后面哪怕遇到问题，也能清楚知道是：

- 点击有问题
- 页面确认有问题
- ADB 分帧有问题
- OCR 识别有问题

不会整条链路糊在一起。

---

## 12. INT 模拟器连接实现迁移记录（2026-07-26）

### 12.1 迁移范围

模拟器连接区域已改为复用 INT worktree 的稳定连接契约，设计图扫图仍由 OCR worktree 自己的“设计图功能测试”区域负责，两者不共用按钮。

来源：

```text
G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-INT\core\automation\adb_controller.py
G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-INT\core\automation\simulator_registry.py
G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-INT\ui\automation_task_specs.py
```

OCR 当前保留的对应文件：

```text
G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\core\automation\adb_controller.py
G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\core\automation\simulator_registry.py
G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\core\automation\adb_task_api.py
G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\ui\automation_bridge.py
G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\ui\automation_task_specs.py
G:\ALLPeoject\PythonProject\AzurLaneResearchTracker-OCR\ui\main_window.py
```

### 12.2 连接结果契约

自动连接入口现在只保留：

```python
AdbController.auto_connect_simulator(...) -> AdbAutoConnectResult
```

结果包含：

- `selected_device`
- `candidates`
- `attempted_serials`
- `simulator_profiles`
- `adb_path` / `adb_source`
- `warnings`
- `command_results`

`AdbTaskApi.auto_connect_simulator()` 会在成功后追加：

- `display_environment`
- `foreground_app`

因此 UI 可以同时展示连接状态、分辨率/DPI、平板模式和当前前台包名。

### 12.3 UI 使用边界

“模拟器连接”区域只提供：

1. 模拟器选择
2. Serial 输入
3. 端口输入
4. `刷新状态`
5. `连接并测试`

设计图的 `测试筛选`、`扫图识别` 以及稀有度/断点参数仍在“设计图功能测试”区域，不会触发模拟器连接区域的按钮。

### 12.4 本次验证

```text
python -m pytest test\v060\adb -q
86 passed

python -m pytest test\v060\ocr\test_design_fragment_scan_ui.py -q
5 passed

python -m pytest test\test_v060_interfaces.py test\test_automation_bridge.py -q
9 passed

python -m pytest test\v060\contracts -q
9 passed
```

目标模块 `compileall` 检查通过，且未操作 `qa_tests/`。全量 `python -m pytest test -q` 在当前环境运行超过 180 秒未结束，因此已停止该长任务；专项回归结果不受影响。

### 12.5 空页面与单页稀有度处理

新增了两类更保守的分流：

1. 空设计图页面：
   - 如果截图中出现“暂无设计图”空状态提示，以及右侧红色警告图标，则 `DesignFragmentDetector` 会直接返回 `empty`。
   - 这类页面不会继续进入 OpenCV / OCR / NN 装备识别链路。

2. 单页或底部确认：
   - 不再因为滚动条看起来“很满”就立即截断。
   - 会先完成拖动和截图，再根据连续两次稳定帧来确认到底部。
   - 这样可以避免把最底部那两张卡片提前裁掉。

### 12.6 顶部回卷与边界确认

`rare / elite / super_rare` 等多页稀有度在开始采集前，需要先可靠回到列表顶部。

当前处理规则：

- 回顶动作后等待页面停止滚动，再保存探针截图。
- 不再因为一次滚动条 `top` 状态就立即结束。
- 连续两次拖动后页面布局保持一致，才确认已经到达顶部。
- 设计图布局签名用于排除背景动画、按钮呼吸效果等无关变化。
- 滚动条状态只作为辅助证据，不单独决定顶部是否到达。

这样可以避免顶部还差少量距离时提前开始识别，导致首行卡片被截断。

---

## 13. 2026-07-27 阶段性总结

本节只记录当前阶段结果，不表示 v0.6.0 设计图自动识别已经全部完成。

### 13.1 当前已经可用的部分

- 从仓库页切换到设计图页，并对页面状态进行确认。
- 设计图筛选页可以切换并确认单个稀有度。
- 单个稀有度可以执行回顶、分帧截图、向下滚动和到底确认。
- `common` 等空设计图页面可以提前识别并跳过后续 OpenCV / OCR / NN。
- 顶部和底部都使用连续稳定截图确认，降低边缘卡片被截断的风险。
- ADB 采集输出包含 `manifest.json / actions.log / device_info.json / summary.json`。
- `summary.json` 可以记录 `resume_cursor / next_resume_cursor / bottom_reached`。
- 识别工作台能够消费 ADB 帧，并调用当前 OpenCV + 名称 OCR + ONNX/PyTorch 辅助链路。
- 稀有度可以作为识别候选过滤条件，但只有筛选状态确认后才建议启用硬过滤。
- `needs_review / ambiguous / rejected_partial` 不进入自动写入链路。

### 13.2 当前还没有完成的部分

- 白、蓝、紫、金、彩五个稀有度的完整自动编排还没有形成一个正式任务。
- 稀有度切换断点和单稀有度内部滚动断点还没有统一成一个总 checkpoint。
- 程序中断后，尚未完整实现“自动恢复筛选状态并继续当前稀有度”的端到端流程。
- 跨帧卡片去重目前已有基础信息，但仍需要用真实截图继续验证边缘卡片与重复卡片不会漏算或重复累计。
- 全稀有度识别结果还没有汇总成一份稳定的当天草稿数据。
- OCR 结果到 Integration 层、再到 `UserDataManager` 的正式写入链路尚未完成。
- 自动写入前的冲突处理、人工复核和失败回滚规则仍需开发。
- 当前准确率主要经过已有样本和人工测试验证，尚未完成覆盖不同账号、不同数量状态和长时间运行的系统验收。

### 13.3 下一阶段开发顺序

1. 完成单稀有度扫图结果的稳定汇总，确保卡片不漏、不重复。
2. 统一稀有度切换断点与滚动断点，形成一个总 `checkpoint.json`。
3. 实现白 → 蓝 → 紫 → 金 → 彩的自动顺序任务，并支持从指定稀有度继续。
4. 把每个稀有度的识别结果合并为当天识别草稿。
5. 对 `needs_review / ambiguous / rejected_partial` 建立明确的审核输出。
6. 接入 Integration 层，只允许通过规则校验的结果写入 `UserDataManager`。
7. 补充断网、ADB 中断、游戏卡顿、筛选状态丢失和模拟器重连测试。
8. 完成全流程人工验收后，再决定是否默认开启正式数据写入。

### 13.4 当前阶段结论

当前可以认为：

- “单稀有度设计图采集与识别”已经进入可测试阶段。
- “全部稀有度自动扫描并写入当天数据”仍处于后续开发阶段。

因此现阶段测试重点应放在页面切换、空页短路、回顶、到底、分帧完整性、断点字段和单稀有度识别结果，不应把正式数据自动写入列为已完成功能。
