@echo off
cd /d "%~dp0"
pip install -r requirements.txt
start "" pythonw app.py