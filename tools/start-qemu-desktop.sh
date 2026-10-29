#!/usr/bin/env bash
# Run the experimental iOS SWEET XNU build via WSL2 and expose its framebuffer
# on Windows localhost. This does not imply SpringBoard or HID works yet.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
kernel="$(printenv SWEET_QEMU_KERNEL || true)"
disk="$(printenv SWEET_QEMU_DISK || true)"
overlay="$(printenv SWEET_QEMU_OVERLAY || true)"
ephemeral="$(printenv SWEET_QEMU_EPHEMERAL || true)"
port="$(printenv SWEET_QEMU_PORT || true)"
seconds="$(printenv SWEET_QEMU_SECONDS || true)"
cpus="$(printenv SWEET_QEMU_CPUS || true)"
debug_console="$(printenv SWEET_QEMU_DEBUG_CONSOLE || true)"
sample="$(printenv SWEET_QEMU_SAMPLE || true)"
sample_delay="$(printenv SWEET_QEMU_SAMPLE_DELAY || true)"
sample_interval="$(printenv SWEET_QEMU_SAMPLE_INTERVAL || true)"
base="$(printenv SWEET_QEMU_OUTPUT_BASE || true)"
[[ -n "$kernel" ]] || kernel="$repo/xnu/out-qemu/kernel.development.sweet"
[[ -n "$disk" ]] || disk="/home/ios-sweet-test/ios16-root-bulk.img"
[[ -n "$overlay" ]] || overlay="/home/ios-sweet-test/ios16-root-persistent.qcow2"
[[ -n "$ephemeral" ]] || ephemeral="0"
[[ -n "$port" ]] || port="8099"
[[ -n "$seconds" ]] || seconds="1200"
[[ -n "$cpus" ]] || cpus="1"
[[ -n "$debug_console" ]] || debug_console="0"
[[ -n "$sample" ]] || sample="SpringBoard,backboardd,datamigrator"
[[ -n "$sample_delay" ]] || sample_delay="12"
[[ -n "$sample_interval" ]] || sample_interval="25"
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
disk_args=(--disk "$disk")
if [[ "$ephemeral" != "1" ]]; then
    command -v qemu-img >/dev/null || { echo "Missing qemu-img" >&2; exit 2; }
    mkdir -p "$(dirname "$overlay")"
    if [[ ! -e "$overlay" ]]; then
        qemu-img create -f qcow2 -F raw -b "$disk" "$overlay"
    fi
    disk_args+=(--overlay "$overlay")
fi
if ! llvm-nm --defined-only "$kernel" | grep 'sweet_virtio_rootdev' > /dev/null; then
    echo "This kernel does not contain the experimental VirtIO root driver." >&2
    exit 2
fi
if [[ "$cpus" != "1" ]] && ! grep -a -q 'sweet_qemu_smp' "$kernel"; then
    echo "This kernel lacks the QEMU SMP topology patch; set SWEET_QEMU_CPUS=1." >&2
    exit 2
fi
mkdir -p "$run"
python3 "$repo/tools/mkadt.py" "$run/qemu.adt" --qemu --highmem "--qemu-cpus=$cpus"
fbarg="sweetfb_noconsole=1"
if [[ "$debug_console" == "1" ]]; then
    fbarg="sweetfb_noconsole=0"
fi
smp_flag=""
if [[ "$cpus" != "1" ]]; then
    smp_flag="sweet_qemu_smp=1"
fi
python3 "$repo/tools/mkpayload.py" "$kernel" "$run/qemu.adt" "$run/payload.bin" \
    --cmdline "debug=0xc serial=3 cpus=$cpus keepsyms=1 -enable_kprintf_spam -noprogress rd=virtiodisk0 unentitled_ios_sim_launch=1 rootrw=1 launchd_unsecure_cache=1 ignition_level=1 wdt_test=no_user_checkin wdt=-1 sweetsample=$sample sweetsample_delay=$sample_delay sweetsample_interval=$sample_interval $fbarg $smp_flag"

python3 "$repo/tools/qemu-live-screen.py" "$run" --enable-input --port "$port" > "$run/viewer.log" 2>&1 &
viewer_pid=$!
cleanup() {
    kill "$viewer_pid" 2>/dev/null || true
    wait "$viewer_pid" 2>/dev/null || true
}
trap cleanup EXIT
echo "Starting experimental iOS XNU; live display at http://127.0.0.1:$port"
if [[ "$ephemeral" == "1" ]]; then
    echo "QEMU ephemeral snapshot; all guest filesystem changes will be discarded."
else
    echo "Guest writes persist in QCOW2 overlay: $overlay"
    echo "The original verified iOS image remains unchanged."
fi
echo "QEMU logs and framebuffer: $run"
echo "Browser sends VirtIO tablet events; iOS touchscreen functionality remains experimental."
python3 "$repo/tools/qemu-sweet.py" "$run/payload.bin" "$run" \
    --kernel "$kernel" "${disk_args[@]}" --tablet --cpus "$cpus" \
    --secs "$seconds" --live-serial
