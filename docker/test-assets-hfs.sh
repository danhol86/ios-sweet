#!/bin/bash
# Disposable, synthetic filesystem integration test. No Apple files involved.
set -euo pipefail
export LIBGUESTFS_BACKEND=direct LIBGUESTFS_MEMSIZE=512
test -c /dev/fuse
mkdir -p /scratch /mnt/test-iossweet
out=/scratch/iossweet-hfs-mount-test.img
test ! -e "$out"
truncate -s 128M "$out"
mkfs.hfsplus -s -J -v iOSRoot "$out"
guestmount -a "$out" -m /dev/sda:/:force,rw --rw /mnt/test-iossweet
echo 'iossweet-synthetic-hfs-pass' >/mnt/test-iossweet/single-instance-test.txt
guestunmount /mnt/test-iossweet
guestfish --ro -a "$out" -m /dev/sda:/ cat /single-instance-test.txt
rm -f "$out"
echo 'GUESTMOUNT_HFS_WRITE_READ_SUCCESS'
