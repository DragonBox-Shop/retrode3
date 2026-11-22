#!/usr/bin/env python3
"""Flash-only web backend gates; no cartridge I/O or kernel access."""
from __future__ import print_function
import imp
import os
import tempfile
import shutil
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = imp.load_source("retrode3_web_flash_mock",
                         os.path.join(HERE, "..", "backend", "service.py"))


class FlashWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="retrode3-flash-web-")
        self.registry = MODULE.core_registry
        self.flash_caps = MODULE.native_flash_capabilities
        self.job = MODULE.Job
        self.cli = MODULE.CLI_BIN

    def tearDown(self):
        MODULE.core_registry = self.registry
        MODULE.native_flash_capabilities = self.flash_caps
        MODULE.Job = self.job
        MODULE.CLI_BIN = self.cli
        shutil.rmtree(self.temp)

    def test_no_flash_without_supported_plugin(self):
        MODULE.native_flash_capabilities = lambda system: {
            "core": system, "available": False, "probe_supported": False,
            "write_supported": False}
        with self.assertRaises(MODULE.ApiError) as captured:
            MODULE.JobManager().submit({"system": "md", "command": "flash_probe"})
        self.assertEqual(captured.exception.code, "flash_probe_unavailable")
        for forbidden in ("flash_write", "flash_erase", "flash_verify"):
            with self.assertRaises(MODULE.ApiError):
                MODULE.JobManager().submit({"system": "md", "command": forbidden})

    def test_flash_probe_is_explicit_and_uses_normal_job_manager(self):
        received = []
        class FakeJob(object):
            def __init__(self, *args, **kwargs):
                self.id = "f" * 32
                self.created = 0
                self.args = args
                received.append(args)
            def snapshot(self):
                return {"id": self.id, "status": "done"}
            def run(self):
                return
        MODULE.Job = FakeJob
        MODULE.native_flash_capabilities = lambda system: {
            "core": system, "name": "Future adapter", "slot": "md",
            "available": True, "probe_supported": True,
            "write_supported": False}
        manager = MODULE.JobManager()
        accepted = manager.submit({"system": "future-plugin", "command": "flash_probe"})
        self.assertEqual(accepted["status"], "done")
        self.assertEqual(received[0][1:3], ("future-plugin", "flash_probe"))
        self.assertEqual(received[0][4]["slot"], "md")
        for bad in (
                {"system": "future-plugin", "command": "flash_probe", "output": "/tmp/x"},
                {"system": "future-plugin", "command": "flash_probe", "filename": "x"},
                {"system": "future-plugin", "command": "flash_probe", "selection": {}}):
            with self.assertRaises(MODULE.ApiError):
                MODULE.JobManager().submit(bad)

    def test_metadata_core_rejection_and_older_cli(self):
        MODULE.core_registry = lambda: {
            "available": True, "cores": [{
                "id": "md", "slot": "md", "name": "MegaDrive",
                "installed": True, "enabled": False, "usable": False,
                "status": "disabled"}]}
        metadata = MODULE.native_flash_capabilities("md")
        self.assertFalse(metadata["available"])
        self.assertFalse(metadata["probe_supported"])
        with self.assertRaises(MODULE.ApiError):
            MODULE.native_flash_capabilities("missing")
        # Even an executable older CLI that lacks the Flash action may not
        # accidentally report itself as flash-capable.
        script = os.path.join(self.temp, "older-cli")
        with open(script, "w") as f:
            f.write("#!/bin/sh\nexit 2\n")
        os.chmod(script, 0o755)
        MODULE.CLI_BIN = script
        MODULE.core_registry = lambda: {
            "available": True, "cores": [{
                "id": "md", "slot": "md", "name": "MegaDrive",
                "installed": True, "enabled": True, "usable": True,
                "status": "ready"}]}
        metadata = MODULE.native_flash_capabilities("md")
        self.assertFalse(metadata["available"])
        self.assertEqual(metadata["reason"], "flash_cli_unavailable")


if __name__ == "__main__":
    unittest.main()
