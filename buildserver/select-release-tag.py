#!/usr/bin/env python3
"""Select the newest release checkpoint tag reachable from a named branch.

Annotated tags use their tagger date; lightweight tags necessarily use the
target commit date. A tag must already belong to the selected branch's
history, and archive/upstream bookkeeping tags never qualify.
"""
import argparse
import re
import subprocess
import sys

SHA = re.compile(r"^[0-9a-f]{40}$")
EXCLUDED = ("archive/", "upstream/", "tracking/")


def git(repo, *args):
    return subprocess.check_output(
        ["git", "-C", repo, *args], text=True, stderr=subprocess.PIPE).strip()


def latest_tag(repo, branch):
    if branch not in ("develop", "master"):
        raise ValueError("invalid release branch")
    tip = git(repo, "rev-parse", "--verify", "refs/heads/" + branch + "^{commit}")
    if not SHA.fullmatch(tip):
        raise ValueError("invalid branch HEAD")
    rows = git(repo, "for-each-ref",
               "--format=%(refname:short)\t%(creatordate:unix)", "refs/tags")
    eligible = []
    for row in rows.splitlines():
        tag, separator, stamp = row.partition("\t")
        if (not separator or not stamp.isdecimal() or
                tag.startswith(EXCLUDED)):
            continue
        try:
            sha = git(repo, "rev-parse", "--verify",
                      "refs/tags/" + tag + "^{commit}")
        except subprocess.CalledProcessError:
            continue
        if not SHA.fullmatch(sha):
            continue
        if subprocess.call(
                ["git", "-C", repo, "merge-base", "--is-ancestor", sha, tip],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
            continue
        eligible.append((int(stamp), tag, sha))
    if not eligible:
        raise ValueError("no eligible release tag in " + branch +
                         " history; refusing untagged HEAD")
    _, tag, sha = max(eligible)
    return tag, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="local checkout or bare repository")
    parser.add_argument("branch", choices=("develop", "master"))
    args = parser.parse_args()
    try:
        tag, sha = latest_tag(args.repo, args.branch)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    print(tag + "\t" + sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
