#!/usr/bin/env bash
# Build an Arch Linux package (.pkg.tar.zst) for ai-translator (Rust + Tauri v2).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PKGDIR="$ROOT/packaging/linux"
PKGNAME="ai-translator"
PKGVER="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/Cargo.toml" | head -1)"
TARBALL="${PKGNAME}-${PKGVER}.tar.gz"

if [[ -z "$PKGVER" ]]; then
  echo "error: cannot read version from Cargo.toml" >&2
  exit 1
fi

sed -i "s/^pkgver=.*/pkgver=${PKGVER}/" "$PKGDIR/PKGBUILD"

echo "==> Preparing source tarball ${TARBALL}"

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
STAGE_SRC="$STAGING/${PKGNAME}-${PKGVER}"
mkdir -p "$STAGE_SRC"

rsync -a \
  --exclude='target/' \
  --exclude='node_modules/' \
  --exclude='dist/' \
  --exclude='.pnpm-store/' \
  --exclude='src-tauri/target/' \
  --exclude='src-tauri/gen/schemas/' \
  --exclude='packaging/linux/pkg/' \
  --exclude='packaging/linux/src/' \
  --exclude='packaging/linux/*.pkg.tar.*' \
  --exclude='packaging/linux/*.tar.gz' \
  --exclude='packaging/windows/dist/' \
  --exclude='packaging/windows/build/' \
  --exclude='.git/' \
  "$ROOT/" "$STAGE_SRC/"

STAGE_SIZE_MIB="$(du -sm "$STAGE_SRC" | cut -f1)"
if (( STAGE_SIZE_MIB > 50 )); then
  echo "error: staged source is ${STAGE_SIZE_MIB} MiB (>50 MiB)." >&2
  exit 1
fi

tar -C "$STAGING" -czf "$PKGDIR/$TARBALL" "${PKGNAME}-${PKGVER}"
rm -rf "$STAGING"

echo "==> Building package with makepkg"
cd "$PKGDIR"
rm -rf pkg src
makepkg -f --noconfirm

echo
echo "==> Done. Packages:"
ls -lh "$PKGDIR"/*.pkg.tar.* 2>/dev/null || true
echo
echo "Install with:"
echo "  sudo pacman -U $PKGDIR/${PKGNAME}-${PKGVER}-*.pkg.tar.zst"
