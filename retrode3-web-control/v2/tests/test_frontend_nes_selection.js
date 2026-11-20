/* NES v2 selector regression: no DOM, browser, PHP or hardware necessary. */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "web", "assets", "app.js"), "utf8");
const begin = source.indexOf("  function selectedProbeData() {");
const end = source.indexOf("  function renderReaderState() {", begin);
assert(begin > 0 && end > begin, "NES selector implementation missing");

function fakeSelect() {
  const el = {value: "", children: [], hidden: false};
  Object.defineProperty(el, "innerHTML", {
    get() { return ""; },
    set() { el.children.length = 0; el.value = ""; }
  });
  Object.defineProperty(el, "options", {get() { return this.children; }});
  el.appendChild = function (item) {
    this.children.push(item);
    if (this.children.length === 1) this.value = item.value;
  };
  return el;
}
const names = ["nes-options", "nes-choice", "nes-choice-control",
  "nes-choice-hint", "nes-manual-toggle", "nes-manual-control",
  "nes-mapper", "nes-prg", "nes-chr", "nes-battery"];
const elements = {};
for (const id of names) elements[id] = fakeSelect();
elements["nes-manual-toggle"].checked = false;
elements["nes-battery"].checked = false;
const probe = {
  title: "NES cartridge", mapping: "unknown",
  candidates: [
    {id: "mmc1-0007", title: "Dr. Mario (Europe)", layout_id: "m1s5-32-32",
      mapper: 1, submapper: 5, prg_kib: 32, chr_kib: 32, read_supported: true},
    {id: "nrom-0002", title: "Unknown board", layout_id: "nrom-32-8",
      mapper: 0, submapper: 0, prg_kib: 32, chr_kib: 8, read_supported: false}
  ],
  read_layouts: [
    {id: "m1s5-32-32", mapper: 1, submapper: 5,
      prg_kib: 32, chr_kib: 32, read_supported: true},
    {id: "nrom-32-8", mapper: 0, submapper: 0,
      prg_kib: 32, chr_kib: 8, read_supported: false}
  ]
};
const ctx = {
  selectedReader: "nes", nesProbeKey: "", nesReaderOptions: null,
  readerOptions: null,
  detectedBySlot: {},
  selectedSlotId: function () { return "nes"; },
  autoDetection: function () {
    return {state: "detected", core_id: "nes", result: probe};
  },
  $: function (id) {return elements[id];},
  t: function (key) {return key;},
  text: function (el, val) {el.textContent = val;},
  document: {createElement: function () {return {value: "", disabled: false};}},
  renderReaderState: function () {}
};
vm.createContext(ctx);
vm.runInContext(source.slice(begin, end), ctx);

ctx.renderNesOptions();
assert.strictEqual(elements["nes-options"].hidden, false);
assert.strictEqual(elements["nes-choice-control"].hidden, false);
assert.strictEqual(ctx.nesReadAllowed(), false, "Ambiguous mapper must require selection");
assert(elements["nes-choice"].children.some(x => x.value === "candidate:mmc1-0007"));
assert(elements["nes-choice"].children.some(x => x.value === "layout:m1s5-32-32"));
assert(elements["nes-choice"].children.some(x =>
  x.value === "candidate:nrom-0002" && x.disabled));
elements["nes-choice"].value = "candidate:mmc1-0007";
assert.strictEqual(ctx.nesReadAllowed(), true);
elements["nes-choice"].value = "layout:nrom-32-8";
assert.strictEqual(ctx.nesReadAllowed(), false);
elements["nes-choice"].value = "layout:m1s5-32-32";
ctx.renderNesOptions();
assert.strictEqual(elements["nes-choice"].value, "layout:m1s5-32-32",
  "Polling must preserve explicit user selection");

ctx.nesReaderOptions = {manual_layout: true, supported_mappers: [
  {mapper: 1, submapper: 0, prg_kib: [32, 128], chr_kib: [0, 32],
    read_supported: true}]};
elements["nes-mapper"].value = "1:0";
ctx.populateNesManualSizes();
elements["nes-manual-toggle"].checked = true;
ctx.renderNesOptions();
assert.strictEqual(elements["nes-manual-control"].hidden, false);
assert.strictEqual(ctx.nesReadAllowed(), true);
elements["nes-battery"].checked = true;
assert.strictEqual(ctx.nesReadAllowed(), false,
  "Battery-backed MMC1 must not offer a dangerous default read");

elements["nes-battery"].checked = false;
elements["nes-manual-toggle"].checked = false;
probe.candidates = []; probe.read_layouts = [];
ctx.renderNesOptions();
assert.strictEqual(ctx.nesReadAllowed(), false);
assert.strictEqual(elements["nes-choice-hint"].textContent, "nes_unknown_layout");
console.log("NES candidate/layout/manual selector regression passed");
