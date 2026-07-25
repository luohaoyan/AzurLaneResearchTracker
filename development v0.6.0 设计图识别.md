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

日期：2026-07-25

当前工作重点：

- ADB 层：让“仓库页 → 设计图页”的切换动作稳定、可确认、可回退。
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
- 每个稀有度单独一个 session
- 每个 session 都有 checkpoint / resume cursor

建议规则：

- 每个稀有度都是独立运行
- 每个稀有度都写自己的 `manifest.json / actions.log / summary.json`
- 不要把不同稀有度的结果混在一个 session 里

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

- 设计图页按稀有度扫图的完整编排
- checkpoint / resume 的更细粒度控制
- 稀有度切换后的重复帧去重策略
- 草稿层和正式表之间的整合层

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
