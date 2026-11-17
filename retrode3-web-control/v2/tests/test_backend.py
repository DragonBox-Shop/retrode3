#!/usr/bin/env python3
"""Safe mocked tests; no cartridge or WLAN operation."""
from __future__ import print_function
import imp
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = imp.load_source("retrode3_web_v2", os.path.join(HERE, "..", "backend", "service.py"))

class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="retrode3-web-test-")
        MODULE.ROOT = self.temp
        MODULE.FILES_ROOT = os.path.join(self.temp, "ROMs")
        MODULE.ensure_storage()

    def tearDown(self):
        shutil.rmtree(self.temp)

    def test_sandbox(self):
        self.assertEqual(MODULE.safe_path(""), MODULE.FILES_ROOT)
        for path in ("../etc", "SNES/../../etc", "/etc", "SNES//file", "SNES/.hidden", "a\\b"):
            with self.assertRaises(MODULE.ApiError):
                MODULE.safe_path(path, must_exist=False)

    def test_symlink_rejected(self):
        os.symlink(self.temp, os.path.join(MODULE.FILES_ROOT, "escape"))
        with self.assertRaises(MODULE.ApiError):
            MODULE.safe_path("escape/file", must_exist=False)

    def test_filename_sanitized(self):
        name = MODULE.sanitized_filename("../danger;rm -rf /")
        self.assertFalse("/" in name)
        self.assertFalse(";" in name)

    def test_native_missing(self):
        manager = MODULE.JobManager()
        old_binary = MODULE.SNES_BIN
        MODULE.SNES_BIN = os.path.join(self.temp, "missing-native")
        try:
            with self.assertRaises(MODULE.ApiError):
                manager.submit({"system": "snes", "command": "probe"})
        finally:
            MODULE.SNES_BIN = old_binary

    def test_size_validation(self):
        manager = MODULE.JobManager()
        old_binary = MODULE.SNES_BIN
        try:
            binary = os.path.join(self.temp, "mock-reader")
            with open(binary, "w") as handle:
                handle.write("#!/bin/sh\nexit 0\n")
            os.chmod(binary, 0o755)
            MODULE.SNES_BIN = binary
            for size in (True, 0, 131071, 4194305, 131073):
                with self.assertRaises(MODULE.ApiError):
                    manager.submit({"system": "snes", "command": "read_rom", "size_bytes": size})
        finally:
            MODULE.SNES_BIN = old_binary

if __name__ == "__main__":
    unittest.main()
