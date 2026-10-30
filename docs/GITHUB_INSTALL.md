# Installing iOS Sweet on Windows from GitHub

**Experimental preview, not a finished iOS simulator.** Use it only for
development and testing with your own iOS media. Safari can now emit DNS and
TCP traffic, but displaying a complete web page has **not** been verified.

## Download

1. Open [Releases](https://github.com/danhol86/ios-sweet/releases).
   Download **ios-sweet-docker-oneclick.zip** from the latest *Docker preview*
   release. Do not download GitHub's automatic **Source code (zip)** unless
   you specifically want to work from source; both contain code, but the
   release ZIP has been checked against the project packaging rules.
2. Extract the ZIP into a normal local folder, for example
   `C:\ios-sweet`. Do not run the installer *inside* the archive.
3. Install and start [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/),
   with the **Linux containers** backend enabled. Docker Desktop may use its
   own internal WSL2 backend. **You do not need to install an Ubuntu WSL
   distribution**, and must not unregister Docker Desktop's WSL distribution.

## Supply the required private iOS files

The public repository and release **cannot provide a ready-to-boot iOS
installation**. Each user supplies:

| File | What it is |
| --- | --- |
| `ios16-net-test.raw` (or another `.raw`) | Their own **prepared iOS 16 HFSX root filesystem**, typically a 16 GiB virtual disk with the project-specific boot/activation compatibility preparation |
| `kernel.development.sweet` | A compatible QEMU/VirtIO-enabled SWEET **XNU ARM64** kernel (the basic Redmi kernel is not sufficient for Docker) |
| `d22ap.adt` | The extracted **iPhone X D22AP device tree** corresponding to the iOS version |

The kernel is built from this repository's XNU patches: fork this repo,
enable GitHub Actions, run the **xnu** workflow on `main` with
`machine_config=SWEET` and `kernel_config=DEVELOPMENT`, then download
its `xnu-kernel` artifact and find `kernel.development.sweet`.
For the iOS root/device-tree preparation, see the project's
[root-image and ADT build instructions](../README.md#how-to-do-it-yourself).
That stage remains a developer workflow and is **not yet one click**.

The private iOS root must come from the user's legitimately obtained Apple
firmware; it is not included in this repository, the Docker image or the
release. The release contains only open project code and the independently
built iOS network bootstrap (with source alongside it).

## Install and launch

1. Double-click **Install-iOS-Sweet.cmd** in the extracted folder.
2. If asked, browse to the three files above. The installer remembers the
   paths locally, checks Docker, builds the QEMU image, and prepares a
   separate writeable disk overlay. The original root image is mounted
   read-only. There is no need to run Linux commands by hand.
3. Open [http://127.0.0.1:8108/](http://127.0.0.1:8108/) or use the desktop
   shortcut **iOS Sweet (Docker)** that the installer creates.

Use `Start-iOS-Sweet-Docker.cmd` to relaunch. To stop, run
`powershell.exe -NoProfile -File tools\Start-IosSweet-Docker.ps1 -Stop`
from the project directory. The stop command affects only iOS Sweet.

## Important limitations

- This is a **code-only public preview**, not a standalone Windows EXE or
  preconfigured iOS image. Downloading it on a new PC is not sufficient by
  itself: the private disk, kernel, and device tree must already be prepared.
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
