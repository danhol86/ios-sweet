#!/usr/bin/env python3
"""Local-only live framebuffer viewer for a running qemu-sweet.py VM.

Serves successive QMP pmemsave snapshots in a Windows browser from Docker.
With --enable-input, pointer events are sent to QEMU's VirtIO tablet.
The emulated iOS HID driver polls input asynchronously; a normal fast desktop
click must be stretched into a real tap so both edges reach SpringBoard.
"""
import argparse
import importlib.util
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import socket
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
#frame{display:block;width:auto;max-width:100%;height:auto;max-height:80vh;margin:12px auto;background:black;border:1px solid #374151;border-radius:22px;touch-action:none}
button{font:600 14px system-ui,sans-serif;padding:10px 18px;margin:5px;background:#323b4b;color:#fff;border:1px solid #64748b;border-radius:10px;cursor:pointer}
button:disabled{opacity:.45;cursor:default}
small{display:block;margin-top:12px;color:#8995a8}
</style></head><body><main>
<h1>ios-sweet QEMU display</h1>
<p>Live physical framebuffer snapshots from the ARM64 VM. INPUT_STATUS</p>
<div id="state">Connecting to QEMU...</div>
<img id="frame" alt="QEMU iPhone framebuffer">
<button type="button" id="swipehome">Swipe up / Home</button>
<p>Click an app normally or drag on the iPhone screen. Swipe from the bottom bar to return Home, or use the button.</p>
<small>Local development viewer. Close this page to stop polling; the VM is managed separately.</small>
</main><script>
var img=document.getElementById("frame"), state=document.getElementById("state");
var busy=false;
var inputEnabled=INPUT_ENABLED, pointerActive=false, lastPointer=0, activeTap=null;
// QEMU sends tablet events asynchronously. A desktop mouse click often lasts
// less than one emulated poll; SpringBoard never sees a complete iOS tap.
// Serialize all QMP requests, and hold the down state for at least 240 ms
// AFTER QEMU acknowledges it. Gestures still send intermediate positions.
var MIN_TAP_MS=240, touchQueue=Promise.resolve();
var homeButton=document.getElementById("swipehome");
homeButton.disabled=!inputEnabled;
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
function coords(ev) {
 var b=img.getBoundingClientRect();
 if(b.width<=0 || b.height<=0)return null;
 var x=Math.min(1,Math.max(0,(ev.clientX-b.left)/b.width));
 var y=Math.min(1,Math.max(0,(ev.clientY-b.top)/b.height));
 return {x:x,y:y};
}
function delay(ms){return new Promise(function(resolve){setTimeout(resolve,ms)});}
async function sendRawTouch(x,y,down) {
 var r=await fetch("/touch",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({x:x,y:y,down:down})});
 if(!r.ok)throw new Error("QEMU rejected touchscreen input ("+r.status+")");
}
function queueTouch(x,y,down,tap,minimumHold) {
 var next=touchQueue.then(async function(){
   if(!down && minimumHold && tap && tap.ackAt) {
     await delay(Math.max(0,minimumHold-(Date.now()-tap.ackAt)));
   }
   await sendRawTouch(x,y,down);
   if(down && tap && !tap.ackAt)tap.ackAt=Date.now();
 });
 // Keep a resolved tail even if an earlier request failed so the next
 // tap can recover. The state line reports network/QMP errors.
 touchQueue=next.catch(function(error){state.textContent="Touch input failed: "+error.message;});
 return touchQueue;
}
img.addEventListener("pointerdown",function(e){
 if(!inputEnabled || pointerActive)return;
 var p=coords(e);if(!p)return;
 e.preventDefault();pointerActive=true;lastPointer=0;
 activeTap={ackAt:0,startX:e.clientX,startY:e.clientY,moved:false};
 img.setPointerCapture(e.pointerId);
 queueTouch(p.x,p.y,true,activeTap,0);
});
img.addEventListener("pointermove",function(e){
 if(!pointerActive || !inputEnabled)return;
 var tap=activeTap;
 if(tap && (Math.abs(e.clientX-tap.startX)>8 || Math.abs(e.clientY-tap.startY)>8))tap.moved=true;
 if(Date.now()-lastPointer<45)return;
 var p=coords(e);if(!p)return;
 lastPointer=Date.now();queueTouch(p.x,p.y,true,tap,0);
});
function pointerUp(e){
 if(!pointerActive)return;
 pointerActive=false;
 var p=coords(e),tap=activeTap;activeTap=null;
 if(!p)return;
 // A swipe must remain a swipe; only brief stationary taps are lengthened.
 queueTouch(p.x,p.y,false,tap,tap && !tap.moved ? MIN_TAP_MS : 0);
}
img.addEventListener("pointerup",pointerUp);
img.addEventListener("pointercancel",pointerUp);
async function sendAt(x,y,down){
 return queueTouch(x,y,down,null,0);
}
homeButton.addEventListener("click",async function(){
 if(!inputEnabled)return;
 homeButton.disabled=true;
 state.textContent="Sending iOS home gesture...";
 try{
   await sendAt(.50,.998,true);
   for(var i=1;i<=28;i++){
     await new Promise(function(resolve){setTimeout(resolve,35)});
     await sendAt(.50,.998-i*.027,true);
   }
   await sendAt(.50,.242,false);
 }catch(e){state.textContent="Home gesture failed: "+e.message}
 finally{homeButton.disabled=false}
});
</script></body></html>"""

def qmp_tablet_event(sockpath, events):
    with qemu.connect_qmp(sockpath) as conn:
        conn.settimeout(5)
        f=conn.makefile("rw")
        if not f.readline():
            raise RuntimeError("QMP unavailable")
        def call(command, arguments=None):
            request={"execute":command}
            if arguments is not None:
                request["arguments"]=arguments
            f.write(json.dumps(request)+"\n")
            f.flush()
            result=json.loads(f.readline())
            if "error" in result:
                raise RuntimeError(str(result["error"]))
        call("qmp_capabilities")
        call("input-send-event", {"events":events})
        f.close()

class ViewerHandler(BaseHTTPRequestHandler):
    outdir = None
    input_enabled = False
    qmp_tcp = None
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            status=("Pointer events are forwarded to QEMU's tablet. iOS HID support remains experimental."
                    if self.input_enabled else "Touch input disabled; run viewer with --enable-input and QEMU with --tablet.")
            blob = HTML.replace("INPUT_STATUS",status).replace(
                "INPUT_ENABLED","true" if self.input_enabled else "false").encode()
            mime = "text/html; charset=utf-8"
        elif path == "/frame.png":
            mon = self.qmp_tcp or self.outdir / "mon.sock"
            rawfile = self.outdir / "viewer-frame.raw"
            pngfile = self.outdir / "viewer-frame.png"
            try:
                if not self.qmp_tcp and not mon.exists():
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

    def do_POST(self):
        if urlsplit(self.path).path != "/touch":
            self.send_error(404)
            return
        if not self.input_enabled:
            self.send_error(403, "Tablet input disabled")
            return
        if self.headers.get("Content-Type","").split(";")[0].strip()!="application/json":
            self.send_error(415, "JSON required")
            return
        try:
            length=int(self.headers.get("Content-Length","0"))
            if not 1 <= length <= 512:
                raise ValueError("Invalid event length")
            event=json.loads(self.rfile.read(length))
            x,y,down=event["x"],event["y"],event["down"]
            if type(down) is not bool or type(x) not in (float,int) or type(y) not in (float,int):
                raise ValueError("Invalid pointer values")
            if not 0 <= x <= 1 or not 0 <= y <= 1:
                raise ValueError("Pointer out of bounds")
            events=[
                {"type":"abs","data":{"axis":"x","value":round(x*32767)}},
                {"type":"abs","data":{"axis":"y","value":round(y*32767)}},
                {"type":"btn","data":{"button":"left","down":down}},
            ]
            qmp_tablet_event(self.qmp_tcp or self.outdir/"mon.sock",events)
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
    if a.qmp_tcp and not (a.qmp_tcp.startswith('tcp://127.0.0.1:') or
                          a.qmp_tcp.startswith('tcp://localhost:')):
        ap.error('QMP TCP endpoint must bind localhost')
    ViewerHandler.qmp_tcp=a.qmp_tcp
    server=HTTPServer((a.host,a.port),ViewerHandler)
    print(f"Local QEMU framebuffer viewer: http://127.0.0.1:{a.port}/", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=="__main__":
    main()
