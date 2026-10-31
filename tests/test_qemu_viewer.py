"""Offline Windows/Linux viewer regression tests; no Apple firmware or VM needed."""

import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
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
        self.assertIn('MIN_TAP_MS=240', viewer.HTML)
        self.assertIn('schedulePoll(nextPollInterval())', viewer.HTML)
        self.assertIn('if(document.hidden||polling)return;', viewer.HTML)
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
        old_ttl = viewer.ViewerHandler.frame_reuse_seconds
        try:
            viewer.ViewerHandler.frame_reuse_seconds = 10  # test only; stable on a busy host
            with ThreadPoolExecutor(max_workers=8) as pool:
                frames = list(pool.map(lambda _: get(self.url+'/frame.png'), range(8)))
        finally:
            viewer.ViewerHandler.frame_reuse_seconds = old_ttl
        self.assertEqual({status for status, _, _ in frames}, {200})
        self.assertEqual(len({headers['ETag'] for _, headers, _ in frames}), 1)
        self.assertEqual(self.snapshots, 1)

    def test_snapshot_timing_metrics_do_not_expose_guest_data(self):
        status, headers, payload = get(self.url+'/metrics.json')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'application/json; charset=utf-8')
        self.assertEqual(json.loads(payload)['frame_samples'], 0)
        self.assertNotIn('ios.qcow2', payload.decode())

        get(self.url+'/frame.png')
        with viewer.ViewerHandler.frame_lock:
            viewer.ViewerHandler.frame_sampled_at = 0  # force a fresh QMP sample
        get(self.url+'/frame.png')  # unchanged screenshot is not PNG-encoded
        status, _, body = get(self.url+'/metrics.json')
        self.assertEqual(status, 200)
        stats = json.loads(body)
        self.assertEqual(stats['frame_samples'], 2)
        self.assertEqual(stats['changed_frames'], 1)
        self.assertEqual(stats['unchanged_frames'], 1)
        self.assertEqual(stats['snapshot_errors'], 0)
        self.assertGreater(stats['mean_snapshot_ms'], 0)
        self.assertGreater(stats['mean_png_encode_ms'], 0)
        self.assertGreater(stats['framebuffer_mib'], 9)
        self.assertNotIn('raw', stats)
        self.assertFalse((Path(self.temp.name) / 'viewer-frame.raw').exists())

    def test_etag_changes_across_boot_and_runtime_status_is_private(self):
        viewer.ViewerHandler.runtime_info = {
            'mode': 'Native Windows QEMU', 'cores': 2, 'diagnostics': False,
        }
        status, headers, blob = get(self.url+'/status.json')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(blob), viewer.ViewerHandler.runtime_info)
        self.assertNotIn('D:', blob.decode())
        first, headers, _ = get(self.url+'/frame.png')
        self.assertEqual(first, 200)
        old_etag = headers['ETag']
        viewer.ViewerHandler.reset_cache()  # emulate a new QEMU boot
        status, headers, _ = get(self.url+'/frame.png', old_etag)
        self.assertEqual(status, 200)
        self.assertNotEqual(old_etag, headers['ETag'])

    def test_html_hot_reload_without_emulator_restart(self):
        # The Python controller stays running while a new browser request
        # reads the edited HTML. No QEMU, reboot or private disk is needed.
        temporary_html = Path(self.temp.name) / 'viewer.html'
        old_path = viewer.ViewerHandler.html_path
        try:
            viewer.ViewerHandler.html_path = temporary_html
            temporary_html.write_text('<html>revision-one INPUT_ENABLED INPUT_STATUS</html>',
                                      encoding='utf-8')
            status, headers, body = get(self.url + '/')
            self.assertEqual(status, 200)
            self.assertIn(b'revision-one true Pointer events', body)
            self.assertEqual(headers['Cache-Control'], 'no-store')
            temporary_html.write_text('<html>revision-two INPUT_ENABLED</html>',
                                      encoding='utf-8')
            status, _, body = get(self.url + '/')
            self.assertEqual(status, 200)
            self.assertIn(b'revision-two true', body)
            self.assertNotIn(b'revision-one', body)
            self.assertEqual(self.snapshots, 0)
            temporary_html.unlink()
            status, _, _ = get(self.url + '/')
            self.assertEqual(status, 503)
        finally:
            viewer.ViewerHandler.html_path = old_path

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

    def test_navigation_swipes_are_bounded_and_batched(self):
        for direction in ('up', 'down', 'left', 'right'):
            self.assertEqual(post(self.url+'/gesture', {'action':'swipe-'+direction}), 204)
            commands = self.gestures[-1]
            self.assertEqual(len(commands), 16)
            self.assertTrue(commands[0][0][-1]['data']['down'])
            self.assertFalse(commands[-1][0][-1]['data']['down'])
            self.assertTrue(all(0 <= event['data']['value'] <= 32767
                                for events, _ in commands for event in events
                                if event['type'] == 'abs'))
            self.assertLess(sum(delay for _, delay in commands), 1.0)
        self.assertEqual(len(self.gestures), 4)
        for invalid in ({'action': 'swipe-diagonal'},
                        {'action': 'swipe-up', 'duration_ms': 100000},
                        {'action': 'swipe-up', 'x': 1.1},
                        {'action': ['swipe-up']},
                        {}):
            self.assertEqual(post(self.url+'/gesture', invalid), 400)
        self.assertEqual(len(self.gestures), 4)
        self.assertEqual(post(self.url+'/gesture', {'action':'swipe-up'},
                              origin='https://hostile.example'), 403)


class NativeConfigTests(unittest.TestCase):
    def test_atomic_native_lock_blocks_concurrent_launcher(self):
        if sys.platform != 'win32':
            self.skipTest('Native Windows file locks require Windows')
        spec = importlib.util.spec_from_file_location(
            'iossweet_singleton_test', TOOL / 'iossweet-native-windows.py')
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        subprocess_code = '''
import importlib.util, sys
s = importlib.util.spec_from_file_location("candidate", sys.argv[1])
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
try:
    with m.native_instance_lock(sys.argv[2]): pass
except RuntimeError as exc:
    print(str(exc)); sys.exit(23)
'''
        with tempfile.TemporaryDirectory() as folder:
            args = [sys.executable, '-c', subprocess_code,
                    str(TOOL / 'iossweet-native-windows.py'), folder]
            with native.native_instance_lock(folder):
                attempt = subprocess.run(args, capture_output=True, text=True, timeout=12)
                self.assertEqual(attempt.returncode, 23)
                self.assertIn('already active', attempt.stdout)
            second = subprocess.run(args, capture_output=True, text=True, timeout=12)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertTrue((Path(folder) / 'native-qemu-instance.lock').exists())

    def test_stop_refuses_non_qemu_process_identity(self):
        if sys.platform != 'win32':
            self.skipTest('Native QEMU PID lookup requires Windows')
        spec = importlib.util.spec_from_file_location(
            'iossweet_stop_guard_test', TOOL / 'iossweet-native-windows.py')
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        self.assertRaises(ValueError, native.verify_own_qemu_pid, 0)
        self.assertRaises(ValueError, native.verify_own_qemu_pid, True)
        self.assertRaises(RuntimeError, native.verify_own_qemu_pid, os.getpid())

    def test_check_fails_cleanly_for_missing_guest_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(TOOL / 'iossweet-native-windows.py'),
                 '--check', '--kernel', str(Path(tmp) / 'missing-kernel'),
                 '--disk', str(Path(tmp) / 'missing-disk')],
                capture_output=True, text=True, timeout=12)
        if sys.platform != 'win32':
            self.skipTest('Native Windows configuration check requires Windows')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('KERNEL_AVAILABLE=False', result.stdout)
        self.assertIn('IOS_DISK_AVAILABLE=False', result.stdout)
        self.assertIn('Missing native Windows prerequisites', result.stderr)

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
                         'sweet_qemu_keep_awake=1', 'sweetfb_noconsole=1',
                         'sweetiolog=-', 'sweet_aks_quiet=1'):
            self.assertIn(required, args)
        for diagnostic in ('sweetsample=', 'sweet_qemu_network_trace=1',
                           'sweet_qemu_necp_trace=1', 'sweet_qemu_smp=1',
                           '-enable_kprintf_spam'):
            self.assertNotIn(diagnostic, args)
        diagnostic = native.guest_boot_args(1, True)
        self.assertIn('sweet_qemu_network_trace=1', diagnostic)
        self.assertIn('-enable_kprintf_spam', diagnostic)
        self.assertNotIn('sweetiolog=-', diagnostic)
        self.assertNotIn('sweet_aks_quiet=1', diagnostic)
        targeted = native.guest_boot_args(2, False, True)
        self.assertIn('sweetsample=driverkitd sweetsample_delay=1 sweetsample_interval=2', targeted)
        self.assertIn('sweet_aks_quiet=1', targeted)
        self.assertNotIn('sweet_qemu_network_trace=1', targeted)
        self.assertNotIn('-enable_kprintf_spam', targeted)
        self.assertNotIn('sweetsample=driverkitd', native.guest_boot_args(2))
        verbose_targeted = native.guest_boot_args(2, True, True)
        self.assertIn('sweetsample=driverkitd,SpringBoard', verbose_targeted)
        self.assertIn('sweet_qemu_network_trace=1', verbose_targeted)
        experimental = native.guest_boot_args(2)
        self.assertIn('cpus=2', experimental)
        self.assertIn('sweet_qemu_smp=1', experimental)
        self.assertRaises(ValueError, native.guest_boot_args, 4)


if __name__ == '__main__':
    unittest.main()
