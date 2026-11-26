/* Browser adapter -> shared CLI selection envelope, no system cases. */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const source = fs.readFileSync(path.join(__dirname, "..", "web", "assets", "app.js"), "utf8");
const start = source.indexOf("  function startJob(command) {");
const end = source.indexOf("  function renderJob(job) {", start);
assert(start > 0 && end > start, "job glue missing");
let payload = null, notices = [], created = false;
const selected = {version: 1, schema_id: "future-v1", mode: "candidate",
                  candidate_id: "region-eu"};
const elements = {filename: {value: "Custom filename"}, read: {disabled: false},
  probe: {disabled: false}, "job-panel": {hidden: true},
  cancel: {disabled: true}};
const ctx = {
  selectedReader: "future-core", activeJob: null,
  hardwareBusy: () => false,
  submitJob: (data) => {payload = data; created = true;},
  $: function (id) {return elements[id];},
  readerById: function (id) { return {id: id, slot: "md",
    capabilities: {commands: ["probe", "read_rom"]}}; },
  genericSchema: function () {return {schema_id: "future-v1"};},
  genericWidget: {allowed: function () {return true;},
    selection: function () {return Object.assign({}, selected);}},
  api: function (route, value) {
    assert.strictEqual(route, "/api/jobs");
    payload = value;
    return {then: function (cb) {cb({id: "test-job"}); return {catch: function () {}};}};
  },
  t: function (v) {return v;},
  notify: function (value) {notices.push(value);},
  renderCores: function () {}, renderJob: function () {},
  schedulePoll: function () {created = true;}
};
vm.createContext(ctx);
vm.runInContext(source.slice(start, end), ctx);
ctx.startJob("read_rom");
assert.deepStrictEqual(JSON.parse(JSON.stringify(payload)), {
  system: "future-core", command: "read_rom", filename: "Custom filename",
  selection: selected});
assert(!("mapping" in payload) && !("mapper" in payload) && !("size_bytes" in payload));
assert(created);

selected.mode = "override";
delete selected.candidate_id;
selected.parameters = {bank_count: 2, safe: true};
ctx.startJob("read_rom");
assert.deepStrictEqual(JSON.parse(JSON.stringify(payload.selection)), selected);
ctx.genericWidget.allowed = function () {return false;};
payload = null;
ctx.startJob("read_rom");
assert.strictEqual(payload, null, "Invalid selection must stop before HTTP call");
assert(notices.length > 0);
console.log("generic browser-to-job v3 payload regression passed");
