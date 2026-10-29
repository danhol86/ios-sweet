# Windows / WSL2 QEMU development (experimental)

This is **not yet an iOS simulator**. The Redmi Note 10 Pro build runs on a physical device; QEMU has a working XNU kernel test harness but no established interactive iOS GUI.

## Environment used, 2026-10-29

- Windows 11 Pro, Intel Core Ultra 7 265KF, 32 GB RAM.
- Ubuntu 24.04 WSL2, QEMU 8.2.2, Python 3, LLVM.
- Public upstream macOS Actions kernel 39158169212, verified against SHA256SUMS (no kernel rebuild required for unmodified QEMU tests).
- Apple's genuine iPhone X iOS 16.7.16 (20H392) OS, SystemOS, and AppOS images; independently CRC checked. Apple artifacts and resulting images are deliberately ignored by git.
- Built a 16 GiB HFS+ disk with upstream startup tweaks; fsck.hfsplus -f -n reports OK.
- Kernel reached 'Process 1 exec of /sbin/launchd' using a disposable 64 MiB HFS+ ramdisk deliberately lacking that executable.

## Disk-backed experiment

xnu/patches/0082-sweet-qemu-virtio-blk.patch introduces a QEMU-only, explicitly opt-in VirtIO MMIO block root (rd=virtiodisk0). The physical Redmi UFS path is unchanged.

- Polls QEMU's VirtIO MMIO transports at 0x0a000000..0x0a003fff and locates block device ID 2, rather than assuming the first slot.
- Uses 512-byte logical sectors, a polled split ring and a 64 KiB bounce buffer. Supports reads and writes; guest writes are directed to QEMU's temporary snapshot by default.
- QEMU qtest confirmed the device at 0x0a003e00 with magic 0x74726976, ID 2.
- **This kernel driver is experimental.** Its presence in a patch is not proof that the kernel builds or that iOS reaches the home screen. Check the actual CI result and boot log before saying it works.

Use the high-memory Apple device tree so the guest has room for iOS userland:

~~~sh
cd /mnt/c/Users/danho/Desktop/ios-sweet
python3 tools/mkadt.py /home/ios-sweet-test/qemu-highmem.adt --qemu --highmem
python3 tools/mkpayload.py xnu/out/kernel.development.sweet \
    /home/ios-sweet-test/qemu-highmem.adt /home/ios-sweet-test/payload-qemu-disk.bin \
    --cmdline 'debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam rd=virtiodisk0 rootrw=1 launchd_unsecure_cache=1 ignition_level=1 wdt=-1 sweetfb_noconsole=0'
python3 tools/qemu-sweet.py /home/ios-sweet-test/payload-qemu-disk.bin \
    /home/ios-sweet-test/qemu-disk-test \
    --kernel xnu/out/kernel.development.sweet \
    --disk /home/ios-sweet-test/ios16-root-bulk.img --secs 120
~~~

**The kernel binary in these commands must have been rebuilt with patch 0082**; the upstream kernel artifact predates that patch and has no VirtIO root driver. QEMU defaults to snapshot=on so writes do not modify the verified HFS+ root. Only use --write-disk to persist writes when intentionally testing a disposable disk copy.

## Remaining work

1. Rebuild with patch 0082 on macOS runner and fix any patch/compile errors.
2. Test VirtIO detection, sector reading, HFS+ mount and launchd on the rebuilt kernel, with real framebuffer/log evidence.
3. Diagnose userspace failures (shared cache, initialization, virtual hardware). The sweet-root-tweaks.py run warned that its optional mobileactivationd system container was absent.
4. Implement live framebuffer presentation (VNC or web) plus an input channel that provides actual IOS HID touch and keys. The stock QEMU helper captures post-run PNGs; it cannot operate SpringBoard interactively.
5. Report reproducible results and do not confuse an XNU console framebuffer with the iOS home screen.

No requirement to run or modify a physical Redmi device for this experiment.