#!/usr/bin/env python3
"""Channel policy tests; no cartridge hardware or network required."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("retrode3_debs", str(ROOT / "packaging/build-debs.py"))
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class TestReleasePolicy(unittest.TestCase):
    def example(self, channel, native, web):
        return {"release_channel": channel, "native_version": native,
                "web_version": web, "core_discovery_abi": 1,
                "core_operations_abi": 1}

    def test_testing_accepts_development_versions(self):
        lock = self.example("testing", "0.3.0~dev20261122-1",
                            "2.0.0+git20261122~dev-1")
        self.assertEqual(builder.validate_release_policy(lock), "testing")

    def test_stable_accepts_release_versions(self):
        lock = self.example("stable", "0.2.0-1", "2.0.0-1")
        self.assertEqual(builder.validate_release_policy(lock), "stable")

    def test_wrong_channel_and_versions_rejected(self):
        bad = [
            self.example("develop-test-only", "0.3.0~dev-1", "2.0.0~dev-1"),
            self.example("stable", "0.2.0~dev-1", "2.0.0-1"),
            self.example("stable", "0.2.0-1", "2.0.0~dev-1"),
            self.example("testing", "0.3.0-1", "2.0.0~dev-1"),
            self.example("testing", "0.3.0~dev-1", "2.0.0-1"),
        ]
        for lock in bad:
            with self.subTest(lock=lock), self.assertRaises(ValueError):
                builder.validate_release_policy(lock)

    def test_unknown_abi_rejected(self):
        lock = self.example("testing", "0.3.0~dev-1", "2.0.0~dev-1")
        lock["core_operations_abi"] = 3
        with self.assertRaises(ValueError):
            builder.validate_release_policy(lock)


if __name__ == "__main__":
    unittest.main()
