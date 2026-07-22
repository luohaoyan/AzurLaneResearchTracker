@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
where py >nul 2>nul
if errorlevel 1 (set "PYTHON=python") else (set "PYTHON=py -3")
%PYTHON% nn_training_lab\scripts\train_equipment_icon_classifier.py --epochs 24 --learning-rate 0.0005
if errorlevel 1 pause
endlocal
