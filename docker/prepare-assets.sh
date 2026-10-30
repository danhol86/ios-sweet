#!/bin/bash
# Only run via the installer, one disposable privileged container at a time.
set -euo pipefail
test -c /dev/fuse || { echo 'FUSE is unavailable: Docker Desktop Linux container must use --privileged.' >&2; exit 20; }
test -d /assets && test -w /assets || { echo '/assets must be a writable private local bind mount.' >&2; exit 21; }
exec /usr/bin/python3 /usr/local/share/iossweet-tools/AutoPrepare-IosSweet.py "$@"
