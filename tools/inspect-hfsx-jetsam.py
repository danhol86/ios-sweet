#!/usr/bin/env python3
"""Read-only, targeted jetsam/launchd policy inspection of a private HFSX root.

Never mounts or modifies the image. The only catalog entries whose data forks
are read are the known launchd plist and two D22/D221 jetsam policy files.
The report contains selected service/policy fields, not arbitrary user data.
Requires no external Python packages.
"""

import argparse
import json
from pathlib import Path
import plistlib


BLOCK_HEADER = 1024
MAX_CATALOG_NODES = 50000
MAX_PLIST_BYTES = 4 * 1024 * 1024
TARGETS = {
    '/iOSRoot/System/Library/xpc/launchd.plist',
    '/iOSRoot/System/Library/LaunchDaemons/com.apple.driverkitd.plist',
    '/iOSRoot/System/Library/LaunchDaemons/com.apple.jetsamproperties.D22.plist',
    '/iOSRoot/System/Library/LaunchDaemons/com.apple.jetsamproperties.D221.plist',
}


def be(data, offset, size):
    return int.from_bytes(data[offset:offset + size], 'big')


def decode_record(data, offset):
    """Decode a catalog leaf key and its file/folder fork metadata."""
    key_length = be(data, offset, 2)
    if key_length < 6 or offset + 2 + key_length > len(data):
        raise ValueError('Invalid HFSX catalog record key')
    parent = be(data, offset + 2, 4)
    characters = be(data, offset + 6, 2)
    if characters * 2 + 6 > key_length:
        raise ValueError('Invalid HFSX Unicode filename')
    name = data[offset + 8:offset + 8 + characters * 2].decode('utf-16-be')
    entry = offset + 2 + key_length
    entry += entry % 2
    kind = be(data, entry, 2)
    result = {'name': name, 'parent': parent, 'kind': kind}
    if kind == 1:
        result['id'] = be(data, entry + 8, 4)
    elif kind == 2:
        result['size'] = be(data, entry + 88, 8)
        result['extents'] = tuple(
            (be(data, entry + 104 + i * 8, 4),
             be(data, entry + 108 + i * 8, 4))
            for i in range(8)
            if be(data, entry + 108 + i * 8, 4)
        )
    return result


def read_fork(handle, block_size, entry):
    size = entry['size']
    if not 0 < size <= MAX_PLIST_BYTES:
        raise ValueError('Unexpected policy plist size')
    data = bytearray()
    for block, count in entry['extents']:
        if block <= 0 or count <= 0:
            raise ValueError('Invalid policy fork extent')
        chunk_size = min(size - len(data), count * block_size)
        if not chunk_size:
            break
        handle.seek(block * block_size)
        chunk = handle.read(chunk_size)
        if len(chunk) != chunk_size:
            raise ValueError('Truncated HFSX plist extent')
        data.extend(chunk)
    if len(data) != size:
        raise ValueError('Policy plist requires unsupported overflow extents')
    return plistlib.loads(data)


def inspect(image):
    """Return only approved policy plists from the HFSX catalog."""
    result = {}
    with image.open('rb') as handle:
        handle.seek(BLOCK_HEADER)
        volume = handle.read(512)
        if volume[:2] != b'HX' or be(volume, 2, 2) != 5:
            raise ValueError('Expected an HFSX volume at the image start')
        block_size = be(volume, 40, 4)
        if block_size < 512 or block_size > 65536 or block_size & (block_size - 1):
            raise ValueError('Unexpected HFSX block size')
        catalog_extents = [
            (be(volume, 288 + i * 8, 4), be(volume, 292 + i * 8, 4))
            for i in range(8) if be(volume, 292 + i * 8, 4)
        ]

        def read_node(number, size=8192):
            offset = number * size
            for block, count in catalog_extents:
                if offset < count * block_size:
                    handle.seek(block * block_size + offset)
                    data = handle.read(size)
                    if len(data) != size:
                        raise ValueError('Truncated HFSX catalog node')
                    return data
                offset -= count * block_size
            raise ValueError('HFSX catalog overflow extents are unsupported')

        header = read_node(0)
        if header[8] != 1:
            raise ValueError('Unexpected catalog header node type')
        size = be(header, 14 + 18, 2)
        if size != 8192:
            raise ValueError('Unexpected HFSX catalog node size')
        next_node = be(header, 14 + 10, 4)
        folders = {}
        candidates = []
        visited = set()
        while next_node:
            if next_node in visited or len(visited) >= MAX_CATALOG_NODES:
                raise ValueError('Cyclic or excessive HFSX catalog')
            visited.add(next_node)
            node = read_node(next_node, size)
            if node[8] != 255:
                raise ValueError('Expected HFSX catalog leaf node')
            for index in range(be(node, 10, 2)):
                start = be(node, size - (index + 1) * 2, 2)
                entry = decode_record(node, start)
                if entry['kind'] == 1:
                    folders[entry['id']] = (entry['parent'], entry['name'])
                elif entry['kind'] == 2 and entry['name'] in {
                    'launchd.plist', 'com.apple.driverkitd.plist',
                    'com.apple.jetsamproperties.D22.plist',
                    'com.apple.jetsamproperties.D221.plist',
                }:
                    candidates.append(entry)
            next_node = be(node, 0, 4)

        for entry in candidates:
            names = [entry['name']]
            parent, seen = entry['parent'], set()
            while parent in folders and parent not in seen:
                seen.add(parent)
                parent, name = folders[parent]
                names.insert(0, name)
            pathname = '/' + '/'.join(names)
            if pathname in TARGETS:
                result[pathname] = read_fork(handle, block_size, entry)
    return result


def summarize(plists):
    report = {'files_found': sorted(plists), 'driverkitd': {}, 'policies': {}}
    d22 = next((v for k, v in plists.items()
                if k.endswith('com.apple.jetsamproperties.D22.plist')), None)
    d221 = next((v for k, v in plists.items()
                 if k.endswith('com.apple.jetsamproperties.D221.plist')), None)
    report['device_policies_identical'] = (d22 == d221) if d22 is not None and d221 is not None else None
    for pathname, data in plists.items():
        if pathname.endswith('com.apple.driverkitd.plist'):
            job = data
        elif pathname.endswith('/xpc/launchd.plist'):
            jobs = data.get('LaunchDaemons', {})
            match = [v for v in jobs.values() if isinstance(v, dict)
                     and v.get('Label') == 'com.apple.driverkitd']
            report['driverkitd']['consolidated_job_count'] = len(match)
            report['driverkitd']['consolidated_jetsam_properties'] = (
                match[0].get('JetsamProperties') if match else None)
            continue
        elif 'jetsamproperties' in pathname:
            version = data.get('Version4', {})
            entries = {}
            for group, subtree in version.items():
                if not isinstance(subtree, dict):
                    continue
                overrides = subtree.get('Override', {})
                defaults = subtree.get('Default', {})
                # The Daemon default contains hundreds of unrelated service
                # names. Do not dump their entire settings into the report.
                global_default = defaults.get('Global', {}) if isinstance(defaults, dict) else {}
                direct_default = defaults.get('com.apple.driverkitd') if isinstance(defaults, dict) else None
                entries[group] = {
                    'global_default': global_default,
                    'default_count': len(defaults) if isinstance(defaults, dict) else 0,
                    'driverkitd_default': direct_default,
                    'override_count': len(overrides) if isinstance(overrides, dict) else 0,
                    'driverkitd_overrides': {
                        k: v for k, v in overrides.items()
                        if 'driverkitd' in k.lower()
                    } if isinstance(overrides, dict) else {},
                }
            report['policies'][Path(pathname).name] = entries
            continue
        else:
            continue
        report['driverkitd'].update({
            'label': job.get('Label'), 'program': job.get('ProgramArguments'),
            'run_at_load': job.get('RunAtLoad'),
            'enable_pressured_exit': job.get('EnablePressuredExit'),
            'jetsam_properties': job.get('JetsamProperties'),
        })
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path, help='Private raw HFSX root disk (read-only)')
    args = parser.parse_args()
    if not args.image.is_file():
        parser.error('Image not found')
    print(json.dumps(summarize(inspect(args.image)), indent=2, default=str))


if __name__ == '__main__':
    main()
