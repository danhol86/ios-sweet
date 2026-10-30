# iOS Sweet: Windows and Docker deployment

**Status (2026-10-30):** the iOS GUI boots on this test machine via WSL2; an
experimental Docker/QEMU container also boots the real interactive iOS 16
home screen with private guest media mounted
read-only. This is NOT a complete iOS simulator. Safari internet connectivity
remains unverified and currently fails in the tested native-WSL kernel.

## What a deployable package can and cannot include

The source code, launcher, Dockerfile, Compose configuration and open-source
rebuilt SWEET kernel can be distributed. The **iOS operating system disk** must
come from the user's own legitimately obtained Apple software and needs the
existing experimental iPhone X / iOS 16.7.16 preparation workflow. A private
extracted `d22ap.adt` device tree from the matching IPSW is **also required**;
the interactive installers prompt for it on first run. No Apple
firmware, device-tree extracts, activation material or private user data are
stored in Git, baked into Docker images, or downloaded automatically.

A *true* one-click deployment on any arbitrary PC cannot yet be claimed:
Windows must support WSL2, virtualization must be enabled, a compatible kernel
must be available, and the user must provide the prepared guest image. On a
fresh PC, WSL installation may require administrator approval and a reboot.
This repository now automates everything after those prerequisites.

## Portable release archive

To prepare a code-only installer ZIP for another Windows computer:

```powershell
.\tools\Build-IosSweet-Package.ps1 -CheckOnly
.\tools\Build-IosSweet-Package.ps1 -Destination 'D:\Releases\ios-sweet-portable.zip'
```

This archives only **committed Git files** and verifies each ZIP entry matches
the tracked tree. It explicitly rejects private image, key and device-tree
file extensions, and writes a `.sha256` checksum manifest alongside the ZIP.
The archive contains the two clickable installers, source, tools, Docker
configuration and docs, **not** proprietary iOS media or the locally built
kernel. Extract it on the destination machine, then follow the setup below.
Do not advertise this as a fully functional network-enabled release until
Safari HTTP and HTTPS have passed guest packet-capture verification.
## Windows 11 / WSL2 (preferred for this machine)

1. Unpack the repository onto a local Windows drive.
2. Double-click **`Install-iOS-Sweet.cmd`**. Select the compatible rebuilt
   `kernel.development.sweet`, **your own** prepared `.raw` iOS guest disk,
   and extracted iPhone X `d22ap.adt` device tree.
   The wizard checks/installs Ubuntu/WSL2 QEMU tools and creates a desktop
   shortcut. If Windows requests a restart, reopen the installer afterward.
3. Double-click **iOS Sweet (QEMU)**. Its URL appears in the PowerShell
   console (default `http://127.0.0.1:8099/`). Keep the console open.

For automated deployment from PowerShell:

```powershell
.\tools\Install-IosSweet-Windows.ps1 -Distro Ubuntu-24.04 -KernelBuild 0086 `
  -KernelFile 'D:\Downloads\kernel.development.sweet' `
  -GuestDisk 'D:\Private\ios-sweet\my-ios.raw' `
  -DeviceTree 'D:\Private\ios-sweet\d22ap.adt'
```

`-CheckOnly` validates without installing or changing shortcuts. The installer
never overwrites an existing rebuilt kernel or guest disk. If a guest file lives
under `/mnt/<drive>` in WSL, reads may be slower than a disk on ext4; the normal
persistent QCOW2 overlay remains in the selected WSL distro. The startup script
only writes to that overlay and never to the original raw disk.

**This machine:** project `D:\Projects\ios-sweet`, distro `Ubuntu-24.04-D`,
GUI shortcut `C:\Users\danho\Desktop\iOS Sweet (Windows).lnk`. The source
is also accessible via its original desktop-path junction.

## Docker Desktop or Linux Docker (experimental alternative)

The dedicated runner is defined in `docker/Dockerfile` and `docker/compose.yml`.
It requires an x86-64 Docker host with enough CPU/RAM. QEMU emulates an ARM64
Cortex-A76 through **TCG software emulation** on x86-64; access to `/dev/kvm`
is NOT required or requested. Docker Desktop runs another Linux environment on
Windows, so there is no guarantee it will be faster than native WSL2.

- Windows: double-click **`Start-iOS-Sweet-Docker.cmd`** and select the private
  kernel, guest disk and device tree on first run, or run the command below.
  The wrapper creates `iOS Sweet (Docker).lnk` for subsequent one-click launches.
- On Linux: set `IOS_SWEET_KERNEL`, `IOS_SWEET_DISK`, and
  `IOS_SWEET_STATE_DIR` to absolute existing host paths, then
  `docker compose -p ios-sweet-qemu -f docker/compose.yml up --build -d`.
- The viewer is published to **`127.0.0.1:8108`** by default, not to the LAN.
- The guest `.raw` file and kernel are mounted **read-only**. Only the
  separate `/state/ios.qcow2` backing overlay and timestamped test logs are
  writable. Do not mount the **same writable overlay** into more than one VM.
- Containerized iOS networking remains experimental; set `-Network` or
  `IOS_SWEET_NETWORK=1` only for explicit troubleshooting.

```powershell
.\tools\Start-IosSweet-Docker.ps1 `
  -KernelPath 'D:\Projects\ios-sweet\xnu\out-qemu-0086\kernel.development.sweet' `
  -GuestDisk 'D:\Private\ios-sweet\my-ios.raw' `
  -DeviceTree 'D:\Private\ios-sweet\d22ap.adt' `
  -StateDirectory 'D:\Private\ios-sweet\docker-state' `
  -CheckOnly
# Remove -CheckOnly to start, then open http://127.0.0.1:8108/
# Stop only this Compose project:
.\tools\Start-IosSweet-Docker.ps1 -Stop
```

The Docker image contains only Ubuntu, QEMU, LLVM, Python and the launcher.
The `.dockerignore` permits only the small entrypoint into the build context,
so private media and test logs cannot accidentally be copied into the image.
Use `docker logs ios-sweet-qemu-ios-sweet-1` for startup messages.

## Cleaning up experimental files

`tools/cleanup-qemu-logs.py` defaults to a dry run and reports the exact files
it would delete. `--apply` removes only old oversized `qemu.log` files under
`/home/ios-sweet-test/desktop-qemu-*`, retains the newest three runs and all
console/packet captures, and refuses to run while WSL QEMU is active. It never
removes private iOS disks, overlays or Docker images/volumes.

The source `research/vm-test` includes archival one-off diagnostics. They are
not included in the Docker image and should not be used as general deployment
prerequisites.

## Current outstanding technical issue

VirtIO Ethernet gets `en0=10.0.2.15/24` through QEMU NAT; ARP and a kernel DNS
round-trip work. Even with an IOKit-registered controller and a persistent
`NetworkInterfaces.plist` entry, Safari sends **no TCP SYN** and its page is
blank. The next fix belongs in iOS application network-path discovery and/or
real IONetworkingFamily controller integration; do not claim that adding
`NetworkInterfaces.plist` or granting sockets alone fixes internet access.
Verify with Safari HTTP **and** HTTPS navigation plus a guest-originated TCP
packet capture before publishing a networking-enabled release.

## Verified local Docker GUI test (2026-10-30)

Tested Windows 11/Docker Desktop, 4 emulated Cortex-A76 cores and experimental
network kernel 0095. The local `ios-sweet-qemu:local` image built successfully,
QEMU started in an unprivileged container, and the browser viewer displayed the
real iOS 16.7.16 lock screen, accepted a touch swipe to unlock and showed
SpringBoard/Home. Safari opened but displayed a blank `google.com` page.

Host viewer: `http://127.0.0.1:8110/` during the test (the default for new
installations is port 8108). Raw disk/kernel were mounted read-only from Windows;
`/state/ios.qcow2` is a separate writable overlay. QEMU logging was reduced
from GB-sized old `-d int,...` debug streams to `guest_errors,unimp` and stayed
near zero during the GUI test. The tested Docker packet capture had ARP/DNS and
multicast only, **no TCP SYN**. The run exited normally when the selected test
duration elapsed. The 32 previously running Docker services were unaffected.

The diagnostic kernel branch `qemu-net-ioreg-probe` has a separate opt-in NECP
trace (`sweet_qemu_necp_trace=1`) to investigate why Safari/Network.framework
does not start socket traffic. Do not merge it into a default package or claim
network support until HTTP+HTTPS and TCP packets pass validation.