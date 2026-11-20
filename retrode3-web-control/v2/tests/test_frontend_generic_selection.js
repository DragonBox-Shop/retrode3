/* Generic v3 selection renderer regression, no browser/hardware needed. */
"use strict";
const assert = require("assert");
const Selector = require("../web/assets/selection-ui.js");

function el(tag) {
  const x = {tagName: tag, value: "", children: [], hidden: false,
    checked: false, disabled: false, events: {}, parentNode: null,
    addEventListener: function (name, handler) { this.events[name] = handler; },
    fire: function (name) { if (this.events[name]) this.events[name](); },
    appendChild: function (item) {
      item.parentNode = this; this.children.push(item);
      if (this.tagName === "select" && this.children.length === 1)
        this.value = item.value;
    }
  };
  Object.defineProperty(x, "options", {get: function () { return this.children; }});
  Object.defineProperty(x, "innerHTML", {
    get: function () { return ""; },
    set: function () { this.children = []; this.value = ""; }
  });
  return x;
}
global.document = {createElement: el};
const parts = {panel: el("div"), choiceBox: el("div"),
  choice: el("select"), overrideBox: el("div"), override: el("input"),
  fields: el("div"), hint: el("p"), overrideHint: el("p")};
let changed = 0, title = null;
const widget = Selector.create(Object.assign({}, parts, {
  translate: function (s) { return s; },
  onChange: function () { changed++; },
  onCandidateTitle: function (s) { title = s; }
}));

const schema = {
  schema_version: 1, schema_id: "future-adapter-v1",
  selection_modes: ["auto", "candidate", "layout", "override"],
  fields: [
    {id: "bank_count", label: "Bank count", type: "enum", required: true,
      values: [{value: 1, label: "One bank"},
               {value: 2, label: "Experimental", read_supported: false}]},
    {id: "safe", label: "Safe access", type: "boolean", default: true},
    {id: "extra", label: "Extra bank", type: "integer", required: false,
      minimum: 1, maximum: 4, visible_when: {bank_count: 2}}
  ],
  rules: [{when: {safe: false}, read_supported: false,
           reason: "Unsafe signals are blocked"},
          {when: {bank_count: 1}, allow: {bank_count: [1]},
           read_supported: true}]
};
const titleProbe = {
  selection_schema_id: "future-adapter-v1",
  identification_status: "ambiguous", ambiguity: "titles_only",
  selection_required: false,
  candidates: [{id: "a", title: "Game A", layout_id: "x", read_supported: true},
               {id: "b", title: "Game B", layout_id: "x", read_supported: true}],
  read_layouts: [{id: "x", label: "Single safe layout", read_supported: true}]
};

widget.update("future-adapter", schema, titleProbe);
assert.strictEqual(widget.allowed(), true, "Title-only ambiguity must allow auto read");
assert.strictEqual(widget.selection().mode, "auto");
assert.strictEqual(parts.choiceBox.hidden, false, "Multiple titles must show dropdown");
parts.choice.value = "candidate:b"; parts.choice.fire("change");
assert.strictEqual(widget.selection().candidate_id, "b");
assert.strictEqual(title, "Game B");
widget.update("future-adapter", schema, titleProbe);
assert.strictEqual(parts.choice.value, "candidate:b", "Polling must not reset choice");

const layouts = Object.assign({}, titleProbe, {
  ambiguity: "layouts", selection_required: true,
  candidates: [{id: "a", title: "Game A", layout_id: "x", read_supported: true},
               {id: "b", title: "Game B", layout_id: "y", read_supported: false,
                reason: "Unapproved bank writes"}],
  read_layouts: [{id: "x", label: "Safe", read_supported: true},
                 {id: "y", label: "Blocked", read_supported: false}]
});
widget.update("future-adapter", schema, layouts);
assert.strictEqual(widget.allowed(), false, "Layout ambiguity must block auto");
assert(parts.choice.children.some(x => x.value === "candidate:b" && x.disabled));
parts.choice.value = "candidate:b";
assert.strictEqual(widget.allowed(), false, "Blocked candidate cannot be chosen");
parts.choice.value = "layout:y";
assert.strictEqual(widget.allowed(), false, "Blocked layout cannot be chosen");
parts.choice.value = "layout:x";
assert.strictEqual(widget.allowed(), true);
assert.strictEqual(widget.selection().mode, "layout");

const unknown = {
  identification_status: "unknown", selection_schema_id: "future-adapter-v1",
  candidates: [], read_layouts: [], selection_required: false
};
widget.update("future-adapter", schema, unknown);
assert.strictEqual(widget.allowed(), false, "Unknown cartridge needs override");
parts.override.checked = true; parts.override.fire("change");
assert.strictEqual(parts.fields.hidden, false);
assert.strictEqual(widget.allowed(), false, "Required field must be completed");
const bank = parts.fields.children[0].children[1];
const safe = parts.fields.children[1].children[1];
const extra = parts.fields.children[2].children[1];
bank.value = "1"; bank.fire("change");
assert.strictEqual(widget.allowed(), true);
assert.deepStrictEqual(widget.selection(), {
  version: 1, schema_id: "future-adapter-v1", mode: "override",
  parameters: {bank_count: 1, safe: true}
});
safe.checked = false; safe.fire("change");
assert.strictEqual(widget.allowed(), false, "Unsupported dependent rule must block read");
safe.checked = true; safe.fire("change");
bank.value = "2"; bank.fire("change");
assert.strictEqual(widget.allowed(), false, "Disabled enum value must never be submitted");
assert.strictEqual(extra.parentNode.hidden, false);
bank.value = "1"; bank.fire("change");
assert.strictEqual(extra.parentNode.hidden, true);

widget.update("future-adapter", schema, Object.assign({}, unknown, {
  selection_schema_id: "outdated-v0"
}));
assert.strictEqual(widget.allowed(), false, "Stale probe/schema combination must be refused");
widget.reset();
assert.strictEqual(parts.override.checked, false);
assert.strictEqual(widget.active(), false);
widget.update("new-slot-plugin", Object.assign({}, schema, {
  schema_id: "new-slot-v1"}), null);
assert.strictEqual(parts.override.checked, false, "Different core must reset override");
assert.strictEqual(widget.selection().schema_id, "new-slot-v1");
assert(changed > 0);
console.log("generic candidate/override frontend regression passed");
