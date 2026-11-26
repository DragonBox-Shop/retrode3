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
assert(node("read").disabled && !node("job-panel").hidden);
assert(node("global-job-status").hidden);
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
assert(node("read").disabled && node("global-job-status").hidden);
ctx.slotData.busy_job = null;
ctx.currentJob = {slot:"md",system:"md",command:"flash_operation",status:"done"};
ctx.currentPage = "writer";
ctx.renderReaderState();
assert(!node("job-panel").hidden && node("job-panel").parent === "writer-progress-anchor");
ctx.currentPage = "reader";
ctx.renderReaderState();
assert(node("job-panel").hidden);
// Completed ROM metadata belongs only to the matching cartridge/core.
const resultStart = source.indexOf("  function renderReadResult() {");
const resultEnd = source.indexOf("  function voltageLabel(", resultStart);
function resultNode() {
  return {hidden:false, textContent:"", children:[],
    appendChild(child) {this.children.push(child);},
    set innerHTML(value) {this.children=[];}};
}
const box = resultNode();
ctx.$ = id => id === "slot-read-result" ? box : node(id);
ctx.document = {createElement: resultNode};
ctx.humanSize = n => n + " bytes";
ctx.currentJob = null;
ctx.activeJob = null;
ctx.slotData = {slots: [
  {id:"nes",status:"occupied",read_result:{system:"nes",title:"NES game",filename:"game.nes",
    size_bytes:40960,crc32:"ABCDEF01",verification:{status:"verified"}}},
  {id:"md",status:"occupied",read_result:{system:"md",title:"MD game",filename:"game.md",
    size_bytes:65536,crc32:"ABCDEF02",verification:{status:"mismatch",expected:"00000000",actual:"ABCDEF02"}}}
]};
vm.runInContext(source.slice(resultStart, resultEnd), ctx);
function allText(el) {return [el.textContent].concat(el.children.map(allText)).join(" ");}
ctx.selectedReader = "nes";
ctx.renderReadResult();
assert(!box.hidden && allText(box).includes("ABCDEF01") && !allText(box).includes("ABCDEF02"));
ctx.selectedReader = "md";
ctx.renderReadResult();
assert(!box.hidden && allText(box).includes("ABCDEF02") && allText(box).includes("read_complete_mismatch"));
ctx.slotData.slots[1].status = "empty";
ctx.renderReadResult();
assert(box.hidden);
ctx.selectedReader = "nes";
ctx.activeJob = "pending";
ctx.currentJob = {slot:"nes",system:"nes",command:"read_rom",status:"queued"};
ctx.renderReadResult();
assert(box.hidden, "Previous result must not appear during a new read");
console.log("Slot-scoped progress, global busy, writer isolation and result rendering passed");
