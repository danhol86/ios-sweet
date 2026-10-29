#!/usr/bin/env bash
# Run the experimental iOS SWEET XNU build via WSL2 and expose its framebuffer
# on Windows localhost. This does not imply SpringBoard or HID works yet.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
kernel="$(printenv SWEET_QEMU_KERNEL || true)"
disk="$(printenv SWEET_QEMU_DISK || true)"
port="$(printenv SWEET_QEMU_PORT || true)"
seconds="$(printenv SWEET_QEMU_SECONDS || true)"
debug_console="$(printenv SWEET_QEMU_DEBUG_CONSOLE || true)"
base="$(printenv SWEET_QEMU_OUTPUT_BASE || true)"
[[ -n "$kernel" ]] || kernel="$repo/xnu/out-qemu/kernel.development.sweet"
[[ -n "$disk" ]] || disk="/home/ios-sweet-test/ios16-root-bulk.img"
[[ -n "$port" ]] || port="8099"
[[ -n "$seconds" ]] || seconds="1200"
[[ -n "$debug_console" ]] || debug_console="0"
[[ -n "$base" ]] || base="/home/ios-sweet-test"
run="$base/desktop-qemu-$(date -u +%Y%m%d-%H%M%S)"

if [[ ! -f "$kernel" ]]; then
    echo "Missing rebuilt VirtIO kernel: $kernel" >&2
    echo "Fetch a kernel built with patches 0082 (disk) and 0083 (tablet) first." >&2
    exit 2
fi
if [[ ! -f "$disk" ]]; then
    echo "Missing verified 16 GiB HFS+ image: $disk" >&2
    exit 2
fi
for tool in qemu-system-aarch64 llvm-nm python3; do
    command -v "$tool" >/dev/null || { echo "Missing $tool" >&2; exit 2; }
done
if ! llvm-nm --defined-only "$kernel" | grep 'sweet_virtio_rootdev' > /dev/null; then
    echo "This kernel does not contain the experimental VirtIO root driver." >&2
    exit 2
fi
mkdir -p "$run"
python3 "$repo/tools/mkadt.py" "$run/qemu.adt" --qemu --highmem
fbarg="sweetfb_noconsole=1"
if [[ "$debug_console" == "1" ]]; then
    fbarg="sweetfb_noconsole=0"
fi
python3 "$repo/tools/mkpayload.py" "$kernel" "$run/qemu.adt" "$run/payload.bin" \
    --cmdline "debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress rd=virtiodisk0 unentitled_ios_sim_launch=1 rootrw=1 launchd_unsecure_cache=1 ignition_level=1 wdt_test=no_user_checkin wdt=-1 $fbarg"

python3 "$repo/tools/qemu-live-screen.py" "$run" --enable-input --port "$port" > "$run/viewer.log" 2>&1 &
viewer_pid=$!
cleanup() {
    kill "$viewer_pid" 2>/dev/null || true
    wait "$viewer_pid" 2>/dev/null || true
}
trap cleanup EXIT
echo "Starting experimental iOS XNU; live display at http://127.0.0.1:$port"
echo "QEMU disk snapshot is enabled; the original image is not modified."
echo "QEMU logs and framebuffer: $run"
echo "Browser sends tablet events, but iOS touchscreen requires guest HID support."
python3 "$repo/tools/qemu-sweet.py" "$run/payload.bin" "$run" \
    --kernel "$kernel" --disk "$disk" --tablet \
    --secs "$seconds" --live-serial
