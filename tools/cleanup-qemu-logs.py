#!/usr/bin/env python3
"""Delete only enormous historical QEMU debug logs, preserve every iOS image.

Dry-run by default. Keep 3 newest diagnostic runs and all console/packet captures.
Use --apply only after reading the planned manifest and confirming no guest runs.
"""
import argparse
from datetime import datetime,timezone
import json,os,pathlib,re,subprocess
p=argparse.ArgumentParser()
p.add_argument('--root',type=pathlib.Path,default=pathlib.Path('/home/ios-sweet-test'))
p.add_argument('--keep',type=int,default=3)
p.add_argument('--apply',action='store_true')
a=p.parse_args()
root=a.root.resolve(strict=True)
assert root == pathlib.Path('/home/ios-sweet-test'), 'Only the verified local test workspace may be cleaned'
assert 1<=a.keep<=30
live=subprocess.run(['pgrep','-af','qemu-system-aarch64'],capture_output=True,text=True)
if live.returncode==0 and live.stdout.strip():
 raise SystemExit('Refusing cleanup while any QEMU guest is running in this WSL distro')
pattern=re.compile(r'desktop-qemu-\d{8}-\d{6}$')
runs=sorted((d for d in root.iterdir() if d.is_dir() and not d.is_symlink() and pattern.fullmatch(d.name)),key=lambda d:d.name,reverse=True)
plan=[]
for d in runs[a.keep:]:
 f=d/'qemu.log'
 if not f.is_file() or f.is_symlink() or f.resolve().parent!=d:continue
 if f.stat().st_size < 5*1024*1024:continue
 context=any((d/x).is_file() for x in ('console.txt','console-now.txt','console-latest.txt','console-full.txt','console-final.txt','console-check.txt','console-trace.txt','result.json','network.pcap'))
 if not context:continue
 plan.append({'path':str(f),'size':f.stat().st_size,'context':True})
print('CLEANUP_PLAN',len(plan),'LOG_GIB',round(sum(item['size'] for item in plan)/1024**3,2),'KEPT_RUNS',a.keep)
for item in sorted(plan,key=lambda x:x['size'],reverse=True)[:10]:
 print(round(item['size']/1024**3,2),item['path'])
manifest=root/'inspection'/('qemu-log-cleanup-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.json')
manifest.parent.mkdir(exist_ok=True)
manifest.write_text(json.dumps({'applied':a.apply,'kept':sorted(d.name for d in runs[:a.keep]),'files':plan},indent=2)+'\n')
print('MANIFEST',manifest)
if a.apply:
 for item in plan:pathlib.Path(item['path']).unlink()
 print('REMOVED_ONLY_QEMU_LOG_FILES',len(plan))
else:print('DRY_RUN_NO_FILES_REMOVED')
