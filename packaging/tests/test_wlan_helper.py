import importlib.machinery
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch, call
import subprocess

path = Path(__file__).resolve().parents[2] / "retrode3-tools/usr/local/bin/retrode3-wlan"
loader = importlib.machinery.SourceFileLoader("wlan_helper", str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
wlan = importlib.util.module_from_spec(spec)
loader.exec_module(wlan)


class WlanTests(unittest.TestCase):
    def test_config_injection_and_password(self):
        cfg = wlan.config('a"\nnetwork={', 'secret"1234')
        self.assertIn("ssid=" + 'a"\nnetwork={'.encode().hex(), cfg)
        self.assertNotIn('secret"1234', cfg)
        self.assertEqual(cfg.count("network={"), 1)
        self.assertIn("key_mgmt=WPA-PSK SAE", cfg)
        self.assertIn("key_mgmt=NONE", wlan.config("open", ""))
        for ssid, pw in (("x"*33, ""), ("", ""), ("x", "short"), ("x", "long\npassword")):
            with self.assertRaises(ValueError):
                wlan.config(ssid, pw)

    def test_scan_deduplicates_and_sorts(self):
        raw = """BSS 94:83:c4:c3:ad:ff(on wlan0)
        freq: 2412
        signal: -46.00 dBm
        SSID: EvilNetworks
        RSN:
            * Authentication suites: PSK SAE
BSS 08:b6:57:71:ef:70(on wlan0)
        freq: 2437
        signal: -74.00 dBm
        SSID: EvilNetworks
        RSN:
            * Authentication suites: PSK SAE
"""
        out = wlan.parse_scan(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["dbm"], -46)
        self.assertEqual(out[0]["security"], "WPA2/WPA3")

    def test_cold_scan_retries_without_restarting_interface(self):
        with patch.object(wlan.NET.__class__, "exists", return_value=True), \
             patch.object(wlan, "link_up", return_value=False), \
             patch.object(wlan.time, "sleep") as sleep, \
             patch.object(wlan, "cmd", side_effect=["", RuntimeError("busy"), "", ""]) as cmd:
            self.assertEqual(wlan.scan(), [])
            self.assertEqual([c.args for c in cmd.call_args_list], [
                (wlan.IP, "link", "set", wlan.IFACE, "up"),
                (wlan.IW, "dev", wlan.IFACE, "scan"),
                (wlan.IW, "dev", wlan.IFACE, "scan"),
                (wlan.IP, "link", "set", wlan.IFACE, "down")])
            self.assertEqual(sleep.call_args_list, [call(0.8), call(0.7)])

    def test_connected_scan_preserves_interface(self):
        with patch.object(wlan.NET.__class__, "exists", return_value=True), \
             patch.object(wlan, "link_up", return_value=True), \
             patch.object(wlan, "cmd", return_value="") as cmd:
            self.assertEqual(wlan.scan(), [])
            cmd.assert_called_once()
            self.assertEqual(cmd.call_args.args, (wlan.IW, "dev", wlan.IFACE, "scan"))

    def test_scan_failure_restores_original_link_state(self):
        with patch.object(wlan.NET.__class__, "exists", return_value=True), \
             patch.object(wlan, "link_up", return_value=False), \
             patch.object(wlan.time, "sleep"), \
             patch.object(wlan, "cmd", side_effect=["", RuntimeError("busy"),
                 subprocess.TimeoutExpired("iw", 8), RuntimeError("busy"), ""]) as cmd:
            with self.assertRaisesRegex(wlan.ScanError, "rejected by driver after retrying"):
                wlan.scan()
            self.assertEqual(cmd.call_args.args, (wlan.IP, "link", "set", wlan.IFACE, "down"))
