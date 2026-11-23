"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

(async function () {
  const source = fs.readFileSync(path.join(__dirname, "..", "web", "assets", "app.js"), "utf8");
  const start = source.indexOf("  function flashReader() {");
  const end = source.indexOf("  function startJob(command) {", start);
  assert(start > 0 && end > start, "Flash writer functions missing");

  const reader = {id: "md", slot: "md", folder: "MD", name: "Mega Drive",
    capabilities: {commands: ["probe_flash", "flash_operation", "write_flash", "verify_flash"]}};
  const el = {
    "writer-system": {value: "md"},
    "writer-file": {files: [{name: "game.md", size: 1024}], value: "C:\\fakepath\\game.md"},
    "writer-upload-status": {textContent: ""},
    "writer-slot-status": {textContent: ""},
    "writer-flash-status": {textContent: ""},
    "writer-operation-hint": {textContent: ""},
    "writer-detect": {disabled: false},
    "writer-start": {disabled: false},
    "writer-erase": {checked: true},
    "writer-program": {checked: true},
    "writer-check": {checked: true},
    "writer-verify-passes": {value: "1", disabled: false},
    "job-panel": {hidden: true},
    "writer-progress-anchor": {appendChild() {}},
    "cancel": {disabled: true}
  };
  let sent = null, uploaded = null;
  const ctx = {
    $: id => {assert(el[id], "unknown DOM element: " + id); return el[id];},
    readerById: id => id === "md" ? reader : null,
    readers: () => [reader], selectedReader: "md",
    slotData: {slots: [{id: "md", status: "occupied"}]},
    writerIdentified: {reader: "md", slot: "md", data: {
      manufacturer_id: 127, device_id: 8953,
      capacity_bytes: 4194304, sector_count: 71
    }},
    activeJob: null, csrf: "csrf", writerSourcePath: "MD/game.md",
    writerUploading: false, writerUploadSerial: 0,
    t: key => key, humanSize: n => n + " bytes",
    text: (element, v) => {element.textContent = String(v);},
    api: (url, data) => {
      assert.strictEqual(url, "/api/jobs");
      sent = JSON.parse(JSON.stringify(data));
      return Promise.resolve({id: "job", status: "queued"});
    },
    notify: () => {throw new Error("unexpected rejected UI command");},
    fail: e => {throw e;},
    renderJob: () => {}, schedulePoll: () => {},
    console
  };
  vm.createContext(ctx);
  vm.runInContext(source.slice(start, end), ctx);
  ctx.renderWriterState();
  assert.strictEqual(el["writer-start"].disabled, false);

  ctx.startFlashJob("flash_operation");
  await Promise.resolve();
  assert.deepStrictEqual(sent, {system:"md", command:"flash_operation",
    erase:true, write:true, verify:true, verify_passes:1, source:"MD/game.md"});

  ctx.activeJob = null;
  sent = null;
  el["writer-erase"].checked = false;
  el["writer-program"].checked = false;
  el["writer-check"].checked = true;
  el["writer-verify-passes"].value = "4";
  ctx.startFlashJob("flash_operation");
  await Promise.resolve();
  assert.deepStrictEqual(sent, {system:"md", command:"flash_operation",
    erase:false, write:false, verify:true, verify_passes:4, source:"MD/game.md"});

  ctx.activeJob = null;
  sent = null;
  el["writer-erase"].checked = true;
  el["writer-check"].checked = false;
  ctx.writerSourcePath = "";
  ctx.renderWriterState();
  assert.strictEqual(el["writer-start"].disabled, false,
    "erase-only requires no ROM upload");
  ctx.startFlashJob("flash_operation");
  await Promise.resolve();
  assert.deepStrictEqual(sent, {system:"md", command:"flash_operation",
    erase:true, write:false, verify:false, verify_passes:0});

  ctx.activeJob = null;
  el["writer-erase"].checked = false;
  ctx.renderWriterState();
  assert.strictEqual(el["writer-start"].disabled, true, "no action disabled");
  el["writer-check"].checked = true;
  el["writer-verify-passes"].value = "0";
  ctx.writerSourcePath = "MD/game.md";
  ctx.renderWriterState();
  assert.strictEqual(el["writer-start"].disabled, true, "invalid verify pass count");
  el["writer-verify-passes"].value = "100";
  ctx.renderWriterState();
  assert.strictEqual(el["writer-start"].disabled, true, "overlarge verify pass count");

  el["writer-verify-passes"].value = "1";
  ctx.writerIdentified = null;
  ctx.renderWriterState();
  assert.strictEqual(el["writer-start"].disabled, true);
  ctx.startFlashJob("probe_flash");
  await Promise.resolve();
  assert.strictEqual(sent.command, "probe_flash");

  ctx.activeJob = null;
  ctx.slotData.slots[0].status = "empty";
  ctx.renderWriterState();
  assert.strictEqual(el["writer-detect"].disabled, false,
    "passive MD sense cannot disable active flash probing");

  // ROM requester, with upload to the logical folder (no server-side list).
  ctx.activeJob = null;
  ctx.writerSourcePath = "";
  ctx.writerIdentified = null;
  ctx.FormData = class {constructor() {this.fields = [];} append(key, value) {this.fields.push([key,value]);}};
  ctx.fetch = (url, options) => {
    uploaded = {url, options};
    return Promise.resolve({ok:true, json:()=>Promise.resolve({
      ok:true, path:"MD/uploaded.md",size:1024})});
  };
  ctx.uploadWriterFile();
  await new Promise(resolve => setImmediate(resolve));
  assert.strictEqual(uploaded.url, "rom-upload.php");
  assert.strictEqual(uploaded.options.method, "POST");
  assert.strictEqual(ctx.writerSourcePath, "MD/uploaded.md");
  assert.strictEqual(el["writer-start"].disabled, true,
    "uploaded file must not bypass chip identification");

  // The browser displays the monotonic-CLI throughput, rather than
  // guessing from network or polling delays.
  const renderStart = source.indexOf("  function renderJob(job) {");
  const renderEnd = source.indexOf("  function schedulePoll() {", renderStart);
  assert(renderStart >= 0 && renderEnd > renderStart);
  const detailNodes = {
    "job-label": {textContent:""},
    "job-percent": {textContent:""},
    "job-fill": {style: {width: ""}},
    "job-speed": {textContent:"", hidden:true},
    "job-detail": {textContent:""},
    "job-result-details": {textContent:""}
  };
  const renderCtx = {
    $: id => {assert(detailNodes[id], "unexpected job element " + id); return detailNodes[id];},
    t: key => key,
    text: (el, str) => {el.textContent = String(str);},
    humanSize: n => n + " bytes",
    console
  };
  vm.createContext(renderCtx);
  vm.runInContext(source.slice(renderStart, renderEnd), renderCtx);
  renderCtx.renderJob({
    command:"flash_operation", status:"running",
    progress:{phase:"program", units:"bytes", bytes_done:32768,
      bytes_total:65536, percent:50, bytes_per_second:10240, elapsed_ms:3200}
  });
  assert(detailNodes["job-speed"].textContent.indexOf("10.0 KiB/s") >= 0 &&
    !detailNodes["job-speed"].hidden,
    "Write rate should be prominent and derived from CLI bytes per second");
  renderCtx.renderJob({
    command:"flash_operation", status:"running",
    progress:{phase:"verify", units:"bytes", bytes_done:8192,
      bytes_total:16384, percent:50, verify_pass:2, verify_passes:3,
      bytes_per_second:20480, elapsed_ms:400}
  });
  assert(detailNodes["job-speed"].textContent.indexOf("20.0 KiB/s") >= 0 &&
    !detailNodes["job-speed"].hidden,
    "Verify must show its own measured rate");
  renderCtx.renderJob({
    command:"flash_operation", status:"running",
    progress:{phase:"erase", units:"sectors", units_done:5,
      units_total:10, percent:50}
  });
  assert(detailNodes["job-speed"].hidden &&
    detailNodes["job-speed"].textContent === "",
    "Erase sector progress should not invent a byte throughput");
  renderCtx.renderJob({
    command:"flash_operation", status:"running",
    progress:{phase:"program", units:"bytes", bytes_done:0,
      bytes_total:65536, percent:0}
  });
  assert(detailNodes["job-speed"].hidden,
    "Rate is hidden when the CLI does not supply throughput");

  console.log("Flash stage selection, repeat count, probe and ROM upload passed");
})().catch(err => {console.error(err); process.exitCode=1;});
