#!/usr/bin/env python3
"""Read the original SWEET kernel's 4 MiB in-memory console ring via QMP.

This works when sweetfb_noconsole=1 (Apple boot logo displayed) and does
not modify the guest or the verified root filesystem. Captured logs may
contain private device/session data; keep them in ignored local run folders.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

qemu_script = Path(__file__).resolve().with_name("qemu-sweet.py")
spec = importlib.util.spec_from_file_location("qemu_sweet", qemu_script)
qemu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qemu)
RING_SIZE = 4 * 1024 * 1024

def symbol_phys(kernel, payload, name):
    syms = subprocess.check_output(
        ["llvm-nm", "--defined-only", str(kernel)], text=True)
    addresses = [int(row.split()[0], 16) for row in syms.splitlines()
                 if row.split()[-1:] == [name]]
    if len(addresses) != 1:
        raise ValueError(f"expected exactly one {name} symbol; got {len(addresses)}")
    base, entry, adt, adtsize, end, phys, size = struct.unpack_from("<7Q", payload, 0x10)
    return phys + addresses[0] - base

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run", type=Path, help="active QEMU output folder containing mon.sock and payload.bin")
    ap.add_argument("--kernel", type=Path, help="matching unstripped kernel; default: project xnu/out-qemu/kernel.development.sweet")
    ap.add_argument("--payload", type=Path, help="SWEETXNU payload file; defaults to run/payload.bin")
    ap.add_argument("--tail", type=int, default=15000, help="display only last N bytes per snapshot (0 means all)")
    ap.add_argument("--follow", action="store_true", help="print only new console bytes while QEMU remains active")
    ap.add_argument("--interval", type=float, default=2)
    ap.add_argument("--seconds", type=float, default=90, help="max follow duration")
    ap.add_argument("--output", type=Path, help="write raw UTF-8 console bytes to an output file (instead of stdout)")
    a = ap.parse_args()
    kernel = a.kernel or qemu_script.parent.parent/"xnu/out-qemu/kernel.development.sweet"
    payload = (a.payload or a.run/"payload.bin").read_bytes()
    total_pa = symbol_phys(kernel,payload,"_sweet_log_total")
    ring_pa = symbol_phys(kernel,payload,"_sweet_log_ring")
    if ring_pa != total_pa + 8:
        ap.error("SWEET console symbols are not contiguous; update this tool before using it")
    print(f"[*] Reading SWEET console at physical {total_pa:#x} / ring {ring_pa:#x}",file=sys.stderr)
    prev_total = None
    start=time.monotonic()
    while True:
        dump=a.run/"qemu-console-dump.raw"
        qemu.qmp(str(a.run/"mon.sock"),pmemsave=(total_pa,8+RING_SIZE,str(dump)))
        buf=dump.read_bytes()
        dump.unlink(missing_ok=True)
        if len(buf) != 8+RING_SIZE:
            raise ValueError(f"invalid console read length {len(buf)}")
        total=struct.unpack_from("<Q",buf)[0]
        if total > (1<<50):
            raise ValueError(f"invalid console total={total}; wrong kernel or guest not initialized")
        ring=buf[8:]
        available=min(total,RING_SIZE)
        end=total%RING_SIZE
        start_pos=(end-available)%RING_SIZE
        rotated=(ring[start_pos:]+ring[:start_pos]) if total >= RING_SIZE else ring[:available]
        if prev_total is None:
            selected=rotated[-a.tail:] if a.tail else rotated
        else:
            delta=min(total-prev_total,RING_SIZE) if total>=prev_total else available
            selected=rotated[-delta:] if delta else b""
        print(f"[*] Console total={total}, emitted={len(selected)}",file=sys.stderr)
        if selected:
            if a.output:
                with a.output.open("ab" if prev_total is not None else "wb") as f:
                    f.write(selected)
            else:
                sys.stdout.write(selected.decode("utf-8","replace"))
                sys.stdout.flush()
        prev_total=total
        if not a.follow or time.monotonic()-start >= a.seconds:
            break
        time.sleep(a.interval)

if __name__=="__main__":
    main()
