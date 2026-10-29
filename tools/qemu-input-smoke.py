"""Prove VirtIO input event queue on QEMU MMIO via qtest + QMP."""
import importlib.util
import json
import os
import pathlib
import socket
import struct
import subprocess
import time

path=pathlib.Path(__file__).resolve().with_name("qemu-virtio-smoke.py")
spec=importlib.util.spec_from_file_location("vblk_test",path)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
MMIO_BASE=0x0a000000
PBASE=0x40010000
DESC=PBASE
AVAIL=PBASE+0x1000
USED=PBASE+0x2000
EVENT=PBASE+0x4000
SOCKET=f"/tmp/ios-sweet-tablet-{os.getpid()}.sock"
try:os.unlink(SOCKET)
except FileNotFoundError:pass

class Q(mod.Qtest):
    def __init__(self):
        self.mmio=MMIO_BASE
        self.proc=subprocess.Popen([
            "qemu-system-aarch64","-M","virt,gic-version=3",
            "-global","virtio-mmio.force-legacy=false","-cpu","cortex-a76",
            "-m","256M","-display","none","-serial","none","-monitor","none",
            "-qtest","stdio","-qmp",f"unix:{SOCKET},server,nowait",
            "-device","virtio-tablet-device,id=sweet-tablet"],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,bufsize=1)
def qmp(events):
    s=socket.socket(socket.AF_UNIX)
    s.settimeout(5)
    s.connect(SOCKET)
    f=s.makefile("rw")
    assert "QMP" in f.readline()
    def call(execute,arguments=None):
        obj={"execute":execute}
        if arguments is not None:obj["arguments"]=arguments
        f.write(json.dumps(obj)+"\n");f.flush()
        value=json.loads(f.readline())
        if "error" in value: raise ValueError(value)
        return value
    call("qmp_capabilities")
    value=call("input-send-event",{"events":events})
    s.close()
    return value

q=Q()
try:
    for slot in range(32):
        q.mmio=MMIO_BASE+slot*0x200
        if q.readl(0)==0x74726976 and q.readl(8)==18:break
    else:raise RuntimeError("no VirtIO input device")
    print("INPUT_DEVICE",hex(q.mmio),"version",q.readl(4))
    q.writel(0x70,0);q.writel(0x70,3)
    q.writel(0x14,1);print("FEATURES_HIGH",hex(q.readl(0x10)))
    q.writel(0x24,0);q.writel(0x20,0)
    q.writel(0x24,1);q.writel(0x20,1)
    q.writel(0x70,11)
    assert q.readl(0x70)&8
    q.writel(0x30,0);maximum=q.readl(0x34);print("QUEUE_SIZE_MAX",maximum)
    assert maximum>=8
    q.writel(0x38,8)
    for low,v in ((0x80,DESC),(0x90,AVAIL),(0xa0,USED)):
        q.writel(low,v&0xffffffff);q.writel(low+4,v>>32)
    q.memwrite(DESC,b"".join(struct.pack("<QIHH",EVENT+i*8,8,2,0) for i in range(8)))
    q.memwrite(AVAIL,struct.pack("<HH"+"H"*8,0,8,*range(8)))
    q.memwrite(USED,b"\0"*128)
    q.writel(0x44,1)
    q.writel(0x70,15)
    print("QMP_INPUT",qmp([
        {"type":"abs","data":{"axis":"x","value":12000}},
        {"type":"abs","data":{"axis":"y","value":21000}},
        {"type":"btn","data":{"button":"left","down":True}}
    ]))
    for attempt in range(100):
        idx=struct.unpack_from("<H",q.memread(USED,4),2)[0]
        if idx>=3:break
        time.sleep(.03)
    print("USED_IDX",idx)
    for i in range(min(8,idx)):
        descriptor_id,length=struct.unpack("<II",q.memread(USED+4+i*8,8))
        type_,code,value=struct.unpack("<HHI",q.memread(EVENT+descriptor_id*8,8))
        print("EVENT",i,"descriptor",descriptor_id,"len",length,
              "type",type_,"code",code,"value",value)
    assert idx>=3,"tablet did not deliver events"
finally:
    q.close()
    print("QEMU_EXIT",q.proc.returncode)