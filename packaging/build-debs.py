#!/usr/bin/env python3
"""Build offline, split Retrode3 Debian packages from a pinned MIPS stage.

This script NEVER installs packages, connects to a Retrode, enables a core,
or uploads anything to an APT repository. Requires host dpkg-deb and readelf.
The source stage is owned exclusively by retrode3-oscr.
"""
import argparse
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
RUNTIME = "retrode3-core-runtime"
CORE_DIRECTORY = "usr/lib/retrode3/cores-available"
CORE_PREFIX = "retrode3-core-"
CORE_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
WEB = "retrode3-web-control"
# Fixed executable modes; every complete staged core pair is discovered at build time.
MODES = {"usr/bin/retrode3-cli": 0o755,
         "usr/sbin/retrode3-corectl": 0o755}

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
    with path.open("rb") as elf:
        data = elf.read(20)
    if (len(data) < 20 or data[:4] != b"\x7fELF" or
            data[4] != 1 or data[5] != 1 or
            int.from_bytes(data[16:18], "little") not in (2, 3) or
            int.from_bytes(data[18:20], "little") != 8):
        error("not an ELF32 little-endian MIPS executable/library: " + str(path))


def core_metadata(source, core):
    values = {}
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            error("invalid core metadata line: " + str(source))
        key, value = line.split("=", 1)
        if key in values:
            error("duplicate core metadata key: " + key)
        values[key] = value
    if (values.get("id") != core or
            not CORE_ID.fullmatch(values.get("slot", "")) or
            not values.get("version") or not values.get("name") or
            len(values["name"]) > 160 or
            any(ord(c) < 32 or ord(c) == 127 for c in values["name"])):
        error("core metadata mismatch: " + str(source))
    return values


def discover_native_packages(stage, layout):
    """Split complete *.so/*.core pairs staged by pinned retrode3-oscr."""
    contract = {"staged_directory": CORE_DIRECTORY,
                "package_prefix": CORE_PREFIX,
                "pair_extensions": [".so", ".core"]}
    if (layout.get("schema_version") != 2 or
            layout.get("discovered_core_packages") != contract or
            set(layout.get("release_packages", {})) != {RUNTIME} or
            layout["release_packages"][RUNTIME] != list(MODES)):
        error("unexpected native package layout")
    directory = stage / CORE_DIRECTORY
    if directory.is_symlink() or not directory.is_dir():
        error("core staging directory missing or is a symlink")
    entries = list(directory.iterdir())
    if not entries:
        error("no cartridge cores staged")
    core_ids = set()
    for entry in entries:
        if (entry.is_symlink() or not entry.is_file() or
                entry.suffix not in (".so", ".core")):
            error("unapproved staged core file: " + str(entry))
        core = entry.stem
        if len(core) > 48 or not CORE_ID.fullmatch(core):
            error("invalid staged core ID: " + core)
        core_ids.add(core)
    native = {RUNTIME: tuple(layout["release_packages"][RUNTIME])}
    for core in sorted(core_ids):
        paths = tuple(CORE_DIRECTORY + "/" + core + ext
                      for ext in (".so", ".core"))
        if not all((stage / rel).is_file() for rel in paths):
            error("incomplete .so/.core pair: " + core)
        native[CORE_PREFIX + core] = paths
    return native


def verify_stage(stage, layout, check_symbols=True):
    if not stage.is_dir() or stage.is_symlink():
        error("stage is missing or a symlink")
    if layout["target_architecture"] != "mipsel":
        error("manifest architecture mismatch")
    native = discover_native_packages(stage, layout)
    expected = set()
    for package, paths in native.items():
        for rel in paths:
            if rel in expected:
                error("duplicate stage file: " + rel)
            expected.add(rel)
            src = stage / rel
            checked_file(src, MODES.get(rel, 0o644))
            if rel.endswith((".so", "retrode3-cli", "retrode3-corectl")):
                elf_mipsel(src)
            if rel.endswith(".core"):
                core_metadata(src, src.stem)
            if check_symbols and rel.endswith(".so"):
                symbols = cmd(["readelf", "--wide", "--dyn-syms", str(src)])
                if ("retrode3_core_describe_v1" not in symbols or
                        "retrode3_core_get_operations_v1" not in symbols):
                    error("core is missing v1 discovery/operations ABI: " + rel)
    if not set(MODES).issubset(expected):
        error("stage omits the shared runtime")
    found = set()
    for parent, dirs, names in os.walk(str(stage), followlinks=False):
        for item in dirs + names:
            candidate = Path(parent) / item
            if candidate.is_symlink():
                error("staging symlink: " + str(candidate))
        for item in names:
            candidate = Path(parent) / item
            found.add(candidate.relative_to(stage).as_posix())
    if found != expected:
        error("unexpected/missing stage files: " + str(sorted(found ^ expected)))
    return native


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
        "Description: " + DESCRIPTIONS.get(
            package, "Retrode3 cartridge core " + package[len(CORE_PREFIX):]),
        " Built from pinned source for offline development-device acceptance."
    ]
    if package == "retrode3-core-runtime":
        lines.insert(6, "Provides: retrode3-core-abi-1")
    return "\n".join(lines) + "\n"


def build_one(work, package, layout, lock, stage, epoch, native=None):
    if native is None:
        native = discover_native_packages(stage, layout)
    if package not in native and package != WEB:
        error("unapproved package: " + package)
    root = work / package
    (root / "DEBIAN").mkdir(parents=True)
    if package in native:
        for rel in native[package]:
            put(root, stage / rel, rel, MODES.get(rel, 0o644))
        if package == RUNTIME:
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
    for required in (native[package] if package in native
                     else ["opt/retrode3-web-v2/backend/service.py",
                           "var/www/html/index.php", "etc/init.d/retrode3-web-v2"]):
        if "./" + required not in names:
            error("missing installed payload from deb: " + required)
    return filename, destination


def symbol_version_report(stage, native):
    """Record linked ABI requirements, without claiming device compatibility."""
    report = {}
    for paths in native.values():
        for rel in paths:
            if rel.endswith(".core"):
                continue
            output = cmd(["readelf", "-W", "--version-info", str(stage / rel)])
            report[rel] = sorted(set(re.findall(
                r"(?:GLIBC|GLIBCXX|CXXABI)_[0-9]+(?:\.[0-9]+)*", output)))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oscr-source", required=True,
                        help="retrode3-oscr checkout at the exact pinned commit")
    parser.add_argument("--stage", required=True,
                        help="OSCR build/migration/stage with MIPS little-endian binaries")
    parser.add_argument("--output", required=True,
                        help="offline output directory, never installed automatically")
    args = parser.parse_args()
    lock = json.loads((HERE / "native-source-lock.json").read_text(encoding="utf-8"))
    layout = json.loads((HERE / "retrode3-core-layout.json").read_text(encoding="utf-8"))
    if (lock["release_channel"] != "develop-test-only" or
            lock["core_discovery_abi"] != 1 or lock["core_operations_abi"] != 1):
        error("unexpected release policy or core ABI; review before changing")
    oscr = Path(args.oscr_source).resolve()
    stage = Path(args.stage).resolve()
    verify_oscr(oscr, lock)
    native = verify_stage(stage, layout)
    # Metadata for every package must match this exact pinned source checkout.
    for package in native:
        if package == RUNTIME:
            continue
        core = package[len(CORE_PREFIX):]
        source_metadata = oscr / "packaging/cores" / (core + ".core")
        checked_file(source_metadata)
        if (source_metadata.read_bytes() !=
                (stage / CORE_DIRECTORY / (core + ".core")).read_bytes()):
            error("staged core metadata differs from pinned source: " + core)
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
        for package in tuple(native) + (WEB,):
            filename, archive = build_one(work, package, layout, lock,
                                          stage, epoch, native)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            records.append({"filename": filename, "sha256": digest,
                            "package": package})
        for record in records:
            os.replace(str(work / record["filename"]), str(out / record["filename"]))
        manifest = {"release_channel": lock["release_channel"],
                    "oscr_commit": lock["oscr_commit"],
                    "sanni_commit": lock["sanni_commit"],
                    "native_version": lock["native_version"],
                    "web_version": lock["web_version"],
                    "source_date_epoch": epoch, "packages": records,
                    "core_ids": [name[len(CORE_PREFIX):] for name in native
                                 if name != RUNTIME],
                    "hardware_accepted": False, "apt_published": False,
                    "target_sysroot_verified": False,
                    "required_symbol_versions": symbol_version_report(stage, native)}
        (out / "build-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
    for record in records:
        print(record["sha256"] + "  " + record["filename"])
    print("OFFLINE test candidates only; no install, publication or image build.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        sys.stderr.write("ERROR: {}\n".format(exc))
        sys.exit(1)
