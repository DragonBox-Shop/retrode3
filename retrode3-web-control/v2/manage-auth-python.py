#!/usr/bin/env python3
"""Optional web-password management, using Debian 12's libcrypt bcrypt."""
import argparse
import crypt
import getpass
import grp
import os
from pathlib import Path
import sys
import tempfile

AUTH = Path("/etc/retrode3-web-control.auth")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("status", "enable", "disable"), nargs="?", default="status")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run as root")
    if args.action == "status":
        print("Password protection is enabled (username: admin)." if os.path.lexists(AUTH)
              else "Password protection is disabled (default).")
        return
    if args.action == "disable":
        AUTH.unlink(missing_ok=True)
        print("Password protection disabled.")
        return
    if not sys.stdin.isatty():
        parser.error("An interactive terminal is required")
    password = getpass.getpass("New optional web password: ")
    if not password or "\0" in password or len(password.encode("utf-8")) > 72:
        parser.error("Password must contain 1-72 UTF-8 bytes and no NUL")
    if password != getpass.getpass("Repeat password: "):
        parser.error("Passwords do not match")
    # Keep the bcrypt format readable by the old PHP gateway for rollback.
    stored = crypt.crypt(password, crypt.mksalt(crypt.METHOD_BLOWFISH, rounds=1024))
    if not stored or not stored.startswith(("$2b$", "$2y$")) or len(stored) != 60:
        parser.error("bcrypt unavailable")
    fd, temp = tempfile.mkstemp(prefix=AUTH.name + ".", dir=str(AUTH.parent))
    try:
        with os.fdopen(fd, "w", encoding="ascii") as out:
            os.fchown(out.fileno(), 0, grp.getgrnam("www-data").gr_gid)
            os.fchmod(out.fileno(), 0o640)
            out.write(stored + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, AUTH)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    print("Password protection enabled (username: admin).")


if __name__ == "__main__":
    main()
