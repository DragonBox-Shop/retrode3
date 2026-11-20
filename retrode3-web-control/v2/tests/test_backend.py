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

    def test_missing_shared_cli_does_not_fall_back(self):
        original = MODULE.CLI_BIN
        try:
            MODULE.CLI_BIN = os.path.join(self.temp, "not-installed")
            self.assertEqual(MODULE.capability_probe()["systems"], [])
            self.assertIsNone(MODULE.reader_capability("snes"))
            with self.assertRaises(MODULE.ApiError) as err:
                MODULE.JobManager().submit({"system": "snes", "command": "probe"})
            self.assertEqual(err.exception.code, "unsupported")
        finally:
            MODULE.CLI_BIN = original

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

    def test_unregistered_core_is_never_invoked(self):
        with self.assertRaises(MODULE.ApiError) as err:
            MODULE.JobManager().submit({"system": "dangerous-helper", "command": "probe"})
        self.assertEqual(err.exception.status, 400)

    def test_size_validation(self):
        manager = MODULE.JobManager()
        for size in (True, 0, 131071, 4194305, 131073):
            with self.assertRaises(MODULE.ApiError):
                manager.submit({"system": "snes", "command": "read_rom", "size_bytes": size})

    def test_cli_registry_missing_and_untrusted_output(self):
        original = MODULE.CLI_BIN
        try:
            MODULE.CLI_BIN = os.path.join(self.temp, "missing-cli")
            inventory = MODULE.core_registry()
            self.assertFalse(inventory["available"])
            self.assertFalse(inventory["control_enabled"])
            bad = os.path.join(self.temp, "bad-cli")
            with open(bad, "w") as stream:
                stream.write("#!/bin/sh\necho '{\"event\":\"cores\",\"cores\":[]}'\n")
            os.chmod(bad, 0o755)
            MODULE.CLI_BIN = bad
            with self.assertRaises(MODULE.ApiError) as failure:
                MODULE.core_registry()
            self.assertEqual(failure.exception.code, "core_protocol_invalid")
        finally:
            MODULE.CLI_BIN = original

    def test_core_inventory_toggle_and_metadata_only_reader(self):
        old = (MODULE.CLI_BIN, MODULE.CORECTL_BIN,
               MODULE.CORECTL_SUDO, MODULE.CORE_CONTROL_ENABLED)
        state = os.path.join(self.temp, "state")
        cli = os.path.join(self.temp, "mock-cli")
        helper = os.path.join(self.temp, "mock-helper")
        with open(state, "w") as stream:
            stream.write("off")
        with open(cli, "w") as stream:
            stream.write("#!/usr/bin/env python3\n")
            stream.write("import json, sys\n")
            stream.write("assert sys.argv[1:] == ['--list-cores', '--protocol', 'ndjson-v1']\n")
            stream.write("on = open(%r).read() == 'on'\n" % state)
            stream.write("print(json.dumps({'protocol':'retrode3-ndjson','version':1,"
                         "'event':'cores','discovery_abi':1,'cores':["
                         "{'id':'md','name':'Mega Drive','version':'0.1',"
                         "'slot':'md','installed':True,'enabled':on,"
                         "'status':'discovered' if on else 'disabled',"
                         "'usable':False,'actions':[]}]}))\n")
        with open(helper, "w") as stream:
            stream.write("#!/usr/bin/env python3\nimport sys\n")
            stream.write("assert len(sys.argv) == 3 and sys.argv[2] == 'md'\n")
            stream.write("assert sys.argv[1] in ('enable','disable')\n")
            stream.write("open(%r,'w').write('on' if sys.argv[1] == 'enable' else 'off')\n" % state)
        os.chmod(cli, 0o755)
        os.chmod(helper, 0o755)
        try:
            MODULE.CLI_BIN = cli
            MODULE.CORECTL_BIN = helper
            MODULE.CORECTL_SUDO = False
            MODULE.CORE_CONTROL_ENABLED = True
            self.assertTrue(MODULE.core_registry()["control_enabled"])
            self.assertFalse(MODULE.core_registry()["cores"][0]["enabled"])
            for invalid in ({"id":"../md","enabled":True},
                            {"id":"md","enabled":"true"}):
                with self.assertRaises(MODULE.ApiError):
                    MODULE.toggle_core(invalid)
            with self.assertRaises(MODULE.ApiError) as missing:
                MODULE.toggle_core({"id":"snes","enabled":True})
            self.assertEqual(missing.exception.status, 404)
            self.assertTrue(MODULE.toggle_core({"id":"md","enabled":True})["core"]["enabled"])
            self.assertFalse(MODULE.reader_capability("md", MODULE.core_registry())["available"])
            self.assertEqual(MODULE.toggle_core({"id":"md","enabled":False})["core"]["status"], "disabled")
            with MODULE.MANAGER.lock:
                MODULE.MANAGER.active = object()
            try:
                with self.assertRaises(MODULE.ApiError) as busy:
                    MODULE.toggle_core({"id":"md","enabled":True})
                self.assertEqual(busy.exception.status, 409)
            finally:
                with MODULE.MANAGER.lock:
                    MODULE.MANAGER.active = None
        finally:
            (MODULE.CLI_BIN, MODULE.CORECTL_BIN,
             MODULE.CORECTL_SUDO, MODULE.CORE_CONTROL_ENABLED) = old


    def test_ready_shared_cli_is_exposed_and_serves_probe_and_read(self):
        """Mock the central CLI transport, not the cartridge bus."""
        import time
        old_cli = MODULE.CLI_BIN
        cli = os.path.join(self.temp, "shared-cli-mock")
        with open(cli, "w") as stream:
            stream.write("#!/usr/bin/env python3\n")
            stream.write("from __future__ import print_function\n")
            stream.write("import json, sys\n")
            stream.write("if '--list-cores' in sys.argv:\n")
            stream.write("  print(json.dumps({'protocol':'retrode3-ndjson','version':1,"
                         "'event':'cores','discovery_abi':1,'cores':["
                         "{'id':id,'name':name,'version':'0.1.0-stage1',"
                         "'slot':id,'installed':True,'enabled':True,"
                         "'status':'ready','usable':True,"
                         "'actions':['probe','read_rom']} for id,name in "
                         "[('snes','Super Nintendo'),('md','Mega Drive'),('nes','Nintendo Entertainment System')]]}))\n")
            stream.write("  sys.exit(0)\n")
            stream.write("assert sys.argv[1:] == ['--protocol', 'ndjson-v1', '--interactive']\n")
            stream.write("print(json.dumps({'protocol':'retrode3-ndjson','version':1,"
                         "'event':'ready','system':'multi'}),flush=True)\n")
            stream.write("for line in sys.stdin:\n")
            stream.write("  cmd=json.loads(line)\n")
            stream.write("  assert cmd['core'] in ('snes','md','nes')\n")
            stream.write("  assert cmd['command'] in ('probe','read_rom')\n")
            stream.write("  rid=cmd['request_id']\n")
            stream.write("  event={'protocol':'retrode3-ndjson','version':1,"
                         "'request_id':rid,'system':cmd['core']}\n")
            stream.write("  if cmd['command']=='probe':\n")
            stream.write("    event.update({'event':'probe_result','title':'TEST CART',"
                         "'mapping':'hi','size_bytes':524288})\n")
            stream.write("    print(json.dumps(event),flush=True)\n")
            stream.write("  else:\n")
            stream.write("    assert 'mapping' not in cmd and 'size_bytes' not in cmd\n")
            stream.write("    with open(cmd['output'],'wb') as fh: fh.write(b'rom data')\n")
            stream.write("    event.update({'event':'progress','percent':100,"
                         "'bytes_done':8,'bytes_total':8})\n")
            stream.write("    print(json.dumps(event),flush=True)\n")
            stream.write("    event.update({'event':'result','ok':True,"
                         "'output':cmd['output'],'bytes_written':8})\n")
            stream.write("    print(json.dumps(event),flush=True)\n")
        os.chmod(cli, 0o755)
        try:
            MODULE.CLI_BIN = cli
            result = MODULE.capability_probe()
            by_id = dict((v["id"], v) for v in result["systems"])
            self.assertTrue(by_id["md"]["available"])
            self.assertTrue(by_id["snes"]["available"])
            self.assertTrue(by_id["nes"]["available"])
            self.assertEqual(by_id["snes"]["transport"], "cli")
            self.assertEqual(by_id["md"]["transport"], "cli")
            self.assertFalse(by_id["md"]["capabilities"]["size_override"])
            self.assertEqual(by_id["md"]["capabilities"]["mappings"], [])
            manager = MODULE.JobManager()
            for system in ("snes", "nes"):
                job_info = manager.submit({"system":system,"command":"probe"})
                job = manager.get(job_info["id"])
                deadline = time.time() + 5
                while job.snapshot()["status"] not in ("done","failed","cancelled") and time.time() < deadline:
                    time.sleep(.02)
                self.assertEqual(job.snapshot()["status"], "done", job.snapshot())
                self.assertEqual(job.snapshot()["result"]["title"], "TEST CART")
                deadline = time.time() + 5
                while manager.active is not None and time.time() < deadline:
                    time.sleep(.02)
            info = manager.submit({"system":"md","command":"read_rom","filename":"mock"})
            job = manager.get(info["id"])
            deadline = time.time() + 5
            while job.snapshot()["status"] not in ("done","failed","cancelled") and time.time() < deadline:
                time.sleep(.02)
            snap = job.snapshot()
            self.assertEqual(snap["status"], "done", snap)
            self.assertEqual(snap["progress"]["percent"], 100)
            self.assertTrue(os.path.isfile(snap["output"]))
            with open(snap["output"], "rb") as fh:
                self.assertEqual(fh.read(), b"rom data")
            with self.assertRaises(MODULE.ApiError):
                manager.submit({"system":"md","command":"read_rom","size_bytes":131072})
        finally:
            MODULE.CLI_BIN = old_cli


    def test_dynamic_cli_reader_is_not_limited_to_known_console_ids(self):
        custom = {"id": "supergb-adapter", "name": "Super Game Boy",
                  "version": "1.0", "slot": "snes", "installed": True,
                  "enabled": True, "status": "ready", "usable": True,
                  "actions": ["probe", "read_rom"]}
        result = MODULE.reader_capability(custom["id"], {
            "available": True, "cores": [custom]})
        self.assertTrue(result["available"])
        self.assertEqual(result["id"], "supergb-adapter")
        self.assertEqual(result["slot"], "snes")
        self.assertEqual(result["transport"], "cli")
        self.assertEqual(result["extension"], "bin")
        self.assertEqual(result["folder"], "SUPERGB-ADAPTER")
        self.assertEqual(result["capabilities"]["commands"], ["probe", "read_rom"])
        self.assertIsNone(MODULE.reader_capability("snes", {
            "available": True, "cores": [custom]}))

    def test_autodetect_matches_core_slot_not_core_id(self):
        old_snapshot, old_capabilities = MODULE.slot_snapshot, MODULE.capability_probe
        slot = {"id": "md", "name": "Mega Drive", "status": "occupied"}
        class FakeJob(object):
            def __init__(self):
                self.status = "running"
            def snapshot(self):
                return {"status": self.status, "result": {
                    "event": "probe_result", "system": "sms-adapter",
                    "title": "SONIC", "mapping": "linear", "size_bytes": 262144}}
            def cancel(self):
                self.status = "cancelled"
        class FakeManager(object):
            def __init__(self):
                self.calls = []
                self.job = FakeJob()
                self.lock = MODULE.threading.RLock()
                self.active = None
            def submit(self, data, automatic=False):
                self.calls.append((data, automatic))
                return {"id": "1" * 32}
            def get(self, key):
                return self.job
        manager = FakeManager()
        watcher = MODULE.AutomaticDetection(manager)
        try:
            MODULE.slot_snapshot = lambda: {"slots": [dict(slot)]}
            MODULE.capability_probe = lambda: {"systems": [{
                "id": "sms-adapter", "name": "Master System",
                "slot": "md", "available": True,
                "capabilities": {"commands": ["probe", "read_rom"]}}]}
            watcher.tick(now=1.0)
            watcher.tick(now=1.4)
            self.assertEqual(manager.calls[0], (
                {"system": "sms-adapter", "command": "probe"}, True))
            manager.job.status = "done"
            watcher.tick(now=1.5)
            self.assertEqual(
                watcher.snapshot()["slots"][0]["detection"]["result"]["title"], "SONIC")
            slot["status"] = "empty"
            watcher._event_changed(
                b"change@/devices/virtual/slot-md\x00SLOT=slot-md\x00SENSE=empty\x00")
            self.assertIsNone(watcher.snapshot()["slots"][0]["detection"]["result"])
            watcher.tick(now=1.6)
            self.assertEqual(watcher.snapshot()["slots"][0]["detection"]["state"], "idle")
            slot["status"] = "occupied"
            watcher.tick(now=1.7)
            self.assertEqual(watcher.snapshot()["slots"][0]["detection"]["state"], "pending")
        finally:
            MODULE.slot_snapshot = old_snapshot
            MODULE.capability_probe = old_capabilities

    def test_autodetect_deduplicates_events_and_waits_passively_when_busy(self):
        old_snapshot, old_capabilities = MODULE.slot_snapshot, MODULE.capability_probe
        slot = {"id": "nes", "name": "Nintendo", "status": "occupied"}
        discovery_calls = [0]

        class FakeJob(object):
            def __init__(self):
                self.status = "running"
                self.cancel_calls = 0
            def snapshot(self):
                return {"status": self.status, "result": {
                    "event": "probe_result", "system": "nes", "title": "Excitebike"}}
            def cancel(self):
                self.cancel_calls += 1
                self.status = "cancelled"

        class FakeManager(object):
            def __init__(self):
                self.lock = MODULE.threading.RLock()
                self.active = None
                self.job = FakeJob()
                self.calls = []
            def get(self, key):
                return self.job
            def submit(self, data, automatic=False):
                self.calls.append((data, automatic))
                return {"id": "2" * 32}

        manager = FakeManager()
        watcher = MODULE.AutomaticDetection(manager)

        def capabilities():
            discovery_calls[0] += 1
            return {"systems": [{"id": "nes", "slot": "nes",
                      "available": True, "capabilities": {"commands": ["probe"]}}]}

        active_event = b"change@/devices/virtual/slot-nes\x00SLOT=slot-nes\x00SENSE=active\x00"
        empty_event = b"change@/devices/virtual/slot-nes\x00SLOT=slot-nes\x00SENSE=empty\x00"
        try:
            MODULE.slot_snapshot = lambda: {"slots": [dict(slot)]}
            MODULE.capability_probe = capabilities
            watcher.tick(now=10.0)
            watcher.tick(now=10.4)
            self.assertEqual(len(manager.calls), 1)
            watcher._event_changed(active_event)
            watcher.tick(now=10.5)
            self.assertEqual(len(manager.calls), 1)
            self.assertEqual(manager.job.cancel_calls, 0)
            manager.job.status = "done"
            watcher.tick(now=10.6)
            self.assertEqual(watcher.snapshot()["slots"][0]["detection"]["result"]["title"],
                             "Excitebike")
            watcher._event_changed(active_event)
            watcher.tick(now=11.0)
            self.assertEqual(len(manager.calls), 1)
            self.assertEqual(discovery_calls[0], 1)

            # Stale empty notification must not discard an occupied slot.
            watcher._event_changed(empty_event)
            self.assertEqual(watcher.snapshot()["slots"][0]["detection"]["state"],
                             "detected")
            slot["status"] = "empty"
            watcher._event_changed(empty_event)
            watcher.tick(now=11.1)
            self.assertEqual(watcher.snapshot()["slots"][0]["detection"]["state"], "idle")
            slot["status"] = "occupied"
            watcher._event_changed(active_event)
            watcher.tick(now=11.2)
            manager.active = object()  # A manual MegaDrive dump holds the bus.
            watcher.tick(now=11.6)
            self.assertEqual(len(manager.calls), 1)
            self.assertEqual(discovery_calls[0], 1)
            manager.active = None
            watcher.tick(now=11.7)
            self.assertEqual(len(manager.calls), 2)
            self.assertEqual(discovery_calls[0], 2)
        finally:
            MODULE.slot_snapshot = old_snapshot
            MODULE.capability_probe = old_capabilities

    def test_ambiguous_slot_does_not_probe_random_adapter(self):
        old_snapshot, old_capabilities = MODULE.slot_snapshot, MODULE.capability_probe
        class FakeManager(object):
            def __init__(self):
                self.lock = MODULE.threading.RLock()
                self.active = None
            def submit(self, *args, **kwargs):
                raise AssertionError("Ambiguous slot must not be probed")
        watcher = MODULE.AutomaticDetection(FakeManager())
        try:
            MODULE.slot_snapshot = lambda: {"slots": [{
                "id": "snes", "name": "Super Nintendo", "status": "occupied"}]}
            MODULE.capability_probe = lambda: {"systems": [
                {"id": x, "slot": "snes", "available": True,
                 "capabilities": {"commands": ["probe"]}}
                for x in ("snes", "sfc-adapter")]}
            watcher.tick(now=5.0)
            watcher.tick(now=5.4)
            self.assertEqual(watcher.snapshot()["slots"][0]["detection"]["state"],
                             "choose_reader")
        finally:
            MODULE.slot_snapshot = old_snapshot
            MODULE.capability_probe = old_capabilities

if __name__ == "__main__":
    unittest.main()
