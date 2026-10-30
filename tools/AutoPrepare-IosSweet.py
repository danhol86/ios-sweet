#!/usr/bin/env python3
"""Acquire personal iPhone X firmware directly from Apple and build locally.

This script runs in a disposable Docker helper, with the user's private
/assets directory mounted from their Windows PC. It NEVER uploads firmware.
The only downloaded public project binary is a SHA-256 pinned, open-source
XNU kernel from the project's GitHub Release. The Apple firmware is selected
by its actual signed BuildManifest for d22ap and exact iOS build 20H392.
"""
import argparse
import hashlib
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remotezip

FIRMWARE_URL = (
    'https://updates.cdn-apple.com/2025FallFCS/fullrestores/'
    '122-77006/1158E502-D76D-4226-AA06-ED5E30CD1111/'
    'iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw'
)
KERNEL_URL = (
    'https://github.com/danhol86/ios-sweet/releases/download/'
    'docker-preview-v0.1.0/kernel.development.sweet'
)
KERNEL_SHA256 = '079a3d2d1849e965f9a055f5627d64e33eab94dd9fd26411cbc717037e52825c'


def log(message):
    print(message, flush=True)


def download_kernel(assets):
    out = assets / 'kernel.development.sweet'
    if out.is_file() and sha256(out) == KERNEL_SHA256:
        log('VERIFIED_KERNEL_CACHED')
        return out
    if out.exists():
        raise RuntimeError('Unexpected kernel contents. Move it aside before retrying.')
    partial = out.with_suffix('.download')
    log('Downloading the verified open-source XNU kernel from GitHub...')
    subprocess.run(
        ['curl', '-fL', '--retry', '3', '--connect-timeout', '30',
         '--max-time', '1200', '-o', str(partial), KERNEL_URL], check=True)
    if sha256(partial) != KERNEL_SHA256:
        partial.unlink(missing_ok=True)
        raise RuntimeError('Public kernel checksum mismatch; refusing to use it')
    os.replace(partial, out)
    log('VERIFIED_OPEN_SOURCE_KERNEL_DOWNLOAD')
    return out


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as data:
        for chunk in iter(lambda: data.read(4 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def get_manifest(assets):
    dest = assets / 'firmware'
    dest.mkdir(parents=True, exist_ok=True)
    entries = remotezip.central_dir(FIRMWARE_URL)
    by_name = {e[0]: e for e in entries}
    if 'BuildManifest.plist' not in by_name:
        raise RuntimeError('Apple firmware ZIP has no BuildManifest.plist')
    if not (dest / 'BuildManifest.plist').is_file():
        remotezip.extract(FIRMWARE_URL, by_name['BuildManifest.plist'], str(dest))
    manifest = plistlib.loads((dest / 'BuildManifest.plist').read_bytes())
    if (manifest.get('ProductVersion'), manifest.get('ProductBuildVersion')) != (
            '16.7.16', '20H392'):
        raise RuntimeError('Unexpected Apple firmware version')
    matches = [b for b in manifest.get('BuildIdentities', [])
               if b.get('Info', {}).get('DeviceClass') == 'd22ap'
               and b.get('Info', {}).get('RestoreBehavior') == 'Erase']
    if len(matches) != 1:
        raise RuntimeError('Expected one iPhone X d22ap restore identity')
    contents = matches[0]['Manifest']
    wanted = {
        'os': contents['OS']['Info']['Path'],
        'sysos': contents['Cryptex1,SystemOS']['Info']['Path'],
        'appos': contents['Cryptex1,AppOS']['Info']['Path'],
        'dt': contents['DeviceTree']['Info']['Path']
    }
    for name, member in wanted.items():
        if member not in by_name or '..' in Path(member).parts or member.startswith('/'):
            raise RuntimeError(f'Unsafe or missing {name} ZIP member')
    return dest, by_name, wanted


def extract_member(dest, by_name, member):
    out = dest / member
    if out.is_file() and out.stat().st_size == by_name[member][3]:
        return out
    log(f'Downloading Apple firmware component: {member}')
    remotezip.extract(FIRMWARE_URL, by_name[member], str(dest))
    if not out.is_file() or out.stat().st_size != by_name[member][3]:
        raise RuntimeError('Incomplete firmware download: ' + member)
    return out


def prepare_device_tree(dest, by_name, parts, assets, lzfse):
    target = assets / 'd22ap.adt'
    if target.is_file() and target.stat().st_size > 16384:
        log('D22AP_CACHED')
        return target
    if target.exists():
        raise RuntimeError('Unrecognised cached DeviceTree; remove manually')
    source = extract_member(dest, by_name, parts['dt'])
    tool = Path(__file__).with_name('extract-im4p-adt.py')
    subprocess.run([sys.executable, str(tool), str(source), str(target),
                    '--lzfse', lzfse], check=True)
    return target


def prepare_root(dest, by_name, parts, assets):
    root = assets / 'ios16-net-test.raw'
    if root.is_file() and root.stat().st_size == (16 << 30):
        log('EXISTING_IOS_DISK_PRESERVED')
        return root
    if root.exists():
        raise RuntimeError('Existing unexpected iOS image. No overwrite attempted.')
    required = [extract_member(dest, by_name, parts[n])
                for n in ('os', 'sysos', 'appos')]
    candidate = assets / 'ios16-net-test.building.raw'
    for incomplete in (candidate, Path(str(candidate)+'.ext4-staging'),
                       Path(str(candidate)+'.tar-staging')):
        if incomplete.exists():
            if incomplete.is_symlink() or not incomplete.is_file():
                raise RuntimeError('Unexpected temporary root build path; refusing deletion')
            log('Removing failed disposable root component: '+incomplete.name)
            incomplete.unlink()
    log('Creating private iOS HFSX disk inside Docker. This may need tens of GB of disk space...')
    os.environ['IOS_SWEET_HFS_MOUNT'] = 'loop-ext4-stage'
    build = Path(__file__).with_name('mkiosroot.sh')
    subprocess.run(['bash', str(build), *map(str, required), str(candidate), '16G'],
                   check=True)
    mount = Path('/tmp/iossweet-root-tweaks')
    mount.mkdir(exist_ok=True)
    try:
        subprocess.run(['guestmount', '-a', str(candidate), '-m', '/dev/sda:/:force,rw',
                        '--rw', str(mount)], check=True)
        subprocess.run([sys.executable,
                        str(Path(__file__).with_name('sweet-root-tweaks.py')),
                        str(mount)], check=True)
    finally:
        subprocess.run(['guestunmount', str(mount)], check=False)
    if candidate.stat().st_size != (16 << 30):
        raise RuntimeError('Guest image size failed verification')
    for path in ('/sbin/launchd',
                 '/System/Library/xpc/launchd.plist',
                 '/Applications/MobileSafari.app'):
        command = ['guestfish', '--ro', '-a', str(candidate),
                   '-m', '/dev/sda:/', 'is-file' if path.endswith('plist')
                   or path.endswith('/launchd') else 'is-dir', path]
        result = subprocess.run(command, check=True, text=True,
                                capture_output=True)
        if result.stdout.strip() != 'true':
            raise RuntimeError('Generated disk lacks required iOS path: '+path)
    os.replace(candidate, root)
    log('PREPARED_PRIVATE_HFSX_ROOT')
    return root


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mode', choices=('inspect', 'device-tree', 'full'),
                    default='full')
    ap.add_argument('--lzfse', default='/usr/local/bin/lzfse')
    ap.add_argument('--assets', type=Path, default=Path('/assets'))
    args = ap.parse_args()
    assets = args.assets.resolve()
    assets.mkdir(parents=True, exist_ok=True)
    dest, entries, wanted = get_manifest(assets)
    log('VERIFIED_APPLE_FIRMWARE iPhone10,3 iOS=16.7.16 build=20H392')
    for name, path in wanted.items():
        log(f'COMPONENT {name}: {path} {entries[path][3]} bytes')
    if args.mode == 'inspect':
        return
    download_kernel(assets)
    prepare_device_tree(dest, entries, wanted, assets, args.lzfse)
    if args.mode == 'full':
        prepare_root(dest, entries, wanted, assets)
    log('IOS_SWEET_AUTO_ASSETS_READY')


if __name__ == '__main__':
    main()
