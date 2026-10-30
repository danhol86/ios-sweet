#!/usr/bin/env bash
# Run experimental iOS SWEET XNU through QEMU inside Docker (or a Linux host).
# The Windows launcher uses Docker; a standalone WSL Ubuntu distro is not needed.
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
network="$(printenv SWEET_QEMU_NETWORK || true)"
necp_trace="$(printenv SWEET_QEMU_NECP_TRACE || true)"
adt_override="$(printenv SWEET_QEMU_ADT || true)"
sample="$(printenv SWEET_QEMU_SAMPLE || true)"
sample_delay="$(printenv SWEET_QEMU_SAMPLE_DELAY || true)"
sample_interval="$(printenv SWEET_QEMU_SAMPLE_INTERVAL || true)"
base="$(printenv SWEET_QEMU_OUTPUT_BASE || true)"
viewer_host="$(printenv SWEET_QEMU_VIEWER_HOST || true)"
qemu_log="$(printenv SWEET_QEMU_LOG_FLAGS || true)"
[[ -n "$kernel" ]] || kernel="$repo/xnu/out-qemu/kernel.development.sweet"
[[ -n "$disk" ]] || disk="/home/ios-sweet-test/ios16-root-bulk.img"
[[ -n "$overlay" ]] || overlay="/home/ios-sweet-test/ios16-root-persistent.qcow2"
[[ -n "$ephemeral" ]] || ephemeral="0"
[[ -n "$port" ]] || port="8099"
[[ -n "$seconds" ]] || seconds="1200"
[[ -n "$cpus" ]] || cpus="1"
[[ -n "$debug_console" ]] || debug_console="0"
[[ -n "$network" ]] || network="0"
[[ -n "$necp_trace" ]] || necp_trace="0"
# XNU proc_name uses MAXCOMLEN=16: MobileGestaltHelper is
# "MobileGestaltHel" in the process sampler. Use its truncated name.
[[ -n "$sample" ]] || sample="SpringBoard,lsd,MobileGestaltHel,backboardd"
[[ -n "$sample_delay" ]] || sample_delay="12"
[[ -n "$sample_interval" ]] || sample_interval="25"
[[ -n "$base" ]] || base="/home/ios-sweet-test"
[[ -n "$viewer_host" ]] || viewer_host="127.0.0.1"
[[ -n "$qemu_log" ]] || qemu_log="int,guest_errors,unimp"
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
if [[ -n "$adt_override" ]]; then
    [[ -f "$adt_override" ]] || { echo "QEMU ADT override is missing: $adt_override" >&2; exit 2; }
    cp "$adt_override" "$run/qemu.adt"
    echo "Using experimental device-tree override: $adt_override"
else
    python3 "$repo/tools/mkadt.py" "$run/qemu.adt" --qemu --highmem "--qemu-cpus=$cpus"
fi
fbarg="sweetfb_noconsole=1"
if [[ "$debug_console" == "1" ]]; then
    fbarg="sweetfb_noconsole=0"
fi
smp_flag=""
if [[ "$cpus" != "1" ]]; then
    smp_flag="sweet_qemu_smp=1"
fi
network_delegate_flag=""
if [[ "$network" == "1" ]]; then
    # Only the opt-in QEMU networking kernel grants socket delegation.
    network_delegate_flag="sweet_qemu_network_delegate=1 sweet_qemu_network_trace=1"
    if [[ "$necp_trace" == "1" ]]; then
        network_delegate_flag="$network_delegate_flag sweet_qemu_necp_trace=1"
    fi
fi
python3 "$repo/tools/mkpayload.py" "$kernel" "$run/qemu.adt" "$run/payload.bin" \
    --cmdline "debug=0xc serial=3 cpus=$cpus keepsyms=1 -enable_kprintf_spam -noprogress rd=virtiodisk0 unentitled_ios_sim_launch=1 rootrw=1 launchd_unsecure_cache=1 ignition_level=1 wdt_test=no_user_checkin wdt=-1 sweetsample=$sample sweetsample_delay=$sample_delay sweetsample_interval=$sample_interval $fbarg $smp_flag $network_delegate_flag"

python3 "$repo/tools/qemu-live-screen.py" "$run" --enable-input --host "$viewer_host" --port "$port" > "$run/viewer.log" 2>&1 &
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
net_args=()
if [[ "$network" == "1" ]]; then
    if ! llvm-nm --defined-only "$kernel" | grep 'sweet_virtio_net_init' > /dev/null; then
        echo "Kernel lacks VirtIO Ethernet; guest internet remains unavailable." >&2
        exit 2
    fi
    net_args+=(--network)
fi
python3 "$repo/tools/qemu-sweet.py" "$run/payload.bin" "$run" \
    --kernel "$kernel" "${disk_args[@]}" --tablet "${net_args[@]}" --cpus "$cpus" \
    --secs "$seconds" --qemu-log "$qemu_log" --live-serial
