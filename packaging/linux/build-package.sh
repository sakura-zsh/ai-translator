#!/usr/bin/env bash
# Build an Arch Linux package (.pkg.tar.zst) for ai-translator.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PKGDIR="$ROOT/packaging/linux"
PKGNAME="ai-translator"
PKGVER="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
TARBALL="${PKGNAME}-${PKGVER}.tar.gz"
STAGING="$PKGDIR/src-staging"

if [[ -z "$PKGVER" ]]; then
  echo "error: cannot read version from pyproject.toml" >&2
  exit 1
fi

# Keep PKGBUILD version in sync with pyproject.toml
sed -i "s/^pkgver=.*/pkgver=${PKGVER}/" "$PKGDIR/PKGBUILD"

echo "==> Preparing source tarball ${TARBALL}"
rm -rf "$STAGING"
mkdir -p "$STAGING/${PKGNAME}-${PKGVER}"

# Copy project files (exclude venv, caches, packaging build artifacts)
rsync -a \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='*.py[cod]' \
  --exclude='*.egg-info/' \
  --exclude='.pytest_cache/' \
  --exclude='.mypy_cache/' \
  --exclude='.ruff_cache/' \
  --exclude='.claude/' \
  --exclude='dist/' \
  --exclude='build/' \
  --exclude='packaging/pkg/' \
  --exclude='packaging/src/' \
  --exclude='packaging/src-staging/' \
  --exclude='packaging/linux/*.pkg.tar.*' \
  --exclude='packaging/linux/*.tar.gz' \
  --exclude='packaging/*/build/' \
  --exclude='packaging/*/dist/' \
  --exclude='packaging/*.log' \
  --exclude='.git/' \
  "$ROOT/" "$STAGING/${PKGNAME}-${PKGVER}/"

# Ensure packaging/ is present in the tarball for launcher + desktop entry
mkdir -p "$STAGING/${PKGNAME}-${PKGVER}/packaging/linux"
cp -a "$PKGDIR/ai-translator.desktop" "$STAGING/${PKGNAME}-${PKGVER}/packaging/linux/"
cp -a "$PKGDIR/ai-translator" "$STAGING/${PKGNAME}-${PKGVER}/packaging/linux/"
chmod 755 "$STAGING/${PKGNAME}-${PKGVER}/packaging/linux/ai-translator"

tar -C "$STAGING" -czf "$PKGDIR/$TARBALL" "${PKGNAME}-${PKGVER}"
rm -rf "$STAGING"

echo "==> Building package with makepkg"
cd "$PKGDIR"
rm -rf pkg src
# Runtime deps (e.g. pyside6) are not required to build a pure-Python package.
makepkg -f --noconfirm --nodeps

echo
echo "==> Done. Packages:"
ls -lh "$PKGDIR"/*.pkg.tar.* 2>/dev/null || true
echo
echo "Install with:"
echo "  sudo pacman -U $PKGDIR/${PKGNAME}-${PKGVER}-*.pkg.tar.zst"
