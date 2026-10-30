# iOS Sweet: Docker-only Windows installation

**Installing from GitHub?** Start with the
[public GitHub installation guide](GITHUB_INSTALL.md) and download the
[verified Docker preview ZIP](https://github.com/danhol86/ios-sweet/releases).

**Status — 30 October 2026:** the real iOS 16.7.16 GUI starts in an ARM64
QEMU guest running inside Docker Desktop on Windows. A native root-owned
SystemConfiguration bootstrap now makes the iOS DNS resolver return valid
Google IP addresses and initiates real external HTTPS connections. This
does **not** by itself establish that Safari renders pages reliably.
This is experimental, not a general-purpose or Apple-supported emulator.

## Install on a new Windows PC

Prerequisites:

1. Windows 11 with virtualization enabled and **Docker Desktop running in
   Linux containers mode** (Docker Desktop may manage its own internal WSL2
   distro). **Do not install an extra Ubuntu WSL distro.**
2. This repository or the code-only portable ZIP, extracted on a Windows
   filesystem accessible to Docker Desktop.
3. The user's own prepared **16 GiB iOS HFSX raw disk**, the matching
   extracted iPhone X **D22AP device tree** (`d22ap.adt`), and a matching
   rebuilt **SWEET XNU** kernel (`kernel.development.sweet`).
   Neither Apple firmware nor prepared iOS media are included in the ZIP or
   Docker image. For a new kernel, build the public open-source XNU patch
   series with the repository's macOS GitHub Actions workflow and download its
   `xnu-kernel` artifact. Preparing the iOS disk itself is still an
   experimental, separate workflow.

**Double-click `Install-iOS-Sweet.cmd`.** The setup checks Docker and
installs official Docker Desktop through winget if necessary. On a fresh
machine it downloads the verified open-source XNU kernel, selects the
exact iPhone X iOS 16.7.16 components from Apple's firmware manifest,
and builds a private HFSX iOS disk inside Docker. It then validates
the image mounts, builds the QEMU image, prepares a network-enabled
guest overlay, and creates the desktop shortcut
**iOS Sweet (Docker)**. Subsequent launches reuse the saved file paths in
`docker/local-config/windows.json` (ignored by Git); no Ubuntu shell, WSL
distribution, root password or system-wide environment configuration is needed.
The saved paths are not baked into the Docker image.

The browser opens `http://127.0.0.1:8108/` when the guest viewer is ready.
The iOS boot itself takes longer. Press **Swipe up / Home** in the viewer to
unlock or return to SpringBoard.

**Fresh-IPSW smoke test (30 October 2026):** All Apple firmware downloads
completed with CRC verification; the device tree exactly matched the
previously verified tree; a 16 GiB HFSX filesystem was built, checked with
`fsck.hfsplus`, and ran the iOS root tweaks. A single clean QEMU guest
booted that image through launchd and executed SpringBoard/backboardd,
but **did not reach the interactive lock screen** during the initial
several-minute smoke test. Subsequent read-only comparison revealed that
38 of 39 dyld cache files matched the older interactive image; subcache
`.15` differed by just one four-byte ARM64 instruction at offset
`0x1619f0c`. The SHA-256-gated patcher applies this QEMU-only
MobileGestalt/LaunchServices workaround to newly generated *local* disks,
not a public image. The second boot and Safari remain under verification.
This is not a stable release.

The new root also lacked all 13 standard system data containers present
in the older interactive build. The updated root preparation creates
these containers with fresh local UUIDs and the verified iOS 16 metadata
schema (the synthetic test proves idempotency), then seeds the
`mobileactivationd` activation data ark. This is an experimental
QEMU-only first-boot compatibility step, not a copy of private device data.

The container mounts all three supplied inputs **read-only** and uses the
separate persistent `docker/local-state/oneclick/ios.qcow2` overlay
for guest writes. The first launch automatically installs the
70 KB iOS ARM64 DNS bootstrap into that overlay; the stock Apple
`ReportCrash` executable is copied to
`ReportCrash.iossweet-original` so the wrapper can execute it after
publishing active IPv4 and DNS state. No installed disk outside the overlay
is modified; re-running setup verifies the bootstrap instead of duplicating
it.
This means an iOS reboot preserves state without changing the original disk.
The default QEMU run duration is now unlimited (0 seconds means until
explicitly stopped), preventing the viewer from disappearing after two
hours while the container is running.
Do not share the same overlay between two simultaneously running instances.
The viewer binds only to localhost.

**QEMU black-screen diagnosis (30 October 2026):** The live guest's
kernel console shows `SWEET FB: display off` after the initial
framebuffer swaps. The browser Home control sends tablet swipes, not
the physical power key, so it does not wake the display. New XNU patch
`0097-sweet-qemu-display-keep-awake.patch` suppresses *only* this
power-off transition when QEMU passes `sweet_qemu_keep_awake=1`.
Physical SWEET devices retain normal display sleep. A newly rebuilt
XNU kernel is required for this change; older installed kernels ignore
the boot arg. The guest also exhibits a mobileactivationd SIGTRAP
crash loop, which is a **separate** unsolved iOS startup problem.

## Running without the installer / in CI

Windows PowerShell, from the extracted project root:

```powershell
.\tools\Start-IosSweet-Docker.ps1 -KernelPath 'D:\Private\kernel.development.sweet' `
  -GuestDisk 'D:\Private\ios16.raw' `
  -DeviceTree 'D:\Private\d22ap.adt' `
  -StateDirectory 'D:\Private\iossweet-state' -CheckOnly

# Remove -CheckOnly for a normal Docker start.
.\tools\Start-IosSweet-Docker.ps1 -Stop
```

`-CheckOnly` verifies inputs and Compose configuration without building or
starting the guest. Use `-Interactive` if you want file-picker dialogs, or
`Start-iOS-Sweet-Docker.cmd` to start using saved paths.

On a Linux Docker host, set absolute existing paths for
`IOS_SWEET_KERNEL`, `IOS_SWEET_DISK`, `IOS_SWEET_ADT`, and
`IOS_SWEET_STATE_DIR`; then run:

```sh
docker compose -p ios-sweet-qemu -f docker/compose.yml up --build -d
```

Windows `Install-iOS-Sweet.cmd` and the desktop shortcut **always run
Docker**, not a standalone WSL Ubuntu environment.

## Portable code-only ZIP

```powershell
.\tools\Build-IosSweet-Package.ps1 -CheckOnly
.\tools\Build-IosSweet-Package.ps1 -Destination 'D:\Releases\ios-sweet-docker.zip'
```

The packaging tool archives committed Git files only, validates the archive,
rejects private Apple/guest media, and writes a SHA-256 manifest.
It does not include the large local iOS image or a built kernel. On a
fresh install these are sourced and prepared automatically where possible.
If packaging
from a developer branch, first commit its changes; otherwise the ZIP will
contain the earlier committed tree.

## Current Safari networking state

Networking is **on by default** using the verified network-enabled kernel
(downloaded automatically from our release when a local one is absent),
and a private guest overlay distinct from earlier tests.
The first boot publishes QEMU `en0=10.0.2.15/24`, route
`10.0.2.2`, DNS `10.0.2.3` and the corresponding dynamic IPv4/DNS
service state as root. The bootstrap is restricted to the QEMU guest
and has no physical-iPhone installation path.

An isolated test confirmed `getaddrinfo("google.com") == 0` repeatedly;
packet capture recorded actual application/system DNS requests and TCP
connections. Separate startup testing confirmed
`IOS_NETSEED_START uid=0` / `IOS_NETSEED_DONE rc=0`. The GUI booted
to the lock screen but touchscreen viewing became unreliable under
Windows memory pressure. **Still verify HTTP and HTTPS page rendering
directly in Safari before declaring complete browser compatibility.**

## Storage and safety

- Use `docker logs ios-sweet-qemu-ios-sweet-1` for Docker startup messages.
- Use `Start-IosSweet-Docker.ps1 -Stop` to stop only iOS Sweet.
- The one-click installer removes/recreates neither shared Docker volumes
  nor other projects' containers. It creates only the `ios-sweet-qemu`
  Compose service and a local bind-mounted overlay.
- Keep at least 3 GiB of free host RAM before starting; emulating iOS
  in QEMU's single-vCPU software mode is demanding.
- Do **not** unregister or delete Docker Desktop's `docker-desktop` WSL
  distribution, its VHDX, or other applications' Docker volumes.
- Old native Windows/Ubuntu launchers are retired. Historical technical
  notes in `docs/QEMU_WINDOWS.md` describe old experiments and are not
  current installation instructions.
- The guest is security-relaxed and experimental. Do not use it for personal
  accounts, credentials or sensitive data.
