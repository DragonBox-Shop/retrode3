/* Generic versioned cartridge selection UI. No console-specific knowledge. */
(function (root) {
  "use strict";

  function addOption(select, value, label, disabled) {
    var el = document.createElement("option");
    el.value = value;
    el.textContent = label;
    el.disabled = Boolean(disabled);
    select.appendChild(el);
    return el;
  }
  function conditionMatches(when, params) {
    if (!when || typeof when !== "object" || Array.isArray(when)) return true;
    return Object.keys(when).every(function (id) { return params[id] === when[id]; });
  }
  function valuesOf(field) {
    return Array.isArray(field.values) ? field.values.map(function (value) {
      return value && typeof value === "object" && !Array.isArray(value) ?
        value : {value: value, label: String(value)};
    }) : [];
  }
  function labelFor(item) {
    var title = item.title || item.label || item.id || "";
    if (item.read_supported === false)
      title += " (" + (item.reason || "not supported") + ")";
    return title;
  }
  function create(config) {
    var panel = config.panel, choiceBox = config.choiceBox, choice = config.choice,
      override = config.override, fieldsBox = config.fields,
      hint = config.hint, overrideHint = config.overrideHint;
    var reader = "", schema = null, probe = null, probeKey = "", fields = {};
    var schemaKey = "";
    function tr(key, fallback) {
      var translated = config.translate && config.translate(key);
      return translated && translated !== key ? translated : fallback;
    }

    function notify() {
      if (config.onChange) config.onChange();
    }
    function reset() {
      reader = ""; schema = null; probe = null; probeKey = ""; schemaKey = "";
      override.checked = false; choice.value = "";
      choice.innerHTML = ""; fieldsBox.innerHTML = ""; fields = {};
      panel.hidden = true; notify();
    }
    function fieldValue(field) {
      var input = fields[field.id];
      if (!input) return undefined;
      if (field.type === "boolean") return Boolean(input.checked);
      if (field.type === "enum") {
        if (!input.value) return undefined;
        try { return JSON.parse(input.value); } catch (e) { return undefined; }
      }
      if (!input.value && input.value !== 0) return undefined;
      if (field.type === "integer") {
        var n = Number(input.value);
        return isFinite(n) && Math.floor(n) === n ? n : undefined;
      }
      return input.value;
    }
    function currentParameters() {
      var result = {};
      (schema && schema.fields || []).forEach(function (field) {
        if (!conditionMatches(field.visible_when, result)) return;
        var val = fieldValue(field);
        if (val !== undefined) result[field.id] = val;
      });
      return result;
    }
    function syncRules() {
      if (!schema) return false;
      var params = {};
      schema.fields.forEach(function (field) {
        var value = fieldValue(field);
        if (value !== undefined) params[field.id] = value;
      });
      var supported = true, errors = [], rules = Array.isArray(schema.rules) ? schema.rules : [];
      var allows = {};
      rules.forEach(function (rule) {
        if (!conditionMatches(rule.when, params)) return;
        if (rule.read_supported === false) {
          supported = false;
          errors.push(rule.reason || tr("generic_unavailable", "Selected configuration is unavailable"));
        }
        if (rule.allow && typeof rule.allow === "object") {
          Object.keys(rule.allow).forEach(function (id) {
            if (!Array.isArray(rule.allow[id])) return;
            if (!allows[id]) allows[id] = rule.allow[id].slice();
            else allows[id] = allows[id].filter(function (val) {
              return rule.allow[id].indexOf(val) !== -1;
            });
          });
        }
      });
      schema.fields.forEach(function (field) {
        var el = fields[field.id];
        if (!el) return;
        var visible = conditionMatches(field.visible_when, params);
        el.parentNode.hidden = !visible;
        if (!visible) return;
        if (field.type === "enum") {
          var possible = valuesOf(field);
          [].forEach.call(el.options, function (option) {
            if (!option.value) return;
            var val;
            try { val = JSON.parse(option.value); } catch (e) { return; }
            var meta = possible.filter(function (v) { return v.value === val; })[0];
            option.disabled = Boolean(meta && meta.read_supported === false) ||
              Boolean(allows[field.id] && allows[field.id].indexOf(val) === -1);
          });
        }
        var value = fieldValue(field);
        var required = field.required === true ||
          Boolean(field.required_when && conditionMatches(field.required_when, params));
        if (required && value === undefined) supported = false;
        if (value === undefined) return;
        if (field.type === "integer") {
          if (typeof value !== "number" || value < 0 || value > 4294967295 ||
              (typeof field.minimum === "number" && value < field.minimum) ||
              (typeof field.maximum === "number" && value > field.maximum))
            supported = false;
        }
        if (field.type === "string" && (typeof value !== "string" || value.length > 127))
          supported = false;
        if (field.type === "enum") {
          var selected = [].filter.call(el.options, function (o) {
            return o.value === JSON.stringify(value);
          })[0];
          if (!selected || selected.disabled) supported = false;
        }
        if (allows[field.id] && allows[field.id].indexOf(value) === -1)
          supported = false;
      });
      overrideHint.textContent = errors.join("; ");
      return supported;
    }
    function renderFields() {
      fieldsBox.innerHTML = ""; fields = {};
      if (!schema || !Array.isArray(schema.fields)) return;
      schema.fields.forEach(function (field) {
        if (!field || !/^[a-zA-Z0-9_-]{1,47}$/.test(field.id || "") ||
            ["enum", "integer", "boolean", "string"].indexOf(field.type) === -1)
          return;
        var wrapper = document.createElement("div");
        wrapper.className = "generic-field";
        var label = document.createElement("label");
        label.textContent = field.label || field.id;
        var el = document.createElement(field.type === "enum" ? "select" : "input");
        el.id = "generic-" + field.id;
        if (field.type === "enum") {
          addOption(el, "", tr("generic_choose_value", "Choose..."), false);
          valuesOf(field).forEach(function (item) {
            addOption(el, JSON.stringify(item.value), String(item.label === undefined ?
              item.value : item.label), item.read_supported === false);
          });
          if (field.default !== undefined) el.value = JSON.stringify(field.default);
        } else if (field.type === "boolean") {
          el.type = "checkbox"; el.checked = field.default === true;
        } else if (field.type === "integer") {
          el.type = "number"; el.step = "1"; el.min = field.minimum === undefined ? "0" : String(field.minimum);
          el.max = field.maximum === undefined ? "4294967295" : String(field.maximum);
          if (field.default !== undefined) el.value = String(field.default);
        } else {
          el.type = "text"; el.maxLength = 127;
          if (field.default !== undefined) el.value = String(field.default);
        }
        label.htmlFor = el.id;
        wrapper.appendChild(label); wrapper.appendChild(el);
        if (field.description) {
          var description = document.createElement("p");
          description.className = "muted small";
          description.textContent = field.description;
          wrapper.appendChild(description);
        }
        fieldsBox.appendChild(wrapper);
        fields[field.id] = el;
        el.addEventListener("change", function () { syncRules(); notify(); });
        el.addEventListener("input", function () { syncRules(); notify(); });
      });
      syncRules();
    }
    function renderChoices() {
      var candidates = probe && Array.isArray(probe.candidates) ? probe.candidates : [];
      var layouts = probe && Array.isArray(probe.read_layouts) ? probe.read_layouts : [];
      var key = JSON.stringify({candidates: candidates, layouts: layouts});
      if (key !== probeKey) {
        probeKey = key;
        choice.innerHTML = "";
        addOption(choice, "", tr("auto", "Automatic"), false);
        var modes = schema.selection_modes || [];
        if (modes.indexOf("candidate") !== -1) candidates.forEach(function (item) {
          if (!item || typeof item.id !== "string") return;
          var layout = layouts.filter(function (l) { return l.id === item.layout_id; })[0];
          var title = labelFor(item) + (layout && layout.label ?
            " · " + layout.label : item.layout_id ? " · " + item.layout_id : "");
          addOption(choice, "candidate:" + item.id, title,
                    item.read_supported === false || Boolean(layout && layout.read_supported === false));
        });
        if (modes.indexOf("layout") !== -1) layouts.forEach(function (item) {
          if (!item || typeof item.id !== "string") return;
          addOption(choice, "layout:" + item.id, labelFor(item),
                    item.read_supported === false);
        });
        choice.value = "";
      }
      choiceBox.hidden = !(candidates.length > 1 || layouts.length > 1 ||
        (probe && probe.selection_required === true));
      var hasSafeLayout = layouts.some(function (item) {
        return item.read_supported !== false;
      });
      hint.textContent = probe && probe.selection_required === true ?
        tr("generic_choice_required", "Select an available game or layout before reading.") :
        probe && probe.identification_status === "unknown" && !hasSafeLayout ?
        tr("generic_unknown", "Unknown cartridge: use a supported manual override.") :
        candidates.length > 1 ?
        tr("generic_optional_title", "Select a title if known, or read automatically when safe.") : "";
    }
    function update(core, nextSchema, nextProbe) {
      if (!core || !nextSchema || nextSchema.schema_version !== 1 ||
          !nextSchema.schema_id || !Array.isArray(nextSchema.fields) ||
          !Array.isArray(nextSchema.selection_modes)) {
        reset(); return;
      }
      var key = core + ":" + nextSchema.schema_id + ":" + JSON.stringify(nextSchema.fields);
      if (schemaKey !== key) {
        schemaKey = key; reader = core; schema = nextSchema;
        choice.innerHTML = ""; probeKey = "";
        override.checked = false;
        renderFields();
      } else schema = nextSchema;
      probe = nextProbe;
      panel.hidden = false;
      renderChoices();
      config.overrideBox.hidden = nextSchema.selection_modes.indexOf("override") === -1 ||
        !nextSchema.fields.length;
      fieldsBox.hidden = !override.checked || config.overrideBox.hidden;
      syncRules();
    }
    function selection() {
      if (!schema) return null;
      var common = {version: 1, schema_id: schema.schema_id};
      if (override.checked && !config.overrideBox.hidden) {
        if (!syncRules()) return null;
        var params = {};
        schema.fields.forEach(function (field) {
          var el = fields[field.id];
          if (!el || el.parentNode.hidden) return;
          var value = fieldValue(field);
          if (value !== undefined) params[field.id] = value;
        });
        if (!Object.keys(params).length) return null;
        common.mode = "override"; common.parameters = params;
      } else if (choice.value.indexOf("candidate:") === 0) {
        common.mode = "candidate"; common.candidate_id = choice.value.slice(10);
      } else if (choice.value.indexOf("layout:") === 0) {
        common.mode = "layout"; common.layout_id = choice.value.slice(7);
      } else common.mode = "auto";
      return common;
    }
    function allowed() {
      if (!schema) return false;
      if (probe && probe.selection_schema_id && probe.selection_schema_id !== schema.schema_id)
        return false;
      var selected = selection();
      if (!selected || schema.selection_modes.indexOf(selected.mode) === -1) return false;
      if (selected.mode === "override") return true;
      var candidates = probe && Array.isArray(probe.candidates) ? probe.candidates : [];
      var layouts = probe && Array.isArray(probe.read_layouts) ? probe.read_layouts : [];
      if (selected.mode === "candidate") {
        return candidates.some(function (c) {
          return c.id === selected.candidate_id && c.read_supported !== false &&
            layouts.some(function (l) {
              return l.id === c.layout_id && l.read_supported !== false;
            });
        });
      }
      if (selected.mode === "layout")
        return layouts.some(function (l) {
          return l.id === selected.layout_id && l.read_supported !== false;
        });
      // Identification and readability are different: an MD/SNES header
      // may have no database title but still identify one safe ROM layout.
      // Unknown NES cartridges with no safe layout still require override.
      return !(probe && (probe.selection_required === true ||
        (Array.isArray(probe.read_layouts) &&
         !layouts.some(function (l) { return l.read_supported !== false; }))));
    }
    choice.addEventListener("change", function () {
      if (choice.value.indexOf("candidate:") === 0 && config.onCandidateTitle) {
        var id = choice.value.slice(10);
        var item = probe && Array.isArray(probe.candidates) &&
          probe.candidates.filter(function (c) { return c.id === id; })[0];
        if (item && item.title) config.onCandidateTitle(item.title, probe);
      }
      notify();
    });
    override.addEventListener("change", function () {
      fieldsBox.hidden = !override.checked;
      syncRules(); notify();
    });
    return {update: update, reset: reset, allowed: allowed,
      selection: selection, active: function () { return !panel.hidden; }};
  }
  root.RetrodeSelection = {create: create, conditionMatches: conditionMatches};
  if (typeof module !== "undefined" && module.exports)
    module.exports = root.RetrodeSelection;
})(typeof window === "undefined" ? {} : window);
