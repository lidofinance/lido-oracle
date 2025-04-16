#!/bin/env sh

set -eu

/usr/local/bin/_pin-cids || echo "Failed to bootstrap CIDs! Some content can be not available locally (offline)."
