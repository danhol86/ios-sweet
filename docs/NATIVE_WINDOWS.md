# Native Windows QEMU backend (experimental)

## Tested local two-core relaunch and rollback (31 October 2026)

On the tested D:-drive Windows machine, `windows-runtime/state/native-cpus.txt`
contains `2`. This **ignored, local-only** file makes the desktop shortcut
select the tested two-core guest saved at
`windows-runtime/state/ios-cpu2-experiment.qcow2`, with a separate backup
at `windows-runtime/backups/cpu2-after-browser-20261031.qcow2`. The
original one-core `ios.qcow2` is not overwritten. The launcher accepts
only this exact known project-local overlay, and still refuses a second
QEMU instance. Its running-instance reuse test retained the same PID.

To return to the original single-core state, run from the project folder:

```powershell
powershell -NoProfile -File tools/Start-IosSweet-Windows.ps1 -Stop
powershell -NoProfile -File tools/Start-IosSweet-Windows.ps1 -SrgbDisplay -SingleCore
```

`-SingleCore` overrides the local preference without deleting it. Removing
`native-cpus.txt` restores the one-core default permanently. A different
PC or fresh clone defaults to one CPU with no preference file. The two-core
guest has also passed a second **normal low-overhead reboot**, unlocked into
SpringBoard, and rendered an example.com HTTP page in Safari; this is
limited repeatability evidence, not proof of sustained stability or a
particular speedup.

Future kernel builds can use `sweetiolog=-` to disable IOKit matching logs
and `sweet_aks_quiet=1` (new patch 0098) to suppress only frequent AKS
selector **logging**. Normal QEMU boots set these switches; diagnostic
boots preserve logs. The AKS patch requires a new, independently validated
kernel and is **not installed on the current verified GUI guest**. Neither
option changes keybag/selector behavior or physical Redmi defaults.

## Viewer and CPU experiments — 31 October 2026

The Windows viewer now caches unchanged framebuffer snapshots and returns
HTTP 304 with an ETag; concurrent clients share one QMP read. It adapts the
refresh interval (350 ms immediately after input, 800 ms while idle, 2500 ms
while the browser tab is hidden), rather than refreshing unconditionally
every 1600 ms. On the live 1080×2400 framebuffer, PNG compression level 2
took about **26 ms** versus **51 ms** for the prior level 6. This is an
encoding benchmark, **not a claim that iOS itself runs twice as fast**.

Home gestures now use one timed, 30-event QMP connection instead of 30
individual browser HTTP/QMP calls. A live run invoked that new QMP path and
returned Safari to SpringBoard in 1.59 seconds. Follow-up tests confirmed
that **240 ms** taps open Safari and navigate from the Google favorite;
**375 ms** on that favorite invoked an unwanted preview/long-press menu and
900 ms triggered the native app menu. The viewer therefore holds short
taps for **240 ms after QMP acknowledgement**, with swipes kept separate.
Cross-origin POST input is rejected.

Normal launches now omit expensive opt-in diagnostic sampling, verbose
network tracing and packet capture. To collect kernel/PCAP evidence again,
launch `tools/Start-IosSweet-Windows.ps1 -SrgbDisplay -Diagnostics` only when
there is **no running guest** (do not shut down a healthy VM just to enable
traces). The desktop shortcut remains on the safe single-core runtime.

Experimental `python tools/iossweet-native-windows.py --cpus 2` exists for
isolated performance testing. It uses QEMU PSCI HVC and two DT CPU nodes;
it **refuses to use the known-good persistent overlay**. Supply a separate,
verified clone with `--overlay PATH` only after the VM has fully stopped.
On 31 October 2026, a two-CPU guest was started using an independently
SHA256-verified copy; the kernel reported both CPUs online and SGI1 verified.
**Subsequent live tests passed:** the two-CPU guest reached the iOS lock
screen, unlocked into SpringBoard via the batched `/gesture` API, launched
MobileSafari, and rendered Google's consent dialog over **HTTPS**. The guest
also loaded and rendered `example.com` over **HTTP** (Safari correctly
marked that particular visit "Not Secure"). Two-core viability is verified;
performance gain and long-running stability are still being assessed, so
one core remains the portable default until further validation.

Eight self-contained offline tests in `tests/test_qemu_viewer.py` cover PNG
channels, frame cache/ETag, concurrent viewers, input security, native
boot-arg boundaries and missing prerequisites.
`python -m unittest discover -s tests -p test_qemu_viewer.py`
passed locally on Windows. Private Apple root disks, screenshots, traces and
QEMU runtime files are not committed to the repository.

Each viewer boot now uses a unique frame-cache session identifier, so a
browser tab left open during QEMU restarts cannot mistakenly treat the
new guest's first frame as an unchanged old image. The local-only
`/status.json` response reports only runtime mode, core count and whether
diagnostic capture is enabled; no paths, keys or device identifiers.
`--check` now returns a nonzero exit status if the Windows QEMU executables,
kernel or 16 GiB iOS disk are missing. It deliberately does **not** reject
low free RAM while a guest is already running, because opening its existing
viewer must remain possible.

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
  A second independent HTTPS check (`https://example.com`) also rendered
  its complete text and secure-padlock UI at 23:25 UTC.
  A controlled HTTP page at `10.0.2.2:8765` also fetched HTML, an image,
  and a JavaScript-requested canary. CPU-only ARM64 emulation remains very
  slow and some repaints appear substantially delayed. This was tested with
  the optional **sRGB virtual display**; it was not tested against P3 in
  the same conditions. See `SAFARI_NETWORK_DIAG.md` for packet evidence.
- The Windows double-click launcher now selects the verified sRGB guest
  configuration and reuses an already-running guest of that mode, rather
  than launching a second VM. This display mode applies only to synthetic
  Windows QEMU; physical-device firmware is never changed by the launcher.
  The new desktop icon is named **iOS Sweet (Windows)**; the obsolete Docker
  shortcut for this project was removed. On busy web pages a longer touch
  (~0.8 seconds) can be needed due to the slow software-emulated input polling.
- The redundant QEMU installation on C: was removed after the D:-resident
  QEMU executables were checksum-verified and tested. All three dedicated
  iOS Sweet Docker image tags, the guest container and project network,
  and approximately 23 GiB of unused generated media were cleaned up.
  The 34 unrelated running Docker services were preserved.

This is experimental engineering code, not a finished iOS Simulator or an
Apple-supported virtualization environment.
