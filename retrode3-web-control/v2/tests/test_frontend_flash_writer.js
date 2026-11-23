"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

(async function () {
  const source = fs.readFileSync(path.join(__dirname, "..", "web", "assets", "app.js"), "utf8");
  const start = source.indexOf("  function flashReader() {");
  const end = source.indexOf("  function startJob(command) {", start);
  assert(start > 0 && end > start, "Flash writer UI functions missing");

  const known = {id: "md", slot: "md", folder: "MD", name: "Mega Drive",
    capabilities: {commands: ["probe_flash", "write_flash", "verify_flash"]}};
  const elements = {
    "writer-system": {value: "md"},
    "writer-file": {value: "MD/game.md"},
    "writer-slot-status": {textContent: ""},
    "writer-flash-status": {textContent: ""},
    "writer-detect": {disabled: false},
    "writer-write": {disabled: false},
    "writer-verify": {disabled: false},
    "job-panel": {hidden: true},
    "writer-progress-anchor": {appendChild() {}},
    "cancel": {disabled: true}
  };
  let submitted = null, promptCount = 0;
  const ctx = {
    $: id => {assert(elements[id], "unknown DOM element: " + id); return elements[id];},
    readerById: id => id === "md" ? known : null,
    readers: () => [known], selectedReader: "md",
    slotData: {slots: [{id: "md", status: "occupied"}]},
    writerIdentified: {reader: "md", slot: "md", data: {
      manufacturer_id: 127, device_id: 8953,
      capacity_bytes: 4194304, sector_count: 71
    }},
    activeJob: null,
    t: key => key, humanSize: n => n + " bytes",
    text: (el, val) => {el.textContent = String(val);},
    confirm: () => {promptCount++; return true;},
    api: (url, data) => {
      assert.strictEqual(url, "/api/jobs");
      submitted = data;
      return Promise.resolve({id: "testjob", status: "queued"});
    },
    notify: () => {throw new Error("unexpected invalid action");},
    fail: e => {throw e;},
    renderJob: () => {}, schedulePoll: () => {},
    console
  };
  vm.createContext(ctx);
  vm.runInContext(source.slice(start, end), ctx);
  ctx.renderWriterState();
  assert.strictEqual(elements["writer-write"].disabled, false);
  assert.strictEqual(elements["writer-verify"].disabled, false);
  ctx.startFlashJob("write_flash");
  await Promise.resolve();
  assert.deepStrictEqual(JSON.parse(JSON.stringify(submitted)),
    {system: "md", command: "write_flash",
     source: "MD/game.md", confirm_erase: true});
  assert.strictEqual(promptCount, 1);
  assert.strictEqual(elements["job-panel"].hidden, false);
  ctx.activeJob = null;
  submitted = null;
  ctx.startFlashJob("verify_flash");
  await Promise.resolve();
  assert.deepStrictEqual(JSON.parse(JSON.stringify(submitted)),
    {system: "md", command: "verify_flash", source: "MD/game.md"});
  assert.strictEqual(promptCount, 1, "verify must never ask to erase");

  ctx.activeJob = null;
  submitted = null;
  ctx.writerIdentified = null;
  ctx.renderWriterState();
  assert.strictEqual(elements["writer-write"].disabled, true);
  assert.strictEqual(elements["writer-verify"].disabled, true);
  ctx.startFlashJob("probe_flash");
  await Promise.resolve();
  assert.deepStrictEqual(JSON.parse(JSON.stringify(submitted)),
    {system: "md", command: "probe_flash"});

  ctx.activeJob = null;
  ctx.slotData.slots[0].status = "empty";
  ctx.writerIdentified = {reader: "md", slot: "md", data: {}};
  ctx.renderWriterState();
  assert.strictEqual(ctx.writerIdentified, null,
    "removal must invalidate a previous Flash identification");
  assert.strictEqual(elements["writer-detect"].disabled, true);
  console.log("Flash tab command wiring and write/verify guard passed");
})().catch(err => { console.error(err); process.exitCode = 1; });
