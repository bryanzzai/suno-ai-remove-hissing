@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PROJECT=src\SunoAiRemoveHissing\SunoAiRemoveHissing.csproj"
set "OUTPUT=dist\SunoAiRemoveHissing-win-x64"

where dotnet >nul 2>nul
if errorlevel 1 (
    echo ERROR: .NET SDK was not found in PATH.
    echo Install the .NET 10 SDK, then run this script again.
    exit /b 1
)

echo.
echo Publishing Suno AI Remove Hissing for Windows x64...
dotnet publish "%PROJECT%" ^
    --configuration Release ^
    --runtime win-x64 ^
    --self-contained true ^
    --output "%OUTPUT%" ^
    /p:PublishSingleFile=true ^
    /p:IncludeNativeLibrariesForSelfExtract=true

if errorlevel 1 (
    echo.
    echo BUILD FAILED.
    exit /b 1
)

echo.
echo BUILD COMPLETE
echo Executable: %OUTPUT%\SunoAiRemoveHissing.exe
echo Backend:    %OUTPUT%\backend\SunoClean_AI.py
echo.
echo The published app still needs Python with CUDA/Demucs and ffmpeg in PATH.
exit /b 0
