#!/usr/bin/env python3
"""Host-side QEMU qtest of VirtIO MMIO split-ring request. Does not boot XNU."""
import argparse
import os
import struct
import subprocess
import time

PBASE = 0x40010000
MMIO_BASE = 0x0a000000
DESC, AVAIL, USED, HEADER, DATA, STATUS = (PBASE+x for x in (0, 0x1000, 0x2000, 0x3000, 0x4000, 0x5000))

class Qtest:
    def __init__(self, image):
        self.mmio = MMIO_BASE
        self.proc = subprocess.Popen([
            "qemu-system-aarch64", "-M", "virt,gic-version=3", "-global", "virtio-mmio.force-legacy=false",
            "-cpu", "cortex-a76", "-m", "256M",
            "-display", "none", "-serial", "none", "-monitor", "none", "-S",
            "-qtest", "stdio", "-drive",
            f"if=none,id=iosdisk,file={image},format=raw,snapshot=on",
            "-device", "virtio-blk-device,drive=iosdisk"
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)

    def request(self, msg):
        self.proc.stdin.write(msg+"\n")
        self.proc.stdin.flush()
        reply=self.proc.stdout.readline().strip()
        if not reply.startswith("OK"):
            raise RuntimeError(f"{msg[:90]} -> {reply[:160]}")
        return reply[2:].strip()

    def readl(self, off):
        return int(self.request(f"readl {self.mmio+off:#x}"),16)

    def writel(self, off, val):
        self.request(f"writel {self.mmio+off:#x} {val:#x}")

    def memwrite(self, addr, blob):
        self.request(f"write {addr:#x} {len(blob):#x} 0x{blob.hex()}")

    def memread(self, addr, size):
        v=self.request(f"read {addr:#x} {size:#x}")
        return bytes.fromhex(v.removeprefix("0x"))

    def close(self):
        self.proc.terminate()
        try: self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired: self.proc.kill()

def main():
    p=argparse.ArgumentParser()
    p.add_argument("disk")
    a=p.parse_args()
    q=Qtest(a.disk)
    try:
        for slot in range(32):
            q.mmio = MMIO_BASE + slot * 0x200
            if q.readl(0) == 0x74726976 and q.readl(8) == 2:
                break
        else:
            raise RuntimeError("VirtIO block device was not found")
        print("device at", hex(q.mmio))
        print("virtio version:", q.readl(4))
        assert q.readl(4) == 2
        assert q.readl(8) == 2
        q.writel(0x70,0)
        q.writel(0x70,3)
        q.writel(0x14,0)
        low_features=q.readl(0x10)
        print("low features:",hex(low_features))
        assert low_features & (1 << 9), "VirtIO disk lacks FLUSH support"
        q.writel(0x14,1)
        print("high features:",hex(q.readl(0x10)))
        assert q.readl(0x10)&1
        q.writel(0x24,0);q.writel(0x20,1 << 9)
        q.writel(0x24,1);q.writel(0x20,1)
        q.writel(0x70,11)
        assert q.readl(0x70)&8
        q.writel(0x30,0)
        assert q.readl(0x34)>=8
        q.writel(0x38,8)
        for lo,v in ((0x80,DESC),(0x90,AVAIL),(0xa0,USED)):
            q.writel(lo,v&0xffffffff)
            q.writel(lo+4,v>>32)
        q.memwrite(DESC,b"\0"*128)
        q.memwrite(AVAIL,b"\0"*32)
        q.memwrite(USED,b"\0"*128)
        q.writel(0x44,1)
        q.writel(0x70,15)
        capacity=q.readl(0x100)|(q.readl(0x104)<<32)
        print("capacity sectors",capacity)
        assert capacity*512==os.path.getsize(a.disk)
        next_idx=0
        def io(sector, write=False, blob=None, flush=False):
            nonlocal next_idx
            q.memwrite(HEADER,struct.pack("<IIQ",4 if flush else (1 if write else 0),0,sector))
            if write:
                assert blob is not None and len(blob)==512
                q.memwrite(DATA,blob)
            q.memwrite(STATUS,b"\xff")
            if flush:
                q.memwrite(DESC,b"".join((
                    struct.pack("<QIHH",HEADER,16,1,1),
                    struct.pack("<QIHH",STATUS,1,2,0)
                )))
            else:
                q.memwrite(DESC,b"".join((
                    struct.pack("<QIHH",HEADER,16,1,1),
                    struct.pack("<QIHH",DATA,512,1 if write else 3,2),
                    struct.pack("<QIHH",STATUS,1,2,0)
                )))
            q.memwrite(AVAIL+4+2*(next_idx%8),struct.pack("<H",0))
            next_idx+=1
            q.memwrite(AVAIL+2,struct.pack("<H",next_idx))
            q.writel(0x50,0)
            for attempt in range(100):
                if struct.unpack_from("<H",q.memread(USED,4),2)[0]==next_idx:
                    break
                time.sleep(0.02)
            else: raise RuntimeError("VirtIO queue never completed")
            status=q.memread(STATUS,1)
            assert status==b"\0", f"VirtIO returned error {status!r}"
            return q.memread(DATA,512)

        image_data=io(2)
        status=b"\0"
        print("request_status",status.hex(),"HFS signature at sector 2",image_data[:2].hex())
        with open(a.disk,"rb") as f:
            f.seek(1024)
            assert image_data == f.read(512), "QEMU disk read differs from image"
        print("VIRTIO_QTEST_READ_MATCH")
        # The second test intentionally writes only to QEMU's temporary
        # snapshot. Verify both the guest readback and the untouched source.
        test_sector=capacity-2
        with open(a.disk,"rb") as f:
            f.seek(test_sector*512)
            original=f.read(512)
        payload=(b"ios-sweet-virtio-qtest"*24)[:512].ljust(512,b"!")
        io(test_sector,write=True,blob=payload)
        assert io(test_sector)==payload
        io(0,flush=True)
        print("VIRTIO_QTEST_FLUSH_OK")
        with open(a.disk,"rb") as f:
            f.seek(test_sector*512)
            assert f.read(512)==original, "Source image changed!"
        print("VIRTIO_QTEST_WRITE_SNAPSHOT_MATCH")
    finally:
        q.close()

if __name__=="__main__":
    main()
