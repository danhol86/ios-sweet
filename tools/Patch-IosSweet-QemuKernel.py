#!/usr/bin/env python3
"""Create a safe, LOCAL-ONLY framebuffer keep-awake test kernel.

Temporary bridge until XNU source patch 0097 is built by GitHub Actions.
Only the exact, known QEMU development kernel is accepted. This patches
one ARM64 instruction at the *verified virtual address* of the
IOMobileFramebufferUserClient::externalMethod RequestPowerChange branch.

The original input is always read-only; the output must not exist.
No firmware or kernel binary is uploaded or packaged by this tool.
"""
import argparse
import hashlib
import os
from pathlib import Path
import struct

ORIGINAL_SHA256 = '079a3d2d1849e965f9a055f5627d64e33eab94dd9fd26411cbc717037e52825c'
PATCHED_SHA256 = '85039335d05d335d1f9b33f7c8131d274477c50020915ff0335b42428abe998a'
ADDRESS = 0xfffffe0007a68b44
OLD = bytes.fromhex('f7179f1a')  # cset w23, eq (off = scalarInput[0] == 0)
NEW = bytes.fromhex('17008052')  # mov w23, #0 (QEMU never blank screen)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def file_offset(image, address):
    if len(image) < 32 or image[:4] != bytes.fromhex('cffaedfe'):
        raise ValueError('Expected 64-bit little-endian Mach-O kernel')
    ncmds = struct.unpack_from('<I', image, 16)[0]
    sizeofcmds = struct.unpack_from('<I', image, 20)[0]
    if ncmds > 200 or sizeofcmds > len(image) - 32:
        raise ValueError('Invalid Mach-O load commands')
    pos = 32
    for _ in range(ncmds):
        if pos + 8 > len(image):
            raise ValueError('Truncated Mach-O load commands')
        cmd, cmdsize = struct.unpack_from('<II', image, pos)
        if cmdsize < 8 or pos + cmdsize > len(image):
            raise ValueError('Invalid Mach-O segment length')
        if cmd == 0x19:
            segname = image[pos+8:pos+24].split(b'\0')[0]
            vmaddr, _, diskpos, size = struct.unpack_from('<QQQQ', image, pos+24)
            if segname == b'__TEXT_EXEC' and vmaddr <= address < vmaddr + size:
                result = diskpos + address - vmaddr
                if result + len(OLD) > len(image):
                    raise ValueError('Address outside kernel image')
                return result
        pos += cmdsize
    raise ValueError('Exact expected __TEXT_EXEC address not found')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    output = args.output.absolute()
    if output.exists() or source == output or output.is_symlink():
        raise ValueError('Output must be a NEW file; original kernel cannot be overwritten')
    if not source.is_file() or source.is_symlink():
        raise ValueError('Source must be an ordinary kernel file')
    if digest(source) != ORIGINAL_SHA256:
        raise ValueError('Unknown kernel SHA-256: refuse all binary patching')
    image = bytearray(source.read_bytes())
    offset = file_offset(image, ADDRESS)
    if image[offset:offset+4] != OLD:
        raise ValueError('Unexpected framebuffer ARM64 code; refuse patch')
    image[offset:offset+4] = NEW
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(output) + '.partial')
    if partial.exists() or partial.is_symlink():
        if not partial.is_file() or partial.is_symlink():
            raise ValueError('Unsafe old kernel patch scratch file')
        partial.unlink()  # Previous interrupted attempt, only this named temp.
    try:
        with partial.open('xb') as stream:
            stream.write(image)
            stream.flush()
            os.fsync(stream.fileno())
        if digest(partial) != PATCHED_SHA256:
            raise ValueError('Patched kernel checksum did not match known candidate')
        os.replace(partial, output)
    finally:
        partial.unlink(missing_ok=True)
    assert output.stat().st_size == source.stat().st_size
    print('QEMU_ONLY_FRAMEBUFFER_KEEP_AWAKE_PATCHED')
    print('FILE_OFFSET=0x%x' % offset)
    print('SOURCE_SHA256=' + ORIGINAL_SHA256)
    print('CANDIDATE_SHA256=' + PATCHED_SHA256)


if __name__ == '__main__':
    main()
