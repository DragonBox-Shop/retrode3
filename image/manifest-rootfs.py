#!/usr/bin/env python3
"""Inventory an unbootable rootfs stage for reproducible follow-up analysis."""
import importlib.util
import json
import sys
from pathlib import Path

path = Path(__file__).with_name("verify-rootfs.py")
spec = importlib.util.spec_from_file_location("retrode3_verify_rootfs", path)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
root = Path(sys.argv[1])
packages = verifier.verify(root)
manifest = {
    "schema": 1,
    "project": "retrode3",
    "stage": "debian-base-rootfs-only",
    "distribution": "Debian 12 Bookworm",
    "architecture": "mipsel",
    "init": "sysvinit-core",
    "bootable": False,
    "hardware_accepted": False,
    "customer_releasable": False,
    "contains_kernel": False,
    "contains_device_tree": False,
    "contains_bootloader": False,
    "contains_usb_gadget_integration": False,
    "contains_retrode_packages": False,
    "security_maintenance": "Debian 12 mipsel is outside official Debian LTS",
    "installed_packages": {
        name: item["Version"] for name, item in sorted(packages.items())
    },
}
print(json.dumps(manifest, indent=2, sort_keys=True))
