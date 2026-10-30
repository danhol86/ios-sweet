# iOS Sweet Windows Docker preview

This is an **experimental, code-only** release for developers. It provides a
Windows batch launcher, an ARM64 QEMU container, input/framebuffer viewing,
isolated QCOW2 persistence, and automatic QEMU guest IPv4/DNS preparation.
It does **not** include a bootable Apple iOS operating system.

**Install:** Download `ios-sweet-docker-oneclick.zip`, extract it, then
double-click `Install-iOS-Sweet.cmd`. See
[the detailed GitHub installation guide](https://github.com/danhol86/ios-sweet/blob/main/docs/GITHUB_INSTALL.md).

**Requires:** Docker Desktop (Linux containers), your own prepared 16 GiB
iOS 16 HFSX root disk, a matching network-enabled QEMU SWEET XNU kernel,
and an iPhone X D22AP device tree. Those files must be supplied separately.
There is no extra Ubuntu/WSL installation.

**Verified:** Fresh Docker build, automatic private-overlay preparation,
real iOS lock screen, simulated touch input, Safari launch, guest DNS
requests and real outbound TCP SYNs.

**Unresolved:** Safari was observed showing `google.com` in the address bar
with a loading indicator and a blank white page. Do not treat this as fully
functional browser networking or a production-ready simulator.

The release intentionally excludes proprietary Apple images, user logs,
tokens, devices, and local private configuration. It includes only the
verified project sources and the project's own small ARM64 DNS bootstrap.
