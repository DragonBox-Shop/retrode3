"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const source = fs.readFileSync(path.join(__dirname, "../web/assets/app.js"), "utf8");
const begin = source.indexOf("  function busyJob() {");
const end = source.indexOf("  function selectReader(", begin);
const elements = {};
function node(id) {
  return elements[id] ||= {hidden: true, disabled: false, textContent: "",
    appendChild(child) { child.parent = id; }};
}
const ctx = {
  $: node, t: key => key, text: (el, value) => { el.textContent = value; },
  selectedReader: "nes", currentPage: "reader", currentJob: null,
  activeJob: null, resuming: false, slotData: {busy_job: null},
  readerById: id => ({id, name:id.toUpperCase(), slot:id, capabilities:{commands:["probe","read_rom"]}}),
  selectedSlotId: () => ctx.selectedReader,
  readerOptionsLoading: false, genericSchema: () => ({}), genericWidget:{allowed:()=>true},
  renderWriterState: () => {}
};
vm.createContext(ctx);
vm.runInContext(source.slice(begin, end), ctx);
ctx.activeJob = "pending";
ctx.currentJob = {slot:"nes",system:"nes",command:"read_rom",status:"queued"};
ctx.renderReaderState();
assert(node("read").disabled);
assert(!node("job-panel").hidden);
assert(node("global-job-cancel").hidden);
ctx.activeJob = "read1";
ctx.currentJob.status = "running";
ctx.currentJob.progress = {percent:64};
ctx.selectedReader = "md";
ctx.renderReaderState();
assert(node("read").disabled && node("job-panel").hidden);
assert(!node("global-job-status").hidden);
assert(node("global-job-label").textContent.includes("NES"));
assert(node("global-job-label").textContent.includes("64%"));
ctx.selectedReader = "nes";
ctx.renderReaderState();
assert(!node("job-panel").hidden);
ctx.currentPage = "writer";
ctx.renderReaderState();
assert(node("job-panel").hidden);
ctx.activeJob = null;
ctx.currentJob = null;
ctx.currentPage = "reader";
ctx.renderReaderState();
assert(node("job-panel").hidden && !node("read").disabled);
assert(node("global-job-status").hidden);
ctx.slotData.busy_job = {slot:"md",system:"md",command:"read_rom",status:"running"};
ctx.renderReaderState();
assert(node("read").disabled && !node("global-job-status").hidden);
ctx.slotData.busy_job = null;
ctx.currentJob = {slot:"md",system:"md",command:"flash_operation",status:"done"};
ctx.currentPage = "writer";
ctx.renderReaderState();
assert(!node("job-panel").hidden && node("job-panel").parent === "writer-progress-anchor");
ctx.currentPage = "reader";
ctx.renderReaderState();
assert(node("job-panel").hidden);
console.log("Slot-scoped progress, global busy and writer isolation passed");
