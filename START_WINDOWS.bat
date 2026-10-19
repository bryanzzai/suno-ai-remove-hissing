@echo off
setlocal
cd /d "%~dp0"
dotnet run --project src\SunoAiRemoveHissing\SunoAiRemoveHissing.csproj
pause
