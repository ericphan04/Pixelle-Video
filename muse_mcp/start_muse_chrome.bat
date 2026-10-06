@echo off
title Muse.ai Chrome Launcher (Port 9222)
echo Dang khoi dong Google Chrome ket noi Muse.ai tren cong 9222...
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="E:\linhtinh\MUSE_MCP\.muse-profile" --no-first-run --no-default-browser-check "https://muse.ai"
echo Chrome da duoc khoi dong tai https://muse.ai
