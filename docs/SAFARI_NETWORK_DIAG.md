# iOS Sweet / QEMU: Safari blank-page network investigation

## Two-core Windows QEMU follow-up (31 October 2026)

The isolated two-core native Windows QEMU guest (run
`windows-runtime/state/windows-qemu-20261031-094744`) booted real iOS 16
to SpringBoard with both virtual CPUs online. Safari navigated to Google
over HTTPS, eventually rendered the Google consent dialog and displayed the
padlock. TCP flows included approximately 4,930 outgoing and 9,982 incoming
bytes for one Google connection; a preceding short TLS connection closed
without a complete page, just like the earlier single-core control.

In a separate navigation, typing `example.com` in Safari loaded the page's
multilingual body. This particular request was **plain HTTP**, indicated by
Safari's "Not Secure" label, not an HTTPS validation of example.com.
Screenshots and PCAP remain under ignored `windows-runtime/network-probe/`
and the run folder. Both CPU counts have now demonstrated real web browsing;
this does not establish improved performance or uninterrupted reliability.

## Latest verified native Windows result (30 October 2026, 23:21 UTC)

**Safari has now rendered a real external HTTPS page.** On the *single*
running native Windows QEMU guest (`http://127.0.0.1:8108/`), tapping the
Google Safari favorite reached `www.google.com`; a screenshot showed the
Google consent dialog, page text, and Safari's HTTPS padlock. Navigating
away and **forward** again re-rendered the same page and padlock. This
supersedes the earlier reports below that Google never loads.

**Independent HTTPS cross-check at 23:25 UTC also passed:** Safari navigated
to `https://example.com` via its address bar and rendered the Example Domain
page, including its multilingual body text and the HTTPS padlock. The
corresponding sanitized TCP flow recorded 1,118 outgoing and 5,844 incoming
payload bytes; see ignored local screenshot
`windows-runtime/network-probe/example-com-rendered.png`. Both public sites
working in the same session is stronger evidence than a successful TLS hello
alone. Cold boot and sustained multi-site browsing still need validation.

The private `windows-runtime/state/windows-qemu-20261030-180638/network.pcap`
showed several Google connections: one closed after a 517-byte TLS ClientHello
and approximately 2.8 KB server flight, but a subsequent connection exchanged
about 4,960 outbound and 10,043 inbound TCP payload bytes and rendered the
Google page. **One aborted TLS flow does not prove all browser requests fail.**
The first visible navigation was unusually slow; wait for actual rendering
and inspect *all* follow-up connections before calling a test failed.

A deterministic local HTTP control also passed. Safari visited
`http://10.0.2.2:8765/`, and a Windows-local HTTP server recorded `GET /`
with a successful 200/304. Safari rendered the green CSS background, followed
by the expected `IOS_SWEET_HTTP_OK` text after a long delay. A richer HTML
control then fetched `/raster.png` and `/probe-canary.txt` (both HTTP 200),
verifying resource loading and JS `fetch` at the transport level. The fresh
control's visual repaint was not conclusively observed before navigation.

The successful guest had **`srgb_display=true`**, advertised by the synthetic
QEMU `/product/artwork-display-gamut` override, and was booted with one ARM64
CPU under QEMU TCG. The sRGB override was **not A/B-tested** against the
default P3 mode for browsing, so it is *not established as the root-cause fix*.
Web browsing is now **demonstrated**, but startup/painting latency and
reliability across other sites remain open issues. No second guest was
started, and the private Apple disk and unrelated Docker services were kept.
The Windows desktop shortcut is now **iOS Sweet (Windows)**, replacing the
obsolete project-specific Docker shortcut. Its launcher was tested to reuse
the existing sRGB guest with unchanged QEMU PID rather than start a duplicate.
During a busy page, a ~850 ms emulated touch hold registered where shorter
~300 ms holds had been intermittently missed.

The earlier kernel's single `sweet_net_trace_count >= 600` budget was
exhausted by `mDNSResponder` socket calls. Commit `ebc43ae` reserves a
separate browser trace budget; GitHub Actions XNU build run `41143670554`
was started for that diagnostic. Do not replace the currently working kernel
automatically with an untested diagnostic build.

## Reproduced condition

- iOS 16.7.16 boots to SpringBoard and MobileSafari opens. The browser
  displays a destination such as `google.com` in its address bar, but
  the webpage can remain entirely white.
- The QEMU guest has functioning `en0=10.0.2.15` and real outbound TCP.
  A root-owned, QEMU-specific SystemConfiguration bootstrap publishes the
  active IPv4 network service, default route, interface link state and
  DNS server `10.0.2.3`.
- An independent native ARM64 iOS diagnostic repeatedly resolved
  `google.com` successfully with `getaddrinfo`, establishing that
  configd/mDNSResponder/DNS work at the system level.
- **This is not proof of working WebKit browsing.** In the recorded clean
  Safari smoke captures, network packets show primarily *Apple background
  services*, not successful requests initiated to Google by WebKit.

## Read-only packet evidence

Analyze an ignored local QEMU capture with:

```powershell
python tools/check-safari-pcap.py "docker/local-state/oneclick/desktop-qemu-<run>/network.pcap"
```

The analyser prints aggregate handshake counts and only classifies SNI into
`google.com`, `example.com`, `apple` or `other`; it does not print
unrelated URLs, credentials, cookies or complete packet payloads.

Representative captures from 30 October 2026:

| Metric | Earlier GUI smoke | Later GUI smoke |
| --- | ---: | ---: |
| Outbound TCP SYNs | 24 | 207 |
| Outbound TLS ClientHellos | 19 | 194 |
| TLS ServerHellos | 19 | 192 |
| Apple-domain TLS SNI | 19 | 176 |
| `google.com` DNS queries | 0 | 0 |
| `google.com` TLS SNI | 0 | 0 |

Consequently, simply seeing TCP and successful TLS handshakes is **not**
a valid Safari success criterion. The remaining blocker might be WebKit's
NECP path/network-service decision, app permissions or process lifecycle.
Do not force policy result flags to success or fake network capability.

## Next isolated experiment

1. Stop and **remove the previous iOS Sweet test container and its
   disposable QEMU run folders** before starting another. Never run
   two emulated iOS guests concurrently; leave all unrelated Docker
   services, images and volumes alone.
2. Boot the known-good guest with `-TraceNetworkPath` and a new
   isolated state overlay; it enables targeted SWEET QEMU WebKit and
   NECP tracing in the rebuilt kernel. Confirm `exec MobileSafari`,
   `exec com.apple.WebKit.Networking`, and WebKit's NECP
   `client-result`/socket/connect activity.
3. In Safari, try `http://example.com`, `https://example.com`, then
   `https://google.com`. For each attempt record a framebuffer screenshot,
   kernel trace and sanitized PCAP summary. Observe whether **WebKit**
   emits a destination DNS query/SYN and whether an actual page renders.
4. If there is no WebKit DNS/TCP attempt, investigate `NWPath`,
   `configd` registration and NECP decisions. If there is an attempt
   but no rendered page, investigate WebKit content process, TLS trust,
   crashes and graphics/compositing. Do not conflate background Apple
   traffic with requests from Safari.

**Current status:** Browser rendering and HTTPS page loading have **not**
passed. Keep the release labelled experimental.

## Updated evidence: later October 30 browser test

The later oneclick capture `desktop-qemu-20261030-163101/network.pcap`
*does* contain requests from Safari/WebKit toward Google. The sanitized
`tools/check-safari-pcap.py` analysis showed four
`www.google.com` DNS queries, successful A records, an outbound SYN,
an inbound SYN/ACK, a TLS ClientHello and a TLS ServerHello from a Google
IPv4 address. XNU tracing also shows
`com.apple.WebKit` network-policy results with interface index 4,
socket creation, and `connectx` returning EINPROGRESS.

This supersedes the earlier captures where there were no Google requests.
It proves DNS/TCP/TLS *transport progress*, **not a rendered webpage**.
Only roughly 517 TCP application bytes were sent by the guest on that
Google connection, versus 2762 received, consistent with TLS negotiation
without a completed HTTP request. Investigate WebKit's TLS/crypto/trust,
response handling and renderer rather than assuming the QEMU NAT path is
completely disconnected. Running QEMU directly on Windows is an
independent performance experiment and will not repair this iOS userland
issue by itself.

## Native Windows verification (30 October 2026)

The migrated guest booted under Windows QEMU 11.1 and reached the iOS
home screen and Safari. The blank Google page issue persists. On the
first native capture, iOS background services completed TCP and TLS
handshakes to Apple servers, but there was no fresh Google connection
in that capture. Do not claim Google browsing is working merely from
successful iOS background network traffic.

The private Windows packet traces are saved under
`windows-runtime/state/windows-qemu-*/network.pcap`; the native
kernel console can be inspected by passing
`--qmp-tcp tcp://127.0.0.1:4444` to `qemu-console-log.py`.

### Plain HTTP control experiment

Safari was directed to `neverssl.com` for a plain HTTP test. Its URL bar
changed to the site's subdomain, but the page remained white. The later
native capture showed 21 outbound TCP port-80 connections and Google
DNS/TLS traffic. The basic PCAP parser found **zero recognizable HTTP
request starts and zero HTTP response starts**. This parser does not
reassemble TCP streams, so these are indicators, not definitive proof
that no application data was transferred.

The blank page is therefore **not explained by TLS alone**. Next, trace
WebKit Networking's request execution and its IPC to the content process
as well as rendering errors. The sanitized analyzer now emits aggregate
HTTP request and response counts and recognizes `neverssl.com` DNS.
