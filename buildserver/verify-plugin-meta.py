#!/usr/bin/env python3
"""Validate the OS git meta recipe before building or publishing packages."""
import json
from pathlib import Path
import sys

EXPECTED = {
    "schema_version": 1,
    "name": "retrode3-cores",
    "source": "all-validated-oscr-core-pairs",
    "depends_on_runtime": True,
    "new_cores_enabled_on_install": False,
}

if __name__ == "__main__":
    try:
        source = Path(sys.argv[1])
        if source.is_symlink() or not source.is_file():
            raise ValueError("missing or unsafe plugin meta recipe")
        data = json.loads(source.read_text(encoding="utf-8"))
        if data != EXPECTED:
            raise ValueError("unsupported plugin meta-package recipe")
    except (IndexError, ValueError, OSError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        sys.exit(1)
