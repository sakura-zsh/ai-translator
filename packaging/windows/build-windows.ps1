# Build a Windows distributable (onedir) with PyInstaller.
# Usage:  powershell -ExecutionPolicy Bypass -File packaging\windows\build-windows.ps1
$ErrorActionPreference = "Stop"

$WinDir = $PSScriptRoot
$Root = Split-Path -Parent (Split-Path -Parent $WinDir)

Write-Host "==> Installing project dependencies and PyInstaller"
python -m pip install -r (Join-Path $Root "requirements.txt")
# No --upgrade: a forced upgrade hits the network on every build.
python -m pip install pyinstaller

Write-Host ""
Write-Host "==> Building (first build takes 5-15 minutes; later builds are faster)"
Write-Host "    Analysis + collecting Qt DLLs is the slow part. Don't close the window."
# No --clean: keeps PyInstaller's dependency-analysis cache, which makes
# rebuilds significantly faster. Delete packaging\windows\build manually
# if you ever need a fully cold build.
python -m PyInstaller --noconfirm `
  --distpath (Join-Path $WinDir "dist") `
  --workpath (Join-Path $WinDir "build") `
  (Join-Path $WinDir "ai-translator.spec")

Write-Host ""
Write-Host "==> Done. Output:"
Get-ChildItem (Join-Path $WinDir "dist") | Format-Table Name, LastWriteTime
Write-Host "Run:  packaging\windows\dist\ai-translator\ai-translator.exe"
Write-Host "Note: OCR mode requires tesseract.exe on PATH"
Write-Host "      (https://github.com/UB-Mannheim/tesseract/wiki)."

# ── Installer (Inno Setup) ───────────────────────────────────────
$IsccCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($Iscc) {
    Write-Host ""
    Write-Host "==> Building installer with Inno Setup"
    # pyproject.toml uses dynamic versioning (single source of truth: app/__init__.py)
    $Version = (Select-String -Path (Join-Path $Root "app\__init__.py") `
        -Pattern '^__version__\s*=\s*"(.+?)"').Matches[0].Groups[1].Value
    if (-not $Version) { throw "Could not read __version__ from app\__init__.py" }
    Write-Host "    Version: $Version"
    & $Iscc "/DAppVersion=$Version" (Join-Path $WinDir "ai-translator.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed with exit code $LASTEXITCODE" }
    Write-Host "Installer: packaging\windows\installer\ai-translator-setup-$Version.exe"
} else {
    Write-Warning "Inno Setup not found - skipped installer build."
    Write-Warning "Install with:  winget install JRSoftware.InnoSetup"
}
