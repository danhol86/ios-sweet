#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  --check)
    command -v qemu-system-aarch64
    command -v llvm-nm
    python3 /app/tools/qemu-sweet.py --check-env
    echo 'Docker QEMU environment verified; no guest was started.'
    exit 0 ;;
esac
kernel="${SWEET_QEMU_KERNEL:-/guest/kernel.development.sweet}"
disk="${SWEET_QEMU_DISK:-/guest/ios.raw}"
overlay="${SWEET_QEMU_OVERLAY:-/state/ios.qcow2}"
for f in "$kernel" "$disk" "${SWEET_QEMU_PRODUCT_ADT:-/guest/d22ap.adt}"; do
  if [[ ! -f "$f" ]]; then
    echo "Missing required user-provided file: $f" >&2
    exit 2
  fi
done
if [[ ! -d /state || ! -w /state ]]; then
  echo 'The /state directory must exist and be writable.' >&2
  exit 2
fi
export SWEET_QEMU_KERNEL="$kernel" SWEET_QEMU_DISK="$disk" SWEET_QEMU_OVERLAY="$overlay"
export SWEET_QEMU_VIEWER_HOST="0.0.0.0"
export SWEET_QEMU_PORT="${SWEET_QEMU_PORT:-8099}"
export SWEET_QEMU_OUTPUT_BASE="${SWEET_QEMU_OUTPUT_BASE:-/state}"
export SWEET_QEMU_LOG_FLAGS="${SWEET_QEMU_LOG_FLAGS:-guest_errors,unimp}"
exec bash /app/tools/start-qemu-desktop.sh
