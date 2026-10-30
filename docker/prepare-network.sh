#!/usr/bin/env bash
# Prepare ONLY the user's writable overlay, never their iOS source disk.
# This executes inside the ephemeral one-click Docker setup container.
set -euo pipefail
guest=/guest/ios.raw
overlay=/state/ios.qcow2
binary=/usr/local/share/iossweet-net-seed
original=/System/Library/CoreServices/ReportCrash
backup=/System/Library/CoreServices/ReportCrash.iossweet-original
export LIBGUESTFS_BACKEND=direct
export LIBGUESTFS_MEMSIZE=512

for f in "$guest" "$binary"; do
  [[ -f "$f" ]] || { echo "Missing input $f" >&2; exit 2; }
done
[[ -d /state && -w /state ]] || { echo 'Writable Docker state missing.' >&2; exit 2; }
if [[ ! -f "$overlay" ]]; then
  qemu-img create -f qcow2 -F raw -b "$guest" "$overlay"
fi
python3 - "$overlay" "$guest" <<'PY'
import json
import subprocess
import sys
info = json.loads(subprocess.check_output(
    ['qemu-img', 'info', '--output=json', sys.argv[1]], text=True))
if info.get('format') != 'qcow2' or info.get('backing-filename') != sys.argv[2]:
    sys.exit('Refusing overlay with an unexpected backing image: '+repr(info))
PY

read_guest() {
  guestfish --ro -a "$overlay" -m /dev/sda:/ "$@"
}

if ! backup_exists="$(read_guest is-file "$backup")"; then
  echo 'libguestfs could not open the iOS overlay; check the bundled Linux kernel.' >&2
  exit 3
fi
if [[ "$backup_exists" == "true" ]]; then
  if ! original_exists="$(read_guest is-file "$original")"; then
    echo 'Could not inspect the existing iOS network bootstrap.' >&2
    exit 3
  fi
  [[ "$original_exists" == "true" ]] || {
    echo 'Original ReportCrash missing; refusing incomplete image.' >&2; exit 3;
  }
  echo 'Existing iOS Sweet network bootstrap found.'
else
  if ! original_exists="$(read_guest is-file "$original")"; then
    echo 'Cannot inspect the iOS ReportCrash executable.' >&2
    exit 3
  fi
  [[ "$original_exists" == "true" ]] || {
    echo 'This image has no stock iOS 16 ReportCrash; cannot prepare network.' >&2
    exit 3
  }
  # Both changes are in the QCOW2 overlay only. Preserve the original Apple
  # executable at a second path so the wrapper execs it with original args.
  guestfish -a "$overlay" run : mount-options force,rw /dev/sda / \
    : cp "$original" "$backup" \
    : upload "$binary" "$original" \
    : chmod 0755 "$original"
fi

expected="$(sha256sum "$binary" | cut -d' ' -f1)"
observed="$(read_guest checksum sha256 "$original")"
[[ "$expected" == "$observed" ]] || {
  echo 'iOS bootstrap checksum mismatch; refusing to boot.' >&2
  exit 3
}
[[ "$(read_guest is-file "$backup")" == "true" ]] || {
  echo 'Original Apple ReportCrash was not preserved.' >&2; exit 3;
}
echo 'IOS_SWEET_NETWORK_READY: isolated guest overlay prepared; original Apple executable preserved.'
