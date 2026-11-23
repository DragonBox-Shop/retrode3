#!/usr/bin/env python3
"""Conservative classifier for package-affecting Git changes.

Only explicitly non-shipping files may be ignored. All unknown paths,
including newly introduced build inputs, force a package rebuild.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

NON_PACKAGE_FILES = frozenset({
    "AGENTS.md",
    "tools/preflight-ci.sh",
    "buildserver/auto-package.sh",
    "buildserver/publish-debs.sh",
    "buildserver/install-launchers.sh",
    "buildserver/release-changes.py",
})
NON_PACKAGE_PREFIXES = (
    ".github/",
    "docs/",
    "packaging/tests/",
    "buildserver/tests/",
    "retrode3-web-control/v2/docs/",
    "retrode3-web-control/v2/tests/",
)


def affects_packages(path):
    """Return True unless the file is known not to affect built .debs."""
    if path in NON_PACKAGE_FILES:
        return False
    if path.startswith(NON_PACKAGE_PREFIXES):
        return False
    if path.endswith(".md"):
        return False
    return True


def affects_oscr_packages(path):
    """Only documentation, CI and mock tests never enter OSCR runtime stage."""
    if path in ("AGENTS.md", "tools/preflight-ci.sh"):
        return False
    if path.startswith((".github/", "docs/", "tests/")):
        return False
    if path.endswith(".md"):
        return False
    # Especially do NOT ignore submodule gitlinks, Makefile, code generators,
    # databases, core metadata, HAL or executable sources.
    return True


def changed_paths(repo, old_commit, new_commit):
    """List changed paths without rename detection; verify ancestral history."""
    for sha in (old_commit, new_commit):
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("invalid Git commit SHA")
    cmd = ["git", "-C", str(Path(repo).resolve())]
    subprocess.run(cmd + ["merge-base", "--is-ancestor", old_commit, new_commit],
                   check=True, stdout=subprocess.DEVNULL)
    data = subprocess.check_output(cmd + ["diff", "--no-ext-diff", "--no-renames",
                                           "--name-only", "-z", old_commit, new_commit, "--"])
    return tuple(os.fsdecode(path) for path in data.split(b"\0") if path)


def only_nonpackage_changes(repo, old_commit, new_commit, scope="os"):
    classifier = affects_oscr_packages if scope == "oscr" else affects_packages
    return all(not classifier(path)
               for path in changed_paths(repo, old_commit, new_commit))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--scope", choices=("os", "oscr"), default="os")
    args = parser.parse_args()
    try:
        changed = changed_paths(args.repo, args.base, args.head)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print("ERROR: cannot verify Git history: {}".format(exc), file=sys.stderr)
        return 2
    classifier = affects_oscr_packages if args.scope == "oscr" else affects_packages
    relevant = [path for path in changed if classifier(path)]
    if relevant:
        print("Package-affecting changes: " + ", ".join(relevant))
        return 1
    print("No package-affecting changes ({} non-package paths).".format(len(changed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
