"""No APT mutations or root access: exercise update policy with mocks."""
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / "assets/retrode3-update-control"
spec = spec_from_loader("update_test", SourceFileLoader("update_test", str(path)))
update = module_from_spec(spec)
spec.loader.exec_module(update)


class UpdateTests(unittest.TestCase):
    def test_plan(self):
        plan = update.parse_plan(
            "Inst retrode3-web-control [2.0-1] (2.0-2 Retrode3:testing [all])\n"
            "Inst retrode3-core-sms-md (0.3-2 Retrode3:testing [mipsel])\n"
            "Conf retrode3-web-control (2.0-2 Retrode3:testing [all])\n")
        self.assertEqual(plan, [
            {"name": "retrode3-core-sms-md", "installed": "", "candidate": "0.3-2"},
            {"name": "retrode3-web-control", "installed": "2.0-1", "candidate": "2.0-2"}])

    def test_reject_unsafe_plans(self):
        for row in ("Remv retrode3-core-md [1]", "Inst retrode3-linux-image (2 repo)",
                    "Inst retrode3-linux-modules (2 repo)", "Inst retrode3-uboot-x1600 (2 repo)",
                    "Inst retrode3-esp-firmware (2 repo)", "Inst libc6 (2 repo)",
                    "Conf libc6 (2 repo)", "Inst retrode3-web-control [2] (1 repo)",
                    "Inst retrode3-core-md malformed"):
            with self.subTest(row=row), self.assertRaises(ValueError):
                update.parse_plan(row)

    def test_status_atomic_and_public(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(update, "RUNTIME", Path(folder)):
            result = update.save("checking")
            self.assertEqual(update.state(), result)
            self.assertEqual((Path(folder) / "status.json").stat().st_mode & 0o777, 0o644)
            self.assertEqual(list(Path(folder).iterdir()), [Path(folder) / "status.json"])

    def test_recheck_refuses_changed_plan_before_install(self):
        with patch.object(update, "apt_base", return_value=["apt-get"]), \
             patch.object(update, "state", return_value={"packages": [{"name":"retrode3-tools","candidate":"2"}]}), \
             patch.object(update, "installed", return_value=["retrode3-tools"]), \
             patch.object(update, "simulate", return_value=[]), \
             patch.object(update, "save") as save, \
             patch.object(update, "command") as command, \
             patch.object(update.os, "open", return_value=15), \
             patch.object(update.os, "fdopen") as fdopen, \
             patch.object(update.os, "fchmod"), patch.object(update.os, "close"):
            update.worker("install", 10, 11)
            command.assert_not_called()
            self.assertEqual(save.call_args.args[0], "failed")
            self.assertIn("changed", save.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
