"""Slot ROM results must survive browser refresh but not cartridge removal."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import service


class SlotReadResultTests(unittest.TestCase):
    def setUp(self):
        self.manager = service.JobManager()
        self.slots = [{"id": "nes", "status": "occupied"},
                      {"id": "md", "status": "occupied"}]
        self.sense = patch.object(service, "slot_snapshot",
                                  side_effect=lambda: {"slots": [dict(s) for s in self.slots]})
        self.sense.start()
        self.addCleanup(self.sense.stop)

    def job(self, slot, crc):
        job = service.Job(self.manager, slot, "read_rom", "Game", {"slot": slot})
        job.presence_generation = self.manager.observe_slot(slot, "occupied")
        job.status = "done"
        job.output = "/tmp/" + slot + ".rom"
        job.result = {"identity": {"title": "Game " + slot}, "size_bytes": 65536,
                      "crc32": crc, "verification": {"status": "mismatch",
                                                      "actual": crc, "expected": "12345678"}}
        return job

    def test_results_are_slot_scoped_and_survive_snapshot(self):
        nes = self.job("nes", "ABCDEF01")
        md = self.job("md", "ABCDEF02")
        self.manager.remember_read(nes)
        self.manager.remember_read(md)
        auto = service.AutomaticDetection(self.manager)
        result = auto.snapshot()
        self.assertEqual(result["slots"][0]["read_result"]["crc32"], "ABCDEF01")
        self.assertEqual(result["slots"][1]["read_result"]["crc32"], "ABCDEF02")
        self.assertEqual(result["slots"][0]["read_result"]["filename"], "nes.rom")
        self.assertEqual(result["slots"][0]["read_result"]["verification"]["status"], "mismatch")
        self.assertIsNone(result["busy_job"])

    def test_removed_and_reinserted_slot_does_not_reuse_old_job(self):
        nes = self.job("nes", "ABCDEF01")
        md = self.job("md", "ABCDEF02")
        self.manager.remember_read(nes)
        self.manager.remember_read(md)
        self.manager.observe_slot("nes", "empty")
        self.manager.observe_slot("nes", "occupied")
        self.manager.remember_read(nes)
        auto = service.AutomaticDetection(self.manager)
        result = auto.snapshot()
        self.assertIsNone(result["slots"][0]["read_result"])
        self.assertEqual(result["slots"][1]["read_result"]["crc32"], "ABCDEF02")

    def test_empty_sense_does_not_keep_a_cartridge_result(self):
        job = self.job("nes", "ABCDEF01")
        self.slots[0]["status"] = "empty"
        self.manager.remember_read(job)
        self.assertNotIn("nes", self.manager.read_results)

    def test_active_summary_contains_physical_slot_and_percent(self):
        job = self.job("nes", "ABCDEF01")
        job.status = "running"
        job.progress = {"percent": 64, "bytes_done": 400}
        self.manager.active = job
        self.assertEqual(self.manager.slot_job_state(), {
            "id": job.id, "system": "nes", "slot": "nes", "command": "read_rom",
            "status": "running", "automatic": False, "progress": {"percent": 64}})


if __name__ == "__main__":
    unittest.main()
