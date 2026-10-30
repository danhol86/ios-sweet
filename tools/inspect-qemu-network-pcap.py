#!/usr/bin/env python3
"""Summarize QEMU test-guest PCAP without printing packet payloads."""
import collections
import pathlib
import struct
import sys

path = pathlib.Path(sys.argv[1])
with path.open("rb") as f:
    header = f.read(24)
    if len(header) != 24:
        raise ValueError("Invalid PCAP header")
    magic = header[:4]
    endian = "<" if magic in (bytes.fromhex("d4c3b2a1"), bytes.fromhex("4d3cb2a1")) else ">"
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
