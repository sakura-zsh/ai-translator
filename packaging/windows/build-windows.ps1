# Build Windows Tauri installer + native CLI binary
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location $Root
try {
    pnpm install --allow-build esbuild
    pnpm tauri build
    cargo build --release -p ai-translator-cli
    Write-Host "GUI bundle: $Root\target\release\bundle"
    Write-Host "CLI binary: $Root\target\release\ai-translator-cli.exe"
} finally {
    Pop-Location
}
