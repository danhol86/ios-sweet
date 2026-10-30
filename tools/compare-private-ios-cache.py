#!/usr/bin/env python3
"""Compare two locally extracted personal iOS subcaches byte-for-byte.

Never submit cache contents to a remote service or commit extracted binaries.
Print only bounded offsets and short surrounding machine-code bytes.
"""
import argparse
import hashlib
import mmap
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda: f.read(4 << 20), b''):
            h.update(data)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('working', type=Path)
    parser.add_argument('original', type=Path)
    args = parser.parse_args()
    with args.working.open('rb') as wf, args.original.open('rb') as of:
        if wf.seek(0, 2) != of.seek(0, 2):
            raise SystemExit('File sizes differ; cannot infer a minimal code patch')
        wf.seek(0)
        of.seek(0)
        with mmap.mmap(wf.fileno(), 0, access=mmap.ACCESS_READ) as w, mmap.mmap(
                of.fileno(), 0, access=mmap.ACCESS_READ) as o:
            changes = []
            previous = None
            for base in range(0, len(o), 1 << 20):
                a = w[base:base + (1 << 20)]
                b = o[base:base + (1 << 20)]
                if a == b:
                    previous = None
                    continue
                for i, (av, bv) in enumerate(zip(a, b)):
                    if av == bv:
                        previous = None
                        continue
                    offset = base + i
                    if previous is not None and previous[1] == offset:
                        previous[1] += 1
                    else:
                        previous = [offset, offset + 1]
                        changes.append(previous)
                    if len(changes) > 1000:
                        raise SystemExit('More than 1000 independent changes; refusing unsafe patch derivation')
            print('WORKING_SHA256', sha256(args.working))
            print('ORIGINAL_SHA256', sha256(args.original))
            print('DIFFERENT_RANGES', len(changes))
            for start, end in changes[:30]:
                print(f'OFFSET=0x{start:x} LENGTH={end-start}',
                      'ORIGINAL=', o[start:end].hex(), 'WORKING=', w[start:end].hex())
                lo = max(0, start-16)
                hi = min(len(o), end+16)
                print('  ORIGINAL_CONTEXT=', o[lo:hi].hex())
                print('  WORKING_CONTEXT=', w[lo:hi].hex())


if __name__ == '__main__':
    main()
