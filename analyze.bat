@echo off
chcp 65001 >nul
echo =================================================
echo  📷 PhotoShutterInspector - Анализ EXIF/Shutter
echo =================================================
echo.

if "%~1"=="" (
    echo Использование:
    echo   analyze.bat файл.CR2              - анализ одного файла
    echo   analyze.bat папка                 - анализ всех файлов в папке
    echo   analyze.bat файл1.CR2 файл2.CR2   - сравнение двух файлов
    echo.
    echo Опции:
    echo   --json output.json   - сохранить в JSON
    echo   --csv output.csv     - сохранить в CSV
    echo.
    pause
    exit /b
)

if "%~2"=="" (
    REM Один аргумент - анализ файла/папки
    python "%~dp0photoshutterinspector.py" "%~1" --pretty --exiftool "%~dp0exiftool.exe"
) else if "%~3"=="" (
    REM Два аргумента - сравнение файлов
    python "%~dp0photoshutterinspector.py" "%~1" --compare "%~2" --exiftool "%~dp0exiftool.exe"
) else (
    REM Три и более - передаём как есть
    python "%~dp0photoshutterinspector.py" %* --exiftool "%~dp0exiftool.exe"
)

echo.
pause
