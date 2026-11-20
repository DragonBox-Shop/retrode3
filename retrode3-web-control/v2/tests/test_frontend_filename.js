/* No-browser regression test for reader-specific ROM filename suggestions. */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "web", "assets", "app.js"), "utf8");
const start = source.indexOf("  function selectReader(id) {");
const end = source.indexOf("  function renderSelectedProbe() {", start);
assert(start !== -1 && end > start, "reader selection helpers missing");

const readers = {
  md: {id: "md", slot: "md"},
  nes: {id: "nes", slot: "nes"},
  snes: {id: "snes", slot: "snes"}
};
const elements = {filename: {value: ""}, system: {value: ""}};
const ctx = {
  selectedReader: "",
  readerById: function (id) { return readers[id] || null; },
  $: function (id) { return elements[id]; },
  configureReaderOptions: function () {},
  renderReaderState: function () {},
  renderSlots: function () {},
  renderSelectedProbe: function () {},
  detectedBySlot: {},
  slotData: {slots: [
    {id: "md", status: "occupied", detection: {
      state: "detected", core_id: "md", result: {title: "SNAKE RATTLE N ROLL"}}},
    {id: "nes", status: "occupied", detection: {
      state: "detected", core_id: "nes", result: {title: "EXCITEBIKE"}}},
    {id: "snes", status: "empty"}
  ]}
};
vm.createContext(ctx);
vm.runInContext(source.slice(start, end), ctx);

ctx.selectReader("md");
assert.strictEqual(elements.filename.value, "SNAKE RATTLE N ROLL");
elements.filename.value = "Custom MD name";
ctx.selectReader("md"); // Reselecting same core must retain user edits.
assert.strictEqual(elements.filename.value, "Custom MD name");
ctx.selectReader("nes");
assert.strictEqual(elements.filename.value, "EXCITEBIKE");
ctx.selectReader("snes");
assert.strictEqual(elements.filename.value, "SNES-Dump");
ctx.selectReader("md");
assert.strictEqual(elements.filename.value, "SNAKE RATTLE N ROLL");
ctx.selectReader("");
assert.strictEqual(elements.filename.value, "");

ctx.slotData = null; // Explicit manual probe result if auto detect is absent.
ctx.detectedBySlot.snes = {reader: "snes", data: {title: "MANUAL SNES"}};
ctx.selectReader("snes");
assert.strictEqual(elements.filename.value, "MANUAL SNES");

console.log("reader-specific ROM filename tests passed");
