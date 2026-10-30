#!/usr/bin/env python3
"""Apply the verified iOS 16.7.16 MobileGestalt workaround LOCALLY.

The iPhone X's stock InstalledContentLibrary calls MGCopyAnswer from
_GenerateBuiltInAppInstallSessionID. In the experimental QEMU guest the
UniqueDeviceID lookup can stall LaunchServices, preventing SpringBoard's
first boot. The already-interactive privately owned test root has a single
4-byte modification at the call site, replacing BL MGCopyAnswer with
MOV X0, #0 (the nil result). The SHA-256 checks below were obtained by
comparing both user's private iOS filesystem caches byte-for-byte.

This tool only accepts an explicit private disk path; it neither contains nor
publishes Apple binary data. It refuses any unexpected iOS version, cache,
instructions, or checksum. It is a QEMU-only compatibility workaround, not
an Apple-supported or security-equivalent device identity implementation.
"""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

CACHE = '/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64.15'
ORIGINAL_SHA256 = 'd1bd6b1db6087199955f7ea475af4c2537da25d4b588011664c518a13ae666f6'
PATCHED_SHA256 = 'cd89323e7a17daa5e1ce3af89ed252fa5be9ccd2eb0b8751e7d81fbc832bf4d5'
FILE_BYTES = 115097600
INSTRUCTION_OFFSET = 0x1619F0C
ORIGINAL_INSTRUCTION = bytes.fromhex('02255e95')
PATCHED_INSTRUCTION = bytes.fromhex('000080d2')


def checksum(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for data in iter(lambda: source.read(4 << 20), b''):
            h.update(data)
    return h.hexdigest()


def guestfish(*args, capture=False):
    env = dict(os.environ, LIBGUESTFS_BACKEND='direct',
               LIBGUESTFS_MEMSIZE='512')
    result = subprocess.run(['guestfish', *map(str, args)], check=True,
                            capture_output=capture, text=capture, env=env)
    return result.stdout.strip() if capture else None


def patch(disk, assets_dir):
    disk = disk.resolve(strict=True)
    assets_dir = assets_dir.resolve(strict=True)
    if not disk.is_file() or disk.is_symlink() or disk.parent != assets_dir:
        raise ValueError('Only a regular generated disk directly inside the private assets directory is permitted')
    if disk.name not in ('ios16-net-test.raw',
                         'ios16-net-test.building.raw'):
        raise ValueError('Refusing to patch an unknown user/private iOS disk')
    if disk.stat().st_size != 16 * (1 << 30):
        raise ValueError('Expected a 16 GiB iOS 16.7.16 generated raw disk')

    with tempfile.TemporaryDirectory(prefix='iossweet-mg-', dir='/tmp') as td:
        local = Path(td) / 'dyld.15'
        print('Checking exact local iOS 16.7.16 cache; no data uploaded...', flush=True)
        guestfish('--ro', '-a', disk, '-m', '/dev/sda:/',
                  'download', CACHE, local)
        if local.stat().st_size != FILE_BYTES:
            raise ValueError('Unrecognised iOS dyld subcache size')
        initial = checksum(local)
        if initial == PATCHED_SHA256:
            print('IOS_SWEET_MG_COMPAT_ALREADY_PRESENT', flush=True)
            return
        if initial != ORIGINAL_SHA256:
            raise ValueError('Unknown iOS cache; compatibility patch REFUSED')
        with local.open('r+b') as f:
            f.seek(INSTRUCTION_OFFSET)
            if f.read(4) != ORIGINAL_INSTRUCTION:
                raise ValueError('Expected ARM64 MGCopyAnswer call was not found')
            f.seek(INSTRUCTION_OFFSET)
            f.write(PATCHED_INSTRUCTION)
            f.flush()
            os.fsync(f.fileno())
        if checksum(local) != PATCHED_SHA256:
            raise ValueError('Exact patched-cache SHA256 mismatch')
        guestfish('-a', disk, 'run', ':', 'mount-options',
                  'force,rw', '/dev/sda', '/', ':', 'upload', local, CACHE)
        observed = guestfish('--ro', '-a', disk, '-m', '/dev/sda:/',
                             'checksum', 'sha256', CACHE, capture=True)
        if observed != PATCHED_SHA256:
            raise ValueError('Installed iOS cache failed post-write checksum verification; discard the incomplete build')
        print('IOS_SWEET_MG_COMPAT_VERIFIED QEMU_ONLY=yes', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disk', type=Path, required=True)
    parser.add_argument('--assets-dir', type=Path, default=Path('/assets'))
    args = parser.parse_args()
    patch(args.disk, args.assets_dir)


if __name__ == '__main__':
    main()
