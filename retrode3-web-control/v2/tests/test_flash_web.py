"""Mocked Web Flash privilege and job contract (no cartridge or root access)."""
import imp
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = imp.load_source("r3_web_flash_test", os.path.join(HERE, "..", "backend", "service.py"))
BRIDGE = imp.load_source("r3_flash_bridge_test", os.path.join(HERE, "..", "service", "retrode3-flashctl.py"))


class FlashBridgeSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="r3-flash-bridge-")
        self.roms = os.path.join(self.tmp, "ROMs")
        self.private = os.path.join(self.tmp, "private")
        os.mkdir(self.roms)
        os.mkdir(self.private)
        self.old_roms, self.old_private = BRIDGE.ROMS, BRIDGE.PRIVATE
        BRIDGE.ROMS, BRIDGE.PRIVATE = self.roms, self.private
        self.source = os.path.join(self.roms, "game.md")
        with open(self.source, "wb") as out:
            out.write(b"AB" * 512)

    def tearDown(self):
        BRIDGE.ROMS, BRIDGE.PRIVATE = self.old_roms, self.old_private
        shutil.rmtree(self.tmp)

    def command(self, action):
        value = {"core": "md", "request_id": "test_1", "command": action}
        if action != "probe_flash":
            value["source"] = self.source
        if action == "write_flash":
            value["confirm_erase"] = True
        return value

    def test_only_explicit_flash_actions(self):
        for command in ("probe_flash", "verify_flash", "write_flash"):
            self.assertEqual(BRIDGE.authorize(self.command(command))["command"], command)
        for bad in ("read_rom", "probe", "list_cores", "erase_raw", "cancel"):
            with self.assertRaises(BRIDGE.FlashRequestError):
                BRIDGE.authorize(self.command(bad))
        with self.assertRaises(BRIDGE.FlashRequestError):
            BRIDGE.authorize(dict(self.command("write_flash"), confirm_erase=False))
        with self.assertRaises(BRIDGE.FlashRequestError):
            BRIDGE.authorize(dict(self.command("verify_flash"), output="/etc/passwd"))
        with self.assertRaises(BRIDGE.FlashRequestError):
            BRIDGE.authorize(dict(self.command("probe_flash"), source=self.source))

    def test_snapshots_unmodifiable_root_copy_and_rejects_links(self):
        private, safe = BRIDGE.snapshot_rom(self.source)
        try:
            self.assertEqual(os.stat(safe).st_size, 1024)
            self.assertEqual(os.stat(private).st_mode & 0o077, 0)
            self.assertEqual(os.stat(safe).st_mode & 0o222, 0)
            with open(self.source, "wb") as out:
                out.write(b"XX" * 512)
            with open(safe, "rb") as copied:
                self.assertEqual(copied.read(), b"AB" * 512)
        finally:
            shutil.rmtree(private)
        link = os.path.join(self.roms, "alias.md")
        os.symlink(self.source, link)
        with self.assertRaises(BRIDGE.FlashRequestError):
            BRIDGE.snapshot_rom(link)
        with self.assertRaises(BRIDGE.FlashRequestError):
            BRIDGE.snapshot_rom("/etc/passwd")


class FlashWebJobs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="r3-flash-web-")
        self.old_root, self.old_files = WEB.ROOT, WEB.FILES_ROOT
        WEB.ROOT, WEB.FILES_ROOT = self.tmp, os.path.join(self.tmp, "ROMs")
        WEB.ensure_storage()
        os.mkdir(os.path.join(WEB.FILES_ROOT, "MD"))
        self.file = os.path.join(WEB.FILES_ROOT, "MD", "game.md")
        with open(self.file, "wb") as out:
            out.write(b"AB" * 512)
        self.old_cap, self.old_job = WEB.reader_capability, WEB.Job
        self.made = []
        self.fake = {"available": True, "folder": "MD", "extension": "md",
                     "slot": "md", "capabilities": {"commands": list(WEB.FLASH_ACTIONS)}}
        WEB.reader_capability = lambda core: self.fake if core == "md" else None
        made = self.made

        class StubJob(object):
            def __init__(self, manager, reader, action, label, capability, **kwargs):
                self.id = str(len(made))
                self.created = len(made)
                self.action = action
                self.opts = kwargs
                made.append(self)
            def snapshot(self):
                return {"id": self.id, "status": "queued"}
            def run(self):
                return
        WEB.Job = StubJob

    def tearDown(self):
        WEB.ROOT, WEB.FILES_ROOT = self.old_root, self.old_files
        WEB.reader_capability, WEB.Job = self.old_cap, self.old_job
        shutil.rmtree(self.tmp)

    def test_flash_confirmation_and_storage_validation(self):
        manager = WEB.JobManager()
        valid = {"system": "md", "command": "write_flash",
                 "source": "MD/game.md", "confirm_erase": True}
        for bad in (dict(valid, confirm_erase=False),
                    dict(valid, source="/dev/slot-md"),
                    dict(valid, source="MD/../../etc/passwd"),
                    dict(valid, source="GBA/game.md"),
                    dict(valid, output="/etc/passwd")):
            with self.assertRaises(WEB.ApiError):
                WEB.JobManager().submit(bad)
        self.assertEqual(manager.submit(valid)["status"], "queued")
        self.assertEqual(self.made[0].opts["source"], self.file)
        self.assertTrue(self.made[0].opts["confirm_erase"])

    def test_probe_is_explicit_and_verify_has_no_write_flag(self):
        with self.assertRaises(WEB.ApiError):
            WEB.JobManager().submit(
                {"system": "md", "command": "probe_flash"}, automatic=True)
        self.assertEqual(WEB.JobManager().submit(
            {"system": "md", "command": "probe_flash"})["status"], "queued")
        self.assertEqual(WEB.JobManager().submit(
            {"system": "md", "command": "verify_flash",
             "source": "MD/game.md"})["status"], "queued")
        self.assertFalse(self.made[-1].opts["confirm_erase"])
        with self.assertRaises(WEB.ApiError):
            WEB.JobManager().submit({"system": "md", "command": "verify_flash",
                                     "source": "MD/game.md", "confirm_erase": True})


if __name__ == "__main__":
    unittest.main()
