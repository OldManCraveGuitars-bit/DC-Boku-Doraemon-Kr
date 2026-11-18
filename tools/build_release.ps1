$ErrorActionPreference = 'Stop'
$releaseRoot = Split-Path -Parent $PSScriptRoot
$payload = Join-Path $releaseRoot 'payload'
$licenses = Join-Path $releaseRoot 'licenses'
$versionFile = Join-Path $releaseRoot 'patcher\version_info.txt'
Push-Location $releaseRoot
try {
    python -m PyInstaller --noconfirm --clean --onefile --windowed `
      --name DC-Boku-Doraemon-Kr-v0.8-Patcher `
      --version-file $versionFile `
      --add-data "$payload;payload" --add-data "$licenses;licenses" `
      --distpath dist --workpath build/pyinstaller --specpath build patcher/patcher.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
} finally { Pop-Location }
