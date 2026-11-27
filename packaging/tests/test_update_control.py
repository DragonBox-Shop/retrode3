"""No APT mutations or root access: exercise update policy with mocks."""
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from io import BytesIO
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

path = Path(__file__).resolve().parents[1] / "assets/retrode3-update-control"
spec = spec_from_loader("update_test", SourceFileLoader("update_test", str(path)))
update = module_from_spec(spec)
spec.loader.exec_module(update)


class UpdateTests(unittest.TestCase):
    def test_clock_already_synchronized_skips_recovery(self):
        log = BytesIO()
        with patch.object(update.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 0)) as run:
            update.sync_clock(log)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0],
                         ["/usr/bin/chronyc", "-n", "waitsync", "1", "1.0", "0", "1"])
        self.assertNotIn(b"WARNING", log.getvalue())

    def test_clock_recovery_refreshes_sources_and_waits(self):
        log = BytesIO()
        with patch.object(update.subprocess, "run", side_effect=[
                subprocess.CompletedProcess([], code) for code in (1, 0, 0, 0, 0)]) as run:
            update.sync_clock(log)
        self.assertEqual([call.args[0][2:] for call in run.call_args_list],
                         [["waitsync", "1", "1.0", "0", "1"], ["refresh"],
                          ["online"], ["burst", "4/4"], ["waitsync", "15", "1.0", "0", "1"]])
        self.assertEqual(run.call_args.kwargs["timeout"], 20)
        self.assertNotIn(b"WARNING", log.getvalue())

    def test_unavailable_ntp_keeps_normal_apt_validation(self):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("chronyc", 3)):
            with self.subTest(error=error), patch.object(update.subprocess, "run",
                                                         side_effect=error) as run:
                log = BytesIO()
                update.sync_clock(log)
                self.assertEqual(run.call_count, 5)
                self.assertIn(b"normal APT time validation", log.getvalue())

    def test_clock_check_precedes_apt_refresh(self):
        calls = Mock()
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(update, "LOG", Path(folder) / "update.log"), \
             patch.object(update, "apt_base", return_value=["apt-get"]), \
             patch.object(update, "sync_clock", calls.clock), \
             patch.object(update, "command", calls.apt), \
             patch.object(update, "installed", return_value=["retrode3-tools"]), \
             patch.object(update, "simulate", return_value=[]), \
             patch.object(update, "save") as save, \
             patch.object(update.os, "close"):
            update.worker("check", 10, 11)
        self.assertEqual([call[0] for call in calls.mock_calls], ["clock", "apt"])
        self.assertEqual(calls.apt.call_args.args[0],
                         ["apt-get", "-o", "APT::Update::Error-Mode=any", "update"])
        save.assert_called_once_with("current", [])

    def test_plan(self):
        plan = update.parse_plan(
            "Inst retrode3-web-control [2.0-1] (2.0-2 Retrode3:testing [all])\n"
            "Inst retrode3-core-sms-md (0.3-2 Retrode3:testing [mipsel])\n"
            "Conf retrode3-web-control (2.0-2 Retrode3:testing [all])\n")
        self.assertEqual(plan, [
            {"name": "retrode3-core-sms-md", "installed": "", "candidate": "0.3-2"},
            {"name": "retrode3-web-control", "installed": "2.0-1", "candidate": "2.0-2"}])

    def test_reject_unsafe_plans(self):
        for row in ("Remv retrode3-core-md [1]", "Inst retrode3-uboot-x1600 (2 repo)",
                    "Inst retrode3-esp-firmware (2 repo)", "Inst libc6 (2 repo)",
                    "Conf libc6 (2 repo)", "Inst retrode3-web-control [2] (1 repo)",
                    "Inst retrode3-core-md malformed"):
            with self.subTest(row=row), self.assertRaises(ValueError):
                update.parse_plan(row)

    def test_kernel_plan_requires_matching_installable_pair(self):
        plan = update.parse_plan(
            "Inst retrode3-linux-image [1] (2 repo)\n"
            "Inst retrode3-linux-modules [1] (2 repo)\n")
        with patch.object(update, "capture",
                          return_value="X-Retrode3-Kernel-Layout: live-v1\n") as capture:
            update.validate_kernel_plan(plan)
            self.assertEqual(capture.call_count, 2)
        with patch.object(update, "capture", return_value="Package: old\n"):
            with self.assertRaisesRegex(ValueError, "staged-only"):
                update.validate_kernel_plan(plan)
        with self.assertRaisesRegex(ValueError, "updated together"):
            update.validate_kernel_plan(plan[:1])
        with self.assertRaisesRegex(ValueError, "same version"):
            update.validate_kernel_plan([plan[0], dict(plan[1], candidate="3")])

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
