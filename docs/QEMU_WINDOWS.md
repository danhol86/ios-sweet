# Windows / WSL2 QEMU development

Status on **2026-10-29**: Real iOS 16.7.16 boots in QEMU on Windows
WSL2, displays a real iOS lock screen, accepts an upward swipe from
the Windows mouse, and unlocks to the home screen. Mouse clicks opened
**Settings**, **General**, **About**, and **Safari**. Safari's native
iOS keyboard accepted mouse taps to type the verified text "hello".
This is an **interactive experimental iOS environment**, not a complete
iPhone simulator. Mobile data, hardware-accelerated graphics, networking,
Apple account services, and arbitrary third-party IPA support are not
yet verified. The guest clock currently starts in 1969.

## Prepared environment

- Windows 11 with WSL2 Ubuntu 24.04; QEMU 8.2.2.
- Validated kernel with patches 0082-0084: macOS Actions run 40929758672
  from fork danhol86/ios-sweet. Verified artifact SHA256:
  c9a41647b93febabc0408ac1ed7091c4a48846e1adab13040e0b6c6b873b4f4f.
  Symbols _sweet_virtio_rootdev and _sweet_virtio_input_init verified.
- Kernel saved at xnu/out-qemu-0084/kernel.development.sweet (gitignored).
  Older kernels are retained separately for regression testing.
- **Interactive GUI kernel:** xnu/out-qemu-0086/kernel.development.sweet,
  built by macOS 15 CI run 40938913078; SHA256
  f5bb5cc5846d04aec986e0232d88540c875c83331857be5cb0ce004e678fbbf5.
  Verified 4-vCPU, VirtIO disk/touchscreen, live SpringBoard and app input.
- Official Apple iPhone X iOS 16.7.16 (20H392) OS, SystemOS, AppOS, and
  device-tree images extracted and CRC-checked. Proprietary Apple images are
  kept outside the repository.
- Full root HFS+ image at /home/ios-sweet-test/ios16-root-bulk.img (16 GiB
  virtual, ~12 GiB physical usage), includes dyld cache, SpringBoard,
  launchd and keybag; fsck.hfsplus confirms it is valid.

## Start the experimental desktop from Windows

On this prepared Windows computer, **double-click**
C:\Users\danho\Desktop\iOS Sweet (Windows).lnk, or use PowerShell:

~~~powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\Users\danho\Desktop\ios-sweet\tools\Start-IosSweet-Windows.ps1' -WorkingGuest
~~~

The -WorkingGuest option uses a **locally prepared, private test disk**
with an experimental user-space compatibility workaround and a
separate persistent QCOW2 overlay. The untouched IPSW and original
baseline overlay are not changed. **This working disk is NOT committed to
Git and must be rebuilt from your own Apple software files on another
machine.**

The Windows launcher starts the Linux VM, opens the framebuffer viewer,
and reuses an existing running viewer without starting a second VM on
the same disk. Default runtime is 7200 seconds. Use -Seconds 600 to
shorten it, or -Ephemeral to discard changes.
For gestures, drag the mouse on the displayed phone. **To return Home,
start at the very bottom white home-indicator bar (about 99.8 percent
down the frame) and drag upward**; starting a little higher just
scrolls the app. A "Swipe up / Home" convenience control has been
added to the browser viewer.
If Windows execution policy blocks the script, launch it explicitly with
the per-command powershell -ExecutionPolicy Bypass -File option rather
than changing machine-wide settings.

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
SWEET_QEMU_CPUS (default 1), SWEET_QEMU_SAMPLE (process names),
SWEET_QEMU_ADT (optional device-tree override), and
SWEET_QEMU_OVERLAY (QCOW2 path). The PowerShell launcher also accepts
explicit -Disk and -Overlay paths in place of -WorkingGuest.

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
- Browser pointer POST /touch sends QMP VirtIO tablet events (HTTP 204).
  In the 0086 interactive guest, iOS logged down at 539,2243 and up at
  539,623 for an upward mouse swipe. That gesture successfully unlocked
  the real lock screen to SpringBoard's app-icon home screen.
- Windows mouse taps opened the stock Settings app; additional taps
  navigated to General and About. The About page visibly reported
  **iOS 16.7.16** and **iPhone X** (17 GB virtual capacity).
- A full bottom-edge home swipe returned from Settings to the app-icon
  home screen. Safari displayed its Favorites page and native keyboard;
  mouse taps successfully typed "hello" into its search field.
- Screenshots were captured from the live QMP-backed 1125x2436 guest
  framebuffer. The working guest also survives restarts via its local
  private QCOW2 overlay. No GPU passthrough, hardware acceleration,
  Apple account or Wi-Fi connectivity is implied by these tests.
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
- In the unmodified baseline, SpringBoard and backboardd were started
  but the GUI remained at the Apple boot logo. Datamigrator exited
  normally (exit code 0); that original baseline remains preserved.
- Separate isolated HFS+ clone test seeded mobileactivationd's missing
  -ActivationState and -DataMigrationCompleted values, verified with
  fsck.hfsplus. The final framebuffer remained at the Apple logo, so
  these flags were NOT applied to the baseline.
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
- 0085: QEMU-only kernel process sampler, compiled by macOS 15 run
  40935552043 and tested in a live guest to capture SpringBoard, lsd
  and MobileGestaltHelper user-space stacks.
- 0086: Configurable sampler delays and 4-vCPU guest support;
  macOS 15 build 40938913078 is successful. SHA256 of verified kernel:
  f5bb5cc5846d04aec986e0232d88540c875c83331857be5cb0ce004e678fbbf5.
  This is the validated **interactive Windows iOS guest kernel**.

## Most recent iOS startup investigation

The 0085 kernel process sampler repeatedly showed SpringBoard stalled in
LaunchServices initialization, and lsd stalled in database seeding.
Symbolication against the **exact iOS 16.7.16 dyld cache** found the
backtrace from lsd into InstalledContentLibrary's
_GenerateBuiltInAppInstallSessionID. This function requests MobileGestalt
key UniqueDeviceID (obfuscated string re6Zb+zwFKJNlkQTUeT+/w).
The requesting worker is blocked in a libMobileGestalt semaphore wait,
while lsd's seeding thread waits for completion and SpringBoard waits for
lsd's database. The root directory /private/var/db/lsd remained empty.
Neither a GPU warning nor a disk I/O error is established as the cause.
Disassembly confirms that the Requested MobileGestalt question is
UniqueDeviceID, the key hashed as re6Zb+zwFKJNlkQTUeT+/w, from
InstalledContentLibrary's built-in-app identity generation. The lsd worker
blocks in libMobileGestalt while its other worker waits for the database
seeding group. Do not supply the user's real hardware identifier in any
synthetic guest or put proprietary images into Git.

The sampler confirmed MobileGestaltHelper was live but idle in its
Mach event loop while lsd repeatedly waited for a UniqueDeviceID
answer. A synthetic /chosen/unique-device-id, synthetic serial-number,
and creating the missing MobileGestalt cache group did not resolve it.

**Isolated proof of concept only:** In a separately copied iOS root
(never in the original image or the baseline overlay) the ARM64 call
to MGCopyAnswer from InstalledContentLibrary's
GenerateBuiltInAppInstallSessionID was replaced with a local nil-return
instruction. That allowed LaunchServices to progress through app
installation seeding, MobileContainerManager and UserManagement calls.
After its persistent overlay settled, the real iOS lock screen, home
screen, stock Settings and in-app navigation all became interactive.

The patched image stays ONLY at
/home/ios-sweet-test/ios16-mgcall-test.raw and its writable state at
/home/ios-sweet-test/ios16-mgcall-overlay.qcow2 on the owner's computer.
**Never commit, distribute, or advertise the patched Apple image as
part of this repository.** The proper future engineering goal is a
faithful MobileGestalt identity/XPC implementation so unmodified
user-space code also reaches SpringBoard.
- The original Redmi UFS and physical touch paths remain unchanged.

## Outstanding issues

1. Replace the local MobileGestalt-call workaround with proper device
   identity and XPC communication while keeping the Apple userland intact.
2. Improve boot time, add a working real-time clock (guest date starts
   in 1969), and verify reliable suspend/resume and shutdown.
3. Explore guest keyboard input, in-app text editing, networking/Wi-Fi,
   audio, notifications, and third-party app installation separately.
4. QEMU graphics are currently software-rendered and may remain slow;
   no hardware GPU emulation or full iOS developer simulator is proven.
5. Preserve the verified original HFS+ image and untouched baseline
   overlay. Keep Apple firmware, caches and user-specific data off Git.
