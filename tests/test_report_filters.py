"""DRIVES section must show real disks, not snap/squashfs/ro pseudo-mounts."""
from __future__ import annotations

from collections import namedtuple

from superclean.report import _keep_partition

Part = namedtuple("Part", ["device", "mountpoint", "fstype", "opts"])


def test_real_root_is_kept():
    assert _keep_partition(Part("/dev/sda2", "/", "ext4", "rw,relatime,errors=remount-ro"))


def test_efi_is_kept():
    assert _keep_partition(Part("/dev/sda1", "/boot/efi", "vfat", "rw,relatime"))


def test_snap_squashfs_is_dropped():
    assert not _keep_partition(Part("/dev/loop3", "/snap/core22/2411", "squashfs", "ro,nodev"))


def test_any_readonly_mount_is_dropped():
    assert not _keep_partition(Part("/dev/sdb1", "/mnt/iso", "iso9660", "ro,relatime"))


def test_remount_ro_option_is_not_confused_with_ro():
    # "errors=remount-ro" contains the letters "ro" but the mount is rw
    assert _keep_partition(Part("/dev/sda2", "/", "ext4", "rw,errors=remount-ro"))


def test_loop_device_is_dropped_even_if_rw():
    assert not _keep_partition(Part("/dev/loop0", "/mnt/img", "ext4", "rw"))
