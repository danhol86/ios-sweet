#!/usr/bin/env python3
"""Offline, read-only iOS Sweet boot-crash signature comparison.

Usage:
    python tools/analyze-qemu-crashes.py windows-runtime/network-probe/*.log

Console snapshots from the same QEMU run can contain repeated crash records;
use one log per run for cross-boot counts. The report shows image-relative
stack offsets, not raw relocated addresses or guest personal information.
Exit 0 means the analysis completed, NOT that all services are healthy.
"""

import argparse
from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import re


HEADER = re.compile(
    r"^CRASH (?P<name>[-\w.]+)\[(?P<pid>\d+)\] sig (?P<sig>\d+)"
    r".*? mh (?P<image>0x[0-9a-fA-F]+)\s*$")
BACKTRACE = re.compile(r"^CRASH (?P<name>[-\w.]+) bt (?P<frames>(?:0x[0-9a-fA-F]+\s*)+)$")
REASON = re.compile(r"^CRASH (?P<name>[-\w.]+) reason (?P<reason>.*)$")
HEX = re.compile(r"0x[0-9a-fA-F]+")
PROCESS = re.compile(r"^exec (?P<name>[-\w.]+)$")
MAX_IMAGE_OFFSET = 0x2000000
# Apple's XNU bsd/sys/reason.h and bsd/sys/kern_memorystatus.h:
# 1 = OS_REASON_JETSAM; 7 = JETSAM_REASON_MEMORY_PERPROCESSLIMIT.
# Distinguish a process exceeding its own limit from global guest/host OOM.
EXIT_REASON = re.compile(r'^ns\s+(\d+)\s+code\s+0x([0-9a-fA-F]+):')
JETSAM_CAUSES = {
    1: 'generic',
    2: 'memory_highwater',
    4: 'memory_vm_page_shortage',
    5: 'memory_process_thrashing',
    6: 'memory_file_cache_thrashing',
    7: 'memory_per_process_limit',
    9: 'idle_exit',
    10: 'zone_map_exhaustion',
    11: 'memory_compressor_thrashing',
    12: 'memory_compressor_space_shortage',
    13: 'low_swap',
    14: 'memory_sustained_pressure',
}


def classify_reason(reason):
    match = EXIT_REASON.match(reason)
    if match is None:
        return {'namespace': 'unknown', 'cause': 'unknown'}
    namespace, code = int(match.group(1)), int(match.group(2), 16)
    if namespace == 1:
        return {'namespace': 'jetsam', 'cause': JETSAM_CAUSES.get(code, f'unknown_code_{code}')}
    if namespace == 2:
        return {'namespace': 'signal', 'cause': f'signal_code_{code}'}
    return {'namespace': f'namespace_{namespace}', 'cause': f'code_{code}'}


@dataclass(frozen=True)
class Crash:
    name: str
    signal: int
    reason: str
    frames: tuple[str, ...]

    def signature(self):
        return (self.name, self.signal, self.reason, self.frames)


def normalize_frames(frames: str, image_base: int) -> tuple[str, ...]:
    """Preserve positions but hide ASLR and unrelated library addresses."""
    result = []
    for frame in HEX.findall(frames):
        absolute = int(frame, 16)
        if image_base <= absolute < image_base + MAX_IMAGE_OFFSET:
            result.append(f"+0x{absolute-image_base:x}")
        else:
            result.append("external")
    return tuple(result)


def analyze(text: str) -> tuple[list[Crash], set[str]]:
    lines = text.splitlines()
    launched = {m.group('name') for line in lines if (m := PROCESS.fullmatch(line))}
    crashes = []
    for index, line in enumerate(lines):
        match = HEADER.fullmatch(line)
        if not match:
            continue
        name = match.group('name')
        image_base = int(match.group('image'), 16)
        frames = ()
        reason = 'unreported'
        # Stop at the next process crash to avoid attaching someone else's
        # stack after truncated QMP snapshots.
        for detail in lines[index+1:index+12]:
            if HEADER.fullmatch(detail):
                break
            bt = BACKTRACE.fullmatch(detail)
            why = REASON.fullmatch(detail)
            if bt and bt.group('name') == name:
                frames = normalize_frames(bt.group('frames'), image_base)
            if why and why.group('name') == name:
                reason = why.group('reason')
        crashes.append(Crash(name, int(match.group('sig')), reason, frames))
    return crashes, launched


def compare(files):
    groups = defaultdict(list)
    launch_counts = defaultdict(int)
    for source in files:
        source = Path(source)
        crashes, launched = analyze(source.read_text(encoding='utf-8', errors='replace'))
        for name in launched:
            launch_counts[name] += 1
        # Many crash lines can be repeated in a single *snapshot*. Distinct
        # signatures count once per input file; callers choose distinct runs.
        for crash in {crash.signature(): crash for crash in crashes}.values():
            groups[crash.signature()].append(source.name)
    return {'files_read': len(files),
            'signatures': [
                {'service': key[0], 'signal': key[1], 'reason': key[2],
                 'termination': classify_reason(key[2]),
                 'relative_frames': list(key[3]), 'observations': len(names),
                 'files': sorted(names), 'service_exec_log_count': launch_counts[key[0]]}
                for key, names in sorted(groups.items(),
                                         key=lambda item: (-len(item[1]), item[0][0]))]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs', type=Path, nargs='+', help='One extracted console log per boot')
    args = parser.parse_args()
    for source in args.logs:
        if not source.is_file():
            parser.error(f'Boot log not found: {source}')
    print(json.dumps(compare(args.logs), indent=2))


if __name__ == '__main__':
    main()
