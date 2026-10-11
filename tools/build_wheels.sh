#!/bin/sh
# ---------------------------------------------------------------------------
# build_wheels.sh - build the manedpy sdist and the three platform wheels.
#
#   sh tools/build_wheels.sh /path/to/dir-with-maned-capi-tarballs [VERSION]
#
# The package is pure ctypes - there is nothing to compile. A "platform
# wheel" here is the pure wheel with the right libmaned_c staged into
# manedpy/_lib/ and the tag rewritten (python -m wheel tags), one wheel per
# capi target:
#
#   maned-capi-$V-universal-apple-darwin  -> macosx_11_0_universal2
#   maned-capi-$V-x86_64-unknown-linux-gnu  -> manylinux_2_35_x86_64
#   maned-capi-$V-aarch64-unknown-linux-gnu -> manylinux_2_35_aarch64
#
# (macOS 11.0 is the engine's deployment target; glibc 2.35 is the ubuntu
# 22.04 toolchain the Linux libraries are built with - PEP 600 tags.)
#
# The sdist is built FIRST, with _lib/ empty, so it never carries a binary:
# source installs rely on $MANEDPY_LIB, exactly like a checkout.
#
# The working tree is restored afterwards (the lib staging and the
# BUILT_AGAINST stamp are build-time state, never committed).
# ---------------------------------------------------------------------------
set -eu

CAPI_DIR=${1:?usage: build_wheels.sh <dir with maned-capi tarballs> [version] [capi-version]}
VERSION=${2:-$(sed -n 's/^version = "\(.*\)"/\1/p' "$(dirname "$0")/../pyproject.toml")}
# The ENGINE version the tarballs carry - the package version may run ahead
# of it (docs-only patch releases). BUILT_AGAINST is stamped with this.
CAPI_VERSION=${3:-$(ls "$CAPI_DIR" | sed -n 's/^maned-capi-\(.*\)-universal-apple-darwin.tar.gz$/\1/p' | head -1)}

cd "$(dirname "$0")/.."
[ -z "$(git status --porcelain)" ] || { echo "build_wheels.sh: tree is dirty; commit or stash first" >&2; exit 1; }

PY=${PYTHON:-.venv/bin/python}
[ -x "$PY" ] || PY=python3
"$PY" -m pip -q install --upgrade build wheel >/dev/null

rm -rf dist build ./*.egg-info
restore() { git checkout -q -- manedpy/_lib.py 2>/dev/null || true; rm -f manedpy/_lib/libmaned_c.*; }
trap restore EXIT

echo "== sdist (no binary)"
rm -f manedpy/_lib/libmaned_c.*
"$PY" -m build --sdist >/dev/null
tar tzf "dist/manedpy-$VERSION.tar.gz" | grep -q '_lib/libmaned_c' \
  && { echo "sdist carries a binary - refusing" >&2; exit 1; } || true

build_one() {
  target=$1; plat=$2; libname=$3
  tb="$CAPI_DIR/maned-capi-$CAPI_VERSION-$target.tar.gz"
  [ -f "$tb" ] || { echo "missing $tb" >&2; exit 1; }
  work=$(mktemp -d); tar xzf "$tb" -C "$work"
  rm -f manedpy/_lib/libmaned_c.*
  # -L: the Linux tarball ships a SONAME symlink chain; the loader opens
  # _lib/<canonical name> by absolute path, so bundle ONE real file.
  cp -L "$work/maned-capi-$CAPI_VERSION-$target/lib/$libname" "manedpy/_lib/$libname"
  sed -i.bak "s/^BUILT_AGAINST = None/BUILT_AGAINST = \"$CAPI_VERSION\"/" manedpy/_lib.py && rm manedpy/_lib.py.bak
  "$PY" -m build --wheel >/dev/null
  "$PY" -m wheel tags --platform-tag "$plat" --remove "dist/manedpy-$VERSION-py3-none-any.whl" >/dev/null
  git checkout -q -- manedpy/_lib.py
  rm -rf "$work"
  echo "   manedpy-$VERSION-py3-none-$plat.whl"
}

echo "== wheels"
build_one universal-apple-darwin      macosx_11_0_universal2  libmaned_c.dylib
build_one x86_64-unknown-linux-gnu    manylinux_2_35_x86_64   libmaned_c.so
build_one aarch64-unknown-linux-gnu   manylinux_2_35_aarch64  libmaned_c.so

echo "== dist/"
ls -l dist
