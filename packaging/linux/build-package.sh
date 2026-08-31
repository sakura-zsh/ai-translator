#!/usr/bin/env bash
# Build an Arch Linux package (.pkg.tar.zst) for ai-translator.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PKGDIR="$ROOT/packaging/linux"
PKGNAME="ai-translator"
PKGVER="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
TARBALL="${PKGNAME}-${PKGVER}.tar.gz"

if [[ -z "$PKGVER" ]]; then
  echo "error: cannot read version from pyproject.toml" >&2
  exit 1
fi

# Keep PKGBUILD version in sync with pyproject.toml
sed -i "s/^pkgver=.*/pkgver=${PKGVER}/" "$PKGDIR/PKGBUILD"

echo "==> Preparing source tarball ${TARBALL}"

# Stage OUTSIDE the source tree. The old in-repo staging dir
# (packaging/linux/src-staging) sat inside the rsync source and, once its
# exclude pattern turned out to be wrong, rsync copied the staging dir
# into itself — recursively — until 22GB were burned before an interrupt.
# mktemp + trap makes self-recursion structurally impossible and leaves
# no leftovers behind.
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
STAGE_SRC="$STAGING/${PKGNAME}-${PKGVER}"
mkdir -p "$STAGE_SRC"

# Copy project files (exclude venv, caches, packaging build artifacts).
# Exclude paths are relative to $ROOT.
rsync -a \
  --exclude='.venv/' \
  --exclude='.testlibs/' \
  --exclude='__pycache__/' \
  --exclude='*.py[cod]' \
  --exclude='*.egg-info/' \
  --exclude='.pytest_cache/' \
  --exclude='.mypy_cache/' \
  --exclude='.ruff_cache/' \
  --exclude='.claude/' \
  --exclude='dist/' \
  --exclude='build/' \
  --exclude='packaging/linux/pkg/' \
  --exclude='packaging/linux/src/' \
  --exclude='packaging/linux/src-staging/' \
  --exclude='packaging/linux/*.pkg.tar.*' \
  --exclude='packaging/linux/*.tar.gz' \
  --exclude='packaging/*/build/' \
  --exclude='packaging/*/dist/' \
  --exclude='packaging/*.log' \
  --exclude='.git/' \
  "$ROOT/" "$STAGE_SRC/"

# Safety fuse: the staged source of this pure-Python project is ~1MB.
# Anything larger means junk is leaking into the tarball — fail loudly
# instead of packaging it (this exact bug once grew to 22GB silently).
STAGE_SIZE_MIB="$(du -sm "$STAGE_SRC" | cut -f1)"
if (( STAGE_SIZE_MIB > 50 )); then
  echo "error: staged source is ${STAGE_SIZE_MIB} MiB (>50 MiB)." \
       "Something is being copied that should be excluded." >&2
  exit 1
fi

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
