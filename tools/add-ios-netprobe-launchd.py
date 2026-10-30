#!/usr/bin/env python3
"""Inject an optional probe into a COPY of an iOS launchd cache plist.

The actual boot manifest is /System/Library/xpc/launchd.plist, not the
individual files in /System/Library/LaunchDaemons.  Only use with a
disposable QCOW2 overlay; never write to a user's original raw iOS disk.
"""
import argparse
from pathlib import Path
import plistlib
import sys

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('original', type=Path, help='binary plist copied from guest')
p.add_argument('output', type=Path, help='new file, must not already exist')
p.add_argument('--program', default='/private/var/tmp/iossweet-net-probe')
p.add_argument('--replace-disabled-bootpd', action='store_true',
               help='In a disposable guest only, repurpose pre-existing disabled bootpd job')
p.add_argument('--replace-reportcrash', action='store_true',
               help='In a disposable guest only, temporarily repurpose enabled ReportCrash job')
a = p.parse_args()
if a.replace_disabled_bootpd and a.replace_reportcrash:
    p.error('Choose at most one existing service to replace')
if a.output.exists() or a.original.resolve() == a.output.resolve():
    p.error('Refusing to modify an existing file')
if a.program not in ('/private/var/tmp/iossweet-net-probe',
                     '/usr/libexec/iossweet-net-probe'):
    p.error('Probe program path not allowed')
data = plistlib.loads(a.original.read_bytes())
jobs = data.get('LaunchDaemons')
if not isinstance(jobs, dict) or len(jobs) < 100:
    p.error('Unexpected iOS launchd cache manifest')
key = ('/System/Library/LaunchDaemons/bootps.plist'
       if a.replace_disabled_bootpd else
       '/System/Library/LaunchDaemons/com.apple.ReportCrash.plist'
       if a.replace_reportcrash else
       '/System/Library/LaunchDaemons/com.iossweet.netprobe.plist')
if a.replace_disabled_bootpd:
    original = jobs.get(key, {})
    if original.get('Label') != 'com.apple.bootpd' or original.get('Disabled') is not True:
        p.error('Expected the original bootpd entry to be disabled')
elif a.replace_reportcrash:
    original = jobs.get(key, {})
    if original.get('Label') != 'com.apple.ReportCrash':
        p.error('Expected a known existing ReportCrash entry')
elif key in jobs or any(j.get('Label') == 'com.iossweet.netprobe'
                      for j in jobs.values()):
    p.error('The probe is already installed')
jobs[key] = {
    'Label': ('com.apple.bootpd' if a.replace_disabled_bootpd
              else 'com.apple.ReportCrash' if a.replace_reportcrash
              else 'com.iossweet.netprobe'),
    'ProgramArguments': [a.program],
    'Disabled': False,
    'RunAtLoad': True,
    'KeepAlive': False,
    'StandardOutPath': '/dev/console',
    'StandardErrorPath': '/dev/console',
}
with a.output.open('xb') as f:
    plistlib.dump(data, f, fmt=plistlib.FMT_BINARY)
verify = plistlib.loads(a.output.read_bytes())
if len(verify['LaunchDaemons']) != len(jobs):
    raise RuntimeError('Probe install verification failed')
print('LAUNCHD_PROBE_PREPARED',len(jobs),key,a.output)
