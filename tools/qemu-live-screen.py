#!/usr/bin/env python3
"""Local-only live framebuffer viewer for a running qemu-sweet.py VM.

Serves successive QMP pmemsave snapshots in a Windows browser from Docker.
With --enable-input, pointer events are sent to QEMU's VirtIO tablet.
The emulated iOS HID driver polls input asynchronously; a normal fast desktop
click must be stretched into a real tap so both edges reach SpringBoard.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.parse import urlsplit
import uuid

qemu_script = Path(__file__).resolve().with_name("qemu-sweet.py")
spec = importlib.util.spec_from_file_location("qemu_sweet", qemu_script)
qemu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qemu)

VIEWER_HTML_PATH = Path(__file__).resolve().with_name('qemu-viewer.html')
HTML = VIEWER_HTML_PATH.read_text(encoding='utf-8')

def qmp_tablet_sequence(sockpath, commands):
    """Send timed pointer events over ONE QMP session, not 30 HTTP connects.

    commands: (QMP input-send-event list, delay-before-seconds) pairs.
    Receive QMP asynchronous notifications until the matching reply.
    """
    with qemu.connect_qmp(sockpath) as conn:
        conn.settimeout(12)
        f=conn.makefile("rw")
        if not f.readline():
            raise RuntimeError("QMP unavailable")
        def call(command, arguments=None):
            request={"execute":command}
            if arguments is not None:
                request["arguments"]=arguments
            f.write(json.dumps(request)+"\n")
            f.flush()
            while True:
                line=f.readline()
                if not line:
                    raise RuntimeError('QMP closed before response')
                result=json.loads(line)
                if "error" in result:
                    raise RuntimeError(str(result["error"]))
                if "return" in result:
                    return
        call("qmp_capabilities")
        for events, delay in commands:
            if delay:
                time.sleep(delay)
            call("input-send-event", {"events":events})
        f.close()


def touch_events(x, y, down):
    return [
        {"type":"abs","data":{"axis":"x","value":round(x*32767)}},
        {"type":"abs","data":{"axis":"y","value":round(y*32767)}},
        {"type":"btn","data":{"button":"left","down":down}},
    ]


def qmp_tablet_event(sockpath, events):
    qmp_tablet_sequence(sockpath, [(events, 0)])


def home_gesture():
    # Hold the initial down event through multiple emulated input polls.
    # Move in stages so the iOS recognizer observes a swipe, not a teleport.
    result = [(touch_events(.5, .998, True), 0)]
    for i in range(1, 29):
        result.append((touch_events(.5, .998-i*.027, True),
                       .18 if i == 1 else .040))
    result.append((touch_events(.5, .242, False), .10))
    return result


def navigation_gesture(direction):
    """Smooth bounded swipe for scrolling and horizontal navigation.

    One QMP connection keeps intermediate positions and delays consistent,
    unlike a fast desktop drag that produces many independent HTTP calls.
    Direction names describe the movement of the virtual finger, not content.
    """
    endpoints = {
        'up': ((.5, .80), (.5, .30)),
        'down': ((.5, .30), (.5, .80)),
        'left': ((.85, .50), (.20, .50)),
        'right': ((.20, .50), (.85, .50)),
    }
    if direction not in endpoints:
        raise ValueError('Unknown navigation swipe')
    start, end = endpoints[direction]
    result = [(touch_events(*start, True), 0)]
    for i in range(1, 15):
        f = i / 14
        x = start[0] + (end[0] - start[0]) * f
        y = start[1] + (end[1] - start[1]) * f
        result.append((touch_events(x, y, True), .12 if i == 1 else .038))
    result.append((touch_events(*end, False), .08))
    return result

class ViewerHandler(BaseHTTPRequestHandler):
    outdir = None
    input_enabled = False
    qmp_tcp = None
    html_path = VIEWER_HTML_PATH
    runtime_info = {'mode': 'QEMU', 'cores': 1, 'diagnostics': False}
    frame_lock = threading.Lock()
    input_lock = threading.Lock()
    frame_png = None
    frame_digest = None
    frame_sequence = 0
    frame_sampled_at = 0.0
    frame_session = None
    frame_samples = 0
    frame_changes = 0
    frame_errors = 0
    frame_snapshot_ms = 0.0
    frame_encode_ms = 0.0
    frame_total_snapshot_ms = 0.0
    frame_total_encode_ms = 0.0

    @classmethod
    def reset_cache(cls):
        with cls.frame_lock:
            cls.frame_png = None
            cls.frame_digest = None
            cls.frame_sequence = 0
            cls.frame_sampled_at = 0.0
            cls.frame_samples = 0
            cls.frame_changes = 0
            cls.frame_errors = 0
            cls.frame_snapshot_ms = 0.0
            cls.frame_encode_ms = 0.0
            cls.frame_total_snapshot_ms = 0.0
            cls.frame_total_encode_ms = 0.0
            # Prevent a stale ETag from a previous VM/boot from suppressing
            # the first screenshot when a user's browser tab survives restart.
            cls.frame_session = uuid.uuid4().hex[:12]

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            status=("Pointer events are forwarded to QEMU's tablet. iOS HID support remains experimental."
                    if self.input_enabled else "Touch input disabled; run viewer with --enable-input and QEMU with --tablet.")
            try:
                # Keep the UI independent of the QEMU process. Developers
                # can edit qemu-viewer.html and just reload the browser.
                html=self.html_path.read_text(encoding='utf-8')
            except OSError as ex:
                self.send_error(503,"Viewer HTML unavailable")
                print(f"viewer HTML load failed: {ex}",file=sys.stderr)
                return
            blob = html.replace("INPUT_STATUS",status).replace(
                "INPUT_ENABLED","true" if self.input_enabled else "false").encode('utf-8')
            mime = "text/html; charset=utf-8"
        elif path == "/status.json":
            blob = json.dumps(self.runtime_info).encode('utf-8')
            mime = "application/json; charset=utf-8"
        elif path == "/metrics.json":
            with self.frame_lock:
                # Only aggregate QMP/PNG timings: never expose guest memory,
                # filenames, URLs, screenshot pixels or private iOS metadata.
                count = self.frame_samples
                changed = self.frame_changes
                metrics = {
                    "frame_samples":count, "changed_frames":changed,
                    "unchanged_frames":count-changed,
                    "snapshot_errors":self.frame_errors,
                    "last_snapshot_ms":round(self.frame_snapshot_ms,2),
                    "last_png_encode_ms":round(self.frame_encode_ms,2),
                    "mean_snapshot_ms":round(self.frame_total_snapshot_ms/count,2) if count else 0,
                    "mean_png_encode_ms":round(self.frame_total_encode_ms/changed,2) if changed else 0,
                    "framebuffer_mib":round(qemu.FB_STRIDE*qemu.FB_H/(1024*1024),2),
                }
            blob = json.dumps(metrics).encode('utf-8')
            mime = "application/json; charset=utf-8"
        elif path == "/frame.png":
            mon = self.qmp_tcp or self.outdir / "mon.sock"
            rawfile = self.outdir / "viewer-frame.raw"
            try:
                if not self.qmp_tcp and not mon.exists():
                    raise FileNotFoundError(mon)
                with self.frame_lock:
                    now=time.monotonic()
                    if self.frame_png is None or now-self.frame_sampled_at >= .28:
                        try:
                            started=time.perf_counter()
                            qemu.qmp(str(mon), pmemsave=(qemu.FB_BASE, qemu.FB_STRIDE * qemu.FB_H, str(rawfile)))
                            raw = rawfile.read_bytes()
                            if len(raw) != qemu.FB_STRIDE * qemu.FB_H:
                                raise RuntimeError("Frame snapshot length mismatch")
                            snapshot_ms=(time.perf_counter()-started)*1000
                            digest=hashlib.blake2b(raw,digest_size=16).digest()
                            encode_ms=0.0
                            if digest != self.frame_digest:
                                encoding_started=time.perf_counter()
                                type(self).frame_png=qemu.encode_png(raw,compression=2)
                                encode_ms=(time.perf_counter()-encoding_started)*1000
                                type(self).frame_digest=digest
                                type(self).frame_sequence+=1
                                type(self).frame_changes+=1
                                type(self).frame_total_encode_ms+=encode_ms
                            type(self).frame_samples+=1
                            type(self).frame_snapshot_ms=snapshot_ms
                            type(self).frame_encode_ms=encode_ms
                            type(self).frame_total_snapshot_ms+=snapshot_ms
                            type(self).frame_sampled_at=time.monotonic()
                        finally:
                            rawfile.unlink(missing_ok=True)
                    blob=self.frame_png
                    etag='"iossweet-'+str(self.frame_session)+'-'+str(self.frame_sequence)+'"'
            except (OSError, RuntimeError, ValueError) as ex:
                with self.frame_lock:
                    type(self).frame_errors+=1
                self.send_error(503, "QEMU framebuffer unavailable")
                print(f"snapshot failed: {ex}", file=sys.stderr)
                return
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag",etag)
                self.send_header("Cache-Control","no-store")
                self.end_headers()
                return
            mime = "image/png"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "no-store")
        if path == "/frame.png":
            self.send_header("ETag",etag)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(blob)

    def do_POST(self):
        path=urlsplit(self.path).path
        if path not in ("/touch", "/gesture"):
            self.send_error(404)
            return
        if not self.input_enabled:
            self.send_error(403, "Tablet input disabled")
            return
        origin=self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}',
                                     f'http://localhost:{self.server.server_port}'):
            self.send_error(403, 'Foreign origin')
            return
        if self.headers.get("Content-Type","").split(";")[0].strip()!="application/json":
            self.send_error(415, "JSON required")
            return
        try:
            length=int(self.headers.get("Content-Length","0"))
            if not 1 <= length <= 512:
                raise ValueError("Invalid event length")
            event=json.loads(self.rfile.read(length))
            with self.input_lock:
                if path == "/gesture":
                    if event == {"action":"home"}:
                        commands = home_gesture()
                    elif isinstance(event, dict) and set(event) == {'action'} and event['action'] in (
                            'swipe-up', 'swipe-down', 'swipe-left', 'swipe-right'):
                        commands = navigation_gesture(event['action'].removeprefix('swipe-'))
                    else:
                        raise ValueError("Unknown gesture")
                    qmp_tablet_sequence(self.qmp_tcp or self.outdir/"mon.sock", commands)
                else:
                    x,y,down=event["x"],event["y"],event["down"]
                    if type(down) is not bool or type(x) not in (float,int) or type(y) not in (float,int):
                        raise ValueError("Invalid pointer values")
                    if not 0 <= x <= 1 or not 0 <= y <= 1:
                        raise ValueError("Pointer out of bounds")
                    qmp_tablet_event(self.qmp_tcp or self.outdir/"mon.sock",touch_events(x,y,down))
        except (ValueError,TypeError,KeyError,IndexError,json.JSONDecodeError):
            self.send_error(400,"Bad tablet event")
            return
        except (OSError,RuntimeError,TimeoutError) as e:
            print(f"tablet input failed: {e}",file=sys.stderr)
            self.send_error(503,"QEMU tablet unavailable")
            return
        self.send_response(204)
        self.send_header("Cache-Control","no-store")
        self.end_headers()

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("outdir", type=Path, help="RUN_OUT used by a running qemu-sweet.py")
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--host", default="127.0.0.1", help="bind address (0.0.0.0 for container only)")
    ap.add_argument("--qmp-tcp", default=None,
                    help="native Windows QEMU monitor endpoint tcp://127.0.0.1:PORT")
    ap.add_argument("--enable-input", action="store_true",
                    help="send browser pointer events to QEMU VirtIO tablet (iOS kernel HID driver still required)")
    a=ap.parse_args()
    if not a.outdir.is_dir():
        ap.error("QEMU output directory does not exist")
    ViewerHandler.outdir=a.outdir.resolve()
    ViewerHandler.input_enabled=a.enable_input
    ViewerHandler.runtime_info={'mode':'QEMU viewer','cores':1,'diagnostics':False}
    ViewerHandler.reset_cache()
    if a.qmp_tcp and not (a.qmp_tcp.startswith('tcp://127.0.0.1:') or
                          a.qmp_tcp.startswith('tcp://localhost:')):
        ap.error('QMP TCP endpoint must bind localhost')
    ViewerHandler.qmp_tcp=a.qmp_tcp
    server=ThreadingHTTPServer((a.host,a.port),ViewerHandler)
    print(f"Local QEMU framebuffer viewer: http://127.0.0.1:{a.port}/", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=="__main__":
    main()
