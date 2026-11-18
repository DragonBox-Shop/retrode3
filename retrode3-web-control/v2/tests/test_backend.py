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

    def test_wifi_detects_device_even_if_legacy_helper_misses_it(self):
        old_root = MODULE.NET_SYSFS_ROOT
        old_helper = MODULE.call_wlan
        old_link = MODULE.wireless_link
        old_ipv4 = MODULE.interface_ipv4
        try:
            wifi_root = os.path.join(self.temp, "network")
            os.makedirs(os.path.join(wifi_root, "wlan0", "phy80211"))
            MODULE.NET_SYSFS_ROOT = wifi_root
            MODULE.call_wlan = lambda command: "no WLAN interface"
            MODULE.wireless_link = lambda interface: {"associated": False, "ssid": ""}
            MODULE.interface_ipv4 = lambda interface: ""
            result = MODULE.wifi_status()
            self.assertTrue(result["available"])
            self.assertEqual(result["interface"], "wlan0")
            self.assertEqual(result["warning"], "legacy_helper_does_not_detect_interface")
            self.assertFalse(result["connected"])
        finally:
            MODULE.NET_SYSFS_ROOT = old_root
            MODULE.call_wlan = old_helper
            MODULE.wireless_link = old_link
            MODULE.interface_ipv4 = old_ipv4

    def test_wifi_missing_device_is_not_assumed_connected(self):
        old_root = MODULE.NET_SYSFS_ROOT
        old_helper = MODULE.call_wlan
        old_which = MODULE.wireless_interfaces
        try:
            MODULE.NET_SYSFS_ROOT = self.temp
            MODULE.wireless_interfaces = lambda: []
            MODULE.call_wlan = lambda command: "no WLAN interface"
            result = MODULE.wifi_status()
            self.assertFalse(result["available"])
            self.assertFalse(result["connected"])
            self.assertEqual(result["reason"], "no_wireless_interface_detected")
        finally:
            MODULE.NET_SYSFS_ROOT = old_root
            MODULE.call_wlan = old_helper
            MODULE.wireless_interfaces = old_which

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
        old_binary = MODULE.READER_SPECS["snes"]["binary"]
        MODULE.READER_SPECS["snes"]["binary"] = os.path.join(self.temp, "missing-native")
        try:
            with self.assertRaises(MODULE.ApiError):
                manager.submit({"system": "snes", "command": "probe"})
        finally:
            MODULE.READER_SPECS["snes"]["binary"] = old_binary

    def test_passive_slot_status_and_unknown_values(self):
        previous = MODULE.SENSE_ROOT
        MODULE.SENSE_ROOT = os.path.join(self.temp, "sysfs")
        try:
            for slot, sense in (("snes", "active"), ("md", "empty"),
                                ("nes", "not-a-valid-kernel-status")):
                directory = os.path.join(MODULE.SENSE_ROOT, "slot-" + slot)
                os.makedirs(directory)
                with open(os.path.join(directory, "sense"), "w") as handle:
                    handle.write(sense + "\n")
            result = MODULE.slot_snapshot()
            by_id = dict((slot["id"], slot) for slot in result["slots"])
            self.assertEqual(by_id["snes"]["status"], "occupied")
            self.assertEqual(by_id["md"]["status"], "empty")
            self.assertEqual(by_id["nes"]["status"], "unknown")
            self.assertIsNone(by_id["snes"]["adapter_id"])
            self.assertIsNone(by_id["snes"]["detected_system"])
            # Missing sysfs entries are not treated as empty cartridges.
            os.unlink(os.path.join(MODULE.SENSE_ROOT, "slot-nes", "sense"))
            self.assertEqual(
                dict((x["id"], x) for x in MODULE.slot_snapshot()["slots"])["nes"]["status"],
                "unavailable")
        finally:
            MODULE.SENSE_ROOT = previous

    def test_only_ndjson_native_core_is_web_available(self):
        old_snes = MODULE.READER_SPECS["snes"]["binary"]
        old_md = MODULE.READER_SPECS["md"]["binary"]
        native = os.path.join(self.temp, "mock-ndjson-snes")
        legacy = os.path.join(self.temp, "mock-one-shot-md")
        with open(native, "w") as handle:
            handle.write("#!/bin/sh\n")
            handle.write("echo '{\"protocol\":\"retrode3-ndjson\",\"version\":1,"
                         "\"event\":\"ready\",\"system\":\"snes\"}'\n")
            handle.write("IFS= read -r command || exit 1\n")
            handle.write("echo '{\"protocol\":\"retrode3-ndjson\",\"version\":1,"
                         "\"event\":\"capabilities\",\"request_id\":\"webcap\","
                         "\"system\":\"snes\",\"commands\":[\"get_capabilities\","
                         "\"probe\",\"read_rom\",\"cancel\"],\"mappings\":[\"lo\",\"hi\"],"
                         "\"size_override\":true,\"max_rom_bytes\":4194304}'\n")
        with open(legacy, "w") as handle:
            handle.write("#!/bin/sh\n")
            handle.write("echo '{\"ok\":false,\"error\":\"unknown option\"}' >&2\n")
            handle.write("exit 2\n")
        os.chmod(native, 0o755)
        os.chmod(legacy, 0o755)
        try:
            MODULE.READER_SPECS["snes"]["binary"] = native
            MODULE.READER_SPECS["md"]["binary"] = legacy
            results = MODULE.capability_probe()["systems"]
            by_id = dict((entry["id"], entry) for entry in results)
            self.assertTrue(by_id["snes"]["available"])
            self.assertEqual(by_id["snes"]["capabilities"]["system"], "snes")
            self.assertFalse(by_id["md"]["available"])
            self.assertEqual(by_id["md"]["reason"], "native_protocol_unavailable")
            with self.assertRaises(MODULE.ApiError):
                MODULE.JobManager().submit({"system": "md", "command": "read_rom"})
        finally:
            MODULE.READER_SPECS["snes"]["binary"] = old_snes
            MODULE.READER_SPECS["md"]["binary"] = old_md

    def test_unregistered_core_is_never_invoked(self):
        with self.assertRaises(MODULE.ApiError) as err:
            MODULE.JobManager().submit({"system": "dangerous-helper", "command": "probe"})
        self.assertEqual(err.exception.status, 400)

    def test_size_validation(self):
        manager = MODULE.JobManager()
        old_binary = MODULE.READER_SPECS["snes"]["binary"]
        try:
            binary = os.path.join(self.temp, "mock-reader")
            with open(binary, "w") as handle:
                handle.write("#!/bin/sh\nexit 0\n")
            os.chmod(binary, 0o755)
            MODULE.READER_SPECS["snes"]["binary"] = binary
            for size in (True, 0, 131071, 4194305, 131073):
                with self.assertRaises(MODULE.ApiError):
                    manager.submit({"system": "snes", "command": "read_rom", "size_bytes": size})
        finally:
            MODULE.READER_SPECS["snes"]["binary"] = old_binary

if __name__ == "__main__":
    unittest.main()
