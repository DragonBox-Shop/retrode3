#!/usr/bin/env python3
"""Offline MIPSEL Lighttpd payload checks; runtime configtest remains mandatory."""
from pathlib import Path
import sys

def require(ok, msg):
    if not ok:
        raise ValueError(msg)

def verify(root):
    for name in ("usr/sbin/lighttpd", "usr/lib/lighttpd/mod_proxy.so"):
        path = root / name
        require(path.is_file() and not path.is_symlink(), "missing Lighttpd binary: " + name)
        with path.open("rb") as stream:
            data = stream.read(20)
        require(data[:6] == b"\x7fELF\x01\x01" and data[18:20] == b"\x08\x00",
                "not ELF32 MIPSEL: " + name)
    link = root / "etc/lighttpd/conf-enabled/99-retrode3-lighttpd.conf"
    require(link.is_symlink() and str(link.readlink()) == "../conf-available/99-retrode3-lighttpd.conf"
            and link.is_file(), "Lighttpd proxy configuration not enabled")
    config = link.read_text()
    for marker in ('server.document-root := "/var/www/retrode3-lighttpd"',
                   'server.modules += ( "mod_proxy" )', '127.0.0.1', '8765'):
        require(marker in config, "missing Lighttpd setting: " + marker)
    for name in ("var/www/retrode3-lighttpd/index.html",
                 "var/www/retrode3-lighttpd/assets/app.js",
                 "opt/retrode3-web-v2/backend/http_gateway.py"):
        require((root / name).is_file(), "missing Web payload: " + name)
    print("Verified offline Lighttpd MIPSEL payload; runtime configtest still required")

if __name__ == "__main__":
    verify(Path(sys.argv[1]))
