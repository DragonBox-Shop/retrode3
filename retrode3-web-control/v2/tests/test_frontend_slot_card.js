/* Slot cards must show identified hardware, not all installed adapters. */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const source = fs.readFileSync(path.join(__dirname, "..", "web", "assets", "app.js"), "utf8");
const start = source.indexOf("  function slotIdentification(slot) {");
const end = source.indexOf("  function refreshSlots() {", start);
assert(start !== -1 && end > start, "slot identification/card functions missing");

function element(tag) {
  return {
    tag: tag, children: [], attrs: {}, handlers: {}, textContent: "", innerHTML: "",
    appendChild: function (node) { this.children.push(node); },
    setAttribute: function (key, value) { this.attrs[key] = value; },
    addEventListener: function (event, handler) { this.handlers[event] = handler; }
  };
}
function allText(el) {
  return [el.textContent].concat(el.children.map(allText)).join(" ");
}
const elements = {
  "slot-list": element("div"), "slots-summary": element("span"),
  advanced: {hidden: true}, "advanced-toggle": element("button")
};
const readers = [
  {id: "md", name: "Mega Drive", slot: "md"},
  {id: "sms-md", name: "Master System (SMS-0007 adapter)", slot: "md"}
];
const slot = {
  id: "md", name: "Mega Drive", status: "occupied", voltage_mv: 3300, detection: {}
};
let chosen = null, notices = [];
const ctx = {
  document: {createElement: element},
  $: function (id) { return elements[id]; },
  text: function (el, value) {
    el.textContent = value === null || value === undefined ? "" : String(value);
  },
  locale: "de",
  t: function (key) {
    const translations = {
      voltage_manual_detail: "Spannung: aktuell {current}; zum Lesen {required} erforderlich. Bitte manuell prüfen.",
      voltage_manual_required_voltage: "Zum Lesen {required} erforderlich. Spannung bitte manuell prüfen.",
      voltage_manual_current_voltage: "Spannung: aktuell {current}. Vor dem Lesen bitte manuell prüfen."
    };
    return translations[key] || key;
  },
  readers: function () { return readers; },
  slotData: {slots: [slot]},
  detectedBySlot: {},
  selectedReader: "md",
  selectReader: function (id) { chosen = id; },
  notify: function (message) { notices.push(message); }
};
vm.createContext(ctx);
vm.runInContext(source.slice(start, end), ctx);

function card() {
  elements["slot-list"].children = [];
  ctx.renderSlots();
  assert.strictEqual(elements["slot-list"].children.length, 1);
  return elements["slot-list"].children[0];
}

// Positive automatic identification: show *only* the detected system.
slot.detection = {state: "detected", core_id: "md",
  result: {title: "SNAKE RATTLE N ROLL", size_bytes: 524288,
    read_voltage_mv: 5000, voltage_status: "manual_required"}};
let node = card();
assert(allText(node).includes("SNAKE RATTLE N ROLL"));
assert(!allText(node).includes("SMS-0007"));
assert(!allText(node).includes("unknown"));
assert(allText(node).includes("aktuell 3,3 V"));
assert(allText(node).includes("zum Lesen 5 V"));
node.handlers.click();
assert.strictEqual(chosen, "md");

// When already at 5 V, display the actual read-back instead of the 3.3 V
// probe default. A ready state must not show a manual-warning banner.
slot.voltage_mv = 5000;
node = card();
assert(allText(node).includes("aktuell 5 V"));
slot.detection.result.voltage_status = "ready";
node = card();
assert(!allText(node).includes("Spannung:"));
slot.voltage_mv = 3300;
slot.detection.result.voltage_status = "manual_required";

// Positive manual probe with stale/inconclusive automatic state remains visible.
slot.detection = {state: "choose_reader", core_id: null, result: null};
ctx.detectedBySlot.md = {reader: "md", data: {
  event: "probe_result", system: "md", system_detected: true,
  title: "SNAKE RATTLE N ROLL"}};
node = card();
assert(allText(node).includes("SNAKE RATTLE N ROLL"));
assert(!allText(node).includes("SMS-0007"));
assert(!allText(node).includes("choose_reader"));
node.handlers.click();
assert.strictEqual(chosen, "md");

// Unknown current voltage must not be invented.
slot.detection = {state: "detected", core_id: "md",
  result: {title: "SNAKE RATTLE N ROLL", read_voltage_mv: 5000,
           voltage_status: "manual_required"}};
slot.voltage_mv = null;
node = card();
assert(allText(node).includes("Zum Lesen 5 V"));
assert(!allText(node).includes("aktuell 3,3 V"));
slot.voltage_mv = 3300;

// A negative SMS signature is not evidence that an SMS adapter is present.
ctx.detectedBySlot.md = {reader: "sms-md", data: {
  event: "probe_result", system: "sms-md", system_detected: false,
  title: "Unknown cartridge"}};
node = card();
assert(allText(node).includes("SMS-0007"));
assert(allText(node).includes("choose_reader"));
assert(!allText(node).includes("Unknown cartridge"));

// Removal invalidates card identity even if the browser has cached a manual probe.
slot.status = "empty";
ctx.detectedBySlot.md = {reader: "md", data: {
  event: "probe_result", system: "md", system_detected: true,
  title: "SNAKE RATTLE N ROLL"}};
node = card();
assert(!allText(node).includes("SNAKE RATTLE N ROLL"));
console.log("confirmed slot card identity tests passed");
