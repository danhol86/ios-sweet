# iOS Sweet: Docker-only Windows installation

**Status — 30 October 2026:** the real iOS 16.7.16 GUI starts in an ARM64
QEMU guest running inside Docker Desktop on Windows. Touch, SpringBoard and
Safari launch. **Safari networking is not working yet.** This is experimental,
not a general-purpose iOS simulator or an Apple-supported runtime.

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

**Double-click `Install-iOS-Sweet.cmd`.** The setup checks Docker and asks
for any missing kernel, iOS disk or device-tree file, validates the image
mounts, builds the QEMU image, and creates the desktop shortcut
**iOS Sweet (Docker)**. Subsequent launches reuse the saved file paths in
`docker/local-config/windows.json` (ignored by Git); no Ubuntu shell, WSL
distribution, root password or system-wide environment configuration is needed.
The saved paths are not baked into the Docker image.

The browser opens `http://127.0.0.1:8108/` when the guest viewer is ready.
The iOS boot itself takes longer. Press **Swipe up / Home** in the viewer to
unlock or return to SpringBoard.

The container mounts all three supplied inputs **read-only** and uses the
separate persistent `docker/local-state/ios.qcow2` overlay for guest writes.
This means an iOS reboot preserves state without changing the original disk.
Do not share the same overlay between two simultaneously running instances.
The viewer binds only to localhost.

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
It does not include the large local iOS image or a built kernel. If packaging
from a developer branch, first commit its changes; otherwise the ZIP will
contain the earlier committed tree.

## Debugging current Safari networking

Networking is **off by default** with the verified GUI-only 0086 kernel.
The experimental networking branch is
`danhol86/ios-sweet:qemu-net-ioreg-probe`; GitHub Actions run
`41031874190` built the combined socket/NECP diagnostic kernel (SHA-256
`d97b60c0a29a6170663eb4bc14027f056180013fde9b4d699b0a9b06e0dcf59a`).
Do not overwrite the stable GUI kernel or state overlay with experimental
networking artifacts. Use a separate test state and distinct Docker Compose
project when testing concurrently.

Confirmed: the Docker host can resolve and fetch `https://example.com`
(HTTP 200), the iOS guest has QEMU `en0=10.0.2.15/24`, and the kernel's
direct DNS probe reaches `10.0.2.3`. **Safari shows a blank page and
emits no TCP SYN**. MobileSafari/WebKit receive NECP
`flags=0x100024 policy=0 ifindex=4 reason=0`, but do not attempt a traced
socket connection. The guest's `SystemConfiguration/preferences.plist`
already contains a manual Ethernet/DNS service while
`NetworkInterfaces.plist` has no entries. Simply seeding that registry
was tested independently and did not fix Safari.

Next troubleshoot actual IONetworkingFamily registration, Network.framework
and DNS dynamic-store service state. Do not fake internet connectivity by
returning successful path or permission results. Verify **both HTTP and
HTTPS in Safari and actual guest-originated TCP SYN traffic** before calling
networking complete. Full technical findings and artifacts are in
`NOTES.md` on the networking branch; the private captures remain local.

## Storage and safety

- Use `docker logs ios-sweet-qemu-ios-sweet-1` for Docker startup messages.
- Use `Start-IosSweet-Docker.ps1 -Stop` to stop only iOS Sweet.
- Do **not** unregister or delete Docker Desktop's `docker-desktop` WSL
  distribution, its VHDX, or other applications' Docker volumes.
- Old native Windows/Ubuntu launchers are retired. Historical technical
  notes in `docs/QEMU_WINDOWS.md` describe old experiments and are not
  current installation instructions.
- The guest is security-relaxed and experimental. Do not use it for personal
  accounts, credentials or sensitive data.
