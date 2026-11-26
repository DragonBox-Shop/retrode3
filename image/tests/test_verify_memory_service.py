"""Check package ownership and boot registration without touching host swap."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "verify_rootfs", Path(__file__).resolve().parents[1] / "verify-rootfs.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class MemoryServiceTests(unittest.TestCase):
    def test_requires_package_owned_executable_and_single_start_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = root / "etc/init.d/retrode3-memory"
            owner = root / "var/lib/dpkg/info/retrode3-tools.list"
            link = root / "etc/rc2.d/S01retrode3-memory"
            for path in (service, owner, link):
                path.parent.mkdir(parents=True, exist_ok=True)
            service.write_text("#!/bin/sh\nexit 0\n")
            service.chmod(0o755)
            owner.write_text("/etc/init.d/retrode3-memory\n")
            link.symlink_to("../init.d/retrode3-memory")
            self.assertEqual(verify.verify_memory_service(root), link)
            owner.write_text("/etc/init.d/other\n")
            with self.assertRaises(ValueError):
                verify.verify_memory_service(root)
            owner.write_text("/etc/init.d/retrode3-memory\n")
            extra = link.with_name("S02retrode3-memory")
            extra.symlink_to("../init.d/retrode3-memory")
            with self.assertRaises(ValueError):
                verify.verify_memory_service(root)
            extra.unlink()
            service.write_text("#!/bin/sh\nsysctl -w vm.swappiness=100\n")
            with self.assertRaises(ValueError):
                verify.verify_memory_service(root)


if __name__ == "__main__":
    unittest.main()
