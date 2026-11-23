"""Mocked Web Flash job contract using the normal unprivileged CLI."""
import imp
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = imp.load_source("r3_web_flash_test", os.path.join(HERE, "..", "backend", "service.py"))


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

    def test_flash_source_folder_and_size_validation(self):
        manager = WEB.JobManager()
        valid = {"system": "md", "command": "write_flash",
                 "source": "MD/game.md"}
        for bad in (dict(valid, source="/dev/slot-md"),
                    dict(valid, source="MD/../../etc/passwd"),
                    dict(valid, source="GBA/game.md"),
                    dict(valid, output="/etc/passwd")):
            with self.assertRaises(WEB.ApiError):
                WEB.JobManager().submit(bad)
        self.assertEqual(manager.submit(valid)["status"], "queued")
        self.assertEqual(self.made[0].opts["source"], self.file)

    def test_probe_is_explicit_and_verify_is_read_only(self):
        with self.assertRaises(WEB.ApiError):
            WEB.JobManager().submit(
                {"system": "md", "command": "probe_flash"}, automatic=True)
        self.assertEqual(WEB.JobManager().submit(
            {"system": "md", "command": "probe_flash"})["status"], "queued")
        self.assertEqual(WEB.JobManager().submit(
            {"system": "md", "command": "verify_flash",
             "source": "MD/game.md"})["status"], "queued")
        with self.assertRaises(WEB.ApiError):
            WEB.JobManager().submit({"system": "md", "command": "verify_flash",
                                     "source": "MD/game.md", "confirm_erase": True})



if __name__ == "__main__":
    unittest.main()
