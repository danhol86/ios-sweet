# Native Windows QEMU backend (experimental)

## `driverkitd` termination diagnosis — 31 October 2026

The recurring guest log entry `CRASH driverkitd[66] sig 9 ... reason ns 1
code 0x7` has a **specific XNU meaning**, not an unknown instruction fault:
namespace `1` is `OS_REASON_JETSAM`, and code `7` is
`JETSAM_REASON_MEMORY_PERPROCESSLIMIT`. That denotes a daemon exceeding its
**guest-side per-process memory limit**, rather than proving that the 32 GiB
Windows host is out of RAM. `SIGKILL` is consistent with this termination.
Apple's XNU sources document the definitions in
[`bsd/sys/reason.h`](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/reason.h)
and [`bsd/sys/kern_memorystatus.h`](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/kern_memorystatus.h).

Five independent archived Windows boots (original and quiet-AKS kernels)
show the **same eight image-relative `driverkitd` stack frames** after
normalising ASLR. Those logs also show SpringBoard/Safari boot succeeding.
This evidence identifies the immediate termination category but does **not**
explain why `driverkitd` reaches its memory limit. Do not disable jetsam,
increase arbitrary limits, or patch the kernel merely to hide the event.
The next diagnostic step is to inspect the private launchd job's
`JetsamProperties` and its memory footprint at termination, then test a
targeted fix on a separate, backed-up guest image. It is also important to
distinguish the **guest jetsam limit** from the host's separate 6 GiB
free-RAM startup guard.

For read-only, repeatable cross-boot analysis, run one saved console per
QEMU session through:

```powershell
python tools/analyze-qemu-crashes.py windows-runtime/network-probe/metrics-boot-console.log windows-runtime/network-probe/quiet-aks-console-progress.log
```

The tool groups ASLR-normalized process signatures, classifies known jetsam
codes, counts separate input logs, and emits JSON without relocated address
values or guest user data. One log **per actual boot** avoids overstating the
number of occurrences when multiple snapshots capture the same event.
Four synthetic Python unit tests validate the analyser without private Apple
images or running QEMU. A successful tool run does not imply guest health.
The existing parallel-frame viewer test now extends its **test-only** cache
reuse window to avoid false failures when a busy Windows host schedules eight
HTTP requests more than 280 ms apart. Production still uses the original
280 ms minimum frame-resample interval. The combined offline suite has 17
passing Python tests and the separate browser-side JavaScript suites.

## Viewer efficiency and hot reload (31 October 2026)

### Smooth one-connection navigation gestures

The browser viewer now offers four optional controls: **Scroll down**, **Scroll
up**, **Swipe left** and **Swipe right**, in addition to the original Home
gesture and freehand pointer/touch handling. Each directional control sends
one validated request to `/gesture`. The backend generates sixteen bounded
tablet events in **one QMP connection**, with intermediate positions and
delays that survive busy iOS input polls. It avoids browser drag speed and
network round trips determining swipe success. Inputs are restricted to four
fixed directions; arbitrary coordinates, durations, or extra payload fields
are rejected. The existing origin and loopback restrictions still apply.
The directional names refer to the finger movement; "Scroll down" moves
the virtual finger upward. JavaScript pointer tests and Python HTTP tests
validate the command count, safe bounds, one-request UI, and rejection of
invalid gestures. Actual scrolling on each app is subject to iOS handling.

On the development host, the first deployment attempt was blocked by the
existing **6 GiB free-RAM safety requirement** while Docker Desktop's WSL VM
was holding much of the 32 GiB host's memory. The live iOS disk was safely
backed up before the attempt. The offline gesture tests pass, but the new
backend gesture code must still pass a real QEMU/Safari check when memory is
available. The launcher intentionally refuses to force a start into heavy
paging, and it never shuts down unrelated Docker containers to make room.

### Pointer recovery and host capture metrics

The HTML viewer queues all touchscreen events in order. It now guarantees
an **up/release event** when the pointer is cancelled, another window gains
focus, the page closes, or the tab is hidden. The down/up delivery is
serialized through the existing QMP input queue, and release requests use
the browser's `keepalive` option to make page-close delivery more resilient.
Only the active pointer ID is allowed to control a drag; lost pointer capture
cannot generate duplicate releases. This fixes the iPhone appearing to
remain pressed after an interrupted mouse or touch gesture. The independent
`node tests/check_viewer_pointer.js` mocks browser events and verifies four
failure/recovery scenarios without QEMU or private Apple firmware.

The controller also serves **loopback-only `/metrics.json`** with the number
of QMP framebuffer reads, changed and unchanged images, capture failures,
and most recent/average capture and PNG compression times. Nothing from
iOS guest memory, URLs, user data, or local filenames is returned. Click
**Viewer performance diagnostics** in the local browser to see these
measurements (and refresh on demand). The measurements are about the
Windows capture/encode pipeline, **not iOS frame rate** or emulation speed.
This adds no periodic metrics sampling: values are updated incidentally
when an actual screenshot is requested.

The final live test on the verified two-core quiet-AKS kernel reached the
home screen and rendered Google's real HTTPS cookie dialog after a delayed
WebKit paint. A representative 78-frame session measured ~25.7 ms for a
QMP full-frame read and ~23.7 ms for PNG encoding when the frame changed,
with zero capture errors. These are host-side means from this one machine,
not guarantees for other machines. Testing PNG compression levels 0, 1, 2,
3 and 6 showed the current level 2 remains a good speed/size tradeoff;
no lossy conversion or extra image dependencies were introduced.

Native launches also now hold a Windows-enforced one-byte file lock
(`windows-runtime/state/native-qemu-instance.lock`) throughout the QEMU
controller's lifetime. A second launch attempting to acquire the same lock
fails immediately, even in the short window before the first QEMU process
appears in the process list. Windows releases the lock automatically if
the controller dies; the existing QEMU process check still protects against
an orphaned emulator. The `-Stop` and `--prepare-only` paths are not blocked
by this lock. A cross-process regression test verifies both rejection while
held and successful reacquisition after release. This is independent of the
ordinary double-click launcher check and protects against rapid double-clicks.
The post-restart live test also completed: the locked single-instance
controller booted to the lock screen, unlocked, launched Safari and rendered
Google's real HTTPS consent page (after a noticeable software-rendering
delay). This verifies GUI and Safari functionality in the same session as
the new lock and adaptive viewer, not a claim of fast page rendering.

The QEMU framebuffer is 1080x2400 BGRA (about **9.9 MiB of raw pixel data**).
Before this change, every visible viewer tab requested a full QMP `pmemsave`
approximately every 0.8 seconds even when nothing changed. That generates
unnecessary host I/O, particularly on the software-emulated Windows guest.
The viewer now requests frames **every 350 ms after activity or a changed
frame**, then relaxes to 1 second, 2.5 seconds and finally 6 seconds after
7, 20 and 60 seconds of inactivity, respectively. It stops polling completely
when the page is hidden and resumes promptly on visibility/focus or input.
Actual encoding remains cached with HTTP 304 for identical frames; no
screenshots are taken by the viewer when there is no connected browser tab.

The full web viewer lives in `tools/qemu-viewer.html`, separate from the
controller `tools/qemu-live-screen.py`. The controller **reads the HTML on
each GET /**, so editing its UI only requires reloading the browser tab—no
iOS/QEMU restart. Backend Python changes still require restarting the
controller normally. `node tests/check_viewer_poll.js` validates the
adaptive refresh policy against a controlled clock, and the Python unit
suite checks that edited HTML is reloaded by an already-running server.
Adaptive view is a host-I/O optimization, **not** a claim that iOS boots,
renders WebKit, or executes instructions faster. All private disk files
and guest kernel contents remain unchanged.

## Verified quiet-kernel selection and smoke checks (31 October 2026)

The optional `0098` AKS debug-logging patch is now **live-tested** with
native two-core QEMU, on a separate private QCOW2 clone. It reached the
lock screen, unlocked into SpringBoard using `POST /gesture`, launched
Safari and **rendered Google's consent dialog over HTTPS with a padlock**.
The matching in-memory SWEET kernel console contained **zero AKS selector
trace lines**, confirming that `sweet_aks_quiet=1` took effect while normal
iOS services remained functional. A second QEMU instance was never run.
GitHub Actions kernel build `41191163506` succeeded. SHA-256 of the newly
tested kernel: `7dc86497ccd0c224ec1e6b8430be6f2dd7a46ac13ef795ed4047d0adf7d3bde8`.

On the tested Windows PC, the new binary is installed **alongside** the
original as ignored `windows-runtime/guest/kernel.aks-quiet.sweet`, with
its hash stored in ignored `windows-runtime/state/native-kernel-sha256.txt`.
The preserved original is `kernel.development.sweet` (SHA-256
`85039335d05d335d1f9b33f7c8131d274477c50020915ff0335b42428abe998a`).
The one-click native launcher selects the newer file only when the local
preference exists and its hash is verified; otherwise it uses the original.
The original kernel also has a separate backup under ignored
`windows-runtime/backups/kernel-original-20261031.sweet`.
**Docker, physical-device preparation and fresh installs remain on their
separately pinned original kernel**, rather than silently changing other
platforms to an untested build.

To roll back after **cleanly stopping** the running emulator, start the
original on the one-core disk using:

```powershell
powershell -NoProfile -File tools/Start-IosSweet-Windows.ps1 -Stop
powershell -NoProfile -File tools/Start-IosSweet-Windows.ps1 -SrgbDisplay -SingleCore -LegacyKernel
```

For a two-core test with the original kernel, omit `-SingleCore` and keep
`-LegacyKernel`. The launcher now rejects any explicit request for the
legacy kernel, a different core count or enabling diagnostics **even if
`-SrgbDisplay` was omitted**, when a nonmatching guest is already running.
It must never start an additional instance to fulfil a mode change.

A read-only runtime smoke check is available:

```powershell
powershell -NoProfile -File tools/Test-IosSweet-Windows.ps1 -ExpectedCpus 2
```

It verifies the current QEMU process/executable, actual kernel file hash,
the viewer's status JSON and a valid framebuffer PNG, without restarting
iOS or changing its disk. It intentionally **does not** claim Safari has
network access; that must be confirmed by an actual browser navigation.

The **previous kernel** had already passed the two-core desktop launcher and
Safari check. The **new quiet-AKS kernel** then passed its own separate
live test on an isolated QCOW2 before local opt-in. Finally, the actual
one-click launcher used the *new* kernel and original current two-core
save, booted to SpringBoard, and rendered Google's secure HTTPS consent
dialog again. The installed original kernel remains the rollback option.
All private test disks and screenshots remain ignored; no Apple system
files are distributed through the repository.

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

Eleven self-contained offline tests in `tests/test_qemu_viewer.py` cover PNG
channels, frame cache/ETag, concurrent viewers, input security, native
boot-arg boundaries, missing prerequisites, QEMU PID safety, live HTML reload
and atomic cross-process startup locking.
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

The `-Stop` path verifies that the saved QEMU PID still points to this
project's actual `qemu-system-aarch64.exe` before sending a QMP shutdown.
This prevents a stale state file or reused localhost QMP port from shutting
down an unrelated process. A live read-only identity check passed against
the running two-core guest; the negative test rejected an ordinary Python
process. The iOS disk is never deleted when shutting down.

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
