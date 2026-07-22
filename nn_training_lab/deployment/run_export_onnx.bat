@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0..\.."
where py >nul 2>nul
if errorlevel 1 (set "PYTHON=python") else (set "PYTHON=py -3")
%PYTHON% nn_training_lab\pytorch_icon_training\scripts\export_onnx.py --run-dir nn_training_lab\pytorch_icon_training\models\run_20260722_191241
pause
endlocal
