@echo off
REM 文件: K:\MultiViewSyncPlayer\packaging\build_windows.bat
REM 功能: 一键构建 MultiViewSyncPlayer onedir + 自检 + 打 zip
REM 输入: packaging/mvsp.spec(及其引用的 bin/icons/version_info.txt)
REM 输出: dist/MultiViewSyncPlayer/MultiViewSyncPlayer.exe + dist/MultiViewSyncPlayer-v0.2.1-win64.zip
REM 运行指令: 从仓库根目录执行 packaging\build_windows.bat
REM 生成时间: 2026-04-27 16:35

setlocal
cd /d %~dp0..

echo === [1/4] 清理上轮产出 ===
if exist build  rmdir /s /q build
if exist dist   rmdir /s /q dist

echo === [2/4] 运行 PyInstaller ===
python -m PyInstaller --clean --noconfirm packaging\mvsp.spec
if errorlevel 1 (
    echo BUILD FAILED
    exit /b 1
)

echo === [3/4] 自检关键文件 ===
if not exist dist\MultiViewSyncPlayer\MultiViewSyncPlayer.exe (
    echo MISSING: MultiViewSyncPlayer.exe
    exit /b 2
)
if not exist dist\MultiViewSyncPlayer\_internal\bin\ffmpeg.exe (
    echo MISSING: _internal\bin\ffmpeg.exe
    exit /b 3
)
if not exist dist\MultiViewSyncPlayer\_internal\bin\ffprobe.exe (
    echo MISSING: _internal\bin\ffprobe.exe
    exit /b 4
)
echo all key files OK

echo === [4/4] 打包 zip ===
powershell -NoProfile -Command "Compress-Archive -Path 'dist\MultiViewSyncPlayer\*' -DestinationPath 'dist\MultiViewSyncPlayer-v0.2.1-win64.zip' -Force"
dir dist\MultiViewSyncPlayer-v0.2.1-win64.zip

echo === DONE ===
endlocal
