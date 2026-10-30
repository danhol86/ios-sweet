# iOS Sweet / QEMU: Safari blank-page network investigation

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
