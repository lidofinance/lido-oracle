#!/bin/sh
# Builds the blst (https://github.com/supranational/blst) Python bindings and drops the
# resulting `blst.py` + compiled extension into the active Python environment's
# site-packages, so `import blst` works like a normal dependency.
#
# Sources come from the vendor/blst submodule when it is checked out. When it is not —
# which happens whenever the image is built from a plain checkout, including pipelines
# living in other repositories — they are fetched at the pinned commit below instead, so
# the build does not depend on how the caller cloned this repo.
#
# Requires `swig` and a C++ compiler on PATH; `git` too when the submodule is absent.
set -eu

# Must match the gitlink in vendor/blst. Checked automatically below whenever git metadata
# is available, so the two cannot drift silently.
BLST_COMMIT="${BLST_COMMIT:-54e6e55674722fc2797ebb4bbb71b26d881eb4b8}"
BLST_URL="${BLST_URL:-https://github.com/supranational/blst}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR_DIR="$ROOT_DIR/vendor/blst"
BINDINGS_DIR="$VENDOR_DIR/bindings/python"

# Guard against the pin drifting away from the submodule. Only possible where the repo's
# git metadata is present — inside the image it is not, hence the pin. Ask git rather than
# testing for a .git directory: in worktrees and submodules .git is a file.
if command -v git >/dev/null 2>&1 && git -C "$ROOT_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    gitlink="$(git -C "$ROOT_DIR" ls-tree HEAD vendor/blst 2>/dev/null | awk '{print $3}')"
    if [ -n "$gitlink" ] && [ "$gitlink" != "$BLST_COMMIT" ]; then
        echo "BLST_COMMIT ($BLST_COMMIT) does not match the vendor/blst submodule ($gitlink)." >&2
        echo "Update the pin in $0 to keep container builds on the same sources." >&2
        exit 1
    fi
fi

if [ ! -f "$BINDINGS_DIR/run.me" ]; then
    echo "vendor/blst is not checked out; fetching blst at $BLST_COMMIT" >&2
    if ! command -v git >/dev/null 2>&1; then
        echo "git is required to fetch blst. Either install git, or check out submodules:" >&2
        echo "  git submodule update --init --recursive" >&2
        exit 1
    fi
    # Fetching the commit by hash makes the content self-verifying: git checks the object
    # hashes, so no separate checksum has to be maintained alongside the pin.
    rm -rf "$VENDOR_DIR"
    mkdir -p "$VENDOR_DIR"
    git -C "$VENDOR_DIR" init -q
    git -C "$VENDOR_DIR" remote add origin "$BLST_URL"
    git -C "$VENDOR_DIR" fetch -q --depth 1 origin "$BLST_COMMIT"
    git -C "$VENDOR_DIR" checkout -q FETCH_HEAD
    rm -rf "$VENDOR_DIR/.git"
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
