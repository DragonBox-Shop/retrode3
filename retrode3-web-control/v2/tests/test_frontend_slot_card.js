/* Slot cards must show identified hardware, not all installed adapters. */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const source = fs.readFileSync(path.join(__dirname, "..", "web", "assets", "app.js"), "utf8");
const start = source.indexOf("  function voltageLabel(millivolts) {");
const end = source.indexOf("  function refreshSlots() {", start);
assert(start !== -1 && end > start, "slot identification/card functions missing");

function element(tag) {
  return {
    tag: tag, children: [], attrs: {}, handlers: {}, textContent: "", innerHTML: "",
    appendChild: function (node) { this.children.push(node); },
    focus: function () { focused = this; },
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
let chosen = null, notices = [], focused = null;
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
  coreState: null,
  showTab: function (tab, slot) { chosen = tab; ctx.openedSlot = slot; },
  detectedBySlot: {},
  selectedReader: "md", activeJob: null, hardwareBusy: () => Boolean(ctx.activeJob),
  busyJob: () => null,
  manualReaderBySlot: {},
  selectReader: function (id) { chosen = id; ctx.selectedReader = id; },
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
node.children[0].handlers.click();
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
node.children[0].handlers.click();
assert.strictEqual(chosen, "md");

// Unknown current voltage must not be invented.
delete ctx.detectedBySlot.md;
slot.detection = {state: "detected", core_id: "md",
  result: {title: "SNAKE RATTLE N ROLL", read_voltage_mv: 5000,
           voltage_status: "manual_required"}};
slot.voltage_mv = null;
node = card();
assert(allText(node).includes("Zum Lesen 5 V"));
assert(!allText(node).includes("aktuell 3,3 V"));
slot.voltage_mv = 3300;

// An inconclusive result has a usable native select in the physical slot,
// not a disabled card or a hidden Advanced-settings-only reader picker.
delete ctx.detectedBySlot.md;
slot.detection = {state: "choose_reader", core_id: null, result: null};
chosen = null;
node = card();
assert.strictEqual(node.tag, "div", "slot card is not an interactive wrapper");
assert(!node.children[0].disabled, "occupied unknown slot must remain clickable");
const manual = node.children.filter(function (part) {
  return part.className === "slot-manual";
})[0];
assert(manual, "unrecognized cartridge must offer an inline picker");
const picker = manual.children.filter(function (part) { return part.tag === "select"; })[0];
assert(picker, "native dropdown missing");
assert.strictEqual(picker.value, "", "no core must be guessed");
assert.strictEqual(picker.children.length, 3, "placeholder + both enabled slot cores");
assert.strictEqual(picker.children[1].value, "md");
assert.strictEqual(picker.children[2].value, "sms-md");
assert.strictEqual(chosen, null);
node.children[0].handlers.click();
assert.strictEqual(focused, picker, "clicking an unknown slot focuses the inline picker");
picker.value = "sms-md";
picker.handlers.change();
assert.strictEqual(chosen, "sms-md", "manual selection updates reader");
assert.strictEqual(ctx.manualReaderBySlot.md, "sms-md");
assert(!ctx.detectedBySlot.md, "manual selection must not invent an identity");
assert(!allText(card()).includes("SNAKE RATTLE N ROLL"));

// Keep the manual choice after passive re-render; never turn it into
// a positive detected-system result without a successful core probe.
node = card();
const chosenPicker = node.children.filter(function (part) {
  return part.className === "slot-manual";
})[0].children.filter(function (part) { return part.tag === "select"; })[0];
assert.strictEqual(chosenPicker.value, "sms-md");
assert(allText(node).includes("slot_system_unrecognized"));

// While automatic identification is still running, do not present a manual
// dropdown that would race its result or an active ROM read job.
slot.detection = {state: "detecting", core_id: null, result: null};
node = card();
assert(!node.children.some(function (part) { return part.className === "slot-manual"; }));
slot.detection = {state: "failed", core_id: null, result: null};
ctx.activeJob = "active-reader-job";
node = card();
const busySelect = node.children.filter(function (part) {
  return part.className === "slot-manual";
})[0].children.filter(function (part) { return part.tag === "select"; })[0];
assert(busySelect.disabled, "cannot switch reader while a job is active");
ctx.activeJob = null;
delete ctx.manualReaderBySlot.md;

// A negative SMS signature is not evidence that an SMS adapter is present.
slot.detection = {state: "choose_reader", core_id: null, result: null};
ctx.detectedBySlot.md = {reader: "sms-md", data: {
  event: "probe_result", system: "sms-md", system_detected: false,
  title: "Unknown cartridge"}};
node = card();
assert(allText(node).includes("SMS-0007"));
assert(allText(node).includes("slot_system_unrecognized"));
assert(!allText(node).includes("Unknown cartridge"));

// Removal invalidates card identity even if the browser has cached a manual probe.
slot.status = "empty";
ctx.detectedBySlot.md = {reader: "md", data: {
  event: "probe_result", system: "md", system_detected: true,
  title: "SNAKE RATTLE N ROLL"}};
node = card();
assert(!allText(node).includes("SNAKE RATTLE N ROLL"));
assert(!node.children.some(function (part) { return part.className === "slot-manual"; }));
assert(node.children[0].disabled, "empty slots must not select a reader");

// With exactly one usable reader, keep a directly selectable card and
// manual Detect action even when automatic probing failed. No needless picker.
slot.id = "snes";
slot.name = "Super Nintendo";
slot.status = "occupied";
slot.detection = {state: "failed", core_id: "snes", result: null,
  error: "probe_failed"};
readers.length = 0;
readers.push({id: "snes", name: "Super Nintendo", slot: "snes"});
ctx.selectedReader = "snes";
node = card();
assert(!node.children.some(function (part) { return part.className === "slot-manual"; }),
  "single-core slot must not require manual dropdown");
assert(allText(node).includes("Super Nintendo"));
assert(allText(node).includes("unknown"));
assert(node.className.includes("selected"));
node.children[0].handlers.click();
assert.strictEqual(chosen, "snes", "single available core remains selectable");
// A valid legacy single-core probe has no system_detected flag.
slot.detection = {state: "detected", core_id: "snes",
  result: {system: "snes", slot: "snes", title: "TERRANIGMA D",
           mapping: "hi", size_bytes: 4194304}};
node = card();
assert(allText(node).includes("TERRANIGMA D"));
assert(!node.children.some(function (part) { return part.className === "slot-manual"; }));
slot.id = "md"; slot.status = "occupied"; slot.detection = {state:"failed"};
readers.length = 0; readers.push({id:"md", name:"Mega Drive", slot:"md"});
ctx.coreState = {available:true, cores:[
  {id:"sms-md", name:"SMS", slot:"md", enabled:false, status:"disabled"},
  {id:"other", name:"Other", slot:"snes", enabled:false, status:"disabled"}]};
// The earlier removal test deliberately left a positive cached MD probe.
// A real refreshSlots() clears it when presence changes. Simulate that
// transition here before testing an unrecognized new cartridge.
node = card();
assert(!allText(node).includes("slot_disabled_plugins"),
  "A positive cached manual probe must suppress the disabled-plugin hint");
delete ctx.detectedBySlot.md;
node = card();
assert(allText(node).includes("slot_disabled_plugins: SMS"));
assert(!allText(node).includes("Other"));
node.children.find(part => part.className === "slot-plugin-link").handlers.click();
assert.strictEqual(chosen, "plugins");
assert.strictEqual(ctx.openedSlot, "md");
ctx.coreState.cores.push(...["GB", "GBA", "Extra"].map(name => ({name, slot:"md", enabled:false, status:"disabled"})));
node = card();
assert(allText(node).includes("SMS, GB, GBA, Extra"));
assert.strictEqual(ctx.disabledPluginPreview([{name:"A".repeat(64)}]), "A".repeat(64));
assert.strictEqual(ctx.disabledPluginPreview([{name:"A".repeat(90)}]), "A".repeat(63) + "…");
assert.strictEqual(ctx.disabledPluginPreview([{name:"A".repeat(61)}, {name:"B"}]), "A".repeat(61) + ", B");
assert.strictEqual(ctx.disabledPluginPreview([{name:"A".repeat(61)}, {name:"B"}, {name:"C"}]), "A".repeat(61) + ", …");
const many = Array.from({length:20}, (_, i) => ({name:"Plugin " + i}));
const preview = ctx.disabledPluginPreview(many);
assert(Array.from(preview).length <= 64);
assert(preview.endsWith(", …"));
assert(preview.includes("Plugin 2"));
assert(!preview.includes("Plugin 19"));
assert(allText(node).includes("slot_disabled_count"));
ctx.coreState.cores.splice(2);
ctx.coreState.cores[0].enabled = true;
assert(!allText(card()).includes("slot_disabled_plugins"));
console.log("confirmed slot card identity, single-core and inline picker tests passed");
