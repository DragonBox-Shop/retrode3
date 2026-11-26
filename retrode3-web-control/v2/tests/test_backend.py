#!/usr/bin/env python3
"""Safe mocked tests; no cartridge or WLAN operation."""
from __future__ import print_function
import importlib.util
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location("retrode3_web_v2", os.path.join(HERE, "..", "backend", "service.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

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
            for slot, voltage in (("snes", "3300mV"), ("md", "5000mV"),
                                  ("nes", "bogus")):
                with open(os.path.join(MODULE.SENSE_ROOT, "slot-" + slot, "vcc"),
                          "w") as handle:
                    handle.write(voltage + "\n")
            result = MODULE.slot_snapshot()
            by_id = dict((slot["id"], slot) for slot in result["slots"])
            self.assertEqual(by_id["snes"]["voltage_mv"], 3300)
            self.assertEqual(by_id["md"]["voltage_mv"], 5000)
            self.assertIsNone(by_id["nes"]["voltage_mv"])
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

    def test_legacy_read_fields_and_missing_v3_selection_are_rejected(self):
        manager = MODULE.JobManager()
        base = {"system": "snes", "command": "read_rom",
                "filename": "test"}
        variants = [
            dict(base), dict(base, mapping="hi"),
            dict(base, size_bytes=131072),
            dict(base, candidate_id="old-nes-candidate"),
            dict(base, layout_id="old-layout"),
            dict(base, mapper=0, prg_kib=32),
            dict(base, selection={"version": 1, "mode": "auto",
                                  "schema_id": "snes-standard-v1"},
                 mapping="hi"),
        ]
        for payload in variants:
            with self.assertRaises(MODULE.ApiError) as error:
                manager.submit(payload)
            self.assertEqual(error.exception.status, 400)

    def test_generic_v3_selection_structure_and_no_mixed_fields(self):
        good = {"version": 1, "mode": "override",
                "schema_id": "some-adapter-v1",
                "parameters": {"banks": 2, "safe": True, "mode": "linear"}}
        self.assertEqual(MODULE.validate_generic_selection(good, "read_rom"), good)
        self.assertEqual(MODULE.validate_generic_selection({
            "version": 1, "mode": "candidate",
            "schema_id": "some-adapter-v1", "candidate_id": "game-42"
        }, "read_rom")["candidate_id"], "game-42")
        invalid = [
            dict(good, version=2),
            dict(good, mode="auto"),
            dict(good, candidate_id="game-42"),
            dict(good, parameters={"banks": 2, "voltage": [3.3]}),
            dict(good, parameters={"banks": True, "safe": object()}),
            dict(good, parameters={"banks": -1}),
            dict(good, parameters={"banks": "x" * 128}),
            {"version": 1, "mode": "candidate",
             "schema_id": "some-adapter-v1", "candidate_id": "../wrong"},
            {"version": 1, "mode": "layout", "schema_id": "some-adapter-v1"},
            {"version": 1, "mode": "override",
             "schema_id": "some-adapter-v1", "parameters": {}}
        ]
        for choice in invalid:
            with self.assertRaises(MODULE.ApiError):
                MODULE.validate_generic_selection(choice, "read_rom")
        with self.assertRaises(MODULE.ApiError):
            MODULE.validate_generic_selection(good, "probe")

    def test_generic_v3_selection_forwards_to_job_on_any_core(self):
        old_reader = MODULE.reader_capability
        old_options = MODULE.native_reader_options
        old_job = MODULE.Job
        received = []
        schema = {"schema_version": 1, "schema_id": "adapter-layout-v1",
                  "selection_modes": ["auto", "candidate", "layout", "override"],
                  "fields": [{"id": "bank_count", "type": "integer"}]}
        choice = {"version": 1, "mode": "override",
                  "schema_id": "adapter-layout-v1",
                  "parameters": {"bank_count": 4, "safe": True}}
        class FakeJob(object):
            def __init__(self, *args, **kwargs):
                self.id = "a" * 32
                self.created = 0
                self.selection = kwargs.get("selection")
                received.append(self.selection)
            def snapshot(self):
                return {"id": self.id, "status": "done"}
            def run(self):
                return
        try:
            MODULE.reader_capability = lambda core_id: {
                "id": core_id, "slot": "snes", "folder": "TEST",
                "extension": "bin", "available": True,
                "capabilities": {"commands": ["probe", "read_rom"],
                                 "mappings": [], "size_override": False}}
            MODULE.native_reader_options = lambda core_id: {
                "system": core_id, "slot": "snes", "selection_schema": schema}
            MODULE.Job = FakeJob
            payload = {"system": "new-console-adapter",
                       "command": "read_rom", "filename": "safe-dump",
                       "selection": choice}
            self.assertEqual(MODULE.JobManager().submit(payload)["status"], "done")
            self.assertEqual(received, [choice])
            for invalid in (
                    dict(payload, mapping="lo"),
                    dict(payload, mapper=0),
                    dict(payload, unexpected=True),
                    dict(payload, command="probe"),
                    dict(payload, selection=dict(choice, schema_id="stale"))):
                with self.assertRaises(MODULE.ApiError):
                    MODULE.JobManager().submit(invalid)
        finally:
            MODULE.reader_capability = old_reader
            MODULE.native_reader_options = old_options
            MODULE.Job = old_job

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


    def test_shared_cli_v3_probe_and_read_all_original_cores(self):
        """Real Python job transport against a harmless CLI v3 mock."""
        import time
        old_cli = MODULE.CLI_BIN
        cli = os.path.join(self.temp, "shared-cli-v3-mock")
        script = """#!/usr/bin/env python3
from __future__ import print_function
import json, sys
cores = [('snes','Super Nintendo'),('md','Mega Drive'),('nes','Nintendo')]
if '--list-cores' in sys.argv:
    print(json.dumps({'protocol':'retrode3-ndjson','version':1,
      'event':'cores','discovery_abi':1,
      'cores':[{'id':id,'name':name,'version':'3.0','slot':id,
        'installed':True,'enabled':True,'status':'ready','usable':True,
        'actions':['probe','read_rom']} for id,name in cores]}))
    sys.exit(0)
assert sys.argv[1:] == ['--protocol', 'ndjson-v1', '--interactive']
print(json.dumps({'protocol':'retrode3-ndjson','version':1,
    'event':'ready','system':'multi'}),flush=True)
for line in sys.stdin:
    cmd = json.loads(line)
    assert cmd['core'] in ('snes','md','nes')
    rid = cmd['request_id']
    event = {'protocol':'retrode3-ndjson','version':1,
             'request_id':rid,'system':cmd['core'],'slot':cmd['core']}
    schema = {'schema_version':1,'schema_id':cmd['core']+'-v3-test',
              'selection_modes':['auto','candidate','layout','override'],
              'fields':[{'id':'banks','type':'integer','required':True,
                         'minimum':1,'maximum':8}]}
    if cmd['command'] == 'get_capabilities':
        event.update({'event':'capabilities','selection_schema':schema})
        print(json.dumps(event),flush=True)
    elif cmd['command'] == 'probe':
        assert set(cmd) == set(['command','core','request_id'])
        event.update({'event':'probe_result','title':'TEST CART',
                      'identification_status':'unknown','ambiguity':'none',
                      'selection_schema_id':schema['schema_id'],
                      'selection_required':False,'candidates':[],
                      'read_layouts':[{'id':'safe','read_supported':True}]})
        print(json.dumps(event),flush=True)
    elif cmd['command'] == 'read_rom':
        assert set(cmd) == set(['command','core','request_id','output','selection'])
        assert cmd['selection'] == {'version':1,'mode':'auto',
                                    'schema_id':schema['schema_id']}
        with open(cmd['output'],'wb') as output:
            output.write(b'rom data')
        event.update({'event':'progress','percent':100,
                      'bytes_done':8,'bytes_total':8})
        print(json.dumps(event),flush=True)
        event.update({'event':'result','ok':True,'output':cmd['output'],
                      'bytes_written':8,'verification':{
                        'status':'not_found','verified':False}})
        print(json.dumps(event),flush=True)
    else:
        raise AssertionError('Unexpected CLI command')
"""
        with open(cli, "w") as stream:
            stream.write(script)
        os.chmod(cli, 0o755)
        try:
            MODULE.CLI_BIN = cli
            registry = MODULE.capability_probe()
            by_id = dict((v["id"], v) for v in registry["systems"])
            self.assertEqual(sorted(by_id), ["md", "nes", "snes"])
            for system in ("snes", "md", "nes"):
                self.assertTrue(by_id[system]["available"])
                self.assertEqual(by_id[system]["slot"], system)
                options = MODULE.native_reader_options(system)
                self.assertEqual(options["selection_schema"]["schema_id"],
                                 system + "-v3-test")
                manager = MODULE.JobManager()
                for command in ("probe", "read_rom"):
                    payload = {"system": system, "command": command}
                    if command == "read_rom":
                        payload.update({"filename": "test-" + system,
                            "selection": {"version": 1, "mode": "auto",
                                          "schema_id": system + "-v3-test"}})
                    info = manager.submit(payload)
                    job = manager.get(info["id"])
                    deadline = time.time() + 5
                    while (job.snapshot()["status"] not in
                           ("done", "failed", "cancelled") and
                           time.time() < deadline):
                        time.sleep(.02)
                    self.assertEqual(job.snapshot()["status"], "done", job.snapshot())
                    if command == "read_rom":
                        with open(job.snapshot()["output"], "rb") as output:
                            self.assertEqual(output.read(), b"rom data")
                    while manager.active is not None and time.time() < deadline:
                        time.sleep(.02)
                    self.assertIsNone(manager.active)
        finally:
            MODULE.CLI_BIN = old_cli

    def test_non_v3_capability_result_is_rejected(self):
        old_reader = MODULE.reader_capability
        old_popen = MODULE.subprocess.Popen
        class FakeProcess(object):
            returncode = 0
            def communicate(self, data, timeout=None):
                return (('{"protocol":"retrode3-ndjson","version":1,'
                         '"event":"capabilities","request_id":"web-options",'
                         '"system":"future-adapter","slot":"snes",'
                         '"manual_layout":true,"supported_mappers":[]}').encode("utf-8"), b"")
        try:
            MODULE.reader_capability = lambda core_id: {
                "id": core_id, "slot": "snes", "available": True}
            MODULE.subprocess.Popen = lambda *args, **kwargs: FakeProcess()
            with self.assertRaises(MODULE.ApiError) as error:
                MODULE.native_reader_options("future-adapter")
            self.assertEqual(error.exception.code, "selection_schema_unavailable")
        finally:
            MODULE.reader_capability = old_reader
            MODULE.subprocess.Popen = old_popen

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


    def test_rom_storage_uses_console_not_adapter_route(self):
        for core_id, slot, expected_folder, expected_extension in (
                ("gba-md", "md", "GBA", "gba"),
                ("gba-snes", "snes", "GBA", "gba"),
                ("md", "md", "MD", "md"),
                ("sms-md", "md", "SMS", "bin"),
                ("supergb-adapter", "snes", "SUPERGB-ADAPTER", "bin")):
            core = {"id": core_id, "name": "Test core",
                    "version": "1.0", "slot": slot, "installed": True,
                    "enabled": True, "status": "ready", "usable": True,
                    "actions": ["probe", "read_rom"]}
            result = MODULE.reader_capability(core_id, {
                "available": True, "cores": [core]})
            self.assertEqual(result["folder"], expected_folder)
            self.assertEqual(result["extension"], expected_extension)
            self.assertEqual(result["id"], core_id)
            self.assertEqual(result["slot"], slot)

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
                    "event": "probe_result", "system": "nes", "title": "Dr. Mario",
                    "mapping": "mmc1", "identification_status": "unique",
                    "selection_required": False,
                    "candidates": [{"id":"mmc1-0007","title":"Dr. Mario",
                                    "layout_id":"m1s5-32-32","mapper":1,
                                    "submapper":5,"prg_kib":32,"chr_kib":32,
                                    "read_supported":True}],
                    "read_layouts":[{"id":"m1s5-32-32","mapper":1,"submapper":5,
                                     "prg_kib":32,"chr_kib":32,"read_supported":True}]}}
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
                             "Dr. Mario")
            detection = watcher.snapshot()["slots"][0]["detection"]["result"]
            self.assertEqual(detection["candidates"][0]["mapper"], 1)
            self.assertEqual(detection["read_layouts"][0]["id"], "m1s5-32-32")
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

    def test_registry_change_reprobes_all_occupied_slots_without_reinsertion(self):
        old = (MODULE.CORES_ENABLED_DIR, MODULE.slot_snapshot,
               MODULE.capability_probe)
        directory = os.path.join(self.temp, "enabled")
        os.mkdir(directory)
        md_link = os.path.join(directory, "md.so")
        snes_link = os.path.join(directory, "snes.so")
        sms_link = os.path.join(directory, "sms-md.so")
        os.symlink("/unused/md.so", md_link)
        os.symlink("/unused/snes.so", snes_link)

        class FakeJob(object):
            def __init__(self, result):
                self.result = result
            def snapshot(self):
                return {"status": "done", "result": self.result}

        class FakeManager(object):
            def __init__(self):
                self.lock = MODULE.threading.RLock()
                self.active = None
                self.calls = []
                self.jobs = {}
            def add(self, slot, result):
                self.calls.append(slot)
                key = str(len(self.calls))
                self.jobs[key] = FakeJob(result)
                return {"id": key}
            def submit(self, data, automatic=False):
                return self.add(data["system"], {
                    "event": "probe_result", "system": data["system"],
                    "title": data["system"]})
            def submit_slot_probe(self, slot):
                return self.add(slot, {
                    "event": "slot_probe_result", "slot": slot,
                    "detection": "detected", "core": "sms-md",
                    "probe_result": {"system": "sms-md", "slot": slot,
                                     "title": "SONIC"}})
            def get(self, key):
                return self.jobs[key]

        def capabilities():
            return {"systems": [
                {"id": core, "slot": "md" if core == "sms-md" else core,
                 "available": True, "capabilities": {"commands": ["probe"]}}
                for core in ("md", "snes", "sms-md")
                if os.path.lexists(os.path.join(directory, core + ".so"))]}

        try:
            MODULE.CORES_ENABLED_DIR = directory
            MODULE.slot_snapshot = lambda: {"slots": [
                {"id": slot, "status": status}
                for slot, status in (("md", "occupied"), ("snes", "occupied"),
                                     ("nes", "empty"))]}
            MODULE.capability_probe = capabilities
            manager = FakeManager()
            watcher = MODULE.AutomaticDetection(manager)
            watcher.tick(now=1.0)
            watcher.tick(now=1.4)
            watcher.tick(now=1.5)
            self.assertEqual(manager.calls, ["md", "snes"])
            self.assertEqual(watcher.snapshot()["registry_revision"], 0)

            # Shell corectl changes the links without an API request or uevent.
            os.symlink("/unused/sms-md.so", sms_link)
            os.utime(directory, (100, 100))
            manager.active = object()
            watcher.tick(now=2.0)
            self.assertEqual(watcher.snapshot()["registry_revision"], 1)
            self.assertEqual([s["detection"]["state"] for s in
                              watcher.snapshot()["slots"]],
                             ["pending", "pending", "idle"])
            watcher.tick(now=2.4)
            self.assertEqual(manager.calls, ["md", "snes"])
            manager.active = None
            watcher.tick(now=2.5)
            watcher.tick(now=2.6)
            self.assertEqual(manager.calls, ["md", "snes", "md", "snes"])
            self.assertEqual(watcher.snapshot()["slots"][0]["detection"]["core_id"],
                             "sms-md")

            # API refresh and the next worker tick must not invalidate twice.
            os.unlink(sms_link)
            os.utime(directory, (200, 200))
            watcher.refresh_registry()
            watcher.tick(now=3.0)
            watcher.tick(now=3.4)
            watcher.tick(now=3.5)
            self.assertEqual(watcher.snapshot()["registry_revision"], 2)
            self.assertEqual(manager.calls,
                             ["md", "snes", "md", "snes", "md", "snes"])
            self.assertEqual(watcher.snapshot()["slots"][0]["detection"]["core_id"],
                             "md")
            watcher.tick(now=4.0)
            self.assertEqual(len(manager.calls), 6)
        finally:
            (MODULE.CORES_ENABLED_DIR, MODULE.slot_snapshot,
             MODULE.capability_probe) = old

    def test_multi_core_slot_uses_cli_slot_probe_and_resolves_core(self):
        old_snapshot, old_capabilities = MODULE.slot_snapshot, MODULE.capability_probe
        class FakeJob(object):
            def snapshot(self):
                return {"status": "done", "result": {
                    "event": "slot_probe_result", "slot": "snes",
                    "detection": "detected", "core": "sfc-adapter",
                    "voltage_status": "manual_required",
                    "probe_result": {"event": "probe_result", "slot": "snes",
                                     "system": "sfc-adapter", "title": "TEST CART",
                                     "read_voltage_mv": 5000}}}
        class FakeManager(object):
            def __init__(self):
                self.lock = MODULE.threading.RLock()
                self.active = None
                self.calls = []
            def submit(self, *args, **kwargs):
                raise AssertionError("Multiple cores must use probe_slot")
            def submit_slot_probe(self, slot_id):
                self.calls.append(slot_id)
                return {"id": "slot-job"}
            def get(self, job_id):
                self.calls.append(job_id)
                return FakeJob()
        manager = FakeManager()
        watcher = MODULE.AutomaticDetection(manager)
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
                             "detecting")
            self.assertEqual(manager.calls, ["snes"])
            watcher.tick(now=5.5)
            result = watcher.snapshot()["slots"][0]["detection"]
            self.assertEqual(result["state"], "detected")
            self.assertEqual(result["core_id"], "sfc-adapter")
            self.assertEqual(result["result"]["title"], "TEST CART")
            self.assertEqual(result["result"]["voltage_status"], "manual_required")
            self.assertEqual(result["result"]["read_voltage_mv"], 5000)
        finally:
            MODULE.slot_snapshot = old_snapshot
            MODULE.capability_probe = old_capabilities

    def test_multi_core_no_match_shows_manual_choice(self):
        old_snapshot, old_capabilities = MODULE.slot_snapshot, MODULE.capability_probe
        class FakeJob(object):
            def snapshot(self):
                return {"status": "done", "result": {
                    "event": "slot_probe_result", "slot": "md",
                    "detection": "manual_required", "core": None,
                    "attempts": [{"core": "md", "outcome": "no_match"},
                                 {"core": "sms-md", "outcome": "no_match"}]}}
        class FakeManager(object):
            def __init__(self):
                self.lock = MODULE.threading.RLock()
                self.active = None
            def submit_slot_probe(self, slot_id):
                return {"id": "job"}
            def get(self, job_id):
                return FakeJob()
        watcher = MODULE.AutomaticDetection(FakeManager())
        try:
            MODULE.slot_snapshot = lambda: {"slots": [{
                "id": "md", "name": "Mega Drive", "status": "occupied"}]}
            MODULE.capability_probe = lambda: {"systems": [
                {"id": x, "slot": "md", "available": True,
                 "capabilities": {"commands": ["probe"]}}
                for x in ("md", "sms-md")]}
            watcher.tick(now=5.0)
            watcher.tick(now=5.4)
            watcher.tick(now=5.5)
            self.assertEqual(watcher.snapshot()["slots"][0]["detection"]["state"],
                             "choose_reader")
        finally:
            MODULE.slot_snapshot = old_snapshot
            MODULE.capability_probe = old_capabilities

    def test_sense_independent_probe_detects_and_rechecks_header(self):
        old_snapshot, old_capabilities = MODULE.slot_snapshot, MODULE.capability_probe
        class FakeJob(object):
            result = {"event": "slot_probe_result", "slot": "md",
                      "detection": "detected", "core": "adapter",
                      "probe_result": {"event": "probe_result", "slot": "md",
                                       "system": "adapter", "title": "TEST CART"}}
            def snapshot(self):
                return {"status": "done", "result": self.result}
        class FakeManager(object):
            def __init__(self):
                self.lock = MODULE.threading.RLock()
                self.active = None
                self.calls = []
                self.job = FakeJob()
            def submit_slot_probe(self, slot_id):
                self.calls.append(slot_id)
                return {"id": "job"}
            def get(self, job_id):
                return self.job
        manager = FakeManager()
        watcher = MODULE.AutomaticDetection(manager)
        try:
            MODULE.slot_snapshot = lambda: {"slots": [{
                "id": "md", "name": "Mega Drive", "status": "empty"}]}
            MODULE.capability_probe = lambda: {"systems": [{
                "id": "adapter", "slot": "md", "available": True,
                "probe_without_sense": True,
                "capabilities": {"commands": ["probe"]}}]}
            watcher.tick(now=1.0)
            watcher.tick(now=3.0)
            self.assertEqual(manager.calls, [])
            watcher.tick(now=4.0)
            watcher.tick(now=4.1)
            self.assertEqual(manager.calls, ["md"])
            slot = watcher.snapshot()["slots"][0]
            self.assertEqual(slot["status"], "occupied")
            self.assertEqual(slot["sense_status"], "empty")
            self.assertEqual(slot["detection"]["core_id"], "adapter")
            manager.job.result = {"event": "slot_probe_result", "slot": "md",
                                  "detection": "empty", "core": None}
            watcher.tick(now=8.0)
            self.assertEqual(manager.calls, ["md"])
            watcher.tick(now=9.2)
            watcher.tick(now=9.3)
            self.assertEqual(manager.calls, ["md", "md"])
            self.assertEqual(watcher.snapshot()["slots"][0]["status"], "empty")
        finally:
            MODULE.slot_snapshot = old_snapshot
            MODULE.capability_probe = old_capabilities

if __name__ == "__main__":
    unittest.main()
