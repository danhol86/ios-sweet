# Native Windows QEMU backend (experimental)

## What changes compared with Docker?

The ARM64 iOS guest can run directly under **Windows QEMU 11.1+**, without
running QEMU in a Linux container, a separate WSL distro, or a Linux VM.
This is a runtime option; it does not magically remove the need to obtain
Apple firmware and prepare a private 16 GiB iOS disk. The existing Docker
installer may still be used for that one-time disk preparation.

**Performance limitation:** On the tested Intel Core Ultra 7 Windows 11 PC,
native QEMU lists **TCG only** as the ARM64 accelerator. The guest cannot
use Intel VT-x or WHPX to execute ARM64 instructions directly. Native
Windows avoids Docker's Linux backend overhead, but may be similarly slow
or slower than Docker QEMU. The iPhone image's device tree requires **7 GiB
of emulated RAM**; the launcher blocks startup if the Windows host has too
little free RAM rather than causing severe paging.

## Run on Windows

1. Install QEMU for Windows (`winget install --id
   SoftwareFreedomConservancy.QEMU --exact`) and Python 3.10+.
2. Obtain a private prepared iOS disk and the verified SWEET kernel using
   the existing first-run Docker setup, or your own equivalent files.
3. Make sure any previous iOS guest is stopped. **Never run two instances.**
4. Double-click **`Start-iOS-Sweet-Windows.cmd`**. It starts native Windows
   QEMU and the same browser viewer at
   <http://127.0.0.1:8108/> if prerequisites and free RAM pass.

Check dependencies without stopping the current guest:

```powershell
powershell -File tools/Start-IosSweet-Windows.ps1 -CheckOnly
python tools/iossweet-native-windows.py --prepare-only
```

Stop a native guest cleanly, flushing its private QCOW2 overlay:

```powershell
powershell -File tools/Start-IosSweet-Windows.ps1 -Stop
```

The Python backend creates a **fresh QEMU-specific ADT**, not a hardware
iPhone DeviceTree, and constructs a RAM boot image from the user's own
local kernel. It uses the project's existing XNU payload and VirtIO
network/input devices.

On this PC, the active QEMU 11.1 runtime, iOS disk, kernel, writable state,
and launcher logs are all under `D:\Projects\ios-sweet\windows-runtime`.
Its `guest/` folder has the private iOS disk and verified kernel; `state/`
holds the active save and per-run traces; `backups/` holds historical guest
states, and `qemu/` contains Windows QEMU binaries. The previous Docker
save was preserved and rebased to this same native iOS base. Docker and
Windows must never access a writable guest overlay simultaneously.

Native QEMU binds its QMP control channel to `127.0.0.1:4444`, and the
viewer binds to `127.0.0.1:8108`. There is no external QMP listener.
Captured network packets and guest logs stay in the ignored local state
directory. The viewer supports normal click-to-tap (with a minimum hold)
and drag gestures over the same VirtIO tablet as the Docker version.

## Validation and known limitations — 30 October 2026

- Windows QEMU **11.1** was installed and probed; `cortex-a76`, VirtIO
  disk/network/tablet are available. Its available ARM accelerator is **TCG**.
- The Windows-native Python backend successfully constructed a QEMU ADT,
  approximately 16 MiB payload, 37 MiB boot RAM and an ARM64 stub.
- Localhost TCP QMP command and touchscreen framing tests passed with a
  synthetic monitor. No second ARM64 emulator was launched.
- Native Windows iOS boot is verified: the lock screen, SpringBoard home
  screen, Safari and Home gesture appeared in the live viewer on
  30 October 2026. A second boot with the final D:-only paths reached the
  lock screen. The host can still have very little free RAM and QEMU is
  software-emulating ARM64; boot and graphics may remain slow.
- Guest network capture from the previous Docker QEMU run showed successful
  `www.google.com` DNS, TCP and TLS ServerHello; Safari still did **not**
  reliably render a web page. That is an iOS WebKit/crypto/rendering issue
  to investigate separately. Native Windows QEMU does not fix it by itself.
- **Later live retest (30 October 2026, 23:21 UTC):** The single Windows QEMU
  guest loaded Google's HTTPS page in Safari, showed its cookie-consent
  dialog and HTTPS padlock, and re-rendered the page from Safari history.
  A controlled HTTP page at `10.0.2.2:8765` also fetched HTML, an image,
  and a JavaScript-requested canary. CPU-only ARM64 emulation remains very
  slow and some repaints appear substantially delayed. This was tested with
  the optional **sRGB virtual display**; it was not tested against P3 in
  the same conditions. See `SAFARI_NETWORK_DIAG.md` for packet evidence.
- The Windows double-click launcher now selects the verified sRGB guest
  configuration and reuses an already-running guest of that mode, rather
  than launching a second VM. This display mode applies only to synthetic
  Windows QEMU; physical-device firmware is never changed by the launcher.
- The redundant QEMU installation on C: was removed after the D:-resident
  QEMU executables were checksum-verified and tested. All three dedicated
  iOS Sweet Docker image tags, the guest container and project network,
  and approximately 23 GiB of unused generated media were cleaned up.
  The 34 unrelated running Docker services were preserved.

This is experimental engineering code, not a finished iOS Simulator or an
Apple-supported virtualization environment.
