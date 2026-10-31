"""Synthetic read-only tests for the HFSX jetsam policy inspector."""

import importlib.util
import io
import plistlib
from pathlib import Path
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'tools' / 'inspect-hfsx-jetsam.py'
spec = importlib.util.spec_from_file_location('inspect_hfsx_jetsam', SOURCE)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class InspectorTests(unittest.TestCase):
    def test_catalog_file_and_folder_record(self):
        def record(name, kind):
            encoded = name.encode('utf-16-be')
            key_length = 6 + len(encoded)
            data = bytearray(256)
            data[0:2] = key_length.to_bytes(2, 'big')
            data[2:6] = (8).to_bytes(4, 'big')
            data[6:8] = (len(name)).to_bytes(2, 'big')
            data[8:8+len(encoded)] = encoded
            offset = 2 + key_length
            data[offset:offset+2] = kind.to_bytes(2, 'big')
            data[offset+8:offset+12] = (123).to_bytes(4, 'big')
            if kind == 2:
                data[offset+88:offset+96] = (400).to_bytes(8, 'big')
                data[offset+104:offset+108] = (5).to_bytes(4, 'big')
                data[offset+108:offset+112] = (1).to_bytes(4, 'big')
            return data

        folder = module.decode_record(record('System', 1), 0)
        self.assertEqual((folder['id'], folder['parent']), (123, 8))
        file = module.decode_record(record('launchd.plist', 2), 0)
        self.assertEqual(file['size'], 400)
        self.assertEqual(file['extents'], ((5, 1),))

    def test_fork_reads_only_selected_extents_and_parses_plist(self):
        content = plistlib.dumps({'Label': 'com.apple.driverkitd'}, fmt=plistlib.FMT_BINARY)
        image = bytearray(4096 * 4)
        image[4096:4096+len(content)] = content
        handle = io.BytesIO(image)
        item = {'size': len(content), 'extents': ((1, 1),)}
        self.assertEqual(module.read_fork(handle, 4096, item)['Label'], 'com.apple.driverkitd')
        with self.assertRaisesRegex(ValueError, 'Unexpected policy plist size'):
            module.read_fork(handle, 4096, {'size': 10**9, 'extents': ((1, 1),)})
        with self.assertRaisesRegex(ValueError, 'unsupported overflow extents'):
            module.read_fork(handle, 4096, {'size': 4097, 'extents': ((1, 1),)})

    def test_rejects_wrong_filesystem_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'wrong.raw'
            source.write_bytes(b'\0' * 8192)
            with self.assertRaisesRegex(ValueError, 'Expected an HFSX'):
                module.inspect(source)
            self.assertEqual(source.read_bytes(), b'\0' * 8192)

    def test_summary_does_not_dump_unrelated_daemon_settings(self):
        p = '/iOSRoot/System/Library/LaunchDaemons/'
        policies = {
            p + 'com.apple.driverkitd.plist': {
                'Label': 'com.apple.driverkitd', 'ProgramArguments': ['/usr/libexec/driverkitd'],
                'RunAtLoad': True, 'EnablePressuredExit': False},
            p + 'com.apple.jetsamproperties.D22.plist': {
                'Version4': {'Daemon': {'Default': {'Global': {}, 'other': {'test': 7}},
                                        'Override': {'something_else': {'limit': 42}}}}},
        }
        report = module.summarize(policies)
        section = report['policies']['com.apple.jetsamproperties.D22.plist']['Daemon']
        self.assertIsNone(section['driverkitd_default'])
        self.assertEqual(section['override_count'], 1)
        self.assertEqual(section['driverkitd_overrides'], {})
        self.assertEqual(section['default_count'], 2)
        self.assertNotIn('other', str(section))

    def test_identical_device_policies_are_reported_without_guessing_when_missing(self):
        prefix = '/iOSRoot/System/Library/LaunchDaemons/'
        same = {'Version4': {'Daemon': {'Default': {'Global': {}}, 'Override': {}}}}
        first = prefix + 'com.apple.jetsamproperties.D22.plist'
        second = prefix + 'com.apple.jetsamproperties.D221.plist'
        self.assertIsNone(module.summarize({first: same})['device_policies_identical'])
        self.assertTrue(module.summarize({first: same, second: same})['device_policies_identical'])
        self.assertFalse(module.summarize({first: same, second: {}})['device_policies_identical'])


if __name__ == '__main__':
    unittest.main()
