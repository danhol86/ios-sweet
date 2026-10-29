# Windows / WSL2 QEMU development

Status on **2026-10-29**: Real iOS 16.7.16 boots from a disk-backed
VirtIO HFS+ image, executes Apple launchd and starts many daemons
(including backboardd and securityd). The QEMU framebuffer renders the
Apple boot logo. **The iOS home screen has NOT been reached or verified.**
This is a development environment, not an established iPhone simulator.

## Prepared environment

- Windows 11 with WSL2 Ubuntu 24.04; QEMU 8.2.2.
- Validated kernel with patches 0082-0084: macOS Actions run 40929758672
  from fork danhol86/ios-sweet. Verified artifact SHA256:
  c9a41647b93febabc0408ac1ed7091c4a48846e1adab13040e0b6c6b873b4f4f.
  Symbols _sweet_virtio_rootdev and _sweet_virtio_input_init verified.
- Kernel saved at xnu/out-qemu-0084/kernel.development.sweet (gitignored).
  Older kernels are retained separately for regression testing.
- Official Apple iPhone X iOS 16.7.16 (20H392) OS, SystemOS, AppOS, and
  device-tree images extracted and CRC-checked. Proprietary Apple images are
  kept outside the repository.
- Full root HFS+ image at /home/ios-sweet-test/ios16-root-bulk.img (16 GiB
  virtual, ~12 GiB physical usage), includes dyld cache, SpringBoard,
  launchd and keybag; fsck.hfsplus confirms it is valid.

## Start the experimental desktop from Windows

In PowerShell:

~~~powershell
wsl -d Ubuntu-24.04 -- env SWEET_QEMU_KERNEL=/mnt/c/Users/danho/Desktop/ios-sweet/xnu/out-qemu-0084/kernel.development.sweet SWEET_QEMU_CPUS=4 bash /mnt/c/Users/danho/Desktop/ios-sweet/tools/start-qemu-desktop.sh
~~~

Open **http://127.0.0.1:8099/** in a Windows browser. The script starts ARM64
QEMU with the verified image attached through VirtIO and a separate local
browser framebuffer viewer. The viewer refreshes the actual guest framebuffer
through QMP. It listens on 127.0.0.1 only. Stop the command to end the VM
and viewer.

For kernel-console debugging instead of the Apple boot logo:

~~~powershell
wsl -d Ubuntu-24.04 -- env SWEET_QEMU_DEBUG_CONSOLE=1 SWEET_QEMU_SECONDS=180 bash /mnt/c/Users/danho/Desktop/ios-sweet/tools/start-qemu-desktop.sh
~~~

Environment overrides: SWEET_QEMU_KERNEL (kernel path as seen from WSL),
SWEET_QEMU_DISK (raw HFS+ image), SWEET_QEMU_PORT (default 8099),
SWEET_QEMU_SECONDS (default 1200), SWEET_QEMU_OUTPUT_BASE,
SWEET_QEMU_CPUS (default 1), SWEET_QEMU_SAMPLE (SpringBoard/backboardd names)
and SWEET_QEMU_OVERLAY (QCOW2 path).

**Safety:** The desktop launcher now defaults to a durable, writable
QCOW2 overlay at /home/ios-sweet-test/ios16-root-persistent.qcow2. Its backing
file remains the original verified read-only 16 GiB root, and the launcher
checks the backing file path/format before starting QEMU. Guest writes
persist across reboots **only in the overlay**. Set SWEET_QEMU_EPHEMERAL=1
to discard guest changes in an old-style snapshot test. Do not use
--write-disk on the original image.

## Confirmed tests

- tools/qemu-virtio-smoke.py IMAGE: VirtIO 2 MMIO device found at
  0x0a003e00, real HFS+ sector read matches source byte-for-byte; a
  temporary guest write/readback plus FLUSH succeeds; original image
  unchanged by snapshot mode.
- Live browser viewer returned real framebuffer PNG to both WSL and Windows
  HTTP clients (HTTP 200).
- Browser pointer POST /touch sent QMP input events to virtio-tablet-device
  (HTTP 204). The compiled 0083 driver consumed them inside the actual
  booted iOS kernel: "SWEET HID: touch 0 down at 539,1199" and matching
  touch-up. This proves the HID path but not SpringBoard interaction.
- QEMU disk-based kernel with no unentitled_ios_sim_launch=1 boot arg
  reached launchd but panicked unexpectedly (CS_KILLED).
- After adding the required boot arg, launchd entered ondemand mode,
  multiple iOS daemons started, and a 100-second boot finished with
  **no kernel panic**; the longer graphical run drew an Apple logo.
  Project's earlier physical-phone boot history also documents the flag.
- New 0083 build ran 125 seconds with no kernel panic. 0083 guest
  VirtIO driver and disk-FLUSH routines were applied and compiled by CI.
- Both 2-vCPU and 4-vCPU versions of 0084 completed XNU initialization,
  mounted disposable HFS+ test volume and reached the expected errno 2
  launchd lookup failure (the intentionally empty image lacks launchd).
- Four-vCPU real-iOS boot verified root HFS+ mount, SpringBoard and
  backboardd starts, and live guest logging under the persistent overlay.
- tools/qemu-console-log.py reads the kernel's 4 MiB console ring via QMP.
  The QEMU runner now saves run/console.txt automatically on normal exit,
  even with the Apple logo obscuring console text.

## In-progress kernel changes

- 0082: Disk-backed VirtIO BSD root rd=virtiodisk0 -- **compiled and booted**.
- 0083: VirtIO tablet -> sweet_hid_touch() input queue and block FLUSH
  ioctls: compiled, real guest disk/HID tested.
- 0084: QEMU-only SMP Aff0 topology and HVC PSCI conduit. Compiled and
  tested with two and four virtual CPUs. The Redmi's original Aff1/SMC path
  is unchanged; QEMU requires explicit sweet_qemu_smp=1 boot arg.
- 0085: QEMU-only call to the existing process stack sampler, to investigate
  why SpringBoard/backboardd remain on the Apple boot logo. Patch written,
  not yet compiled or verified.
- The original Redmi UFS and physical touch paths remain unchanged.

## Outstanding issues

1. Compile and validate the opt-in 0085 process sampler, obtain periodic
   SpringBoard/backboardd stack traces during the 4-vCPU graphical boot.
2. Diagnose Apple's graphical service initialization. Backboardd repeatedly
   requests IOAcceleratorES but no GPU service exists in QEMU. The existing
   phone port uses CPU software rendering. A GUI home screen is not yet shown.
3. Verify the last boot stages, startup times and whether SpringBoard actually
   creates its framebuffer surface. Longer guest runs may be needed.
4. The HID tap path works in-kernel; verify the user interface actually
   handles pointer actions once the Home screen appears.
5. The persistent overlay should be retained and inspected rather than
   rebuilding a clean root on each reboot. The source image is immutable.

Do not claim the project is a fully functional iOS simulator until a real
interactive SpringBoard and app launch have been demonstrated.
