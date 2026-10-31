"""Offline Windows/Linux viewer regression tests; no Apple firmware or VM needed."""

import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zlib


TOOL = Path(__file__).resolve().parents[1] / 'tools'
spec = importlib.util.spec_from_file_location('sweet_viewer_test', TOOL / 'qemu-live-screen.py')
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)


def get(url, etag=None):
    headers = {'If-None-Match': etag} if etag else {}
    try:
        with urlopen(Request(url, headers=headers), timeout=5) as result:
            return result.status, dict(result.headers), result.read()
    except HTTPError as error:
        return error.code, dict(error.headers), error.read()


def post(url, body, origin=None):
    headers = {'Content-Type': 'application/json'}
    if origin:
        headers['Origin'] = origin
    request = Request(url, data=json.dumps(body).encode(), headers=headers, method='POST')
    try:
        with urlopen(request, timeout=5) as result:
            return result.status
    except HTTPError as error:
        return error.code


class PNGTests(unittest.TestCase):
    def test_client_avoids_long_press_threshold(self):
        self.assertIn('MIN_TAP_MS=375', viewer.HTML)
        self.assertIn('setTimeout(poll,interval)', viewer.HTML)
        self.assertIn('fetch("/gesture"', viewer.HTML)

    def test_live_png_matches_bgra_byte_order(self):
        qemu = viewer.qemu
        buf = bytearray(qemu.FB_STRIDE * qemu.FB_H)
        buf[:8] = bytes((0, 0, 255, 255, 255, 0, 0, 255))  # red then blue
        png = qemu.encode_png(buf, compression=2)
        self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))
        width, height = struct.unpack_from('>II', png, 16)
        self.assertEqual((width, height), (1080, 2400))
        offset = 8
        pieces = []
        while offset < len(png):
            length, = struct.unpack_from('>I', png, offset)
            name = png[offset+4:offset+8]
            data = png[offset+8:offset+8+length]
            if name == b'IDAT':
                pieces.append(data)
            offset += length + 12
        raw = zlib.decompress(b''.join(pieces))
        self.assertEqual(raw[:7], b'\x00\xff\x00\x00\x00\x00\xff')
        self.assertRaises(ValueError, qemu.encode_png, b'too short')


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_qmp = viewer.qemu.qmp
        self.old_sequence = viewer.qmp_tablet_sequence
        self.raw = bytearray(viewer.qemu.FB_STRIDE * viewer.qemu.FB_H)
        self.snapshots = 0
        self.gestures = []

        def fake_snapshot(_socket, *, pmemsave):
            self.snapshots += 1
            self.assertEqual(pmemsave[1], len(self.raw))
            Path(pmemsave[2]).write_bytes(self.raw)

        def fake_sequence(_socket, commands):
            self.gestures.append(commands)

        viewer.qemu.qmp = fake_snapshot
        viewer.qmp_tablet_sequence = fake_sequence
        viewer.ViewerHandler.reset_cache()
        viewer.ViewerHandler.outdir = Path(self.temp.name)
        viewer.ViewerHandler.qmp_tcp = 'tcp://127.0.0.1:4444'
        viewer.ViewerHandler.input_enabled = True
        self.server = viewer.ThreadingHTTPServer(('127.0.0.1', 0), viewer.ViewerHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        viewer.qemu.qmp = self.old_qmp
        viewer.qmp_tablet_sequence = self.old_sequence
        self.temp.cleanup()

    def test_frame_cache_etag_and_changed_frame(self):
        status, headers, png = get(self.url+'/frame.png')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertTrue(png.startswith(b'\x89PNG'))
        etag = headers['ETag']
        self.assertEqual(self.snapshots, 1)

        status, _, payload = get(self.url+'/frame.png', etag)
        self.assertEqual((status, payload), (304, b''))
        self.assertEqual(self.snapshots, 1)

        time.sleep(.32)
        status, _, payload = get(self.url+'/frame.png', etag)
        self.assertEqual((status, payload), (304, b''))
        self.assertEqual(self.snapshots, 2)  # sampled but not re-encoded

        self.raw[:4] = bytes((0, 0, 255, 255))
        time.sleep(.32)
        status, headers, png = get(self.url+'/frame.png', etag)
        self.assertEqual(status, 200)
        self.assertNotEqual(headers['ETag'], etag)
        self.assertTrue(png.startswith(b'\x89PNG'))
        self.assertEqual(self.snapshots, 3)
        self.assertFalse((Path(self.temp.name) / 'viewer-frame.raw').exists())

    def test_parallel_clients_share_one_snapshot(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            frames = list(pool.map(lambda _: get(self.url+'/frame.png'), range(8)))
        self.assertEqual({status for status, _, _ in frames}, {200})
        self.assertEqual(len({headers['ETag'] for _, headers, _ in frames}), 1)
        self.assertEqual(self.snapshots, 1)

    def test_input_origin_validation_and_single_home_batch(self):
        bad = post(self.url+'/touch', {'x': .5, 'y': .5, 'down': True},
                   origin='https://untrusted.example')
        self.assertEqual(bad, 403)
        self.assertFalse(self.gestures)

        bad = post(self.url+'/touch', {'x': 1.1, 'y': .5, 'down': True})
        self.assertEqual(bad, 400)
        self.assertEqual(post(self.url+'/gesture', {'action':'not-home'}), 400)
        self.assertEqual(post(self.url+'/touch', {'x': .5, 'y': .5, 'down': True},
                              origin=self.url), 204)
        self.assertEqual(len(self.gestures), 1)
        self.assertEqual(len(self.gestures[0]), 1)
        self.assertEqual(post(self.url+'/gesture', {'action':'home'}), 204)
        self.assertEqual(len(self.gestures), 2)
        self.assertEqual(len(self.gestures[1]), 30)
        self.assertTrue(self.gestures[1][0][0][-1]['data']['down'])
        self.assertFalse(self.gestures[1][-1][0][-1]['data']['down'])


class NativeConfigTests(unittest.TestCase):
    def test_quiet_boot_retains_network_and_disables_trace(self):
        spec = importlib.util.spec_from_file_location(
            'iossweet_windows_test', TOOL / 'iossweet-native-windows.py')
        try:
            native = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(native)
        except ImportError:
            self.skipTest('Native launcher requires Windows')
        args = native.guest_boot_args()
        for required in ('cpus=1', 'rd=virtiodisk0',
                         'sweet_qemu_network_delegate=1',
                         'sweet_qemu_keep_awake=1', 'sweetfb_noconsole=1'):
            self.assertIn(required, args)
        for diagnostic in ('sweetsample=', 'sweet_qemu_network_trace=1',
                           'sweet_qemu_necp_trace=1', 'sweet_qemu_smp=1',
                           '-enable_kprintf_spam'):
            self.assertNotIn(diagnostic, args)
        diagnostic = native.guest_boot_args(1, True)
        self.assertIn('sweet_qemu_network_trace=1', diagnostic)
        self.assertIn('-enable_kprintf_spam', diagnostic)
        experimental = native.guest_boot_args(2)
        self.assertIn('cpus=2', experimental)
        self.assertIn('sweet_qemu_smp=1', experimental)
        self.assertRaises(ValueError, native.guest_boot_args, 4)


if __name__ == '__main__':
    unittest.main()
