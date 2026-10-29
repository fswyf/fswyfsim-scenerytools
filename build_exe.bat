@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ==================================================
echo  BGL 机场反编译器 - 构建 EXE
echo ==================================================
echo.
echo 需要 Windows + Python 3.10+（会检查/安装 PyInstaller）
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [错误] 找不到 python，请先安装 Python 3.10+ 并加入 PATH。
  pause
  exit /b 1
)

python -c "import PyInstaller" 2>nul
if errorlevel 1 (
  echo [提示] 正在安装 PyInstaller ...
  python -m pip install --upgrade pyinstaller
  if errorlevel 1 (
    echo [错误] PyInstaller 安装失败。
    pause
    exit /b 1
  )
)

echo [1/2] 构建图形界面版（无控制台窗口）...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name BGLAirportDecompiler ^
  --distpath "%~dp0dist" --workpath "%~dp0build" --specpath "%~dp0" ^
  "%~dp0src\gui_app.py"
if errorlevel 1 (
  echo [错误] GUI 版构建失败。
  pause
  exit /b 1
)

echo [2/2] 构建命令行版（有控制台窗口）...
python -m PyInstaller --noconfirm --clean --onefile --console ^
  --name bgl2xml-cli ^
  --distpath "%~dp0dist" --workpath "%~dp0build" --specpath "%~dp0" ^
  "%~dp0src\cli.py"
if errorlevel 1 (
  echo [错误] CLI 版构建失败。
  pause
  exit /b 1
)

echo.
echo ==================================================
echo  构建完成
echo   图形界面: dist\BGLAirportDecompiler.exe
echo   命令行  : dist\bgl2xml-cli.exe
echo ==================================================
echo.
echo 试一下：dist\bgl2xml-cli.exe "某机场.bgl"
pause
