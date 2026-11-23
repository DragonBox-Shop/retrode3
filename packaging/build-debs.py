#!/usr/bin/env python3
"""Build offline, split Retrode3 Debian packages from a pinned MIPS stage.

This script NEVER installs packages, connects to a Retrode, enables a core,
or uploads anything to an APT repository. Requires host dpkg-deb and readelf.
The source stage is owned exclusively by retrode3-oscr.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
NATIVE = ("retrode3-core-runtime", "retrode3-core-snes",
          "retrode3-core-md", "retrode3-core-nes")
WEB = "retrode3-web-control"
MODES = {"usr/bin/retrode3-cli": 0o755,
         "usr/sbin/retrode3-corectl": 0o755}
for _core in ("snes", "md", "nes"):
    MODES["usr/lib/retrode3/cores-available/" + _core + ".so"] = 0o644
    MODES["usr/lib/retrode3/cores-available/" + _core + ".core"] = 0o644

WEB_FILES = (
    ("backend/service.py", "opt/retrode3-web-v2/backend/service.py", 0o644),
    ("web/index.php", "var/www/html/index.php", 0o644),
    ("web/api.php", "var/www/html/api.php", 0o644),
    ("web/auth.php", "var/www/html/auth.php", 0o644),
    ("web/assets/app.js", "var/www/html/assets/app.js", 0o644),
    ("web/assets/selection-ui.js", "var/www/html/assets/selection-ui.js", 0o644),
    ("web/assets/style.css", "var/www/html/assets/style.css", 0o644),
    ("web/locales/de.json", "var/www/html/locales/de.json", 0o644),
    ("web/locales/en.json", "var/www/html/locales/en.json", 0o644),
    ("service/retrode3-web-v2.init", "etc/init.d/retrode3-web-v2", 0o755),
    ("manage-auth-on-retrode.sh", "usr/sbin/retrode3-web-v2-auth", 0o755),
)
WEB_EXTRA = (
    ("packaging/assets/retrode3-web-v2.start",
     "opt/retrode3-web-v2/start.sh", 0o755),
    ("packaging/assets/retrode3-web-v2.default",
     "etc/default/retrode3-web-v2", 0o644),
    ("packaging/assets/retrode3-prefork.conf",
     "etc/apache2/conf-available/retrode3-prefork.conf", 0o644),
    ("packaging/assets/retrode3-corectl.sudoers",
     "etc/sudoers.d/retrode3-corectl", 0o440),
)
CONFFILES = {
    "retrode3-core-runtime": ("/etc/init.d/retrode3-core-runtime",),
    WEB: ("/etc/init.d/retrode3-web-v2", "/etc/default/retrode3-web-v2",
          "/etc/sudoers.d/retrode3-corectl",
          "/etc/apache2/conf-available/retrode3-prefork.conf")
}
DESCRIPTIONS = {
    "retrode3-core-runtime":
        "Shared Retrode3 cartridge CLI and SysV bus-lock preparation",
    "retrode3-core-snes": "Read-only SNES cartridge module for Retrode3",
    "retrode3-core-md": "Read-only Mega Drive cartridge module for Retrode3",
    "retrode3-core-nes": "NES NROM and MMC1 ROM reader module for Retrode3",
    WEB: "Retrode3 Web Control v2 with Python backend and SysV service"
}


def error(message):
    raise ValueError(message)

def auto_version_lock(lock, os_commit, epoch, oscr_commit=None, version_stamp=None):
    """Derive a unique Debian revision from the exact OS source commit.

    Retains the branch's pinned base versions, adding an ordered UTC commit
    timestamp and Git hash to the Debian *revision* (after the last hyphen).
    Never rewrites tracked source locks. The same commit yields the same
    versions on retry.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", os_commit):
        error("invalid OS source commit for automatic Debian version")
    stamp = datetime.datetime.fromtimestamp(
        int(epoch), datetime.timezone.utc
    ).strftime("%Y%m%d%H%M%S")
    if version_stamp is not None:
        if not re.fullmatch(r"[0-9]{14}", version_stamp):
            error("invalid UTC package build version stamp")
        stamp = version_stamp
    suffix = "+auto" + stamp + "." + os_commit[:12]
    if oscr_commit is not None:
        if not re.fullmatch(r"[0-9a-f]{40}", oscr_commit):
            error("invalid OSCR source revision")
        suffix += "." + oscr_commit[:12]
    effective = dict(lock)
    for field in ("native_version", "web_version"):
        version = lock[field]
        if "-" not in version:
            error("automatic Debian version requires an explicit -revision")
        effective[field] = version + suffix
    return effective


def validate_release_policy(lock):
    """Validate package versioning and channel without weakening the ABI gate."""
    channel = lock.get("release_channel")
    if channel not in ("testing", "stable"):
        error("unexpected release channel: " + str(channel))
    if lock.get("core_discovery_abi") != 1 or lock.get("core_operations_abi") != 1:
        error("unsupported core ABI; review before changing")
    for field in ("native_version", "web_version"):
        version = lock.get(field, "")
        if (not isinstance(version, str) or
                not re.fullmatch(r"[0-9][A-Za-z0-9.+:~_-]*", version)):
            error("invalid Debian package version: " + field)
        if channel == "stable" and "~dev" in version:
            error("stable may not use development package versions: " + field)
        if channel == "testing" and "~dev" not in version:
            error("testing requires a development package version: " + field)
    return channel




def cmd(argv, cwd=None):
    return subprocess.check_output(argv, cwd=str(cwd) if cwd else None,
                                   stderr=subprocess.STDOUT).decode("utf-8").strip()


def checked_file(source, expected_mode=None):
    if source.is_symlink() or not source.is_file():
        error("missing, nonregular or symlink source: " + str(source))
    if expected_mode is not None:
        mode = stat.S_IMODE(source.stat().st_mode)
        if mode != expected_mode:
            error("wrong file mode: {} expected {:o} got {:o}".format(
                  source, expected_mode, mode))
    if source.stat().st_size == 0:
        error("empty source: " + str(source))


def verify_oscr(oscr, lock):
    if not oscr.is_dir():
        error("OSCR checkout missing: " + str(oscr))
    expected = lock["oscr_commit"]
    actual = cmd(["git", "rev-parse", "HEAD"], cwd=oscr)
    if actual != expected:
        error("OSCR commit mismatch: expected {} got {}".format(expected, actual))
    gitlink = cmd(["git", "rev-parse", "HEAD:" + lock["sanni_submodule"]],
                  cwd=oscr)
    if gitlink != lock["sanni_commit"]:
        error("Sanni submodule gitlink mismatch: " + gitlink)
    subdir = oscr / lock["sanni_submodule"]
    if not subdir.is_dir():
        error("Sanni submodule not checked out")
    if cmd(["git", "rev-parse", "HEAD"], cwd=subdir) != lock["sanni_commit"]:
        error("Sanni checkout revision does not match pinned gitlink")
    if cmd(["git", "status", "--porcelain", "--untracked-files=no"], cwd=oscr):
        error("OSCR tracked files have modifications")
    return actual


def elf_mipsel(path):
    data = path.open("rb").read(20)
    if (len(data) < 20 or data[:4] != b"\x7fELF" or
            data[4] != 1 or data[5] != 1 or
            int.from_bytes(data[16:18], "little") not in (2, 3) or
            int.from_bytes(data[18:20], "little") != 8):
        error("not an ELF32 little-endian MIPS executable/library: " + str(path))


def verify_stage(stage, layout, check_symbols=True):
    if not stage.is_dir() or stage.is_symlink():
        error("stage is missing or a symlink")
    if layout["target_architecture"] != "mipsel":
        error("manifest architecture mismatch")
    if set(layout["release_packages"]) != set(NATIVE):
        error("unexpected native package layout")
    expected = set()
    for package in NATIVE:
        for rel in layout["release_packages"][package]:
            if rel in expected or rel not in MODES:
                error("duplicate/unapproved stage path: " + rel)
            expected.add(rel)
            src = stage / rel
            checked_file(src, MODES[rel])
            if rel.endswith((".so", "retrode3-cli", "retrode3-corectl")):
                elf_mipsel(src)
            if rel.endswith(".core"):
                core = src.stem
                values = {}
                for line in src.read_text(encoding="utf-8").splitlines():
                    if "=" in line:
                        key, value = line.split("=", 1)
                        values[key] = value
                if (values.get("id") != core or values.get("slot") != core or
                        not values.get("version") or not values.get("name")):
                    error("core metadata mismatch: " + rel)
            if check_symbols and rel.endswith(".so"):
                symbols = cmd(["readelf", "--wide", "--dyn-syms", str(src)])
                if ("retrode3_core_describe_v1" not in symbols or
                        "retrode3_core_get_operations_v1" not in symbols):
                    error("core is missing v1 discovery/operations ABI: " + rel)
    if expected != set(MODES):
        error("source layout omits expected native file(s)")
    found = set()
    for parent, dirs, names in os.walk(str(stage), followlinks=False):
        for item in dirs + names:
            p = Path(parent) / item
            if p.is_symlink():
                error("staging symlink: " + str(p))
        for item in names:
            p = Path(parent) / item
            found.add(p.relative_to(stage).as_posix())
    if found != expected:
        error("unexpected/missing stage files: " + str(sorted(found ^ expected)))


def put(root, source, target, mode):
    checked_file(source)
    out = root / target
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(source), str(out))
    os.chmod(str(out), mode)


def put_text(root, target, content, mode=0o644):
    out = root / target
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    os.chmod(str(out), mode)


def maintainer_scripts(root, package):
    scripts = {"preinst": "common.preinst"}
    if package == "retrode3-core-runtime":
        scripts.update({"postinst": "runtime.postinst",
                        "postrm": "runtime.postrm"})
    elif package == WEB:
        scripts.update({"preinst": "web.preinst",
                        "prerm": "web.prerm",
                        "postinst": "web.postinst",
                        "postrm": "web.postrm"})
    for target, name in scripts.items():
        put(root, HERE / "maintainer" / name, "DEBIAN/" + target, 0o755)


def control_text(package, lock):
    native_version = lock["native_version"]
    version = lock["web_version"] if package == WEB else native_version
    arch = "all" if package == WEB else "mipsel"
    if package == "retrode3-core-runtime":
        deps = "libc6, libstdc++6, passwd, adduser, init-system-helpers"
    elif package == WEB:
        deps = ("retrode3-core-runtime (>= " + native_version + "), "
                "retrode3-tools, retrode3-udev-rules, python3 (>= 3.4), "
                "php5-cli | php-cli, php5 | php, letux-httpd, "
                "sudo, passwd, adduser, init-system-helpers")
    else:
        deps = ("retrode3-core-runtime (>= " + native_version +
                "), retrode3-core-abi-1, libc6, libstdc++6")
    lines = [
        "Package: " + package, "Version: " + version,
        "Section: utils", "Priority: optional", "Architecture: " + arch,
        "Maintainer: OpenPandora GmbH <info@openpandora.org>",
        "Depends: " + deps,
        "X-Retrode3-OSCR-Commit: " + lock["oscr_commit"],
        "X-Retrode3-Sanni-Commit: " + lock["sanni_commit"],
        "X-Retrode3-Core-Discovery-ABI: " + str(lock["core_discovery_abi"]),
        "X-Retrode3-Core-Operations-ABI: " + str(lock["core_operations_abi"]),
        "Description: " + DESCRIPTIONS[package],
        (" Built from pinned source for the Retrode3 " +
         lock["release_channel"] + " package channel.")
    ]
    if package == "retrode3-core-runtime":
        lines.insert(6, "Provides: retrode3-core-abi-1")
    return "\n".join(lines) + "\n"


def build_one(work, package, layout, lock, stage, epoch):
    root = work / package
    (root / "DEBIAN").mkdir(parents=True)
    if package in NATIVE:
        for rel in layout["release_packages"][package]:
            put(root, stage / rel, rel, MODES[rel])
        if package == "retrode3-core-runtime":
            put(root, REPO / "retrode3-core-runtime/etc/init.d/retrode3-core-runtime",
                "etc/init.d/retrode3-core-runtime", 0o755)
    else:
        source = REPO / "retrode3-web-control/v2"
        for rel, target, mode in WEB_FILES:
            put(root, source / rel, target, mode)
        for rel, target, mode in WEB_EXTRA:
            put(root, REPO / rel, target, mode)
        put_text(root, "var/www/html/index.html",
                 '<!doctype html><html><meta charset="utf-8">'
                 '<meta http-equiv="refresh" content="0;url=index.php">'
                 '<a href="index.php">Retrode3</a></html>\n')
    put_text(root, "DEBIAN/control", control_text(package, lock))
    if package in CONFFILES:
        put_text(root, "DEBIAN/conffiles", "\n".join(CONFFILES[package]) + "\n")
    maintainer_scripts(root, package)
    for parent, dirs, files in os.walk(str(root)):
        for name in dirs + files:
            p = os.path.join(parent, name)
            os.utime(p, (epoch, epoch), follow_symlinks=False)
    os.utime(str(root), (epoch, epoch))
    version = lock["web_version"] if package == WEB else lock["native_version"]
    filename = "{}_{}_{}.deb".format(package, version, "all" if package == WEB else "mipsel")
    destination = work / filename
    environment = os.environ.copy()
    environment["SOURCE_DATE_EPOCH"] = str(epoch)
    subprocess.check_call(["dpkg-deb", "--root-owner-group", "-Zxz",
                           "--build", str(root), str(destination)], env=environment)
    info = cmd(["dpkg-deb", "--field", str(destination), "Package", "Architecture"])
    if package not in info:
        error("dpkg-deb metadata validation failed: " + filename)
    names = cmd(["dpkg-deb", "--contents", str(destination)])
    for required in (layout["release_packages"][package] if package in NATIVE
                     else ["opt/retrode3-web-v2/backend/service.py",
                           "var/www/html/index.php", "etc/init.d/retrode3-web-v2"]):
        if "./" + required not in names:
            error("missing installed payload from deb: " + required)
    return filename, destination


def symbol_version_report(stage):
    """Record linked ABI versions, without asserting target libc compatibility."""
    report = {}
    for rel in MODES:
        if not (rel.endswith(".so") or rel.endswith("retrode3-cli") or
                rel.endswith("retrode3-corectl")):
            continue
        output = cmd(["readelf", "-W", "--version-info", str(stage / rel)])
        report[rel] = sorted(set(re.findall(
            r"(?:GLIBC|GLIBCXX|CXXABI)_[0-9]+(?:\.[0-9]+)*", output)))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-lock", default=str(HERE / "native-source-lock.json"),
                        help="JSON lock resolved for this build; defaults to static source lock")
    parser.add_argument("--oscr-source", required=True,
                        help="retrode3-oscr checkout at the exact pinned commit")
    parser.add_argument("--stage", required=True,
                        help="OSCR build/migration/stage with MIPS little-endian binaries")
    parser.add_argument("--output", required=True,
                        help="offline output directory, never installed automatically")
    args = parser.parse_args()
    lock = json.loads(Path(args.source_lock).read_text(encoding="utf-8"))
    layout = json.loads((HERE / "retrode3-core-layout.json").read_text(encoding="utf-8"))
    auto_version = os.environ.get("RETRODE3_AUTO_VERSION", "0") == "1"
    if auto_version:
        os_commit = cmd(["git", "-c", "safe.directory=" + str(REPO),
                         "rev-parse", "HEAD"], cwd=REPO)
        epoch_git = int(cmd(["git", "-c", "safe.directory=" + str(REPO),
                             "show", "-s", "--format=%ct", "HEAD"], cwd=REPO))
        follow_oscr = os.environ.get("RETRODE3_FOLLOW_OSCR_BRANCH", "0") == "1"
        stamp = os.environ.get("RETRODE3_VERSION_STAMP") or None
        lock = auto_version_lock(
            lock, os_commit, epoch_git,
            oscr_commit=lock["oscr_commit"] if follow_oscr else None,
            version_stamp=stamp)
    release_channel = validate_release_policy(lock)
    oscr = Path(args.oscr_source).resolve()
    stage = Path(args.stage).resolve()
    verify_oscr(oscr, lock)
    verify_stage(stage, layout)
    out = Path(args.output).resolve()
    if out == stage or out == oscr or out == REPO:
        error("output would overwrite a source or staging tree")
    out.mkdir(parents=True, exist_ok=True)
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "1795132800"))
    if epoch < 0:
        error("invalid SOURCE_DATE_EPOCH")
    with tempfile.TemporaryDirectory(prefix=".retrode3-debs-", dir=str(out)) as temp:
        work = Path(temp)
        records = []
        for package in NATIVE + (WEB,):
            filename, archive = build_one(work, package, layout, lock, stage, epoch)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            records.append({"filename": filename, "sha256": digest,
                            "package": package})
        for record in records:
            os.replace(str(work / record["filename"]), str(out / record["filename"]))
        manifest = {"release_channel": release_channel,
                    "auto_versioned": auto_version,
                    "oscr_branch": (os.environ.get("RETRODE3_OSCR_BRANCH")
                                    if os.environ.get("RETRODE3_FOLLOW_OSCR_BRANCH") == "1"
                                    else None),
                    "version_stamp": (os.environ.get("RETRODE3_VERSION_STAMP")
                                      if auto_version else None),
                    "os_repository": "DragonBox-Shop/retrode3",
                    "os_commit": cmd(["git", "-c", "safe.directory=" + str(REPO),
                                      "rev-parse", "HEAD"], cwd=REPO),
                    "oscr_commit": lock["oscr_commit"],
                    "sanni_commit": lock["sanni_commit"],
                    "native_version": lock["native_version"],
                    "web_version": lock["web_version"],
                    "source_date_epoch": epoch, "packages": records,
                    "hardware_accepted": False, "apt_published": False,
                    "target_sysroot_verified": False,
                    "required_symbol_versions": symbol_version_report(stage)}
        (out / "build-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
    for record in records:
        print(record["sha256"] + "  " + record["filename"])
    print("OFFLINE packages only; no install, publication or image build.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        sys.stderr.write("ERROR: {}\n".format(exc))
        sys.exit(1)
