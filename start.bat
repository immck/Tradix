@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo 未检测到 Python，请先安装 Python 3.10+ 并加入 PATH。
  pause
  exit /b 1
)
start "" /b python -c "import time, webbrowser; time.sleep(1.5); webbrowser.open('http://127.0.0.1:8899')"
python server.py
pause
