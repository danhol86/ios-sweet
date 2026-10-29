# Windows / WSL2 QEMU development

Status on **2026-10-29**: Real iOS 16.7.16 boots from a disk-backed
VirtIO HFS+ image, executes Apple launchd and starts many daemons
(including backboardd and securityd). The QEMU framebuffer renders the
Apple boot logo. **The iOS home screen has NOT been reached or verified.**
This is a development environment, not an established iPhone simulator.

## Prepared environment

- Windows 11 with WSL2 Ubuntu 24.04; QEMU 8.2.2.
- Kernel built with patch 0082-sweet-qemu-virtio-blk.patch by macOS Actions
  run 40924239864 in fork danhol86/ios-sweet. SHA256 of verified artifact:
  41c6b43b2f9303f23d8e20a65cfaa8b47230070a919101f24f59cfd7a3fe305d.
  Symbol _sweet_virtio_rootdev verified with llvm-nm.
- Kernel installed at xnu/out-qemu/kernel.development.sweet (gitignored).
- Official Apple iPhone X iOS 16.7.16 (20H392) OS, SystemOS, AppOS, and
  device-tree images extracted and CRC-checked. Proprietary Apple images are
  kept outside the repository.
- Full root HFS+ image at /home/ios-sweet-test/ios16-root-bulk.img (16 GiB
  virtual, ~12 GiB physical usage), includes dyld cache, SpringBoard,
  launchd and keybag; fsck.hfsplus confirms it is valid.

## Start the experimental desktop from Windows

In PowerShell:

~~~powershell
wsl -d Ubuntu-24.04 -- bash /mnt/c/Users/danho/Desktop/ios-sweet/tools/start-qemu-desktop.sh
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
SWEET_QEMU_SECONDS (default 1200), SWEET_QEMU_OUTPUT_BASE, and
SWEET_QEMU_CPUS (default 1).

**Safety:** The QEMU disk uses snapshot mode by default; guest writes are
discarded, protecting the verified source. Never use --write-disk on the
original image during experimental kernel testing.

## Confirmed tests

- tools/qemu-virtio-smoke.py IMAGE: VirtIO 2 MMIO device found at
  0x0a003e00, real HFS+ sector read matches source byte-for-byte; a
  temporary guest write/readback plus FLUSH succeeds; original image
  unchanged by snapshot mode.
- Live browser viewer returned real framebuffer PNG to both WSL and Windows
  HTTP clients (HTTP 200).
- Browser pointer POST /touch sent QMP input events to virtio-tablet-device
  (HTTP 204). QEMU event-queue test confirms EV_ABS X/Y, BTN_LEFT and EV_SYN.
  This is NOT proof that the iOS guest consumes touch yet.
- QEMU disk-based kernel with no unentitled_ios_sim_launch=1 boot arg
  reached launchd but panicked unexpectedly (CS_KILLED).
- After adding the required boot arg, launchd entered ondemand mode,
  multiple iOS daemons started, and a 100-second boot finished with
  **no kernel panic**; the longer graphical run drew an Apple logo.
  Project's earlier physical-phone boot history also documents the flag.

## In-progress kernel changes

- 0082: Disk-backed VirtIO BSD root rd=virtiodisk0 -- **compiled and booted**.
- 0083: Experimental VirtIO tablet -> sweet_hid_touch() input queue,
  and correct block FLUSH ioctl (DKIOCSYNCHRONIZE / DKIOCSYNCHRONIZECACHE).
  The host protocols are tested; the kernel patch is not validated by CI or
  a live boot until the next build.
- 0084: Optional QEMU SMP topology override. A two-CPU disposable-ramdisk
  test showed that the upstream kernel panics on QEMU's Aff0 MPIDRs
  (SweetCPU invalid topology). The override only applies with the
  sweet_qemu_smp=1 boot argument; one CPU remains the proven default until
  a rebuilt kernel is actually tested with multiple virtual CPUs.
- The original Redmi UFS and physical touch paths remain unchanged.

## Outstanding issues

1. Build patch 0083 on macOS; verify it was actually applied and compiled
   (not merely a green workflow). Verify input and disk FLUSH in QEMU.
2. Diagnose Apple's graphical service initialization. Backboardd repeatedly
   requests IOAcceleratorES but no GPU service exists in QEMU. The existing
   phone port uses CPU software rendering. A GUI home screen is not yet shown.
3. Verify the last boot stages, startup times and whether SpringBoard actually
   creates its framebuffer surface. Longer guest runs may be needed.
4. User interaction is conditional on iOS HID delivery, not merely QMP
   accepting tablet events.
5. Test the optional QEMU-only multicore topology patch before using
   SWEET_QEMU_CPUS greater than 1. The launcher refuses multicore when
   the kernel binary does not contain the new SMP boot-argument string.

Do not claim the project is a fully functional iOS simulator until a real
interactive SpringBoard and app launch have been demonstrated.
