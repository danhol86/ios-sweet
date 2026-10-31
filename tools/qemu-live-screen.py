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

    @classmethod
    def reset_cache(cls):
        with cls.frame_lock:
            cls.frame_png = None
            cls.frame_digest = None
            cls.frame_sequence = 0
            cls.frame_sampled_at = 0.0
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
                            qemu.qmp(str(mon), pmemsave=(qemu.FB_BASE, qemu.FB_STRIDE * qemu.FB_H, str(rawfile)))
                            raw = rawfile.read_bytes()
                            if len(raw) != qemu.FB_STRIDE * qemu.FB_H:
                                raise RuntimeError("Frame snapshot length mismatch")
                            digest=hashlib.blake2b(raw,digest_size=16).digest()
                            if digest != self.frame_digest:
                                type(self).frame_png=qemu.encode_png(raw,compression=2)
                                type(self).frame_digest=digest
                                type(self).frame_sequence+=1
                            type(self).frame_sampled_at=time.monotonic()
                        finally:
                            rawfile.unlink(missing_ok=True)
                    blob=self.frame_png
                    etag='"iossweet-'+str(self.frame_session)+'-'+str(self.frame_sequence)+'"'
            except (OSError, RuntimeError, ValueError) as ex:
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
                    if event != {"action":"home"}:
                        raise ValueError("Unknown gesture")
                    qmp_tablet_sequence(self.qmp_tcp or self.outdir/"mon.sock",home_gesture())
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
