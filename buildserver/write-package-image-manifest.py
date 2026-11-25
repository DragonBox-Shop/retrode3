#!/usr/bin/env python3
"""Record exact signed APT sources and boot candidate package versions."""
import hashlib
import json
from pathlib import Path
import sys

work = Path("/work")
kernel_release = sys.argv[1]
uboot_root = Path(sys.argv[2])
os_pkg = json.loads((work / "published-packages.json").read_text())
platform = json.loads((work / "published-platform.json").read_text())


def sha256(file):
    h = hashlib.sha256()
    with Path(file).open("rb") as stream:
        for b in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


files = ("retrode3-rootfs.tar.xz", "kernel-bundle.tar.gz",
         "retrode3-develop.img.xz")
manifest = {
    "schema": 2,
    "apt_suite": "testing",
    "branch": "develop",
    "os_tag": os_pkg["os_tag"],
    "os_commit": os_pkg["os_commit"],
    "oscr_tag": os_pkg["oscr_tag"],
    "oscr_commit": os_pkg["oscr_commit"],
    "kernel_commit": platform["sources"]["kernel"],
    "uboot_commit": platform["sources"]["uboot"],
    "platform_packages": {p["name"]: p["version"] for p in platform["packages"]},
    "kernel_release": kernel_release,
    "bootloader_source_built": True,
    "bootloader_combined_sha256": sha256(
        uboot_root / "u-boot-with-spl-mbr-gpt.bin"),
    "apt_public_fingerprint": (Path("/private/apt-fingerprint").read_text().strip()),
    "image_builder_commit": (work / "image-builder-commit").read_text().strip(),
    "kernel_and_uboot_compiled_during_image_build": False,
    "package_snapshot": os_pkg,
    "platform_package_snapshot": platform,
    "hardware_accepted": False,
    "customer_releasable": False,
    "files": {name: sha256(work / name) for name in files},
}
manifest_path = work / "full-image-manifest.json"
manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
checks = files + ("full-image-manifest.json",)
(work / "FULL-IMAGE-SHA256SUMS").write_text(
    "".join(sha256(work / name) + "  " + name + "\n" for name in checks))
print("Package-driven image manifest:", manifest_path)
