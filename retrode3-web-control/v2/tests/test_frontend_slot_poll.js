/* Polling may not close an open manual selector or guess the first core. */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const source = fs.readFileSync(
  path.join(__dirname, "..", "web", "assets", "app.js"), "utf8");
const start = source.indexOf("  function refreshSlots() {");
const end = source.indexOf("  function loadCapabilities() {", start);
assert(start >= 0 && end > start, "slot refresh function missing");
const readers = [
  {id: "md", slot: "md"}, {id: "sms-md", slot: "md"}
];
function snap(status, state, core, detected) {
  return {slots: [{id: "md", name: "Mega Drive", status: status,
    detection: {state: state, core_id: core || null,
      result: detected === undefined ? null : {system_detected: detected,
        title: "TEST GAME"}}}]};
}
let incoming = snap("occupied", "choose_reader");
let renders = 0, selections = [];
const focusedSelect = {
  classList: {contains: function (name) { return name === "slot-manual-select"; }},
  getAttribute: function (name) { return name === "data-slot" ? "md" : null; }
};
const elements = {
  filename: {value: ""}, "slots-summary": {textContent: ""}
};
const ctx = {
  slotData: {slots: []}, slotFingerprint: null,
  selectedReader: "", activeJob: null, probeTarget: null,
  manualReaderBySlot: {}, detectedBySlot: {}, autoNames: {},
  genericWidget: null, document: {activeElement: null},
  $: function (id) { return elements[id]; },
  api: function (url) {
    assert.strictEqual(url, "/api/slots");
    return Promise.resolve(incoming);
  },
  readers: function () { return readers; },
  selectedSlotId: function () { return ctx.selectedReader ? "md" : ""; },
  autoDetection: function (id) {
    const entry = ctx.slotData.slots.filter(function (s) { return s.id === id; })[0];
    return entry && entry.detection;
  },
  slotIdentification: function (slot) {
    if (slot.status !== "occupied" || !slot.detection ||
        slot.detection.state !== "detected" ||
        !slot.detection.result || slot.detection.result.system_detected !== true)
      return null;
    const reader = readers.filter(function (r) { return r.id === slot.detection.core_id; })[0];
    return reader ? {reader: reader, result: slot.detection.result} : null;
  },
  selectReader: function (id) { selections.push(id); ctx.selectedReader = id; },
  renderSlots: function () { ++renders; },
  renderSelectedProbe: function () {},
  t: function (key) { return key; },
  text: function (el, value) { el.textContent = String(value); },
  fail: function (error) { throw error; }
};
vm.createContext(ctx);
vm.runInContext(source.slice(start, end), ctx);

async function run() {
  // Presence alone and two ready adapters must not silently select 'md'.
  await ctx.refreshSlots();
  assert.strictEqual(ctx.selectedReader, "");
  assert.deepStrictEqual(selections, [""]);
  assert.strictEqual(renders, 1);

  ctx.manualReaderBySlot.md = "sms-md";
  ctx.selectedReader = "sms-md";
  ctx.document.activeElement = focusedSelect;
  incoming = snap("occupied", "choose_reader");
  await ctx.refreshSlots();
  assert.strictEqual(renders, 1, "poll closed the native dropdown");
  assert.strictEqual(ctx.manualReaderBySlot.md, "sms-md");
  assert.strictEqual(ctx.selectedReader, "sms-md");

  // A negative core signature must not automatically overwrite the choice.
  incoming = snap("occupied", "detected", "md", false);
  await ctx.refreshSlots();
  assert.strictEqual(ctx.selectedReader, "sms-md");
  assert.strictEqual(renders, 1);

  // Positive identification supersedes the manual guess and redraws the card.
  incoming = snap("occupied", "detected", "md", true);
  await ctx.refreshSlots();
  assert.strictEqual(ctx.selectedReader, "md");
  assert(renders > 1);

  // Cartridge removal clears the remembered manual choice and the selection.
  incoming = snap("empty", "idle");
  await ctx.refreshSlots();
  assert.strictEqual(ctx.selectedReader, "");
  assert.strictEqual(ctx.manualReaderBySlot.md, undefined);
  console.log("slot polling and manual selector persistence tests passed");
}
run().catch(function (error) {
  console.error(error);
  process.exitCode = 1;
});
