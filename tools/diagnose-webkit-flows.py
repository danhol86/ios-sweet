#!/usr/bin/env python3
"""Read-only, payload-free TCP flow audit for a private QEMU guest capture.

Only prints counts and TCP metadata. Never prints URLs, request data,
credentials or arbitrary destination names. Identifies known smoke-test
IP addresses using the matching DNS replies in the same PCAP.
"""
import collections
import importlib.util
import ipaddress
import struct
import sys
from pathlib import Path

spec=importlib.util.spec_from_file_location(
    'safari_pcap', Path(__file__).with_name('check-safari-pcap.py'))
parser=importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)
dns_name=parser.dns_name

APPROVED = ('google.com', 'example.com', 'neverssl.com')
GUEST = '10.0.2.15'


def packets(path):
    with path.open('rb') as f:
        header = f.read(24)
        if len(header) != 24 or header[:4] != b'\xd4\xc3\xb2\xa1':
            raise ValueError('Expected Ethernet little-endian PCAP')
        while True:
            header = f.read(16)
            if not header:
                break
            if len(header) != 16:
                raise ValueError('Truncated capture')
            sec, usec, captured, original = struct.unpack('<IIII', header)
            if captured > 65536:
                raise ValueError('Unexpected packet size')
            p = f.read(captured)
            if len(p) != captured:
                raise ValueError('Truncated packet')
            if len(p) < 34 or p[12:14] != b'\x08\x00':
                continue
            i = 14
            ihl = (p[i] & 15) * 4
            if ihl < 20 or len(p) < i+ihl+8:
                continue
            src, dst = tuple(str(ipaddress.IPv4Address(p[pos:pos+4]))
                             for pos in (i+12, i+16))
            yield sec+usec/1e6, p, i+ihl, src, dst


def analyze(path):
    dns_addresses = collections.defaultdict(set)
    flows = {}
    for timestamp, p, start, src, dst in packets(path):
        if p[23] == 17 and len(p) >= start+8:
            sport, dport = struct.unpack_from('!HH', p, start)
            if sport != 53 or dst != GUEST:
                continue
            dns = p[start+8:]
            if len(dns) < 12 or not dns[2] & 0x80:
                continue
            name, pos = dns_name(dns, 12)
            if not name or not any(name.endswith(d) for d in APPROVED):
                continue
            pos += 4
            for _ in range(min(struct.unpack_from('!H', dns, 6)[0], 40)):
                if pos+2 > len(dns):
                    break
                if dns[pos] & 0xc0 == 0xc0:
                    pos += 2
                else:
                    _, pos = dns_name(dns, pos)
                if pos+10 > len(dns):
                    break
                typ, _, _, size = struct.unpack_from('!HHIH', dns, pos)
                pos += 10
                if pos+size > len(dns):
                    break
                if typ == 1 and size == 4:
                    category = next(d for d in APPROVED if name.endswith(d))
                    dns_addresses[str(ipaddress.IPv4Address(dns[pos:pos+4]))].add(category)
                pos += size
            continue
        if p[23] != 6 or len(p) < start+20:
            continue
        sport, dport = struct.unpack_from('!HH', p, start)
        outgoing = src == GUEST and dport in (80,443)
        incoming = dst == GUEST and sport in (80,443)
        if not outgoing and not incoming:
            continue
        remote = dst if outgoing else src
        clientport = sport if outgoing else dport
        targetport = dport if outgoing else sport
        key = remote, clientport, targetport
        f = flows.setdefault(key, {'counts':collections.Counter(), 'unique':set(),
                                    'first':timestamp, 'last':timestamp,
                                    'bytes': collections.Counter(),
                                    'window_min': {}, 'window_max': {}})
        f['last'] = timestamp
        direction = 'out' if outgoing else 'in'
        flags = p[start+13]
        seq, ack = struct.unpack_from('!II',p,start+4)
        win = struct.unpack_from('!H',p,start+14)[0]
        f['window_min'][direction] = min(win, f['window_min'].get(direction,win))
        f['window_max'][direction] = max(win, f['window_max'].get(direction,win))
        tcp_hl = ((p[start+12] >> 4)&15)*4
        if tcp_hl < 20:
            continue
        data = p[start+tcp_hl:]
        f['bytes'][direction] += len(data)
        f['counts'][direction+'pkt'] += 1
        if flags & 2:
            f['counts'][direction+'syn'] += 1
        if flags & 16:
            f['counts'][direction+'ack'] += 1
        if flags & 4:
            f['counts'][direction+'rst'] += 1
        if flags & 1:
            f['counts'][direction+'fin'] += 1
        if data:
            f['counts'][direction+'data'] += 1
            segment=(direction,seq,len(data))
            if segment in f['unique']:
                f['counts'][direction+'retransmit'] += 1
            f['unique'].add(segment)
            if outgoing and targetport==80 and data.startswith((b'GET ',b'POST ',b'HEAD ')):
                f['counts']['http_request'] += 1
            if incoming and targetport==80 and data.startswith(b'HTTP/'):
                f['counts']['http_response'] += 1
    summaries=[]
    for (addr,port,dport),flow in flows.items():
        names = dns_addresses.get(addr,set())
        if not names and dport!=80:
            continue
        c=flow['counts']
        summaries.append({
            'dest': '+'.join(sorted(names)) if names else 'other-http',
            'port':dport,
            'duration_sec':round(flow['last']-flow['first'],1),
            'out_bytes':flow['bytes']['out'],
            'in_bytes':flow['bytes']['in'],
            'out_syn':c['outsyn'], 'in_syn':c['insyn'],
            'in_data_pkt':c['indata'], 'out_data_pkt':c['outdata'],
            'tcp_out_retrans':c['outretransmit'],'tcp_in_retrans':c['inretransmit'],
            'out_fin':c['outfin'], 'in_fin':c['infin'],
            'out_rst':c['outrst'], 'in_rst':c['inrst'],
            'windows_min_out':flow['window_min'].get('out'),
            'windows_min_in':flow['window_min'].get('in'),
            'http_req':c['http_request'], 'http_resp':c['http_response'],
        })
    import json
    selected=sorted(summaries, key=lambda x:(x['dest'],x['port'],x['out_bytes']), reverse=True)
    print('SMOKE_TEST_TCP_FLOWS', len(selected))
    for row in selected[:75]:
        print(json.dumps(row,sort_keys=True))


if __name__=='__main__':
    analyze(Path(sys.argv[1]))
