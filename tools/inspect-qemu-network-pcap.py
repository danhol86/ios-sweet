#!/usr/bin/env python3
"""Inspect QEMU guest PCAP without exposing packet payloads.

Exit 2 with --require-tcp-syn when the guest has not attempted a TCP
connection. This is a fail-closed networking smoke gate, not a claim that
DNS/HTTPS and Safari work merely because one SYN exists.
"""
import argparse
import collections
import pathlib
import struct
import sys

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("path", type=pathlib.Path)
ap.add_argument("--require-tcp-syn", action="store_true",
                help="fail when no guest-originated TCP connection is present")
args = ap.parse_args()
path = args.path
with path.open("rb") as f:
    header = f.read(24)
    if len(header) != 24:
        raise ValueError("Invalid PCAP header")
    magic = header[:4]
    if magic in (bytes.fromhex("d4c3b2a1"), bytes.fromhex("4d3cb2a1")):
        endian = "<"
    elif magic in (bytes.fromhex("a1b2c3d4"), bytes.fromhex("a1b23c4d")):
        endian = ">"
    else:
        raise ValueError("Unknown PCAP byte order or unsupported format")
    counts = collections.Counter()
    interesting = []
    while (record := f.read(16)):
        if len(record) != 16:
            raise ValueError("Incomplete record")
        sec, usec, incl, orig = struct.unpack(endian + "IIII", record)
        packet = f.read(incl)
        if len(packet) < 14:
            counts["short ethernet"] += 1
            continue
        ether_type = struct.unpack("!H", packet[12:14])[0]
        if ether_type == 0x0806:
            counts["ARP"] += 1
        elif ether_type == 0x0800 and len(packet) >= 34:
            proto = packet[23]
            offset = 14 + (packet[14] & 15) * 4
            if proto == 6 and len(packet) >= offset + 14:
                counts["TCP"] += 1
                src, dst = struct.unpack("!HH", packet[offset:offset + 4])
                flags = packet[offset + 13]
                if flags & 2 and not flags & 16:
                    counts["TCP SYN"] += 1
                interesting.append(("TCP", src, dst, hex(flags)))
            elif proto == 17 and len(packet) >= offset + 8:
                counts["UDP"] += 1
                src, dst = struct.unpack("!HH", packet[offset:offset + 4])
                if src == 53 or dst == 53:
                    counts["DNS UDP"] += 1
                interesting.append(("UDP", src, dst, ""))
            else:
                counts["other IPv4"] += 1
        else:
            counts[f"other EtherType {ether_type:04x}"] += 1
    print("COUNTS", dict(counts))
    print("TRANSPORT", interesting[-25:])
    if args.require_tcp_syn and counts["TCP SYN"] == 0:
        print("NETWORK_SMOKE_FAIL: no guest TCP SYN; ARP/DNS alone do not prove Safari internet.",
              file=sys.stderr)
        sys.exit(2)
    if args.require_tcp_syn:
        print("GUEST_TCP_SYN_PRESENT: still verify Safari HTTP/HTTPS page content.")
