#!/usr/bin/env python3
"""Run the existing SWEET ARM64 payload in native Windows QEMU.

No Docker/WSL runtime is used. Apple firmware is supplied privately by
the user; the prepared iOS root disk is always mounted read-only under a
separate native QCOW2 overlay. QMP binds only to Windows loopback.
The simulator remains experimental: ARM64 on x86 uses QEMU TCG software
emulation, and Safari's iOS-side network readiness is not yet proven.
"""
import argparse
import ctypes
import datetime
import importlib.util
import json
import msvcrt
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
TOOL = Path(__file__).resolve().parent
WIN_RUNTIME = ROOT / 'windows-runtime'
WIN_GUEST = WIN_RUNTIME / 'guest'
WIN_STATE = WIN_RUNTIME / 'state'
sys.path.insert(0, str(TOOL))

spec = importlib.util.spec_from_file_location('iossweet_qemu', TOOL / 'qemu-sweet.py')
qemu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qemu)
view_spec = importlib.util.spec_from_file_location('iossweet_viewer', TOOL / 'qemu-live-screen.py')
viewer = importlib.util.module_from_spec(view_spec)
view_spec.loader.exec_module(viewer)

PORTABLE_QEMU_DIR = ROOT / 'windows-runtime/qemu'
QEMU_DIR = Path(os.environ.get(
    'IOS_SWEET_QEMU_DIR',
    str(PORTABLE_QEMU_DIR if (PORTABLE_QEMU_DIR / 'qemu-system-aarch64.exe').is_file()
        else Path(r'C:\Program Files\qemu'))))


def log(message):
    print(message, flush=True)


def free_ram_gib():
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [('dwLength', ctypes.c_ulong),
                    ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong),
                    ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong),
                    ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong),
                    ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
    memory = MEMORYSTATUSEX()
    memory.dwLength = ctypes.sizeof(memory)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise OSError('Unable to read Windows available RAM')
    return memory.ullAvailPhys / (1 << 30)


def check_single_instance():
    # On this PC, the old QEMU Docker guest must not overlap a native run.
    try:
        result = subprocess.run(['docker', 'ps', '--format', '{{.Names}}'],
                                capture_output=True, text=True, timeout=8)
        if result.returncode == 0 and any(
                x.startswith(('ios-sweet-qemu-', 'ios-sweet-netprobe-'))
                for x in result.stdout.splitlines()):
            raise RuntimeError('Docker iOS Sweet is still running. Stop it first; never run two iOS guests.')
    except FileNotFoundError:
        pass  # Docker is not required on Windows.
    except subprocess.TimeoutExpired:
        raise RuntimeError('Docker state could not be checked; refusing potential duplicate guest')
    result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq qemu-system-aarch64.exe',
                             '/FO', 'CSV', '/NH'], capture_output=True,
                            text=True, timeout=10)
    if result.returncode or 'qemu-system-aarch64.exe' in result.stdout.lower():
        raise RuntimeError('Another native ARM64 QEMU may be running; stop it before starting.')


def verify_own_qemu_pid(pid):
    """Confirm a saved PID is this project's QEMU before using QMP quit.

    An old active-native.json or reused localhost port must never cause
    `--stop` to close an unrelated emulator or service.
    """
    if os.name != 'nt' or type(pid) is not int or not 1 <= pid <= 0xffffffff:
        raise ValueError('Invalid native QEMU process identity')
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.QueryFullProcessImageNameW.argtypes = (
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_ulong))
    kernel32.QueryFullProcessImageNameW.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel32.OpenProcess(0x1000, 0, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        raise RuntimeError('Saved native QEMU PID is no longer running')
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.c_ulong(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer,
                                                   ctypes.byref(length)):
            raise RuntimeError('Cannot verify native QEMU executable path')
        expected = QEMU_DIR / 'qemu-system-aarch64.exe'
        if not expected.is_file() or not Path(buffer.value).samefile(expected):
            raise RuntimeError('Saved PID is not this project\'s QEMU; refusing to signal it')
    finally:
        kernel32.CloseHandle(handle)


def validate_file(path, description):
    path = path.resolve(strict=True)
    if not path.is_file():
        raise ValueError(description + ' must be an existing file')
    return path


def slash(path):
    return str(path).replace('\\', '/')


def guest_boot_args(cpus=1, diagnostics=False):
    """Keep costly sampling/tracing off for ordinary native Windows boots.

    Multi-core is opt-in until its boot and app behavior are validated. The
    `sweet_qemu_smp` switch changes only QEMU's virtual MPIDR/PSCI path.
    """
    if cpus not in (1, 2):
        raise ValueError('Only 1 CPU (stable) or 2 CPUs (experimental) supported')
    base = (
        'debug=0xc serial=3 cpus={cpus} keepsyms=1 '
        '-noprogress rd=virtiodisk0 unentitled_ios_sim_launch=1 rootrw=1 '
        'launchd_unsecure_cache=1 ignition_level=1 wdt_test=no_user_checkin '
        'wdt=-1 sweet_qemu_keep_awake=1 sweetfb_noconsole=1 '
        'sweet_qemu_network_delegate=1'
    ).format(cpus=cpus)
    if cpus > 1:
        base += ' sweet_qemu_smp=1'
    if diagnostics:
        base += (' -enable_kprintf_spam '
                 'sweetsample=SpringBoard,lsd,MobileGestaltHel,backboardd '
                 'sweetsample_delay=12 sweetsample_interval=25 '
                 'sweet_qemu_network_trace=1 sweet_qemu_necp_trace=1')
    else:
        # Patch 0049 normally traces up to 400 backboardd IOKit matches.
        # Preserve full trace access for --diagnostics, but skip costly
        # dictionary serialization and printing in normal iOS sessions.
        base += ' sweetiolog=- sweet_aks_quiet=1'
    return base


def check_overlay(qemu_img, disk, overlay):
    if overlay.exists():
        data = json.loads(subprocess.check_output(
            [str(qemu_img), 'info', '--output=json', slash(overlay)],
            text=True, timeout=30))
        backing = data.get('full-backing-filename') or data.get('backing-filename')
        if (data.get('format') != 'qcow2' or not backing
                or data.get('backing-filename-format') != 'raw'
                or slash(Path(backing).resolve()).lower() != slash(disk).lower()):
            raise RuntimeError('Existing Windows overlay has a different backing disk. Refusing to modify it.')
    else:
        overlay.parent.mkdir(parents=True, exist_ok=True)
        prior = ROOT / 'docker/local-state/oneclick/ios.qcow2'
        if prior.is_file() and prior.resolve() != overlay.resolve():
            # The DNS/SystemConfiguration bootstrap and iOS app preferences
            # are in this private overlay. Preserve them when switching
            # away from Docker. Never edit the source Docker QCOW2.
            if prior.is_symlink():
                raise RuntimeError('Old overlay is a symlink; refusing migration')
            partial = Path(str(overlay)+'.migrating')
            if partial.exists() or partial.is_symlink():
                raise RuntimeError('Old native migration scratch must be reviewed before retry')
            try:
                shutil.copy2(prior, partial)
                subprocess.run([str(qemu_img), 'rebase', '-u', '-f', 'qcow2',
                                '-F', 'raw', '-b', slash(disk), slash(partial)],
                               check=True, timeout=60)
                validate_overlay_info(qemu_img, disk, partial)
                os.replace(partial, overlay)
                log('MIGRATED_PRIVATE_DOCKER_OVERLAY_WITH_NEW_WINDOWS_BACKING_PATH')
            finally:
                partial.unlink(missing_ok=True)
        else:
            subprocess.run([str(qemu_img), 'create', '-f', 'qcow2',
                            '-F', 'raw', '-b', slash(disk), slash(overlay)],
                           check=True, timeout=30)
        check_overlay(qemu_img, disk, overlay)


def validate_overlay_info(qemu_img, disk, overlay):
    data = json.loads(subprocess.check_output(
        [str(qemu_img), 'info', '--output=json', slash(overlay)],
        text=True, timeout=30))
    backing = data.get('full-backing-filename') or data.get('backing-filename')
    if (data.get('format') != 'qcow2' or not backing
            or data.get('backing-filename-format') != 'raw'
            or slash(Path(backing).resolve()).lower() != slash(disk).lower()):
        raise RuntimeError('QCOW2 has incorrect backing disk; refusing to boot')


def check_ports(qmp_port, viewer_port):
    if qmp_port == viewer_port:
        raise ValueError('QMP and viewer must use different ports')
    for port in (qmp_port, viewer_port):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', port))


def stop_native(state):
    active = state / 'active-native.json'
    if not active.is_file():
        log('NO_ACTIVE_NATIVE_IOS_GUEST')
        return
    record = json.loads(active.read_text())
    verify_own_qemu_pid(record['qemu_pid'])
    port = int(record['qmp_port'])
    if not (1 <= port <= 65535):
        raise ValueError('Invalid saved QMP port')
    # Request an orderly QEMU exit to flush the QCOW2 overlay. Never kill an
    # unrelated process or erase the persistent native guest disk.
    with qemu.connect_qmp(f'tcp://127.0.0.1:{port}') as connection:
        file = connection.makefile('rw')
        if not file.readline():
            raise RuntimeError('Native QEMU did not reply to QMP handshake')
        file.write('{"execute":"qmp_capabilities"}\n')
        file.flush()
        while True:
            result = json.loads(file.readline())
            if 'return' in result or 'error' in result:
                if 'error' in result:
                    raise RuntimeError(str(result['error']))
                break
        file.write('{"execute":"quit"}\n')
        file.flush()
    log('NATIVE_QEMU_GRACEFUL_SHUTDOWN_REQUESTED')


def prepare(args, state, qemu_bin, qemu_img, require_ram=True):
    kernel = validate_file(args.kernel, 'Kernel')
    disk = validate_file(args.disk, 'Apple iOS root disk')
    # The Apple d22ap tree is retained privately for firmware preparation.
    # QEMU's virt board MUST use the project's generated QEMU-specific ADT:
    # the actual iPhone tree lacks /chosen/dram-base and MMIO virt addresses.
    if disk.stat().st_size != 16 * (1 << 30):
        raise ValueError('Expected the verified 16 GiB iOS HFSX disk')
    if args.kernel_sha256:
        import hashlib
        digest = hashlib.sha256(kernel.read_bytes()).hexdigest()
        if digest.lower() != args.kernel_sha256.lower():
            raise RuntimeError('Kernel checksum mismatch: refusing boot')
    run = state / ('windows-qemu-' + datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S'))
    if run.exists():
        raise RuntimeError('Existing native run directory: '+str(run))
    run.mkdir(parents=True)
    qemu_adt = run / 'qemu.adt'
    adt_cmd = [sys.executable, str(TOOL / 'mkadt.py'),
               str(qemu_adt), '--qemu', '--highmem',
               '--qemu-cpus='+str(args.cpus)]
    if args.srgb_display:
        adt_cmd.append('--qemu-srgb-display')
    subprocess.run(adt_cmd,
                   check=True, timeout=60)
    log('NATIVE_QEMU_DISPLAY_GAMUT='+('sRGB_EXPERIMENT' if args.srgb_display else 'P3_ORIGINAL'))
    cmdline = guest_boot_args(args.cpus, args.diagnostics)
    payload = run / 'payload.bin'
    subprocess.run([sys.executable, str(TOOL / 'mkpayload.py'),
                    str(kernel), str(qemu_adt), str(payload), '--cmdline', cmdline],
                   check=True, timeout=90)
    data = payload.read_bytes()
    phys, image, ba_pa, entry = qemu.build_image(data)
    (run / 'ram.bin').write_bytes(image)
    (run / 'stub.bin').write_bytes(qemu.stub(ba_pa, entry))
    mem_size = struct.unpack_from('<Q', data, 0x40)[0]
    ram_gib = max(4, -(-(phys + mem_size - 0x40000000) // (1 << 30)))
    if ram_gib > 12:
        raise ValueError('Unexpected guest RAM size')
    # This is a guard against making an already paging Windows host much
    # slower. User can free RAM and retry without touching any saved overlay.
    available = free_ram_gib()
    # A 7 GiB QEMU address space does not commit every byte at startup.
    # The earlier working guest used ~5.2 GiB of resident RAM. Reserve
    # at least 6 GiB, warn if short of the whole virtual address space.
    minimum_free = max(6, ram_gib - 1)
    if require_ram and available < minimum_free:
        raise RuntimeError(f'Windows has only {available:.1f} GiB free, but this QEMU '
                           f'guest maps {ram_gib} GiB. At least {minimum_free:.1f} GiB '
                           'must be free to safely begin booting.')
    if require_ram and available < ram_gib:
        log(f'WARNING: HOST_RAM_FREE_{available:.1f}GiB_BELOW_GUEST_ADDRESS_SPACE_{ram_gib}GiB')
    if require_ram:
        check_overlay(qemu_img, disk, args.overlay)
    log(f'PREPARED_NATIVE_QEMU_GUEST_RAM={ram_gib}GiB WINDOWS_FREE={available:.1f}GiB')
    return run, disk, ram_gib, phys


def start(args):
    if os.name != 'nt':
        raise RuntimeError('Native Windows backend must be run from Windows, not Docker or WSL')
    qemu_bin = QEMU_DIR / 'qemu-system-aarch64.exe'
    qemu_img = QEMU_DIR / 'qemu-img.exe'
    for path in (qemu_bin, qemu_img):
        validate_file(path, 'Native QEMU executable')
    check_single_instance()
    if args.cpus > 1 and args.overlay.resolve() == (WIN_STATE/'ios.qcow2').resolve():
        raise RuntimeError('Experimental two-core QEMU cannot write the known-good '
                           'iOS overlay. Supply a separately backed-up test overlay.')
    check_ports(args.qmp_port, args.port)
    state = args.state.resolve()
    state.mkdir(parents=True, exist_ok=True)
    # Atomic Windows file lock closes the small TOCTOU window between
    # process enumeration and launch. The handle remains open until QEMU
    # and the local viewer both exit. It never deletes user state.
    with (state / 'native-instance.lock').open('a+b') as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError('Native iOS Sweet is already starting/running') from error
        try:
            run_locked(args, state, qemu_bin, qemu_img)
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def run_locked(args, state, qemu_bin, qemu_img):
    run, disk, ram_gib, phys = prepare(args, state, qemu_bin, qemu_img)
    endpoint = f'tcp://127.0.0.1:{args.qmp_port}'
    argv = [str(qemu_bin), '-M', 'virt,gic-version=3',
            '-accel', 'tcg,thread=multi',
            '-global', 'virtio-mmio.force-legacy=false',
            '-cpu', 'cortex-a76', '-smp', str(args.cpus), '-m', f'{ram_gib}G',
            '-nic', 'none', '-nographic',
            '-serial', 'file:' + slash(run / 'serial.txt'),
            '-qmp', f'tcp:127.0.0.1:{args.qmp_port},server=on,wait=off',
            '-no-reboot',
            '-device', f'loader,file={slash(run / "ram.bin")},addr={phys:#x},force-raw=on',
            '-device', f'loader,file={slash(run / "stub.bin")},addr={qemu.STUB_PA:#x},force-raw=on',
            '-device', f'loader,addr={qemu.STUB_PA:#x},cpu-num=0',
            '-drive', f'if=none,id=iosroot,format=qcow2,file={slash(args.overlay)},snapshot=off',
            '-device', 'virtio-blk-device,drive=iosroot',
            '-device', 'virtio-tablet-device,id=sweet-tablet',
            '-netdev', 'user,id=sweetnet,net=10.0.2.0/24',
            '-device', 'virtio-net-device,netdev=sweetnet,mac=02:50:53:57:00:01']
    if args.diagnostics:
        argv += ['-d', 'guest_errors,unimp',
                 '-D', slash(run / 'qemu.log'),
                 '-object', f'filter-dump,id=sweetdump,netdev=sweetnet,file={slash(run / "network.pcap")}']
    (run / 'command.json').write_text(json.dumps(argv[1:], indent=2))
    log('NATIVE_WINDOWS_QEMU='+str(qemu_bin))
    qemu_log = (run / 'qemu-stdout.txt').open('w', encoding='utf-8')
    process = None
    server = None
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                   stdout=qemu_log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError(f'Native QEMU exited {process.returncode}; inspect {run / "qemu-stdout.txt"}')
            try:
                with qemu.connect_qmp(endpoint) as conn:
                    if conn.recv(512):
                        break
            except (ConnectionError, OSError):
                time.sleep(.2)
        else:
            raise RuntimeError('Native QEMU QMP did not become ready')
        viewer.ViewerHandler.outdir = run
        viewer.ViewerHandler.input_enabled = True
        viewer.ViewerHandler.qmp_tcp = endpoint
        viewer.ViewerHandler.runtime_info = {
            'mode': 'Native Windows QEMU',
            'cores': args.cpus,
            'diagnostics': args.diagnostics,
        }
        viewer.ViewerHandler.reset_cache()
        server = viewer.ThreadingHTTPServer(('127.0.0.1', args.port), viewer.ViewerHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        (state / 'active-native.json').write_text(json.dumps({
            'qemu_pid': process.pid, 'qmp_port': args.qmp_port,
            'viewer_port': args.port, 'run': str(run),
            'srgb_display': args.srgb_display,
            'cpus': args.cpus, 'diagnostics': args.diagnostics}, indent=2))
        log(f'NATIVE_WINDOWS_VIEWER_READY=http://127.0.0.1:{args.port}/')
        if not args.no_browser:
            webbrowser.open(f'http://127.0.0.1:{args.port}/')
        while process.poll() is None:
            time.sleep(.5)
        log('QEMU_EXITED='+str(process.returncode))
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if process and process.poll() is None:
            try:
                qemu.qmp(endpoint, 'quit')
                process.wait(timeout=12)
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
        qemu_log.close()
        active = state / 'active-native.json'
        if active.is_file():
            active.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, default=WIN_GUEST / 'kernel.development.sweet')
    parser.add_argument('--disk', type=Path, default=WIN_GUEST / 'ios16-net-test.raw')
    parser.add_argument('--overlay', type=Path, default=WIN_STATE / 'ios.qcow2')
    parser.add_argument('--state', type=Path, default=WIN_STATE)
    parser.add_argument('--kernel-sha256', default='85039335d05d335d1f9b33f7c8131d274477c50020915ff0335b42428abe998a')
    parser.add_argument('--port', type=int, default=8108)
    parser.add_argument('--qmp-port', type=int, default=4444)
    parser.add_argument('--cpus', type=int, default=1, choices=(1, 2),
                        help='one core is verified; two-core QEMU is an isolated experimental mode')
    parser.add_argument('--diagnostics', action='store_true',
                        help='opt in to verbose kernel traces, sampling and network PCAP; avoid for normal use')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--srgb-display', action='store_true',
                        help='experiment: advertise an 8-bit sRGB screen instead of iPhone X P3 in synthetic QEMU /product ADT')
    parser.add_argument('--check', action='store_true', help='validate native Windows dependencies without starting or stopping a guest')
    parser.add_argument('--prepare-only', action='store_true',
                        help='build QEMU RAM/boot images using native Windows Python without starting a guest or changing any iOS disk')
    parser.add_argument('--stop', action='store_true', help='ask the Windows QEMU guest to exit cleanly')
    args = parser.parse_args()
    if args.stop:
        stop_native(args.state)
        return
    if args.check:
        installed = (QEMU_DIR / 'qemu-system-aarch64.exe').is_file() and \
                    (QEMU_DIR / 'qemu-img.exe').is_file()
        kernel_ok = args.kernel.is_file()
        disk_ok = args.disk.is_file() and args.disk.stat().st_size == 16 * (1 << 30)
        print('WINDOWS_NATIVE_QEMU='+str(QEMU_DIR / 'qemu-system-aarch64.exe'))
        print('QEMU_INSTALLED='+str(installed))
        print('KERNEL_AVAILABLE='+str(kernel_ok))
        print('IOS_DISK_AVAILABLE='+str(disk_ok))
        print('QEMU_DEVICE_TREE=GENERATED_NATIVELY')
        print(f'WINDOWS_FREE_RAM_GIB={free_ram_gib():.2f}')
        print('NATIVE_ARM64_ACCEL=TCG_SOFTWARE_ONLY')
        # A double-click must fail clearly when setup files are absent; a
        # successful --check used to exit 0 even if everything was missing.
        # Do not enforce available RAM here: an ALREADY RUNNING guest uses RAM
        # and must still be reopenable by the desktop launcher.
        if not installed or not kernel_ok or not disk_ok:
            raise SystemExit('Missing native Windows prerequisites. See '
                             'docs/NATIVE_WINDOWS.md for setup and verified files.')
        return
    if args.prepare_only:
        if os.name != 'nt':
            raise RuntimeError('Windows-only preparation')
        state = args.state.resolve()
        state.mkdir(parents=True, exist_ok=True)
        run, disk, ram_gib, phys = prepare(args, state,
            validate_file(QEMU_DIR/'qemu-system-aarch64.exe','QEMU executable'),
            validate_file(QEMU_DIR/'qemu-img.exe','QEMU img executable'),
            require_ram=False)
        print('NATIVE_WINDOWS_PAYLOAD_PREPARED='+str(run/'payload.bin'))
        print('NATIVE_WINDOWS_REQUIRED_RAM_GIB='+str(ram_gib))
        print('NATIVE_WINDOWS_GUEST_NOT_STARTED')
        return
    start(args)


if __name__ == '__main__':
    main()
