#!/usr/bin/env python3
"""Keep only the previously verified Retrode3 APT source in the final image."""
from pathlib import Path
import sys

def finalize(root):
    apt = root / "etc/apt"
    parts = apt / "sources.list.d"
    keep = parts / "retrode3.list"
    key = root / "usr/share/keyrings/retrode3-archive-keyring.gpg"
    expected = ("deb [arch=mipsel signed-by=/usr/share/keyrings/retrode3-archive-keyring.gpg] "
                "https://packages.retrode.com testing main")
    if (not keep.is_file() or keep.is_symlink() or
            keep.read_text(encoding="ascii").strip() != expected or
            not key.is_file() or key.is_symlink() or not key.stat().st_size):
        raise ValueError("missing verified Retrode3 testing source or key")
    candidates = [apt / "sources.list"] + sorted(parts.glob("*.list")) + sorted(parts.glob("*.sources"))
    for path in candidates:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("unsafe APT source: " + str(path))
    for path in candidates:
        if path != keep and path.exists():
            path.unlink()

if __name__ == "__main__":
    finalize(Path(sys.argv[1]))
