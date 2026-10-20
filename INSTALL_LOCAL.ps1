[CmdletBinding()]
param(
    [string]$InstallPath = 'C:\Apps\SunoAiRemoveHissing'
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSCommandPath
$projectPath = Join-Path $repoRoot 'src\SunoAiRemoveHissing\SunoAiRemoveHissing.csproj'
$appsRoot = [IO.Path]::GetFullPath('C:\Apps')
$installFullPath = [IO.Path]::GetFullPath($InstallPath)
$appsPrefix = $appsRoot.TrimEnd('\') + '\'

if (-not $installFullPath.StartsWith($appsPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "InstallPath must be below C:\Apps. Received: $installFullPath"
}

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw '.NET 10 SDK was not found in PATH.'
}

if (Test-Path -LiteralPath $installFullPath) {
    Write-Host "Removing previous local install: $installFullPath"
    Remove-Item -LiteralPath $installFullPath -Recurse -Force
}

New-Item -ItemType Directory -Path $installFullPath -Force | Out-Null

Write-Host "Publishing self-contained Windows app to: $installFullPath"
& dotnet publish $projectPath `
    --configuration Release `
    --runtime win-x64 `
    --self-contained true `
    --output $installFullPath `
    /p:PublishSingleFile=true `
    /p:IncludeNativeLibrariesForSelfExtract=true `
    /p:DebugType=None `
    /p:DebugSymbols=false

if ($LASTEXITCODE -ne 0) {
    throw "dotnet publish failed with exit code $LASTEXITCODE"
}

$exePath = Join-Path $installFullPath 'SunoAiRemoveHissing.exe'
$backendPath = Join-Path $installFullPath 'backend\SunoClean_AI.py'
if (-not (Test-Path -LiteralPath $exePath)) { throw "Publish did not create $exePath" }
if (-not (Test-Path -LiteralPath $backendPath)) { throw "Publish did not copy $backendPath" }

Get-ChildItem -LiteralPath $installFullPath -Filter '*.pdb' -File -Recurse | Remove-Item -Force

Write-Host ''
Write-Host 'INSTALL COMPLETE'
Write-Host "App:     $exePath"
Write-Host "Backend: $backendPath"
Write-Host 'The app still needs your chosen Python installation with NumPy, SciPy, and ffmpeg available in PATH.'
