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
RUNTIME = "retrode3-core-runtime"
CORE_DIRECTORY = "usr/lib/retrode3/cores-available"
CORE_PREFIX = "retrode3-core-"
CORE_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
WEB = "retrode3-web-control"
TOOLS = "retrode3-tools"
UDEV = "retrode3-udev-rules"
META = "retrode3-cores"
BOOKWORM_ALL = (WEB, TOOLS, UDEV)
# Fixed executable modes; every complete staged core pair is discovered at build time.
MODES = {"usr/bin/retrode3-cli": 0o755,
         "usr/sbin/retrode3-corectl": 0o755}

WEB_FILES = (
    ("backend/service.py", "opt/retrode3-web-v2/backend/service.py", 0o644),
    ("backend/http_gateway.py", "opt/retrode3-web-v2/backend/http_gateway.py", 0o644),
    ("web/index.html", "var/www/retrode3-lighttpd/index.html", 0o644),
    ("web/assets/app.js", "var/www/retrode3-lighttpd/assets/app.js", 0o644),
    ("web/assets/selection-ui.js", "var/www/retrode3-lighttpd/assets/selection-ui.js", 0o644),
    ("web/assets/style.css", "var/www/retrode3-lighttpd/assets/style.css", 0o644),
    ("web/locales/de.json", "var/www/retrode3-lighttpd/locales/de.json", 0o644),
    ("web/locales/en.json", "var/www/retrode3-lighttpd/locales/en.json", 0o644),
    ("service/retrode3-web-v2.init", "etc/init.d/retrode3-web-v2", 0o755),
    ("manage-auth-python.py", "usr/sbin/retrode3-web-v2-auth", 0o755),
)
TOOL_FILES = (
    ("retrode3-tools/usr/local/bin/retrode3-admin",
     "usr/local/bin/retrode3-admin", 0o755),
    ("retrode3-tools/usr/local/bin/retrode3-wlan",
     "usr/local/bin/retrode3-wlan", 0o755),
    ("packaging/assets/retrode3-tools.sudoers",
     "etc/sudoers.d/retrode3", 0o440),
)
UDEV_FILES = (
    ("packaging/assets/70-retrode3-cartridge.rules",
     "etc/udev/rules.d/70-retrode3-cartridge.rules", 0o644),
)

WEB_EXTRA = (
    ("packaging/assets/retrode3-web-v2.start",
     "opt/retrode3-web-v2/start.sh", 0o755),
    ("packaging/assets/retrode3-web-v2.default",
     "etc/default/retrode3-web-v2", 0o644),
    ("packaging/assets/99-retrode3-lighttpd.conf",
     "etc/lighttpd/conf-available/99-retrode3-lighttpd.conf", 0o644),
    ("packaging/assets/retrode3-corectl.sudoers",
     "etc/sudoers.d/retrode3-corectl", 0o440),
    ("packaging/assets/retrode3-ssh-control", "usr/sbin/retrode3-ssh-control", 0o755),
    ("packaging/assets/retrode3-ssh.init", "etc/init.d/retrode3-ssh", 0o755),
    ("packaging/assets/retrode3-ssh.sudoers", "etc/sudoers.d/retrode3-ssh", 0o440),
)
CONFFILES = {
    "retrode3-core-runtime": ("/etc/init.d/retrode3-core-runtime",),
    WEB: ("/etc/init.d/retrode3-web-v2", "/etc/default/retrode3-web-v2",
          "/etc/sudoers.d/retrode3-corectl", "/etc/sudoers.d/retrode3-ssh",
          "/etc/init.d/retrode3-ssh",
          "/etc/lighttpd/conf-available/99-retrode3-lighttpd.conf"),
    TOOLS: ("/etc/sudoers.d/retrode3",),
    UDEV: ("/etc/udev/rules.d/70-retrode3-cartridge.rules",)
}
DESCRIPTIONS = {
    "retrode3-core-runtime":
        "Shared Retrode3 cartridge CLI and SysV bus-lock preparation",
    "retrode3-core-snes": "Read-only SNES cartridge module for Retrode3",
    "retrode3-core-md": "Read-only Mega Drive cartridge module for Retrode3",
    "retrode3-core-nes": "NES NROM and MMC1 ROM reader module for Retrode3",
    WEB: "Retrode3 Web Control v2 with Python backend and SysV service",
    TOOLS: "Retrode3 legacy administrative and WLAN helper scripts",
    UDEV: "Retrode3 cartridge node permissions for udev and SysV init",
    META: "Meta-package for all released Retrode3 cartridge cores"
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
        if not re.fullmatch(r"(?:[0-9]{14}|[0-9]{23})", version_stamp):
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
        if core == "runtime" or len(core) > 48 or not CORE_ID.fullmatch(core):
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


def package_version(package, lock):
    return lock["web_version"] if package in BOOKWORM_ALL else lock["native_version"]


def package_arch(package):
    return "all" if package in BOOKWORM_ALL else "mipsel"


def validate_meta_recipe():
    recipe = HERE / "core-meta.json"
    if not recipe.is_file() or recipe.is_symlink():
        error("missing or unsafe core meta recipe")
    if json.loads(recipe.read_text(encoding="utf-8")) != {
            "schema_version": 1, "name": META,
            "source": "all-validated-oscr-core-pairs",
            "depends_on_runtime": True, "new_cores_enabled_on_install": False}:
        error("unsupported plugin meta-package recipe")


def meta_dependencies(native, lock):
    cores = sorted(name for name in native
                   if name != RUNTIME and name.startswith(CORE_PREFIX))
    if RUNTIME not in native or not cores:
        error("meta-package requires runtime and a nonempty core set")
    return ", ".join("{} (= {})".format(name, lock["native_version"])
                     for name in [RUNTIME] + cores)


def validate_meta_manifest(manifest, lock):
    """Require the exact candidate package set before APT publication."""
    ids = manifest.get("core_ids")
    if (not isinstance(ids, list) or not ids or
            any(not isinstance(core, str) or core == "runtime" or
                len(core) > 48 or not CORE_ID.fullmatch(core) for core in ids) or
            len(ids) != len(set(ids))):
        error("invalid or duplicate core IDs in meta-package manifest")
    native = [RUNTIME] + [CORE_PREFIX + core for core in ids]
    names = [record.get("package") for record in manifest.get("packages", [])]
    expected = set(native) | set(BOOKWORM_ALL) | {META}
    if len(names) != len(expected) or set(names) != expected:
        error("meta-package manifest does not contain the exact released core set")
    return meta_dependencies(native, lock)


def control_text(package, lock, native=None):
    native_version = lock["native_version"]
    web_version = lock["web_version"]
    version = package_version(package, lock)
    arch = package_arch(package)
    if package == META:
        deps = meta_dependencies(native or {}, lock)
    elif package == "retrode3-core-runtime":
        deps = "libc6, libstdc++6, passwd, adduser, init-system-helpers"
    elif package == WEB:
        deps = ("retrode3-core-runtime (>= " + native_version + "), "
                "retrode3-tools (>= " + web_version + "), "
                "retrode3-udev-rules (>= " + web_version + "), "
                "python3, lighttpd, "
                "sudo, passwd, adduser, init-system-helpers")
    elif package == TOOLS:
        deps = ("bash, sudo, iw, wireless-tools, net-tools, "
                "wget, unzip")
    elif package == UDEV:
        deps = ("udev, retrode3-core-runtime (>= " + native_version + ")")
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
        (" Built from pinned source for the Retrode3 " +
         lock["release_channel"] + " package channel.")
    ]
    if package == "retrode3-core-runtime":
        lines.insert(6, "Provides: retrode3-core-abi-1")
    if package == WEB:
        lines.insert(6, "Conflicts: apache2")
    return "\n".join(lines) + "\n"


def build_one(work, package, layout, lock, stage, epoch, native=None):
    if native is None:
        native = discover_native_packages(stage, layout)
    if package not in native and package not in BOOKWORM_ALL + (META,):
        error("unapproved package: " + package)
    root = work / package
    (root / "DEBIAN").mkdir(parents=True)
    if package in native:
        for rel in native[package]:
            put(root, stage / rel, rel, MODES.get(rel, 0o644))
        if package == RUNTIME:
            put(root, REPO / "retrode3-core-runtime/etc/init.d/retrode3-core-runtime",
                "etc/init.d/retrode3-core-runtime", 0o755)
    elif package == WEB:
        source = REPO / "retrode3-web-control/v2"
        for rel, target, mode in WEB_FILES:
            put(root, source / rel, target, mode)
        for rel, target, mode in WEB_EXTRA:
            put(root, REPO / rel, target, mode)
    elif package == TOOLS:
        for rel, target, mode in TOOL_FILES:
            put(root, REPO / rel, target, mode)
    elif package == UDEV:
        for rel, target, mode in UDEV_FILES:
            put(root, REPO / rel, target, mode)
    elif package == META:
        put_text(root, "usr/share/doc/retrode3-cores/README",
                 "Install every released Retrode3 cartridge core.\n"
                 "Core enablement is an independent administrator decision.\n")
    put_text(root, "DEBIAN/control", control_text(package, lock, native))
    if package in CONFFILES:
        put_text(root, "DEBIAN/conffiles", "\n".join(CONFFILES[package]) + "\n")
    maintainer_scripts(root, package)
    for parent, dirs, files in os.walk(str(root)):
        for name in dirs + files:
            p = os.path.join(parent, name)
            os.utime(p, (epoch, epoch), follow_symlinks=False)
    os.utime(str(root), (epoch, epoch))
    version = package_version(package, lock)
    filename = "{}_{}_{}.deb".format(package, version, package_arch(package))
    destination = work / filename
    environment = os.environ.copy()
    environment["SOURCE_DATE_EPOCH"] = str(epoch)
    subprocess.check_call(["dpkg-deb", "--root-owner-group", "-Zxz",
                           "--build", str(root), str(destination)], env=environment)
    info = cmd(["dpkg-deb", "--field", str(destination), "Package", "Architecture"])
    if package not in info:
        error("dpkg-deb metadata validation failed: " + filename)
    names = cmd(["dpkg-deb", "--contents", str(destination)])
    required_files = {
        WEB: ("opt/retrode3-web-v2/backend/service.py",
              "opt/retrode3-web-v2/backend/http_gateway.py",
              "var/www/retrode3-lighttpd/index.html",
              "etc/lighttpd/conf-available/99-retrode3-lighttpd.conf",
              "etc/init.d/retrode3-web-v2"),
        TOOLS: ("usr/local/bin/retrode3-admin", "usr/local/bin/retrode3-wlan"),
        UDEV: ("etc/udev/rules.d/70-retrode3-cartridge.rules",),
        META: ("usr/share/doc/retrode3-cores/README",),
    }
    for required in native[package] if package in native else required_files[package]:
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
    native = verify_stage(stage, layout)
    validate_meta_recipe()
    recipes = oscr / "packaging/cores"
    if not recipes.is_dir() or recipes.is_symlink():
        error("missing or unsafe OSCR core recipes")
    recipe_ids = {entry.stem for entry in recipes.glob("*.core")}
    staged_ids = {name[len(CORE_PREFIX):] for name in native if name != RUNTIME}
    if recipe_ids != staged_ids:
        error("staged core set differs from pinned OSCR recipes")
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
        for package in tuple(native) + BOOKWORM_ALL + (META,):
            filename, archive = build_one(work, package, layout, lock,
                                          stage, epoch, native)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            records.append({"filename": filename, "sha256": digest,
                            "package": package})
        for record in records:
            os.replace(str(work / record["filename"]), str(out / record["filename"]))
        manifest = {"release_channel": release_channel,
                    "auto_versioned": auto_version,
                    "os_tag": (os.environ.get("RETRODE3_RELEASE_TAG") or None),
                    "oscr_tag": (os.environ.get("RETRODE3_OSCR_TAG") or None),
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
                    "core_ids": [name[len(CORE_PREFIX):] for name in native
                                 if name != RUNTIME],
                    "hardware_accepted": False, "apt_published": False,
                    "target_sysroot_verified": False,
                    "required_symbol_versions": symbol_version_report(stage, native)}
        validate_meta_manifest(manifest, lock)
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
