#!/usr/bin/env python3
"""Synthetic localhost QMP protocol test; no QEMU, disk, or iOS instance."""
import importlib.util
import json
from pathlib import Path
import socket
import threading

tool = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('test_qemu', tool/'qemu-sweet.py')
qemu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qemu)
view_spec = importlib.util.spec_from_file_location('test_viewer', tool/'qemu-live-screen.py')
viewer = importlib.util.module_from_spec(view_spec)
view_spec.loader.exec_module(viewer)


def serve(listener, observed):
    for _ in range(2):
        connection, _ = listener.accept()
        with connection:
            handle = connection.makefile('rw')
            handle.write(json.dumps({'QMP':{'version':{'qemu':{'major':11,'minor':1,'micro':0}},
                                             'capabilities':[]}})+'\n')
            handle.flush()
            while True:
                line = handle.readline()
                if not line:
                    break
                request = json.loads(line)
                observed.append(request)
                handle.write(json.dumps({'return': {}})+'\n')
                handle.flush()


def main():
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(2)
    seen = []
    worker = threading.Thread(target=serve, args=(listener, seen), daemon=True)
    worker.start()
    endpoint = f'tcp://127.0.0.1:{listener.getsockname()[1]}'
    qemu.qmp(endpoint, pmemsave=(0x9c000000, 4096, 'dummy-frame.raw'))
    viewer.qmp_tablet_event(endpoint, [
        {'type':'abs','data':{'axis':'x','value':20000}},
        {'type':'btn','data':{'button':'left','down':True}}])
    listener.close()
    assert [r['execute'] for r in seen] == [
        'qmp_capabilities','pmemsave','qmp_capabilities','input-send-event']
    assert seen[1]['arguments']['size'] == 4096
    assert seen[3]['arguments']['events'][1]['data']['down']
    print('WINDOWS_LOOPBACK_QMP_AND_TOUCH_PROTOCOL_PASS')


if __name__=='__main__':
    main()
