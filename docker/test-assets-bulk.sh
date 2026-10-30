#!/bin/bash
# Fully synthetic native-ext4-to-HFS bulk-copy integration smoke.
# No Apple OS image is used, and the scratch filesystem is deleted.
set -euo pipefail
export LIBGUESTFS_BACKEND=direct LIBGUESTFS_MEMSIZE=512
test -c /dev/fuse
test ! -e /scratch/bulk-hfs.img
mkdir -p /mnt/iossweet-bulk-stage
truncate -s 128M /scratch/bulk-hfs.img
mkfs.hfsplus -s -J -v iOSRoot /scratch/bulk-hfs.img
truncate -s 128M /scratch/bulk-stage.ext4
mkfs.ext4 -q -F /scratch/bulk-stage.ext4
mount -t ext4 -o loop /scratch/bulk-stage.ext4 /mnt/iossweet-bulk-stage
mkdir -p /mnt/iossweet-bulk-stage/Test
printf 'iossweet-tar-bulk-pass' > /mnt/iossweet-bulk-stage/Test/file.txt
ln /mnt/iossweet-bulk-stage/Test/file.txt /mnt/iossweet-bulk-stage/Test/hardlink.txt
ln -s file.txt /mnt/iossweet-bulk-stage/Test/symlink.txt
chown 501:501 /mnt/iossweet-bulk-stage/Test/file.txt
tar --numeric-owner -C /mnt/iossweet-bulk-stage -cpf /scratch/bulk.tar .
umount /mnt/iossweet-bulk-stage
guestfish -a /scratch/bulk-hfs.img run : mount-options force,rw /dev/sda / : tar-in /scratch/bulk.tar /
guestfish --ro -a /scratch/bulk-hfs.img -m /dev/sda:/ cat /Test/file.txt
guestfish --ro -a /scratch/bulk-hfs.img -m /dev/sda:/ readlink /Test/symlink.txt
guestfish --ro -a /scratch/bulk-hfs.img -m /dev/sda:/ stat /Test/file.txt
rm -f /scratch/bulk.tar /scratch/bulk-stage.ext4 /scratch/bulk-hfs.img
echo 'BULK_HFS_IMPORT_READWRITE_AND_LINKS_SUCCESS'
