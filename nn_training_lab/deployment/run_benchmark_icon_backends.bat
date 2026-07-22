@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0..\.."
where py >nul 2>nul
if errorlevel 1 (set "PYTHON=python") else (set "PYTHON=py -3")
%PYTHON% nn_training_lab\scripts\benchmark_icon_backends.py --pytorch-run nn_training_lab\pytorch_icon_training\models\run_20260722_191241 --onnx-dir nn_training_lab\deployment\onnx_models\run_20260722_191241 --limit 120
pause
endlocal
