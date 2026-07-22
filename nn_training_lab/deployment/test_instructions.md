# 装备 icon 识别部署测试说明

本文用于交给测试工程师验收 v0.6.0 OCR/图像识别中的“设计图装备 icon 识别”部分。

当前推荐正式方案：

```text
OpenCV 高置信直出
OCR 辅助识别名称和碎片数量
ONNX Runtime 处理 OpenCV ambiguous / unknown / 低置信 icon
PyTorch 保留给训练、调试和对照，不建议作为普通用户默认依赖
```

重要约束：

```text
模型主输出必须是 equipment_name。
equipment_id 只作为当前 equipment_library.csv 的运行时映射。
半截卡片必须 rejected_partial，不能让模型猜。
benchmark 不是独立真实截图准确率，不能宣称 98%。
```

## 1. 目录与文件总览

### 1.1 用户测试入口

```text
recognition_workbench\
```

用途：给人工测试使用的整图识别工作台。

关键文件：

```text
recognition_workbench\run_recognition.py
recognition_workbench\RUN_RECOGNITION.bat
recognition_workbench\RUN_RECOGNITION_NO_PREVIEW.bat
recognition_workbench\use.txt
recognition_workbench\test_img\
recognition_workbench\test_out\
```

功能说明：

```text
run_recognition.py
  读取 test_img 中的完整设计图截图。
  调用 OpenCV 卡片检测、OCR 数量/名称识别、OpenCV icon 匹配、ONNX/PyTorch 疑难 fallback。
  输出 annotated 预览图、CSV、JSON 和模型元数据。

RUN_RECOGNITION.bat
  双击运行默认识别流程，生成 annotated 预览。

RUN_RECOGNITION_NO_PREVIEW.bat
  双击运行无预览流程，只输出 CSV/JSON，适合正式接入时减少文件写入。
```

### 1.2 核心识别代码

```text
core\recognition\
```

关键文件与功能：

```text
core\recognition\design_fragment_detector.py
  负责识别设计图页面中的装备卡片。
  输出每张卡片的 bbox、icon_roi、quantity_roi、visibility。
  半截卡片应标记为 partial，不进入 icon/数量识别。

core\recognition\equipment_icon_matcher.py
  OpenCV 装备图标匹配器。
  使用 data/images、accepted gallery、reviewed gallery 进行模板/颜色/边缘/哈希/局部融合匹配。
  高置信结果可直接作为 final_equipment_name 的证据。

core\recognition\equipment_card_reader.py
  负责读取卡片中的碎片数量、需求数量，以及可选的卡片名称 OCR。
  依赖 ocr_engine.py。

core\recognition\ocr_engine.py
  PaddleOCR 延迟加载封装。
  PaddleOCR 缺失或模型目录未配置时应返回 unavailable，不允许 import 崩溃。

core\recognition\equipment_name_resolver.py
  将 OCR 读到的装备名称文本解析到 equipment_library.csv 中的 equipment_name。
  用于纠正图标相似但文字能区分的装备。

core\recognition\equipment_attribute_reranker.py
  使用 Wiki 属性签名辅助重排疑难候选。
  当前主要用于训练/分析，不建议作为唯一判定来源。

core\recognition\preview_renderer.py
  使用 Pillow 绘制中文 annotated 预览文字。
  解决 OpenCV putText 中文显示为 ??? 的问题。
```

### 1.3 完整截图识别流水线

```text
nn_training_lab\scripts\run_screenshot_pipeline.py
```

功能：

```text
整图截图 -> 卡片检测 -> 半截卡拒绝 -> OpenCV icon -> OCR 名称/数量 -> NN fallback -> 输出 CSV/JSON/annotated
```

主要输出字段：

```text
filename
rarity
card_no
visibility
bbox
icon_roi
name_roi
quantity_roi
opencv_status
opencv_equipment_name
opencv_confidence
name_ocr_status
name_ocr_text
name_resolve_equipment_name
nn_status
nn_equipment_name
nn_confidence
final_status
final_equipment_name
recognition_source
fragment_count
required_count
warnings
```

通过标准：

```text
完整卡片才允许进入 icon/数量识别。
半截卡片必须 rejected_partial。
final_equipment_name 必须是装备名称，不是 ID。
OpenCV/ONNX/PyTorch 冲突时不能强行写成功，应进入 needs_review。
```

## 2. 模型与训练数据说明

### 2.1 当前 PyTorch 模型

当前模型目录：

```text
nn_training_lab\pytorch_icon_training\models\run_20260722_191241\
```

关键文件：

```text
best.pt
label_map.json
training_summary.json
metrics.csv
epoch_001.pt ... epoch_080.pt
```

模型信息：

```text
backbone: ResNet18
label_key: equipment_name
classes: 210
train_samples: 330
validation_samples: 90
epochs: 80
device: NVIDIA GeForce RTX 5070 Ti
best_validation_top1: 0.7888888888888889
```

说明：

```text
PyTorch 模型用于训练、调试和对照。
普通用户环境不建议默认依赖 PyTorch。
模型输出 equipment_name，equipment_id 只从 data\equipment_library.csv 动态映射。
```

### 2.2 ONNX 部署模型

当前 ONNX 目录：

```text
nn_training_lab\deployment\onnx_models\run_20260722_191241\
```

文件：

```text
equipment_icon_resnet18_fp32.onnx
equipment_icon_resnet18_fp16.onnx
equipment_icon_resnet18_int8_dynamic.onnx
label_map.json
onnx_export_summary.json
```

各版本说明：

```text
FP32
  兼容性最好，推荐作为通用兜底模型。

FP16
  半精度模型。本机 CPUExecutionProvider benchmark 最快。
  其他机器需要复测；在部分 CPU/后端上未必比 FP32 快。

INT8 dynamic
  动态量化模型。本机未变快，暂不推荐默认。
  如果后续要低端 CPU 极致优化，需要准备校准集做静态量化。
```

ONNX 推理代码：

```text
nn_training_lab\inference\onnx_icon_classifier.py
```

功能：

```text
加载 ONNX Runtime。
自动选择 provider。
读取 label_map.json。
对 108x108 或其他完整正方形 icon 做 224x224 归一化。
输出 top-k equipment_name 候选。
```

Provider 策略：

```text
优先级：
TensorrtExecutionProvider
CUDAExecutionProvider
DmlExecutionProvider
OpenVINOExecutionProvider
CPUExecutionProvider

当前 requirements 只固定 CPU ONNX Runtime。
DirectML / CUDA / OpenVINO / TensorRT 是可选环境，不强制安装。
```

### 2.3 OpenCV 图库

OpenCV 匹配主要使用：

```text
data\images\
ocr_training_lab\equipment_icon_matcher_v2\accepted_icon_gallery\
ocr_training_lab\equipment_icon_matcher_v2\reviewed_icon_gallery\
nn_training_lab\archive\equipment_icon_matcher_v2\reviewed_icon_gallery\
```

关键 manifest：

```text
ocr_training_lab\equipment_icon_matcher_v2\reviewed_icon_gallery\reviewed_icon_gallery_manifest.csv
nn_training_lab\archive\equipment_icon_matcher_v2\reviewed_icon_gallery\reviewed_icon_gallery_manifest.csv
```

说明：

```text
reviewed gallery 是人工确认样本，优先级高。
accepted gallery 是较早的机器/人工混合确认样本。
data\images 是 Wiki 爬虫获得的基础图标。
```

### 2.4 人工单 icon 样本导入

代码：

```text
nn_training_lab\scripts\add_confirmed_single_icon.py
```

用途：

```text
把用户直接发来的完整 icon 加入 OpenCV reviewed gallery 和 NN archive。
支持用 equipment_id 从 equipment_library.csv 反查 equipment_name，避免 Windows 命令行中文编码问题。
```

示例：

```powershell
python nn_training_lab\scripts\add_confirmed_single_icon.py --icon "icon.png" --equipment-id S2-002 --case-id 20260722_s2_002_user_icon_310mm
```

已导入样本：

```text
equipment_name: 试作型三联装310mm主炮#T0
equipment_id: S2-002
source: 用户补充单 icon
OpenCV top1 confidence: 0.9999999
PyTorch top1 confidence: 0.9895
ONNX FP32 top1 confidence: 0.9841
```

## 3. 环境准备

在项目根目录执行：

```powershell
python -m pip install -r requirements.txt
```

基础 ONNX 部署依赖：

```text
onnx
onnxruntime
onnxconverter-common
onnxscript
```

可选后端：

```text
onnxruntime-directml  # Windows 核显/部分独显 DirectML
onnxruntime-gpu       # NVIDIA CUDA
OpenVINO/TensorRT     # 当前只做 provider 探测，不作为默认依赖
```

不要求测试工程师必须安装可选后端。纯 CPU 环境必须能跑。

## 4. 快速整图测试

把完整设计图截图放到：

```text
recognition_workbench\test_img\
```

双击：

```text
recognition_workbench\RUN_RECOGNITION.bat
```

或命令：

```powershell
python recognition_workbench\run_recognition.py --nn-backend auto
```

输出目录：

```text
recognition_workbench\test_out\run_时间戳\
```

检查文件：

```text
annotated\*_pipeline.png
screenshot_pipeline_results.csv
screenshot_pipeline_results.json
screenshot_pipeline_summary.json
recognition_model.json
```

通过标准：

```text
脚本不崩溃。
recognition_model.json 存在。
recognition_model.json 中 label_key == equipment_name。
CSV 中 final_equipment_name 为装备名称。
半截卡片为 rejected_partial。
annotated 图中文字中文正常，不应显示 ???。
```

## 5. 后端切换测试

默认自动选择，ONNX 可用时优先 ONNX，不可用时回退 PyTorch：

```powershell
python recognition_workbench\run_recognition.py --nn-backend auto
```

强制 ONNX：

```powershell
python recognition_workbench\run_recognition.py --nn-backend onnx
```

强制 ONNX FP16：

```powershell
python recognition_workbench\run_recognition.py --nn-backend onnx --onnx-model equipment_icon_resnet18_fp16.onnx
```

强制 PyTorch：

```powershell
python recognition_workbench\run_recognition.py --nn-backend pytorch
```

关闭 NN，只测 OpenCV + OCR：

```powershell
python recognition_workbench\run_recognition.py --nn-backend off
```

关闭 annotated 预览：

```powershell
python recognition_workbench\run_recognition.py --no-preview
```

通过标准：

```text
--nn-backend onnx 时 recognition_model.json 中 backend 包含 onnx。
--nn-backend pytorch 时 recognition_model.json 中 backend 包含 pytorch。
--nn-backend off 时不应调用 NN fallback。
--no-preview 时不生成 annotated 目录，但 CSV/JSON 仍正常输出。
```

## 6. ONNX 导出测试

双击：

```text
nn_training_lab\deployment\run_export_onnx.bat
```

或命令：

```powershell
python nn_training_lab\pytorch_icon_training\scripts\export_onnx.py --run-dir nn_training_lab\pytorch_icon_training\models\run_20260722_191241
```

输出目录：

```text
nn_training_lab\deployment\onnx_models\run_20260722_191241\
```

通过标准：

```text
onnx_export_summary.json 存在。
FP32 / FP16 / INT8 dynamic 至少 FP32 status == ok。
label_map.json 存在且 label_key == equipment_name。
```

## 7. Benchmark 测试

双击：

```text
nn_training_lab\deployment\run_benchmark_icon_backends.bat
```

或命令：

```powershell
python nn_training_lab\scripts\benchmark_icon_backends.py --pytorch-run nn_training_lab\pytorch_icon_training\models\run_20260722_191241 --onnx-dir nn_training_lab\deployment\onnx_models\run_20260722_191241 --limit 120
```

输出目录：

```text
nn_training_lab\deployment\benchmark_out\run_时间戳\
```

检查文件：

```text
backend_benchmark_report.txt
backend_benchmark_summary.json
backend_benchmark_results.csv
```

已测参考结果：

```text
OpenCV：top1=0.975，top3=0.975，avg_ms=327.29
PyTorch CUDA：top1=0.9667，top3=0.975，avg_ms=76.59
ONNX FP32 CPU：top1=0.9667，top3=0.975，avg_ms=73.26
ONNX FP16 CPU：top1=0.9667，top3=0.975，avg_ms=12.73
ONNX INT8 dynamic CPU：top1=0.9667，top3=0.975，avg_ms=89.16
```

通过标准：

```text
benchmark 脚本不崩溃。
至少 CPUExecutionProvider 可用。
输出 CSV/JSON/TXT。
top1/top3/avg_ms 字段存在。
```

注意：

```text
benchmark 使用现有训练/图库样本，是工程诊断，不代表独立真实截图准确率。
测试报告中不得写“已达到 98% 真实准确率”。
```

## 8. 项目回归测试

OCR 模块：

```powershell
python -m pytest test\v060\ocr -q --basetemp=.tmp_pytest_ocr_acceptance
```

契约测试：

```powershell
python -m pytest test\v060\contracts -q --basetemp=.tmp_pytest_contracts_acceptance
```

测试后清理：

```powershell
python -c "from pathlib import Path; import shutil; root=Path.cwd(); [shutil.rmtree(p) for p in root.glob('.tmp_pytest*') if p.is_dir()]"
```

当前开发机已跑结果：

```text
test\v060\ocr：187 passed
test\v060\contracts：9 passed
workbench ONNX FP16 smoke：通过
```

## 9. 重点验收字段

### 9.1 recognition_model.json

必须检查：

```text
backend
pytorch_model
onnx_model_dir
onnx_model
label_key
```

通过标准：

```text
label_key == equipment_name
backend 与命令行指定后端一致
```

### 9.2 screenshot_pipeline_results.csv

重点字段：

```text
filename
rarity
card_no
visibility
opencv_status
opencv_equipment_name
opencv_confidence
name_ocr_status
name_ocr_text
name_resolve_equipment_name
nn_status
nn_equipment_name
nn_confidence
final_status
final_equipment_name
recognition_source
fragment_count
required_count
warnings
```

通过标准：

```text
final_equipment_name 是装备名称。
半截卡片 visibility 非 full 时 final_status 应是 rejected_partial。
warnings 中出现冲突时，不应强行 final_status=success。
fragment_count / required_count 不应和装备强化等级混淆。
```

### 9.3 annotated 预览图

通过标准：

```text
中文正常显示。
绿色/红色/橙色等状态框清晰。
卡片编号能和 CSV card_no 对上。
半截卡片应明显标注为 rejected/partial。
```

## 10. 建议测试矩阵

### 10.1 纯 CPU 机器

必测：

```powershell
python recognition_workbench\run_recognition.py --nn-backend onnx
python recognition_workbench\run_recognition.py --nn-backend onnx --onnx-model equipment_icon_resnet18_fp16.onnx
```

目标：

```text
确认 CPUExecutionProvider 可用。
确认速度可接受。
确认无 CUDA/PyTorch 依赖也能跑 ONNX。
```

### 10.2 NVIDIA 独显机器

必测：

```powershell
python recognition_workbench\run_recognition.py --nn-backend pytorch
python recognition_workbench\run_recognition.py --nn-backend onnx
```

目标：

```text
对比 PyTorch CUDA 与 ONNX Runtime。
确认 PyTorch 不是普通用户必需。
```

### 10.3 核显或 AMD/Intel 显卡机器

可选安装：

```powershell
python -m pip install onnxruntime-directml
```

目标：

```text
确认 DmlExecutionProvider 是否出现在 available_providers。
确认 DirectML 运行是否稳定。
```

### 10.4 新截图人工验收

请准备未参与训练的新设计图截图，重点覆盖：

```text
金装主炮
彩装主炮
相似鱼雷
名称相似但 icon 相近的装备
页面顶部/底部半截卡片
不同排序：稀有度 / 可建造 / 数量
```

通过标准：

```text
高置信正确率肉眼可接受。
疑难样本进入 needs_review，而不是乱填。
半截卡片不识别。
数量识别不把强化等级当数量。
```

## 11. 已知限制和后续建议

已知限制：

```text
当前 benchmark 不是独立真实截图准确率。
DirectML/OpenVINO/TensorRT 只做 provider 探测，不强制依赖。
INT8 是动态量化，不是校准后的静态量化。
当前 backbone 是 ResNet18，模型仍有压缩空间。
设计图部分可用；装备页遮挡场景暂未作为最终验收目标。
```

后续优化建议：

```text
如果要进一步减小模型体积，可训练 MobileNetV3-small / EfficientNet-lite 对照。
如果要优化低端 CPU，可准备校准集做静态 INT8。
如果要优化核显，可单独验证 onnxruntime-directml。
如果要优化 Intel CPU/核显，可单独做 OpenVINO 导出和 benchmark。
```

## 12. 测试报告建议格式

测试工程师可按下面格式反馈：

```text
【装备 icon 识别验收报告】

测试机器：
CPU：
GPU：
内存：
Python：

测试命令：

截图数量：
完整卡片数量：
半截卡片数量：

后端：
OpenCV：
ONNX FP32：
ONNX FP16：
PyTorch：

结果：
final_success：
needs_review：
partial_rejected：

人工抽查结论：
明显错误样本：
疑难样本：
速度是否可接受：

是否通过：
阻塞问题：
建议：
```
