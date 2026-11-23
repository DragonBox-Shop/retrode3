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
    "writer-file": {files: [{name: "game.md", size: 1024}], value: "C:\\fakepath\\game.md"},
    "writer-upload-status": {textContent: ""},
    "writer-slot-status": {textContent: ""},
    "writer-flash-status": {textContent: ""},
    "writer-detect": {disabled: false},
    "writer-write": {disabled: false},
    "writer-verify": {disabled: false},
    "job-panel": {hidden: true},
    "writer-progress-anchor": {appendChild() {}},
    "cancel": {disabled: true}
  };
  let submitted = null;
  const ctx = {
    $: id => {assert(elements[id], "unknown DOM element: " + id); return elements[id];},
    readerById: id => id === "md" ? known : null,
    readers: () => [known], selectedReader: "md",
    slotData: {slots: [{id: "md", status: "occupied"}]},
    writerIdentified: {reader: "md", slot: "md", data: {
      manufacturer_id: 127, device_id: 8953,
      capacity_bytes: 4194304, sector_count: 71
    }},
    activeJob: null, csrf: "test-csrf", writerSourcePath: "MD/game.md",
    writerUploading: false, writerUploadSerial: 0,
    t: key => key, humanSize: n => n + " bytes",
    text: (el, val) => {el.textContent = String(val);},
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
    {system: "md", command: "write_flash", source: "MD/game.md"});
  assert.strictEqual(elements["job-panel"].hidden, false);
  ctx.activeJob = null;
  submitted = null;
  ctx.startFlashJob("verify_flash");
  await Promise.resolve();
  assert.deepStrictEqual(JSON.parse(JSON.stringify(submitted)),
    {system: "md", command: "verify_flash", source: "MD/game.md"});

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

  // Flash probe availability must not be coupled to a flaky passive
  // MD sense switch. The CLI and kernel decide whether a cart exists.
  ctx.activeJob = null;
  ctx.slotData.slots[0].status = "empty";
  ctx.renderWriterState();
  assert.strictEqual(elements["writer-detect"].disabled, false);

  ctx.activeJob = null;
  ctx.slotData.slots[0].status = "empty";
  ctx.writerIdentified = {reader: "md", slot: "md", data: {}};
  ctx.renderWriterState();
  assert.strictEqual(ctx.writerIdentified, null,
    "removal must invalidate a previous Flash identification");
  assert.strictEqual(elements["writer-detect"].disabled, false);
  // Upload via native file requester (not a list of files already on the device).
  ctx.activeJob = null;
  ctx.slotData.slots[0].status = "occupied";
  ctx.writerSourcePath = "";
  let upload = null;
  ctx.FormData = class { constructor() { this.values = []; } append(k, v) { this.values.push([k,v]); }};
  ctx.fetch = (url, options) => {
    upload = {url, options};
    return Promise.resolve({ok:true, json:()=>Promise.resolve({ok:true,path:"MD/uploaded.md",size:1024})});
  };
  ctx.uploadWriterFile();
  await new Promise(resolve => setImmediate(resolve));
  assert.strictEqual(upload.url, "rom-upload.php");
  assert.strictEqual(upload.options.method, "POST");
  assert.strictEqual(ctx.writerSourcePath, "MD/uploaded.md");
  assert.strictEqual(elements["writer-upload-status"].textContent.indexOf("uploaded") >= 0, true);
  assert.strictEqual(elements["writer-write"].disabled, true,
    "Upload alone must not bypass Flash chip identification");
  console.log("Flash tab, direct file upload and hardware-probe guard passed");
})().catch(err => { console.error(err); process.exitCode = 1; });
