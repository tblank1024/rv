#!/usr/bin/env bash
# Pin the rvc2mqtt build context (fork of linuxkidd/rvc-monitor-py) to a known
# commit so image rebuilds are reproducible. Run before `docker compose build`
# on a fresh checkout, or any time to verify the pin.
#
# Override the location with RVC_MONITOR_DIR (same variable compose uses).
set -euo pipefail

REPO_URL="https://github.com/tblank1024/rvc-monitor-py.git"
PINNED_COMMIT="0ad119d801bedd7706e3154cacca596c397e721e"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIR="${RVC_MONITOR_DIR:-$SCRIPT_DIR/../../../linuxkidd/rvc-monitor-py}"

if [ ! -d "$DIR/.git" ]; then
    echo "Cloning $REPO_URL at $PINNED_COMMIT into $DIR"
    git clone "$REPO_URL" "$DIR"
    git -C "$DIR" checkout --quiet "$PINNED_COMMIT"
    exit 0
fi

HEAD="$(git -C "$DIR" rev-parse HEAD)"
if [ "$HEAD" != "$PINNED_COMMIT" ]; then
    echo "WARNING: $DIR is at ${HEAD:0:7}, pinned commit is ${PINNED_COMMIT:0:7}."
    echo "         The next rvc2mqtt build will not be reproducible."
    echo "         Either 'git -C $DIR checkout $PINNED_COMMIT' or update"
    echo "         PINNED_COMMIT in this script after testing."
    exit 1
fi

if [ -n "$(git -C "$DIR" status --porcelain)" ]; then
    echo "WARNING: $DIR has uncommitted changes; rvc2mqtt builds will include them."
    exit 1
fi

echo "rvc-monitor-py OK at pinned commit ${PINNED_COMMIT:0:7}"
