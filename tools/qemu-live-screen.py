#!/usr/bin/env python3
"""Local-only live framebuffer viewer for a running qemu-sweet.py VM.

Serves successive QMP pmemsave snapshots in a Windows browser via WSL2
localhost forwarding. It is NOT a touch/HID input implementation.
"""
import argparse
import importlib.util
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys
from urllib.parse import urlsplit

qemu_script = Path(__file__).resolve().with_name("qemu-sweet.py")
spec = importlib.util.spec_from_file_location("qemu_sweet", qemu_script)
qemu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qemu)

HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ios-sweet QEMU display</title>
<style>
html,body{margin:0;background:#11151c;color:#f7f8fc;font-family:system-ui,-apple-system,Segoe UI,sans-serif}
main{margin:auto;max-width:680px;padding:18px 20px;text-align:center}
h1{font-size:20px;margin:4px 0 8px}
p{font-size:13px;color:#a5b3c7;line-height:1.5}
#state{font:13px ui-monospace,monospace;margin:10px}
#frame{display:block;width:auto;max-width:100%;height:auto;max-height:80vh;margin:12px auto;background:black;border:1px solid #374151;border-radius:22px}
small{display:block;margin-top:12px;color:#8995a8}
</style></head><body><main>
<h1>ios-sweet QEMU display</h1>
<p>Live physical framebuffer snapshots from the ARM64 VM. Touch, mouse and keyboard control are not connected to iOS yet.</p>
<div id="state">Connecting to QEMU...</div>
<img id="frame" alt="QEMU iPhone framebuffer">
<small>Local development viewer. Close this page to stop polling; the VM is managed separately.</small>
</main><script>
var img=document.getElementById("frame"), state=document.getElementById("state");
var busy=false;
async function refresh(){
 if(busy) return;
 busy=true;
 try {
   var response=await fetch("/frame.png?ts="+Date.now(), {cache:"no-store"});
   if(!response.ok) throw new Error("No running VM / QMP ("+response.status+")");
   var blob=await response.blob(), next=URL.createObjectURL(blob), previous=img.src;
   img.src=next;
   if(previous.startsWith("blob:")) URL.revokeObjectURL(previous);
   state.textContent="Live snapshot received "+new Date().toLocaleTimeString();
 } catch(e) {state.textContent=String(e.message);}
 finally {busy=false;}
}
refresh();setInterval(refresh,1600);
</script></body></html>"""

class ViewerHandler(BaseHTTPRequestHandler):
    outdir = None
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            blob = HTML.encode()
            mime = "text/html; charset=utf-8"
        elif path == "/frame.png":
            mon = self.outdir / "mon.sock"
            rawfile = self.outdir / "viewer-frame.raw"
            pngfile = self.outdir / "viewer-frame.png"
            try:
                if not mon.exists():
                    raise FileNotFoundError(mon)
                qemu.qmp(str(mon), pmemsave=(qemu.FB_BASE, qemu.FB_STRIDE * qemu.FB_H, str(rawfile)))
                raw = rawfile.read_bytes()
                if len(raw) != qemu.FB_STRIDE * qemu.FB_H:
                    raise RuntimeError("Frame snapshot length mismatch")
                qemu.write_png(str(pngfile), raw)
                blob = pngfile.read_bytes()
            except (OSError, RuntimeError, ValueError) as ex:
                self.send_error(503, "QEMU framebuffer unavailable")
                print(f"snapshot failed: {ex}", file=sys.stderr)
                return
            finally:
                rawfile.unlink(missing_ok=True)
            mime = "image/png"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(blob)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("outdir", type=Path, help="RUN_OUT used by a running qemu-sweet.py")
    ap.add_argument("--port", type=int, default=8099)
    a=ap.parse_args()
    if not a.outdir.is_dir():
        ap.error("QEMU output directory does not exist")
    ViewerHandler.outdir=a.outdir.resolve()
    server=HTTPServer(("127.0.0.1",a.port),ViewerHandler)
    print(f"Local QEMU framebuffer viewer: http://127.0.0.1:{a.port}/", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=="__main__":
    main()