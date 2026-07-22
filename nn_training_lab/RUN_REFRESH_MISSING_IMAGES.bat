@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
where py >nul 2>nul
if errorlevel 1 (set "PYTHON=python") else (set "PYTHON=py -3")
%PYTHON% nn_training_lab\scripts\refresh_missing_equipment_images.py
if errorlevel 1 pause
endlocal
