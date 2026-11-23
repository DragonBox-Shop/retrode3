#!/usr/bin/env python3
"""Channel policy tests; no cartridge hardware or network required."""
import importlib.util
import subprocess
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

    def test_auto_versions_are_reproducible_and_distinct(self):
        lock = self.example("stable", "0.2.0-1", "2.0.0-1")
        sha = "0123456789abcdef" * 2 + "01234567"
        first = builder.auto_version_lock(lock, sha, 1795433699)
        second = builder.auto_version_lock(lock, sha, 1795433699)
        newer = builder.auto_version_lock(lock, sha, 1795433700)
        self.assertEqual(first, second)
        self.assertEqual(lock["native_version"], "0.2.0-1")
        self.assertEqual(lock["web_version"], "2.0.0-1")
        self.assertNotEqual(first["native_version"], newer["native_version"])
        self.assertIn("+auto", first["native_version"])
        self.assertEqual(builder.validate_release_policy(first), "stable")
        for kind in ("native_version", "web_version"):
            self.assertEqual(subprocess.call(
                ["dpkg", "--compare-versions", first[kind], "gt",
                 lock[kind]]), 0)
            self.assertEqual(subprocess.call(
                ["dpkg", "--compare-versions", newer[kind], "gt",
                 first[kind]]), 0)

    def test_auto_testing_versions_keep_channel(self):
        lock = self.example("testing", "0.3.0~dev20261122-2",
                            "2.0.0+git20261122~dev-2")
        auto = builder.auto_version_lock(
            lock, "a" * 40, 1795433699)
        self.assertEqual(builder.validate_release_policy(auto), "testing")
        self.assertEqual(subprocess.call(
            ["dpkg", "--compare-versions", auto["native_version"], "gt",
             lock["native_version"]]), 0)

    def test_auto_version_requires_commit_and_debian_revision(self):
        lock = self.example("stable", "0.2.0-1", "2.0.0-1")
        with self.assertRaises(ValueError):
            builder.auto_version_lock(lock, "not-a-commit", 1795433699)
        lock["native_version"] = "0.2.0"
        with self.assertRaises(ValueError):
            builder.auto_version_lock(lock, "a" * 40, 1795433699)

    def test_unknown_abi_rejected(self):
        lock = self.example("testing", "0.3.0~dev-1", "2.0.0~dev-1")
        lock["core_operations_abi"] = 3
        with self.assertRaises(ValueError):
            builder.validate_release_policy(lock)


if __name__ == "__main__":
    unittest.main()
