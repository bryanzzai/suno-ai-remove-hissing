[CmdletBinding()]
param(
    [string]$Output = (Join-Path $PSScriptRoot 'dist\SunoAiRemoveHissing-Portable'),
    [string]$PythonForPackaging = 'python'
)

$ErrorActionPreference = 'Stop'

# This is deliberately an inspectable build recipe.  The runtime Python is not
# installed on Windows; it is copied into the output folder with its packages.
$project = Join-Path $PSScriptRoot 'src\SunoAiRemoveHissing\SunoAiRemoveHissing.csproj'
$requirements = Join-Path $PSScriptRoot 'backend\requirements.txt'
$pythonVersion = '3.11.9'
$pythonTag = '311'
$work = Join-Path $PSScriptRoot '.portable-build'
$runtime = Join-Path $Output 'runtime'
$tools = Join-Path $Output 'tools'

if (-not (Get-Command $PythonForPackaging -ErrorAction SilentlyContinue)) {
    throw "Packaging Python '$PythonForPackaging' was not found. Install Python 3.11+ only on the build machine."
}

Remove-Item $Output -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Output, $work, $runtime, $tools | Out-Null

dotnet publish $project `
    -c Release `
    -r win-x64 `
    --self-contained true `
    -o $Output `
    /p:PublishSingleFile=true `
    /p:IncludeNativeLibrariesForSelfExtract=true `
    /p:DebugType=None `
    /p:DebugSymbols=false

# 1. Official CPython embedded distribution: no registry entries and no PATH use.
$pythonZip = Join-Path $work "python-$pythonVersion-embed-amd64.zip"
Invoke-WebRequest "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-embed-amd64.zip" -OutFile $pythonZip
Expand-Archive $pythonZip -DestinationPath $runtime -Force

# Embedded Python disables 'site' by default.  Enable only this package folder.
$pth = Join-Path $runtime "python$pythonTag._pth"
@(
    "python$pythonTag.zip"
    '.'
    'Lib\site-packages'
    'import site'
) | Set-Content -Path $pth -Encoding ascii

# 2. NumPy and SciPy wheels are copied to the embedded runtime.
& $PythonForPackaging -m pip install --disable-pip-version-check --only-binary=:all: `
    --target (Join-Path $runtime 'Lib\site-packages') `
    -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'Installing backend Python packages failed.' }

# 3. Static FFmpeg: the finished application calls only this one executable.
$ffmpegZip = Join-Path $work 'ffmpeg-release-essentials.zip'
$ffmpegUnpacked = Join-Path $work 'ffmpeg'
Invoke-WebRequest 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $ffmpegZip
Expand-Archive $ffmpegZip -DestinationPath $ffmpegUnpacked -Force
$ffmpeg = Get-ChildItem $ffmpegUnpacked -Recurse -Filter ffmpeg.exe | Select-Object -First 1
if ($null -eq $ffmpeg) { throw 'The FFmpeg archive did not contain ffmpeg.exe.' }
Copy-Item $ffmpeg.FullName (Join-Path $tools 'ffmpeg.exe') -Force

@'
Third-party components bundled with this portable build

- CPython embeddable package: https://www.python.org/downloads/windows/
- NumPy: https://numpy.org/license/
- SciPy: https://scipy.org/about/
- FFmpeg essentials build: https://www.gyan.dev/ffmpeg/builds/

These components remain separate executables/libraries in the portable folder.
'@ | Set-Content -Path (Join-Path $Output 'THIRD_PARTY_NOTICES.txt') -Encoding utf8

# Fail the build if the copied runtime cannot do the work the app requires.
& (Join-Path $runtime 'python.exe') -c "import numpy, scipy; print('Portable Python OK:', numpy.__version__, scipy.__version__)"
if ($LASTEXITCODE -ne 0) { throw 'The portable Python runtime cannot import NumPy and SciPy.' }
& (Join-Path $tools 'ffmpeg.exe') -version
if ($LASTEXITCODE -ne 0) { throw 'The bundled FFmpeg executable did not start.' }

Write-Host "Portable folder created: $Output"
