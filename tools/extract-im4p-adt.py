#!/usr/bin/env python3
"""Extract d22ap.adt from the user's own Apple IMG4 DeviceTree IM4P.

The IM4P envelope is ASN.1 DER. A 'bvx2' payload is standard LZFSE; the
external lzfse CLI is compiled from the open-source lzfse submodule of
sgan81/apfs-fuse. No private Apple binary is committed to this repository.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys


def tlv(blob, offset):
    if offset >= len(blob):
        raise ValueError('Incomplete IM4P DER item')
    tag = blob[offset]
    offset += 1
    length = blob[offset]
    offset += 1
    if length & 0x80:
        count = length & 0x7f
        if count == 0 or count > 4:
            raise ValueError('Bad DER length prefix')
        length = int.from_bytes(blob[offset:offset + count], 'big')
        offset += count
    end = offset + length
    if end > len(blob):
        raise ValueError('DER item extends beyond IM4P file')
    return tag, blob[offset:end], end


def extract(path, destination, lzfse):
    blob = path.read_bytes()
    tag, outer, end = tlv(blob, 0)
    if tag != 0x30 or end != len(blob):
        raise ValueError('Not a complete DER SEQUENCE')
    parts = []
    offset = 0
    while offset < len(outer) and len(parts) < 4:
        t, payload, offset = tlv(outer, offset)
        parts.append((t, payload))
    if len(parts) != 4 or parts[0] != (0x16, b'IM4P') or (
            parts[1] != (0x16, b'dtre')) or parts[3][0] != 0x04:
        raise ValueError('Not an Apple DeviceTree (dtre) IM4P')
    payload = parts[3][1]
    if not payload.startswith(b'bvx2'):
        raise ValueError('Unsupported DeviceTree compression; expected LZFSE bvx2')
    if destination.exists():
        raise FileExistsError('Refusing to overwrite DeviceTree')
    compressed = destination.with_suffix(destination.suffix + '.lzfse')
    if compressed.exists():
        raise FileExistsError('Existing unverified compressed payload')
    compressed.write_bytes(payload)
    try:
        subprocess.run([lzfse, '-decode', '-i', str(compressed),
                        '-o', str(destination)], check=True)
        if destination.stat().st_size < 16384:
            raise ValueError('Decompressed Apple DeviceTree too small')
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import adt
        root, _ = adt.parse(destination.read_bytes())
        product = [n for n in root.children if any(
            name == 'name' and value == b'product\0'
            for name, _flags, value in n.props)]
        if not product:
            raise ValueError('Missing iPhone X /product node')
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    finally:
        compressed.unlink(missing_ok=True)
    print(f'VERIFIED_D22AP_ADT={destination} BYTES={destination.stat().st_size}',
          flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('im4p', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--lzfse', default='/usr/local/bin/lzfse')
    args = parser.parse_args()
    extract(args.im4p, args.output, args.lzfse)


if __name__ == '__main__':
    main()
