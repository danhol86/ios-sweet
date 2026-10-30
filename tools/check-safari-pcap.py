#!/usr/bin/env python3
"""Summarise QEMU guest network traffic without exposing packet payloads.

This is read-only. Output deliberately omits full URLs, credentials, and
arbitrary hostnames. It distinguishes kernel TCP connectivity from real
HTTP/TLS flows to sites used in the Safari smoke test.
"""
import collections
import ipaddress
from pathlib import Path
import struct
import sys

TRACK = ('google.com', 'example.com')


def tls_sni(payload):
    if len(payload) < 9 or payload[:1] != b'\x16' or payload[5] != 1:
        return None
    limit = min(len(payload), 5 + int.from_bytes(payload[3:5], 'big'))
    pos = 9
    if pos + 34 > limit:
        return None
    pos += 34
    if pos >= limit:
        return None
    sid = payload[pos]
    pos += 1 + sid
    if pos + 2 > limit:
        return None
    cipher = int.from_bytes(payload[pos:pos + 2], 'big')
    pos += 2 + cipher
    if pos >= limit:
        return None
    compression = payload[pos]
    pos += 1 + compression
    if pos + 2 > limit:
        return None
    remaining = int.from_bytes(payload[pos:pos + 2], 'big')
    pos += 2
    end = min(pos + remaining, limit)
    while pos + 4 <= end:
        t, n = struct.unpack_from('!HH', payload, pos)
        pos += 4
        if pos + n > end:
            return None
        if t == 0 and n >= 5:
            ext = payload[pos:pos+n]
            namelen = int.from_bytes(ext[3:5], 'big')
            if ext[2] == 0 and len(ext) >= 5 + namelen:
                return ext[5:5 + namelen].decode('ascii','replace').lower()
        pos += n
    return None


def dns_name(data, pos):
    labels = []
    for _ in range(32):
        if pos >= len(data):
            return None, pos
        n = data[pos]
        pos += 1
        if n == 0:
            return '.'.join(labels), pos
        if n & 0xc0 or pos + n > len(data):
            return None, pos
        labels.append(data[pos:pos + n].decode('ascii', 'replace').lower())
        pos += n
    return None, pos


def analyse(filename):
    src = str(filename)
    counts = collections.Counter()
    qnames = collections.Counter()
    google_ips = set()
    tcp_syn_dest = collections.Counter()
    streams = collections.defaultdict(lambda: collections.Counter())
    tls_names = collections.Counter()
    with open(src, 'rb') as fp:
        header = fp.read(24)
        if header[:4] != b'\xd4\xc3\xb2\xa1':
            raise RuntimeError('Expected little-endian Ethernet PCAP')
        if struct.unpack_from('<I', header, 20)[0] != 1:
            raise RuntimeError('Expected Ethernet PCAP')
        while chunk := fp.read(16):
            if len(chunk) != 16:
                break
            _, _, n, _ = struct.unpack('<IIII', chunk)
            pkt = fp.read(n)
            if len(pkt) < 34 or pkt[12:14] != b'\x08\x00':
                continue
            length = (pkt[14] & 0x0f) * 4
            ipoff = 14 + length
            if len(pkt) < ipoff + 8:
                continue
            proto = pkt[23]
            addr = str(ipaddress.IPv4Address(pkt[26:30]))
            remote = str(ipaddress.IPv4Address(pkt[30:34]))
            if proto == 17:
                sport, dport, _, _ = struct.unpack_from('!HHHH', pkt, ipoff)
                if {sport, dport} & {53}:
                    data = pkt[ipoff + 8:]
                    if len(data) < 12:
                        continue
                    qr = bool(data[2] & 0x80)
                    name, pos = dns_name(data, 12)
                    if name and any(t in name for t in TRACK):
                        qnames[name] += 1
                    if qr and name and 'google.com' in name:
                        # Minimal A record parser; CNAME and compression are
                        # not dereferenced. This is only for smoke evidence.
                        num = struct.unpack_from('!H', data, 6)[0]
                        pos += 4
                        for _ in range(min(num, 30)):
                            if pos + 12 > len(data):
                                break
                            if data[pos] & 0xc0 == 0xc0:
                                pos += 2
                            else:
                                _, pos = dns_name(data, pos)
                            if pos + 10 > len(data):
                                break
                            typ, _, _, rdlen = struct.unpack_from('!HHIH', data, pos)
                            pos += 10
                            if pos + rdlen > len(data):
                                break
                            if typ == 1 and rdlen == 4:
                                google_ips.add(str(ipaddress.IPv4Address(data[pos:pos + 4])))
                            pos += rdlen
                continue
            if proto != 6 or len(pkt) < ipoff + 20:
                continue
            sport, dport = struct.unpack_from('!HH', pkt, ipoff)
            flags = pkt[ipoff + 13]
            hdr_len = (pkt[ipoff + 12] >> 4) * 4
            payload = pkt[ipoff + hdr_len:]
            from_guest = addr == '10.0.2.15'
            if from_guest and flags & 2 and not flags & 16:
                tcp_syn_dest[(remote, dport)] += 1
            if dport in (80, 443) and from_guest:
                target = remote
                if flags & 2:
                    streams[target]['out_syn'] += 1
                if payload:
                    streams[target]['out_bytes'] += len(payload)
                if payload.startswith(b'\x16\x03') and len(payload) >= 6:
                    if payload[5] == 1:
                        streams[target]['client_hello'] += 1
                        name = tls_sni(payload)
                        if name:
                            bucket = next((t for t in TRACK if t in name),
                                          'apple' if name.endswith('.apple.com') else 'other')
                            tls_names[bucket] += 1
                if payload.startswith(b'GET ') or payload.startswith(b'HEAD '):
                    streams[target]['http_request'] += 1
            if sport in (80, 443) and remote == '10.0.2.15':
                target = addr
                if (flags & 18) == 18:
                    streams[target]['in_synack'] += 1
                if payload:
                    streams[target]['in_bytes'] += len(payload)
                if payload.startswith(b'\x16\x03') and len(payload) >= 6:
                    if payload[5] == 2:
                        streams[target]['server_hello'] += 1
                if payload.startswith(b'HTTP/'):
                    streams[target]['http_response'] += 1
                if payload.startswith(b'\x15\x03'):
                    streams[target]['tls_alert'] += 1
    print('GOOGLE_DNS_QUERIES', dict(qnames))
    print('GOOGLE_IPV4_ANSWERS', sorted(google_ips))
    print('TCP_SYN_COUNT', sum(tcp_syn_dest.values()))
    print('PORT_80_CONNECTIONS', sum(v for (ip,p),v in tcp_syn_dest.items() if p == 80))
    print('PORT_443_CONNECTIONS', sum(v for (ip,p),v in tcp_syn_dest.items() if p == 443))
    print('TLS_CLIENT_HELLOS', sum(x.get('client_hello', 0) for x in streams.values()))
    print('TLS_SERVER_HELLOS', sum(x.get('server_hello', 0) for x in streams.values()))
    print('TLS_ALERTS', sum(x.get('tls_alert', 0) for x in streams.values()))
    print('TLS_SNI_CATEGORIES', dict(tls_names))
    print('GOOGLE_CONNECTIONS', {ip: dict(streams[ip]) for ip in sorted(google_ips)
          if ip in streams})


if __name__ == '__main__':
    analyse(Path(sys.argv[1]))
