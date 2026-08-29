# Build a Windows distributable (onedir) with PyInstaller.
# Usage:  powershell -ExecutionPolicy Bypass -File packaging\windows\build-windows.ps1
$ErrorActionPreference = "Stop"

$WinDir = $PSScriptRoot
$Root = Split-Path -Parent (Split-Path -Parent $WinDir)

Write-Host "==> Installing PyInstaller"
python -m pip install --upgrade pyinstaller

Write-Host "==> Building"
python -m PyInstaller --noconfirm --clean `
  --distpath (Join-Path $WinDir "dist") `
  --workpath (Join-Path $WinDir "build") `
  (Join-Path $WinDir "ai-translator.spec")

Write-Host ""
Write-Host "==> Done. Output:"
Get-ChildItem (Join-Path $WinDir "dist") | Format-Table Name, LastWriteTime
Write-Host "Run:  packaging\windows\dist\ai-translator\ai-translator.exe"
Write-Host "Note: OCR mode requires tesseract.exe on PATH"
Write-Host "      (https://github.com/UB-Mannheim/tesseract/wiki)."
