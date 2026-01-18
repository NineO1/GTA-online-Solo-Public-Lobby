@echo off
REM Build single-file Solo_Public_Lobby_V-Online.exe
REM Run this from the project root (where create_rule_admin_gui_simple.py and GTAO.ico / GTAO_active.ico live).

SETLOCAL

REM Activate venv if present
if exist "venv\Scripts\activate.bat" (
  call "venv\Scripts\activate.bat"
)

REM Ensure PyInstaller is installed (pinned for Python 3.12)
echo Installing/ensuring PyInstaller...
pip install --upgrade pip >nul 2>&1
pip install "pyinstaller==6.18.0" >nul 2>&1

REM Check required icon files
if not exist "GTAO.ico" (
  echo ERROR: GTAO.ico not found in the current folder.
  echo Place GTAO.ico next to create_rule_admin_gui_simple.py and re-run this script.
  pause
  exit /b 1
)
if not exist "GTAO_active.ico" (
  echo ERROR: GTAO_active.ico not found in the current folder.
  echo Place GTAO_active.ico next to create_rule_admin_gui_simple.py and re-run this script.
  pause
  exit /b 1
)

REM Clean previous PyInstaller outputs (optional but recommended)
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "Solo_Public_Lobby_V-Online.spec" del /f /q "Solo_Public_Lobby_V-Online.spec"

REM Build command
echo Building one-file EXE...
py -3 -m PyInstaller ^
  --onefile ^
  --name "Solo_Public_Lobby_V-Online" ^
  --uac-admin ^
  --windowed ^
  --icon="GTAO.ico" ^
  --add-data "GTAO_active.ico;." ^
  --clean ^
  create_rule_admin_gui_simple.py

if %ERRORLEVEL% EQU 0 (
  echo.
  echo Build succeeded.
  echo The EXE is: %CD%\dist\Solo_Public_Lobby_V-Online.exe
) else (
  echo.
  echo Build failed. See the PyInstaller output above for details.
)

pause
ENDLOCAL