#!/usr/bin/env python3
"""Add an iOS Sweet-only networking seeder job to a COPY of launchd.plist.

Usage:
    python prepare-ios-network-seed.py ORIGINAL_LAUNCHD.plist NEW_LAUNCHD.plist

Only install the output in a NEW disposable QCOW2 image. The original iOS
image, existing services, and copied source manifest are never modified.
"""
import argparse
from pathlib import Path
import plistlib

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
if args.output.exists() or args.source.resolve() == args.output.resolve():
    parser.error('Refusing to modify existing file')

original = plistlib.loads(args.source.read_bytes())
jobs = original.get('LaunchDaemons')
if not isinstance(jobs, dict) or len(jobs) < 300:
    parser.error('Unexpected iOS 16 consolidated launchd cache')
entry = '/System/Library/LaunchDaemons/org.iossweet.qemu-network.plist'
if entry in jobs or any(j.get('Label') == 'org.iossweet.qemu-network'
                        for j in jobs.values()):
    parser.error('Seeder already installed')
jobs[entry] = {
    'Label': 'org.iossweet.qemu-network',
    'ProgramArguments': ['/usr/libexec/iossweet-net-seed'],
    'RunAtLoad': True,
    'KeepAlive': False,
    'UserName': 'root',
}
with args.output.open('xb') as fp:
    plistlib.dump(original, fp, fmt=plistlib.FMT_BINARY)
written = plistlib.loads(args.output.read_bytes())
assert written['LaunchDaemons'][entry] == jobs[entry]
assert len(written['LaunchDaemons']) == len(jobs)
print('PREPARED_IOS_NETWORK_STARTUP', entry, len(jobs))
