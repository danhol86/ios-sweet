# Installing iOS Sweet on Windows from GitHub

**Experimental preview, not a finished iOS simulator.** The installer is
being upgraded to prepare the private iOS root automatically from the
official Apple IPSW. Safari can emit DNS and TCP traffic, but displaying a
complete web page has **not** been verified.

## Download

1. Open [Releases](https://github.com/danhol86/ios-sweet/releases).
   Download **ios-sweet-docker-oneclick.zip** from the latest *Docker preview*
   release. Do not download GitHub's automatic **Source code (zip)** unless
   you specifically want to work from source; both contain code, but the
   release ZIP has been checked against the project packaging rules.
2. Extract the ZIP into a normal local folder, for example
   `C:\ios-sweet`. Do not run the installer *inside* the archive.
3. Double-click **Install-iOS-Sweet.cmd**. If Docker Desktop is missing, the
   installer attempts to install the official `Docker.DockerDesktop` package
   through Windows Package Manager (winget). Windows may require UAC
   confirmation, a reboot or initial Docker Desktop setup before you
   double-click the installer again. Docker Desktop must be in **Linux
   containers** mode. You **do not** need a separate Ubuntu WSL distribution.

On a supported Windows machine the installer now attempts to download the
verified open-source XNU kernel from this project's GitHub Release, extract
the exact iPhone X DeviceTree and OS/cryptexes directly from Apple's
iOS 16.7.16 (20H392) firmware, then build a private HFSX guest disk inside
Docker. **At least 35 GiB of free disk space** is checked before the first
full preparation; the download and image creation are substantial.
Cached, completed downloads are reused on retry. No Apple firmware is
uploaded to this repository or Docker Hub.

The source of this automatic preparation is
`tools/AutoPrepare-IosSweet.py`, `tools/extract-im4p-adt.py`, and
`docker/Dockerfile.assets`. This new path remains experimental until a
fresh-from-IPSW guest has passed the same boot tests as the original
prepared guest.

## Advanced: supply an existing prepared iOS disk

The public repository and release **cannot contain a prebuilt Apple iOS
installation**. If automatic preparation is unavailable for your system,
you can still supply these files yourself:

| File | What it is |
| --- | --- |
| `ios16-net-test.raw` (or another `.raw`) | Their own **prepared iOS 16 HFSX root filesystem**, typically a 16 GiB virtual disk with the project-specific boot/activation compatibility preparation |
| `kernel.development.sweet` | A compatible QEMU/VirtIO-enabled SWEET **XNU ARM64** kernel (the basic Redmi kernel is not sufficient for Docker) |
| `d22ap.adt` | The extracted **iPhone X D22AP device tree** corresponding to the iOS version |

The normal installer downloads an existing verified open-source
`kernel.development.sweet` automatically. Developers rebuilding the kernel
can fork the repo, enable GitHub Actions, run the **xnu** workflow on `main`
with `machine_config=SWEET` and `kernel_config=DEVELOPMENT`, then download
its `xnu-kernel` artifact and find `kernel.development.sweet`.
For the iOS root/device-tree preparation, see the project's
[root-image and ADT build instructions](../README.md#how-to-do-it-yourself).
The project still supports this manual workflow for debugging.

The private iOS root must come from the user's legitimately obtained Apple
firmware; it is not included in this repository, the Docker image or the
release. The release contains only open project code and the independently
built iOS network bootstrap (with source alongside it).

## Install and launch

1. Double-click **Install-iOS-Sweet.cmd** in the extracted folder.
2. The installer checks Docker and prepares the necessary assets
   automatically when possible. If you already have a prepared root image,
   you can select it instead. A separate writeable disk overlay is created
   automatically. The original root image is mounted read-only.
3. Open [http://127.0.0.1:8108/](http://127.0.0.1:8108/) or use the desktop
   shortcut **iOS Sweet (Docker)** that the installer creates.

Use `Start-iOS-Sweet-Docker.cmd` to relaunch. To stop, run
`powershell.exe -NoProfile -File tools\Start-IosSweet-Docker.ps1 -Stop`
from the project directory. The stop command affects only iOS Sweet.

## Important limitations

- This is a **code-only public preview**, not a preconfigured Apple iOS
  image or a supported emulator. First-time preparation must use the
  user's own local download of Apple's firmware; it is not bundled.
- iOS boots and the HTTP viewer works in the tested environment. System
  DNS resolves hostnames and the emulated guest transmits real TCP packets.
  Safari may still display an empty white page when navigating.
- iOS emulation uses **software QEMU** and is demanding on host memory.
  Close other large applications first. The installer checks for at least
  3 GiB of *available Windows RAM* before starting a new guest.
- Do not use personal accounts, credentials, or private files in this
  security-relaxed experimental guest.
- The original Redmi hardware instructions and flash procedures are
  **separate** from this Windows/Docker path. Running the Docker installer
  does not flash or modify a physical phone.
- Only **one iOS Sweet emulator** is permitted. The launcher uses a Windows
  mutex, refuses overlapping startup attempts, and stops old diagnostic
  instances. The optional `-CleanRetry` cleans only project-specific
  Docker containers, images, and disposable run folders; it preserves
  your iOS source disk and unrelated Docker services.
