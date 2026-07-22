@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
if "%~1"=="" (
  set /p "INPUT=Icon file or folder: "
) else (
  set "INPUT=%~1"
)
where py >nul 2>nul
if errorlevel 1 (set "PYTHON=python") else (set "PYTHON=py -3")
%PYTHON% nn_training_lab\scripts\run_nn_icon_inference.py "%INPUT%" --top-k 3
if errorlevel 1 pause
endlocal
