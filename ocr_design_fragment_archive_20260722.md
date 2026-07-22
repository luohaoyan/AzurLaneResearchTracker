# v0.6.0 设计图装备图标识别归档说明

归档时间：2026-07-22

归档目的：

- 固化当前已经通过 QA 的“设计图装备图标识别”实现。
- 为后续主线合并提供文件清单、接口说明和测试入口。
- 为后续单独开启“装备页识别”对话提供可借鉴的 OpenCV/OCR/ONNX/PyTorch 资料。
- 避免历史训练输出、预览图和临时标注目录混入正式合并。

## 1. 当前 QA 结论

QA 报告结论：

- OCR 专项：196/196 passed
- 全量回归：369/369 passed
- pip check：无损坏依赖
- 主输出：equipment_name
- equipment_id：仅作为运行时映射
- 半截卡片：rejected_partial
- 冲突样本：needs_review
- --no-preview：正常输出 CSV/JSON
- 中文预览：正常显示

推荐正式链路：

```text
OpenCV 高置信直出
+ OCR 名称/数量辅助
+ ONNX FP16 fallback
```

## 2. 主线合并建议范围

建议优先合并以下正式运行代码：

```text
core/recognition/design_fragment_detector.py
core/recognition/equipment_card_reader.py
core/recognition/equipment_icon_matcher.py
core/recognition/equipment_name_resolver.py
core/recognition/ocr_engine.py
core/recognition/preview_renderer.py
core/recognition/template_matcher.py
core/recognition/scene_analyzer.py
core/recognition/ocr_task_api.py
core/recognition/__init__.py
config/recognition/
recognition_workbench/
nn_training_lab/inference/
nn_training_lab/scripts/run_screenshot_pipeline.py
nn_training_lab/scripts/benchmark_icon_backends.py
nn_training_lab/pytorch_icon_training/scripts/
nn_training_lab/deployment/
test/v060/ocr/
requirements.txt
```

合并时需要重点确认：

- 不要合并 `qa_tests/`。
- 不要合并 `.tmp_pytest*`。
- 不要合并历史 `test_out/`、`img_out/`、`__pycache__/`。
- PyTorch 训练中间 epoch 体积很大，不建议进入主仓库。
- ONNX 部署模型是否进入 Git，由合并工程师按仓库体积策略决定。

## 3. 正式接口契约

设计图识别最终输出以装备名称为主：

```text
final_equipment_name: 装备名称
equipment_id: 由当前 data/equipment_library.csv 运行时映射
fragment_count: 左侧已有碎片数量
required_count: 右侧合成需求数量
final_status: success / needs_review / rejected_partial / unavailable
recognition_source: opencv / ocr / onnx / pytorch / mixed
warnings: 冲突和低置信提示
```

不得把模型主标签改回 equipment_id。

原因：

- equipment_id 可能随 Wiki/爬虫数据更新而变化。
- equipment_name 相对稳定，更适合作为模型类别标签。

## 4. 人工测试入口

把完整 1280x720 设计图截图放入：

```text
recognition_workbench/test_img/
```

双击运行：

```text
recognition_workbench/RUN_RECOGNITION.bat
```

只输出 CSV/JSON，不生成预览图：

```text
recognition_workbench/RUN_RECOGNITION_NO_PREVIEW.bat
```

输出位置：

```text
recognition_workbench/test_out/run_时间戳/
```

重点查看：

```text
annotated/*_pipeline.png
screenshot_pipeline_results.csv
screenshot_pipeline_results.json
screenshot_pipeline_summary.json
recognition_model.json
```

## 5. 模型状态

PyTorch 训练模型：

```text
nn_training_lab/pytorch_icon_training/models/run_20260722_191241/
```

ONNX 部署模型：

```text
nn_training_lab/deployment/onnx_models/run_20260722_191241/
```

ONNX 文件：

```text
equipment_icon_resnet18_fp32.onnx
equipment_icon_resnet18_fp16.onnx
equipment_icon_resnet18_int8_dynamic.onnx
label_map.json
onnx_export_summary.json
```

推荐默认：

```text
equipment_icon_resnet18_fp16.onnx
```

注意：

- FP16 在当前开发机 benchmark 最快。
- 不同 CPU/GPU/核显环境需要重新跑 benchmark。
- PyTorch 主要用于训练和对照，不建议成为普通用户默认依赖。

## 6. 后续训练入口

重建训练集：

```powershell
python nn_training_lab/scripts/build_equipment_icon_nn_dataset.py
```

训练 PyTorch ResNet18：

```powershell
python nn_training_lab/pytorch_icon_training/scripts/train_resnet_icon_classifier.py --epochs 80
```

导出 ONNX：

```powershell
python nn_training_lab/pytorch_icon_training/scripts/export_onnx.py --run-dir nn_training_lab/pytorch_icon_training/models/run_20260722_191241
```

benchmark：

```powershell
python nn_training_lab/scripts/benchmark_icon_backends.py --pytorch-run nn_training_lab/pytorch_icon_training/models/run_20260722_191241 --onnx-dir nn_training_lab/deployment/onnx_models/run_20260722_191241 --limit 120
```

## 7. 后续装备页识别可借鉴内容

装备页识别建议另开目录，不要与设计图识别混在一起。

可以复用：

- OpenCV icon 匹配器的图库加载和候选融合策略。
- OCR engine 的延迟加载、unavailable 兜底和本地模型目录配置。
- preview_renderer 的中文预览绘制。
- ONNX/PyTorch icon classifier 的 equipment_name 输出契约。
- benchmark 脚本的后端对比方式。

不建议直接复用：

- 设计图卡片 ROI。
- 设计图碎片数量规则。
- 设计图半截卡片判定阈值。

装备页需要单独处理：

- 装备中小人遮挡。
- 强化等级数字抹除。
- 右下角堆叠数量识别。
- “装备中 ON/OFF”状态。
- 装备页稀有度/类型筛选状态。
- 跨页去重和断点续接。

## 8. 当前不要宣称的内容

不要宣称：

```text
真实用户截图准确率已达到 98%
装备页识别已经完成
模型对所有新装备都能识别
INT8 已完成静态校准
DirectML/OpenVINO/TensorRT 已完成正式验证
```

可以说明：

```text
设计图 icon 识别链路已通过 QA 回归。
当前推荐 OpenCV + OCR + ONNX FP16 fallback。
独立真实截图准确率仍需持续人工验收。
装备页识别建议单独建模和测试。
```
