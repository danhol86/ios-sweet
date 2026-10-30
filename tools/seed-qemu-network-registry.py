#!/usr/bin/env python3
"""Experimental iOS guest registry test. NEVER edits an existing image/disk."""
import argparse
import pathlib
import plistlib
import subprocess

p=argparse.ArgumentParser()
p.add_argument('--base', required=True, type=pathlib.Path)
p.add_argument('--overlay', required=True, type=pathlib.Path)
p.add_argument('--config-dir', default='/home/ios-sweet-test/inspection', type=pathlib.Path)
p.add_argument('--io-path', default='IOService:/D22AP/SweetPlatformExpert/sweet-qemu-virtio-net/en0')
a=p.parse_args()
assert a.base.is_file(), a.base
assert not a.overlay.exists(), 'Target already exists; refusing to touch another guest'
assert a.base.resolve()!=a.overlay.resolve()
a.config_dir.mkdir(parents=True,exist_ok=True)
source=a.config_dir/'guest-networkinterfaces.plist'
assert source.is_file(), 'Original guest registry snapshot missing'
value=plistlib.loads(source.read_bytes())
assert not value.get('Interfaces'), 'Expected an empty test registry'
value['Interfaces']=[{
    'Active':True, 'BSD Name':'en0', 'IOBuiltin':True,
    'IOInterfaceNamePrefix':'en','IOInterfaceType':6,'IOInterfaceUnit':0,
    'IOMACAddress':bytes.fromhex('025053570001'), 'IOPathMatch':a.io_path,
    'SCNetworkInterfaceInfo':{'UserDefinedName':'QEMU Ethernet'},
    'SCNetworkInterfaceType':'Ethernet',
}]
prepared=a.config_dir/'iossweet-qemu-registered-plist'
prepared.write_bytes(plistlib.dumps(value,fmt=plistlib.FMT_BINARY))
def run(*args):
    cp=subprocess.run(args,capture_output=True,text=True,timeout=180)
    if cp.returncode:raise RuntimeError(f'{args[0]}: {cp.stderr[-1000:]}')
run('qemu-img','create','-f','qcow2','-F','raw','-b',str(a.base),str(a.overlay))
guest='/private/var/preferences/SystemConfiguration/NetworkInterfaces.plist'
run('guestfish','-a',str(a.overlay),'run',':','mount-options','force,rw','/dev/sda','/',':',
    'upload',str(prepared),guest)
verified=a.config_dir/'iossweet-qemu-registered-verified.plist'
run('guestfish','--ro','-a',str(a.overlay),'-m','/dev/sda:/','download',guest,str(verified))
assert plistlib.loads(verified.read_bytes())==value, 'Guest registry differs'
print('EXPERIMENTAL_INTERFACE_REGISTRY_VERIFIED',a.overlay)
