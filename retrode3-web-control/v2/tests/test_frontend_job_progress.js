/* Shared job progress rendering: read, erase, program, verify.
 * The writer is deliberately NOT enabled by these tests. */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const source = fs.readFileSync(path.join(__dirname, "..", "web", "assets", "app.js"), "utf8");
const start = source.indexOf("  function renderJob(job) {");
const end = source.indexOf("  function schedulePoll() {", start);
assert(start > 0 && end > start, "job progress renderer missing");

const elements = {
  "job-label": {textContent: ""},
  "job-percent": {textContent: ""},
  "job-fill": {style: {width: ""}},
  "job-detail": {textContent: ""},
  "job-result-details": {textContent: ""}
};
const ctx = {
  $: function (id) {assert(elements[id], "unexpected DOM lookup " + id); return elements[id];},
  t: function (key) {return key;},
  text: function (el, value) {el.textContent = String(value);},
  humanSize: function (n) {return n + " B";},
  notify: function () {throw new Error("running job must not notify completion");}
};
vm.createContext(ctx);
vm.runInContext(source.slice(start, end), ctx);
function render(phase, percent, extras, status) {
  ctx.renderJob({
    status: status || "running",
    command: "write_flash",
    progress: Object.assign({phase: phase, percent: percent}, extras || {})
  });
}

render("erase", 25, {units: "sectors", units_done: 2, units_total: 8});
assert.strictEqual(elements["job-label"].textContent, "progress_phase_erase");
assert.strictEqual(elements["job-percent"].textContent, "25%");
assert.strictEqual(elements["job-fill"].style.width, "25%");
assert.strictEqual(elements["job-detail"].textContent, "2 / 8 progress_sectors");

render("program", 50, {units: "bytes", bytes_done: 2048, bytes_total: 4096});
assert.strictEqual(elements["job-label"].textContent, "progress_phase_program");
assert.strictEqual(elements["job-detail"].textContent, "2048 B / 4096 B");

render("verify", 12, {units: "bytes", bytes_done: 512, bytes_total: 4096});
assert.strictEqual(elements["job-label"].textContent, "progress_phase_verify");
assert.strictEqual(elements["job-percent"].textContent, "12%");
assert.strictEqual(elements["job-detail"].textContent, "512 B / 4096 B");

// Each real phase has its own percentage. Starting verify does not mean
// programming had failed or that the job already succeeded.
render("verify", 0, {bytes_done: 0, bytes_total: 4096});
assert.strictEqual(elements["job-percent"].textContent, "0%");
render("verify", 50, {bytes_done: 2048, bytes_total: 4096}, "cancelling");
assert.strictEqual(elements["job-label"].textContent,
                   "progress_phase_verify · cancelling");

// Backward compatibility with existing read_rom jobs.
render("read_rom", 63, {bytes_done: 630, bytes_total: 1000});
assert.strictEqual(elements["job-label"].textContent, "progress_phase_read_rom");
assert.strictEqual(elements["job-detail"].textContent, "630 B / 1000 B");

// Unknown phases fall back to the job state, never arbitrary UI text.
render("unexpected", 41, {});
assert.strictEqual(elements["job-label"].textContent, "running");
render("program", 999, {bytes_done: -1, bytes_total: 4096});
assert.strictEqual(elements["job-percent"].textContent, "100%");
assert.strictEqual(elements["job-detail"].textContent, "");
render("program", NaN, {bytes_done: 0, bytes_total: 4096});
assert.strictEqual(elements["job-percent"].textContent, "0%");

console.log("phase-aware shared job progress regression passed");
