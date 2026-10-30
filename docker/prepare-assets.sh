#!/bin/bash
# Only run via the installer, one disposable privileged container at a time.
set -euo pipefail
# Only the full HFSX firmware assembly mounts APFS/FUSE volumes. Kernel
# downloads, checksum verification, and local one-instruction patching do not
# need a privileged Docker container or an extra WSL distro.
mode=full
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
  if [[ "${args[$i]}" == --mode && $((i+1)) -lt ${#args[@]} ]]; then
    mode="${args[$((i+1))]}"
  elif [[ "${args[$i]}" == --mode=* ]]; then
    mode="${args[$i]#--mode=}"
  fi
done
if [[ "$mode" == full ]]; then
  test -c /dev/fuse || { echo 'FUSE is unavailable: Docker Desktop Linux container must use --privileged.' >&2; exit 20; }
fi
test -d /assets && test -w /assets || { echo '/assets must be a writable private local bind mount.' >&2; exit 21; }
exec /usr/bin/python3 /usr/local/share/iossweet-tools/AutoPrepare-IosSweet.py "$@"
