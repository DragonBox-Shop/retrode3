#!/usr/bin/env python3
"""Validate offline Debian 12 Apache/PHP wiring without executing MIPSEL httpd.

QEMU chroots without /proc and normal init are not reliable targets for an
Apache runtime configtest. This verifier is deliberately NOT a substitute
for the real-hardware Apache configuration and HTTP tests.
"""
from pathlib import Path
import re
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def mipsel_elf(path):
    require(path.is_file() and not path.is_symlink(),
            "missing or symlinked Apache binary: " + str(path))
    with path.open("rb") as stream:
        data = stream.read(20)
    require(len(data) == 20 and data[:6] == b"\x7fELF\x01\x01"
            and data[18:20] == b"\x08\x00",
            "Apache shared library is not ELF32 MIPSEL: " + str(path))


def verify(root):
    conf = root / "etc/apache2/apache2.conf"
    require(conf.is_file() and not conf.is_symlink(),
            "missing Apache configuration")
    config = conf.read_text(encoding="utf-8")
    require(re.search(r"(?m)^\s*IncludeOptional\s+mods-enabled/\*\.load\s*$", config),
            "Apache configuration does not include enabled LoadModule files")
    enabled = root / "etc/apache2/mods-enabled"
    require(enabled.is_dir() and not enabled.is_symlink(),
            "untrusted Apache enabled modules directory")
    for other in ("mpm_event.load", "mpm_worker.load"):
        entry = enabled / other
        require(not entry.exists() and not entry.is_symlink(),
                "conflicting Apache MPM: " + other)
    for name, module, target in (
        ("mpm_prefork.load", "mpm_prefork_module",
         "/usr/lib/apache2/modules/mod_mpm_prefork.so"),
        ("php8.2.load", "php_module",
         "/usr/lib/apache2/modules/libphp8.2.so"),
    ):
        entry = enabled / name
        require(entry.is_symlink() and entry.is_file(),
                "missing enabled Apache module: " + name)
        lines = [line.strip() for line in entry.read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
        require(lines == ["LoadModule " + module + " " + target],
                "wrong or inactive LoadModule directive in " + name)
        mipsel_elf(root / target.lstrip("/"))
    print("Verified offline Apache: prefork MIPSEL MPM and PHP 8.2 modules enabled")
    print("Apache runtime configtest deferred to Retrode3 hardware boot")


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("Usage: verify-apache-offline.py /rootfs")
        verify(Path(sys.argv[1]))
    except (OSError, UnicodeError, ValueError) as exc:
        print("Offline Apache verification failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
