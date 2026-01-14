@echo off
chcp 65001 >nul
echo ========================================
echo  Сборка PhotoShutterInspector в EXE
echo ========================================
echo.

:: Проверка PyInstaller
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo Установка PyInstaller...
    pip install pyinstaller
)

echo.
echo Сборка CLI версии...
pyinstaller --onefile --console --name PhotoShutterInspector --icon=NONE photoshutterinspector.py

echo.
echo Сборка GUI версии...
pyinstaller --onefile --windowed --name PhotoShutterInspector_GUI --icon=NONE gui.py

echo.
echo ========================================
echo  Готово! Файлы в папке dist\
echo ========================================
echo.
echo Для работы нужен ExifTool рядом с exe:
echo   - exiftool.exe
echo   - exiftool_files\
echo.
pause
