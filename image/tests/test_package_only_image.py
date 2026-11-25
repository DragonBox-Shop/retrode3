"""Package-driven boot image regression tests; no hardware required."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "platform", ROOT / "buildserver/verify-platform-snapshot.py")
platform = importlib.util.module_from_spec(spec)
spec.loader.exec_module(platform)


def candidate():
    kinds = ("retrode3-linux-image", "retrode3-linux-modules",
             "retrode3-uboot-x1600")
    return {
        "schema": 1, "suite": "testing", "hardware_accepted": False,
        "apt_published": True,
        "sources": {"kernel": "a" * 40, "uboot": "b" * 40},
        "packages": [{
            "name": name,
            "version": "7.3.0~rc5+git20261125+example-1",
            "filename": name + "_7.3.0~rc5+git20261125+example-1_mipsel.deb",
            "sha256": "c" * 64,
        } for name in kinds],
    }


class PackageOnlyImageTests(unittest.TestCase):
    def check(self, doc):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "published-platform.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            return platform.verify(path, "testing")

    def test_valid_pinned_kernel_and_uboot(self):
        self.assertEqual(len(self.check(candidate())["packages"]), 3)

    def test_missing_package_fails_closed(self):
        doc = candidate()
        doc["packages"].pop()
        with self.assertRaises(ValueError):
            self.check(doc)

    def test_incorrect_or_unsigned_metadata_fails_closed(self):
        for field, value in (("suite", "stable"), ("apt_published", False),
                             ("hardware_accepted", True)):
            doc = candidate()
            doc[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(doc)

    def test_mismatched_modules_image_version_rejected(self):
        doc = candidate()
        doc["packages"][1]["version"] = "0.1.0-1"
        doc["packages"][1]["filename"] = (
            "retrode3-linux-modules_0.1.0-1_mipsel.deb")
        with self.assertRaises(ValueError):
            self.check(doc)

    def test_new_image_has_no_compilation_or_git_clone(self):
        image = (ROOT / "buildserver/build-image-from-packages.sh").read_text()
        host = (ROOT / "buildserver/run-image.sh").read_text()
        for forbidden in ("git clone", "kernel_make", "make -C",
                          "u-boot-src", "kernel-src"):
            self.assertNotIn(forbidden, image)
        self.assertIn("apt-get -y --no-install-recommends install", image)
        self.assertIn("published-platform.json", image)
        self.assertIn("build-image-from-packages.sh", host)
        self.assertIn("verify-platform-snapshot.py", host)
        self.assertNotIn("kernel_url=https", host)
        self.assertIn('bash "$vhost/package_$branch.sh"', host)
        package = (ROOT / "buildserver/package-develop-all.sh").read_text()
        self.assertIn('bash "$automation" develop', package)
        self.assertIn("package-platform-develop.sh", package)
        self.assertIn("publish-platform-develop.sh", package)
        self.assertNotIn('bash /srv/www/vhosts/retrode.com/package_develop.sh', package)

    def test_podman_bare_sha256_builder_id_normalized(self):
        # Podman's .Id normally has no sha256: prefix. The host must
        # normalize it before passing the fingerprint to the cache verifier.
        producer = (ROOT / "buildserver/package-platform-develop.sh").read_text()
        self.assertIn(
            'if [[ "$image_id" =~ ^[a-f0-9]{64}$ ]]; then',
            producer)
        self.assertIn('image_id="sha256:$image_id"', producer)
        self.assertIn(
            '[[ "$image_id" =~ ^sha256:[a-f0-9]{64}$ ]]',
            producer)
        self.assertIn('Invalid Podman builder image ID:', producer)
        self.assertLess(producer.index('image_id="sha256:$image_id"'),
                        producer.index('platform-cache.py" key'))

    def test_signing_directory_supports_secure_setgid_inheritance(self):
        publisher = (ROOT / "buildserver/publish-platform-develop.sh").read_text()
        self.assertIn('"700:$owner_uid"', publisher)
        self.assertIn('"2700:$owner_uid"', publisher)
        self.assertIn('"600:$owner_uid:1"', publisher)
        self.assertIn('! -L "$secret_dir"', publisher)
        self.assertIn('! -L "$secret"', publisher)
        self.assertIn('stage=signature-preflight', publisher)
        self.assertNotIn('== "700:$(id -u)"', publisher)

    def test_rootless_mmdebstrap_bootstrap(self):
        rootfs = (ROOT / "image/build-bookworm-rootfs.sh").read_text()
        container = (ROOT / "buildserver/Containerfile.image").read_text()
        self.assertIn("mmdebstrap", container)
        self.assertIn("arch-test", container)
        self.assertIn("mmdebstrap \\\n", rootfs)
        self.assertIn("--mode=root", rootfs)
        self.assertIn("--skip=check/canmount,chroot/mount", rootfs)
        self.assertIn("--architectures=mipsel", rootfs)
        self.assertIn("--include=sysvinit-core", rootfs)
        self.assertIn("--format=tar", rootfs)
        self.assertIn("--exclude='./dev/*'", rootfs)
        self.assertNotIn("debootstrap --arch=mipsel", rootfs)
        self.assertNotIn("debootstrap --second-stage", rootfs)
        self.assertNotIn("chroot \"$root\" /usr/bin/apt-get install", rootfs)
        self.assertIn('verify-rootfs.py" "$root"', rootfs)

    def test_apt_chroot_only_binds_five_safe_character_devices(self):
        host = (ROOT / "buildserver/run-image.sh").read_text()
        assembler = (ROOT / "buildserver/build-image-from-packages.sh").read_text()
        self.assertIn('device_mounts=()', host)
        self.assertIn('for device in null zero random urandom tty; do', host)
        self.assertIn('[[ -c "/dev/$device" && ! -L "/dev/$device" ]]', host)
        self.assertIn('device_mounts+=( -v "/dev/$device:/work/rootfs/dev/$device:rw" )', host)
        self.assertIn('"${device_mounts[@]}"', host)
        self.assertIn('Chroot APT devices ready', assembler)
        self.assertIn('[[ -c "/work/rootfs/dev/$device" ]]', assembler)
        self.assertIn('--exclude=\'./dev/*\'', assembler)
        self.assertIn('--exclude=\'dev/*\'', assembler)
        self.assertNotIn('mknod ', assembler)

    def test_offline_core_enablement_creates_trusted_state(self):
        image = (ROOT / "buildserver/build-image-from-packages.sh").read_text()
        self.assertIn('core_enabled="$core_parent/cores-enabled"', image)
        self.assertIn('install -d -o 0 -g 0 -m 0755 "$core_enabled"', image)
        self.assertIn('[[ ! -L "$core_parent" && ! -L "$core_enabled" ]]', image)
        self.assertIn('"$(stat -c \'%u:%g:%a\' "$core_enabled")" == 0:0:755', image)
        self.assertLess(image.index('install -d -o 0 -g 0 -m 0755 "$core_enabled"'),
                        image.index('retrode3-corectl enable "$core"'))

    def test_package_image_does_not_import_ssh_keys(self):
        host = (ROOT / "buildserver/run-image.sh").read_text()
        image = (ROOT / "buildserver/build-image-from-packages.sh").read_text()
        self.assertNotIn("ssh.pub", host)
        self.assertNotIn("--ssh-authorized-key", image)
        self.assertIn("--with-retrode3", image)

    def test_final_apache_mpm_checked_after_apt(self):
        image = (ROOT / "buildserver/build-image-from-packages.sh").read_text()
        self.assertIn('for module in mpm_prefork.load php8.2.load; do', image)
        self.assertIn('python3 /src/image/verify-apache-offline.py /work/rootfs', image)
        self.assertNotIn('chroot /work/rootfs /usr/sbin/apache2ctl configtest', image)
        self.assertLess(image.index('apt-get -y --no-install-recommends install'),
                        image.index('verify-apache-offline.py'))

    def test_resume_skips_bootstrap_and_apt_but_verifies_packages(self):
        host = (ROOT / "buildserver/run-image.sh").read_text()
        image = (ROOT / "buildserver/build-image-from-packages.sh").read_text()
        self.assertIn('"$2" == --resume', host)
        self.assertIn('cmp -s "$run/published-packages.json" "$published"', host)
        self.assertIn('cmp -s "$run/published-platform.json" "$platform"', host)
        self.assertIn('RETRODE3_IMAGE_RESUME=$resume', host)
        self.assertIn('if [[ "$resume" == 0 ]]; then', image)
        self.assertIn('=== RESUME: existing Bookworm rootfs retained', image)
        self.assertIn('=== RESUME: checking already-installed package versions', image)
        self.assertIn('"$state" == "install ok installed"', image)
        self.assertIn('sha256sum --check --strict SHA256SUMS', image)
        self.assertIn('rm -rf -- /work/stage', image)

    def test_package_producer_cache_and_source_recipe_contract(self):
        producer = (ROOT / "buildserver/package-platform-develop.sh").read_text()
        self.assertIn("platform-cache.py", producer)
        self.assertIn("CACHE HIT", producer)
        self.assertIn("CACHE MISS", producer)
        self.assertIn("platform-package-set.json", producer)
        builder = (ROOT / "buildserver/build-platform-component.sh").read_text()
        self.assertIn("/work/source/packaging/retrode3/build-debs.sh", builder)
        self.assertIn('[[ "$sha" == "$RETRODE3_COMPONENT_SHA" ]]', builder)


if __name__ == "__main__":
    unittest.main()
