#!/bin/sh
# Builds the blst (https://github.com/supranational/blst) Python bindings from the
# vendor/blst git submodule and drops the resulting `blst.py` + compiled extension into the
# active Python environment's site-packages, so `import blst` works like a normal dependency.
#
# Requires `swig` and a C++ compiler on PATH.
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BINDINGS_DIR="$ROOT_DIR/vendor/blst/bindings/python"

if [ ! -f "$BINDINGS_DIR/run.me" ]; then
    echo "vendor/blst submodule is empty. Run: git submodule update --init" >&2
    exit 1
fi

# -fPIC is required to link libblst.a into the shared _blst extension. build.sh normally
# defaults CFLAGS to include it, but that default is skipped entirely if the CFLAGS env var is
# already set (e.g. this project's own reproducible-build CFLAGS) - pass it as an explicit
# extra flag instead, which build.sh always appends regardless of CFLAGS.
python3 "$BINDINGS_DIR/run.me" -fPIC

PURELIB="$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
PLATLIB="$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["platlib"])')"
cp "$BINDINGS_DIR"/blst.py "$PURELIB/"
cp "$BINDINGS_DIR"/_blst.*.so "$PLATLIB/"

echo "Installed blst.py into $PURELIB and the compiled extension into $PLATLIB"
