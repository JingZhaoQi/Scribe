# Build the Windows installers (.msi and .exe) for Scribe.
#
# Mirrors packaging/build_mac.sh: bundle a standalone Python interpreter with all
# dependencies, plus pandoc, plus the sources -- but no model weights. The app
# downloads those on demand.
#
# Not verified on real hardware yet; CI builds it, nobody has run the result.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$Payload = Join-Path $PWD "src-tauri\payload"   # must live inside src-tauri

Write-Host "> 1/5 Precompile the frontend"
node scripts/build_frontend.js

Write-Host "> 2/5 Stage a standalone Python environment"
if (Test-Path $Payload) { Remove-Item -Recurse -Force $Payload }
New-Item -ItemType Directory -Force -Path $Payload | Out-Null

# A venv cannot be redistributed: its scripts hard-code absolute paths. Copy the
# uv-managed standalone interpreter (python-build-standalone) instead.
uv python install 3.12
$pyDir = (uv python dir).Trim()
$pyRoot = Get-ChildItem -Path $pyDir -Directory |
    Where-Object { $_.Name -like "cpython-3.12.*-windows-*" } |
    Sort-Object Name | Select-Object -Last 1
if (-not $pyRoot) { throw "no uv-managed CPython 3.12 found; run: uv python install 3.12" }
Write-Host "  interpreter: $($pyRoot.FullName)"
Copy-Item -Recurse $pyRoot.FullName (Join-Path $Payload "python")

$Py = Join-Path $Payload "python\python.exe"
if (-not (Test-Path $Py)) { throw "python.exe missing from the copied interpreter" }
Remove-Item -Force (Join-Path $Payload "python\Lib\EXTERNALLY-MANAGED") -ErrorAction SilentlyContinue

# CPU-only torch: the default PyPI wheel pulls CUDA and inflates the installer
# by several GB for hardware most users do not have.
uv pip install --python $Py --quiet --index-url https://download.pytorch.org/whl/cpu torch torchvision
uv pip install --python $Py --quiet "mineru[core]" `
    python-docx lxml beautifulsoup4 Pillow fastapi uvicorn pypdf pymupdf
& $Py -c "import mineru, docx, fitz; print('  bundled environment self-check passed')"

Write-Host "> 3/5 Copy sources and pandoc"
New-Item -ItemType Directory -Force -Path (Join-Path $Payload "src") | Out-Null
Copy-Item -Recurse "src\p2w" (Join-Path $Payload "src\p2w")
Copy-Item -Recurse "src\p2w_gui" (Join-Path $Payload "src\p2w_gui")
Get-ChildItem -Path (Join-Path $Payload "src") -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

$PandocVer = "3.6.3"
$PandocZip = Join-Path $env:TEMP "pandoc.zip"
Invoke-WebRequest -Uri "https://github.com/jgm/pandoc/releases/download/$PandocVer/pandoc-$PandocVer-windows-x86_64.zip" -OutFile $PandocZip
Expand-Archive -Path $PandocZip -DestinationPath (Join-Path $env:TEMP "pandoc-dist") -Force
$PandocExe = Get-ChildItem -Path (Join-Path $env:TEMP "pandoc-dist") -Recurse -Filter "pandoc.exe" | Select-Object -First 1
Copy-Item $PandocExe.FullName (Join-Path $Payload "pandoc.exe")

Write-Host "> 4/5 Skipping model weights (downloaded on first use)"

Write-Host "> 5/5 Build the Tauri shell and installers"
# resources is injected here rather than in tauri.conf.json so `tauri dev` does
# not fail when payload/ is absent. Passed as a file: quoting a JSON literal
# through PowerShell to an external program mangles it.
$cfgFile = Join-Path $env:TEMP "tauri.build.json"
# NSIS only: WiX light.exe needs ~8 minutes per language for a 1.4 GB payload
# with tens of thousands of files, and fails outright on the second pass.
[System.IO.File]::WriteAllText($cfgFile, '{"tauri":{"bundle":{"resources":["payload/**/*"],"targets":["nsis"]}}}')

# CI caches src-tauri/target, so a previous run's renamed installer is still
# sitting in the bundle directory. Left there it makes the lookup below match
# two files and the rename fail with "Cannot convert 'System.Object[]'".
$bundleDir = "src-tauri\target\release\bundle\nsis"
if (Test-Path $bundleDir) { Remove-Item -Recurse -Force $bundleDir }

tauri build --config $cfgFile

$nsis = Get-ChildItem -Path $bundleDir -Filter *.exe -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime | Select-Object -Last 1
if (-not $nsis) { throw "no installer produced; check the build output" }
# English installer filename; GitHub strips non-ASCII from release asset names.
$version = (Get-Content "src-tauri\tauri.conf.json" | ConvertFrom-Json).package.version
$enName = [string](Join-Path $nsis.DirectoryName "Scribe_${version}_x64-setup.exe")
Move-Item -Force $nsis.FullName $enName
Write-Host "OK  $enName"
Write-Host "Unsigned -- SmartScreen will warn on first launch."
