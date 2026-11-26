/* Retrode3 web v2: browser never talks to cartridge devices or shell. */
(function () {
  "use strict";
  var locale = "en", messages = {}, capabilities = null, activeJob = null;
  var fileFolder = "", jobTimer = null, slotData = null, slotFingerprint = null;
  var selectedReader = "";
  var detectedBySlot = {}, probeTarget = null, autoNames = {};
  var manualReaderBySlot = {};
  var coreState = null, corePending = false, registryRevision = null;
  var readerOptions = null, readerOptionsLoading = false, readerOptionsRequest = 0;
  var genericWidget = null;
  var writerIdentified = null;
  var writerSourcePath = "";
  var writerUploading = false;
  var writerUploadSerial = 0;
  var direct = Boolean(document.querySelector('meta[name="retrode3-transport"]'));
  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var csrf = csrfMeta ? csrfMeta.content : "";
  function apiUrl(route, query) {
    var url = direct ? route : "api.php?route=" + encodeURIComponent(route);
    if (query !== undefined) url += (direct ? "?" : "&") + "path=" + encodeURIComponent(query);
    return url;
  }
  var $ = function (id) { return document.getElementById(id); };
  function t(key) { return messages[key] || key; }
  function text(el, value) { el.textContent = value === null || value === undefined ? "" : String(value); }
  function button(label, handler) {
    var el = document.createElement("button");
    el.type = "button"; text(el, label); el.addEventListener("click", handler); return el;
  }
  function notify(message) {
    text($("toast"), message); $("toast").classList.add("visible");
    /* Toast disappears on the next user-triggered action. */
  }
  function api(route, data, query) {
    var url = apiUrl(route, query);
    var options = {credentials: "same-origin", cache: "no-store"};
    if (data !== undefined) {
      options.method = "POST";
      options.headers = {"Content-Type": "application/json", "X-CSRF-Token": csrf};
      options.body = JSON.stringify(data);
    }
    return fetch(url, options).then(function (response) {
      return response.json().catch(function () { throw new Error(t("error_generic")); })
        .then(function (body) {
          if (!response.ok) throw new Error(body.message || body.error || t("error_generic"));
          return body;
        });
    });
  }
  function fail(err) { notify(err && err.message ? err.message : t("error_generic")); }
  function humanSize(n) {
    if (n === null || n === undefined) return "—";
    if (n >= 1048576) return (n / 1048576).toFixed(2) + " MiB";
    if (n >= 1024) return (n / 1024).toFixed(1) + " KiB";
    return n + " B";
  }
  function localize() {
    document.documentElement.lang = locale;
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      var key = el.getAttribute("data-i18n");
      if (messages[key]) text(el, messages[key]);
    });
    renderReaderState();
    if (slotData) renderSlots();
    renderSelectedProbe();
    renderCores();
    renderWriterState();
  }
  function setLocale(lang) {
    if (!/^(en|de)$/.test(lang)) lang = "en";
    locale = lang; $("locale").value = lang;
    var docsRoot = "https://github.com/DragonBox-Shop/retrode3/blob/master/retrode3-web-control/v2/docs/";
    $("help-online-link").href = docsRoot + "user-guide." + lang + ".md";
    $("help-developer-link").href = docsRoot + "developer-guide." + lang + ".md";
    fetch("locales/" + lang + ".json", {cache: "no-store"})
      .then(function (r) { if (!r.ok) throw new Error("locale"); return r.json(); })
      .then(function (data) { messages = data; localize(); })
      .catch(fail);
  }
  function showTab(id) {
    document.querySelectorAll(".tab").forEach(function (el) {
      el.classList.toggle("active", el.getAttribute("data-tab") === id);
    });
    document.querySelectorAll(".page").forEach(function (el) {
      el.classList.toggle("active", el.id === id);
    });
    if (id === "writer") {
      $("writer-progress-anchor").appendChild($("job-panel"));
    } else {
      $("reader-progress-anchor").appendChild($("job-panel"));
    }
    if (id === "files") listFiles();
    if (id === "reader") loadCapabilities();
    if (id === "writer") renderWriterState();
    if (id === "settings") loadSettings();
    if (id === "plugins") loadCores();
  }
  function readers() {
    return capabilities && capabilities.systems ?
      capabilities.systems.filter(function (entry) { return entry.available; }) : [];
  }
  function readerById(id) {
    return readers().filter(function (entry) { return entry.id === id; })[0] || null;
  }
  function selectedProbeData() {
    var slot = selectedSlotId(), detected = slot && autoDetection(slot);
    if (detected && detected.state === "detected" &&
        detected.core_id === selectedReader && detected.result &&
        detected.result.system_detected !== false)
      return detected.result;
    var cached = slot && detectedBySlot[slot];
    return cached && cached.reader === selectedReader ? cached.data : null;
  }
  function genericSchema() {
    return readerOptions && readerOptions.system === selectedReader &&
      readerOptions.selection_schema || null;
  }
  function loadReaderOptions() {
    var id = selectedReader, reader = readerById(id);
    if (!reader || readerOptionsLoading ||
        (readerOptions && readerOptions.system === id)) return;
    var serial = ++readerOptionsRequest;
    readerOptionsLoading = true;
    renderReaderState();
    api("/api/reader-options/" + encodeURIComponent(id)).then(function (data) {
      if (serial !== readerOptionsRequest || selectedReader !== id) return;
      if (!data || data.system !== id || data.slot !== reader.slot ||
          !data.selection_schema)
        throw new Error(t("generic_schema_error"));
      readerOptions = data;
      readerOptionsLoading = false;
      renderSelectedProbe();
    }).catch(function (err) {
      if (serial !== readerOptionsRequest || selectedReader !== id) return;
      readerOptionsLoading = false;
      readerOptions = null;
      renderReaderState();
      fail(err);
    });
  }
  function renderGenericOptions() {
    if (!genericWidget) return;
    var schema = genericSchema();
    if (schema) genericWidget.update(selectedReader, schema, selectedProbeData());
    else if (genericWidget.active()) genericWidget.reset();
    renderReaderState();
  }
  function renderReaderState() {
    var reader = readerById(selectedReader);
    text($("selected-reader"), reader ? reader.name : t("choose_reader"));
    text($("reader-support"), reader ? reader.name : t("reader_unavailable"));
    var commands = reader && reader.capabilities && reader.capabilities.commands || [];
    $("probe").disabled = !reader || commands.indexOf("probe") === -1 || Boolean(activeJob);
    $("read").disabled = !reader || commands.indexOf("read_rom") === -1 ||
      Boolean(activeJob) || readerOptionsLoading || !genericSchema() ||
      !genericWidget || !genericWidget.allowed();
    renderWriterState();
  }
  function selectReader(id) {
    var previous = selectedReader;
    var reader = readerById(id);
    selectedReader = reader ? id : "";
    $("system").value = selectedReader;
    // A filename belongs to a reader/cartridge, not to the global dialog.
    // Preserve manual edits only when the same reader stays selected.
    if (selectedReader !== previous) {
      readerOptionsRequest += 1;
      readerOptions = null;
      readerOptionsLoading = false;
      if (genericWidget) genericWidget.reset();
      $("filename").value = reader ? suggestedFilename(reader) : "";
    } else if (reader && !$("filename").value) {
      $("filename").value = suggestedFilename(reader);
    }
    renderReaderState();
    if (slotData) renderSlots();
    renderSelectedProbe();
    if (reader) loadReaderOptions();
  }
  function selectedSlotId() {
    var reader = readerById(selectedReader);
    return reader ? reader.slot : "";
  }
  function autoDetection(slotId) {
    var entry = slotData && slotData.slots.filter(function (s) {
      return s.id === slotId && s.status === "occupied";
    })[0];
    return entry && entry.detection || null;
  }
  function suggestedFilename(reader) {
    var detected = autoDetection(reader.slot);
    if (detected && detected.state === "detected" &&
        detected.core_id === reader.id && detected.result &&
        detected.result.system_detected !== false && detected.result.title)
      return detected.result.title;
    var cached = detectedBySlot[reader.slot];
    if (cached && cached.reader === reader.id && cached.data && cached.data.title)
      return cached.data.title;
    return reader.id.toUpperCase() + "-Dump";
  }
  function renderSelectedProbe() {
    var slot = selectedSlotId();
    var detected = slot && autoDetection(slot);
    var cached = slot && detectedBySlot[slot];
    if (detected && detected.state === "detected" &&
        detected.core_id === selectedReader && detected.result &&
        detected.result.system_detected !== false) {
      renderProbe(detected.result, false);
    } else if (cached && cached.reader === selectedReader) {
      // Manual probes remain visible even if auto-detection was inconclusive.
      renderProbe(cached.data, false);
    } else {
      var box = $("game-info");
      box.innerHTML = "";
      var empty = document.createElement("p");
      empty.className = "muted";
      text(empty, detected && ["pending", "detecting"].indexOf(detected.state) !== -1 ?
        t("detecting_automatically") : t("not_detected"));
      box.appendChild(empty);
    }
    renderGenericOptions();
  }
  function voltageLabel(millivolts) {
    if (typeof millivolts !== "number" || !isFinite(millivolts) ||
        (millivolts !== 3300 && millivolts !== 5000)) return "";
    var amount = (millivolts / 1000).toFixed(1).replace(/\.0$/, "");
    return (locale === "de" ? amount.replace(".", ",") : amount) + " V";
  }
  function manualVoltageNotice(slot, identified) {
    if (!identified || identified.result.voltage_status !== "manual_required")
      return "";
    var current = voltageLabel(slot.voltage_mv);
    var required = voltageLabel(identified.result.read_voltage_mv);
    if (current && required)
      return t("voltage_manual_detail").replace("{current}", current).replace("{required}", required);
    if (required)
      return t("voltage_manual_required_voltage").replace("{required}", required);
    if (current)
      return t("voltage_manual_current_voltage").replace("{current}", current);
    return t("voltage_manual_required");
  }
  function slotIdentification(slot) {
    if (!slot || slot.status !== "occupied") return null;
    var matching = readers().filter(function (reader) { return reader.slot === slot.id; });
    var cached = detectedBySlot[slot.id];
    if (cached && cached.data) {
      var manualReader = matching.filter(function (reader) { return reader.id === cached.reader; })[0];
      // In a shared slot, only an explicit positive signature identifies an adapter.
      // A legacy one-reader manual probe may have no system_detected flag.
      var positive = cached.data.system_detected === true ||
        (matching.length === 1 && cached.data.system_detected !== false &&
         cached.data.title && cached.data.system === cached.reader);
      if (manualReader && positive) return {reader: manualReader, result: cached.data};
    }
    var automatic = slot.detection || {};
    if (automatic.state === "detected" && automatic.result &&
        automatic.result.system_detected !== false) {
      var autoReader = matching.filter(function (reader) { return reader.id === automatic.core_id; })[0];
      if (autoReader) return {reader: autoReader, result: automatic.result};
    }
    return null;
  }
  function renderSlots() {
    if (!slotData) return;
    var list = $("slot-list"); list.innerHTML = "";
    var occupied = slotData.slots.filter(function (slot) { return slot.status === "occupied"; });
    text($("slots-summary"), occupied.length ? occupied.length + " " + t("slots_occupied") : t("no_occupied_slots"));
    slotData.slots.forEach(function (slot) {
      var matching = readers().filter(function (reader) { return reader.slot === slot.id; });
      var identified = slotIdentification(slot);
      var automatic = slot.detection || {};
      var waiting = automatic.state === "pending" || automatic.state === "detecting";
      // One compatible reader needs no manual system dropdown, even if the
      // header probe fails. The user must still be able to run Detect manually.
      var manualChoice = !identified && slot.status === "occupied" && !waiting && matching.length > 1;
      var chosenManually = manualReaderBySlot[slot.id] || "";
      var isSelected = identified ? identified.reader.id === selectedReader :
        manualChoice ? Boolean(chosenManually && chosenManually === selectedReader) :
        slot.status === "occupied" && matching.length === 1 &&
          matching[0].id === selectedReader;
      // A select may not be nested in a button. The card is a plain container
      // with a separate focusable card button and manual reader selector.
      var card = document.createElement("div");
      card.className = "slot-card" + (slot.status === "occupied" ? " occupied" : "") +
        (isSelected ? " selected" : "");
      var main = document.createElement("button");
      main.type = "button";
      main.className = "slot-card-main";
      main.setAttribute("aria-pressed", isSelected ? "true" : "false");
      main.disabled = slot.status !== "occupied";
      var title = document.createElement("strong");
      text(title, slot.name); main.appendChild(title);
      var state = document.createElement("span");
      text(state, slot.status === "occupied" ? t("slot_occupied") :
        slot.status === "empty" ? t("slot_empty") :
        slot.status === "unavailable" ? t("slot_unavailable") : t("slot_unknown"));
      main.appendChild(state);
      var hint = document.createElement("small");
      var systemName = identified ? identified.reader.name :
        slot.status === "occupied" && matching.length ? (
          waiting ? t("detecting_automatically") :
            matching.length === 1 ? matching[0].name : t("slot_system_unrecognized")) :
        (slot.status === "occupied" ? t("slot_no_reader") :
          matching.map(function (r) { return r.name; }).join(", "));
      text(hint, systemName);
      main.appendChild(hint);
      if (slot.status === "occupied" && matching.length) {
        var game = document.createElement("span");
        game.className = "slot-game";
        var gameTitle = identified && identified.result.title;
        text(game, identified ? (gameTitle || identified.reader.name) :
          (waiting ? t("detecting_automatically") : t("unknown")));
        main.appendChild(game);
        var voltageText = manualVoltageNotice(slot, identified);
        if (voltageText) {
          var voltageNotice = document.createElement("small");
          text(voltageNotice, voltageText);
          main.appendChild(voltageNotice);
        }
      }
      card.appendChild(main);
      var picker = null;
      if (manualChoice) {
        var manual = document.createElement("div");
        manual.className = "slot-manual";
        var manualLabel = document.createElement("label");
        var pickerId = "slot-reader-" + slot.id;
        manualLabel.setAttribute("for", pickerId);
        text(manualLabel, t("slot_manual_label"));
        manual.appendChild(manualLabel);
        picker = document.createElement("select");
        picker.id = pickerId;
        picker.className = "slot-manual-select";
        picker.setAttribute("data-slot", slot.id);
        picker.disabled = Boolean(activeJob);
        var placeholder = document.createElement("option");
        placeholder.value = "";
        text(placeholder, t("slot_manual_placeholder"));
        picker.appendChild(placeholder);
        matching.forEach(function (reader) {
          var option = document.createElement("option");
          option.value = reader.id;
          text(option, reader.name);
          picker.appendChild(option);
        });
        picker.value = matching.some(function (reader) {
          return reader.id === chosenManually;
        }) ? chosenManually : "";
        picker.addEventListener("change", function () {
          var current = slotData && slotData.slots.filter(function (item) {
            return item.id === slot.id;
          })[0];
          if (activeJob || !current || current.status !== "occupied" ||
              slotIdentification(current)) {
            renderSlots();
            return;
          }
          var choice = matching.filter(function (reader) {
            return reader.id === picker.value;
          })[0];
          if (choice) {
            manualReaderBySlot[slot.id] = choice.id;
            // Choosing a core is not proof of adapter identity. Never
            // fabricate a probe result or change voltage from the browser.
            selectReader(choice.id);
          } else {
            delete manualReaderBySlot[slot.id];
            if (selectedSlotId() === slot.id) selectReader("");
            else renderSlots();
          }
        });
        manual.appendChild(picker);
        var disclaimer = document.createElement("small");
        text(disclaimer, t("slot_manual_note"));
        manual.appendChild(disclaimer);
        card.appendChild(manual);
      }
      main.addEventListener("click", function () {
        if (identified) selectReader(identified.reader.id);
        else if (picker) picker.focus();
        else if (waiting) notify(t("detecting_automatically"));
        else if (matching.length === 1) selectReader(matching[0].id);
        else notify(t("slot_no_reader"));
      });
      list.appendChild(card);
    });
  }
  function refreshSlots() {
    return api("/api/slots").then(function (data) {
      if (!data || !Array.isArray(data.slots)) return;
      if (typeof data.registry_revision === "number") {
        var changed = registryRevision !== null && registryRevision !== data.registry_revision;
        registryRevision = data.registry_revision;
        if (changed) {
          var oldSlot = selectedSlotId();
          if (oldSlot && autoNames[oldSlot] && $("filename").value === autoNames[oldSlot])
            $("filename").value = selectedReader.toUpperCase() + "-Dump";
          writerIdentified = null;
          detectedBySlot = {};
          manualReaderBySlot = {};
          autoNames = {};
          if (!activeJob) probeTarget = null;
          if (genericWidget) genericWidget.reset();
          slotData = data;
          slotFingerprint = null;
          renderSelectedProbe();
          loadCores();
          return loadCapabilities();
        }
      }
      var previousSlots = slotData && slotData.slots || [];
      data.slots.forEach(function (slot) {
        var previous = previousSlots.filter(function (entry) { return entry.id === slot.id; })[0];
        if (typeof writerIdentified !== "undefined" && writerIdentified &&
            writerIdentified.slot === slot.id && previous &&
            previous.status === "occupied" && slot.status === "empty")
          writerIdentified = null;
        if (!previous || previous.status !== slot.status || slot.status !== "occupied") {
          delete detectedBySlot[slot.id];
          delete manualReaderBySlot[slot.id];
          if (slot.id === selectedSlotId()) {
            if (genericWidget) genericWidget.reset();
          }
          if (slot.status !== "occupied" && selectedSlotId() === slot.id &&
              autoNames[slot.id] && $("filename").value === autoNames[slot.id]) {
            $("filename").value = selectedReader.toUpperCase() + "-Dump";
          }
          delete autoNames[slot.id];
        }
      });
      slotData = data;
      var fingerprint = data.slots.map(function (slot) { return slot.id + ":" + slot.status; }).join("|");
      if (probeTarget && data.slots.some(function (slot) {
        return slot.id === probeTarget.slot && slot.status !== probeTarget.status;
      })) probeTarget = null;
      if (fingerprint !== slotFingerprint && !activeJob) {
        slotFingerprint = fingerprint;
        var occupied = data.slots.filter(function (slot) { return slot.status === "occupied"; });
        // Never implicitly select the first adapter for an unrecognized slot.
        var chosen = occupied.map(function (slot) {
          var identified = slotIdentification(slot);
          if (identified) return identified.reader.id;
          var available = readers().filter(function (reader) {
            return reader.slot === slot.id;
          });
          if (available.length === 1) return available[0].id;
          var manual = manualReaderBySlot[slot.id];
          return available.some(function (r) { return r.id === manual; }) ? manual : "";
        }).filter(function (id) { return Boolean(id); });
        selectReader(chosen.indexOf(selectedReader) !== -1 ?
          selectedReader : (chosen[0] || ""));
      }
      // Follow a new positive slot identification once. Do not repeatedly
      // override a user's explicit manual reader choice on later refreshes.
      data.slots.forEach(function (slot) {
        var current = slot.detection || {};
        var previous = previousSlots.filter(function (entry) { return entry.id === slot.id; })[0];
        var prior = previous && previous.detection || {};
        if (!activeJob && slot.status === "occupied" &&
            current.state === "detected" && current.core_id && current.result &&
            current.result.system_detected !== false &&
            (prior.state !== "detected" || prior.core_id !== current.core_id ||
             !prior.result || prior.result.system_detected === false) &&
            readers().some(function (reader) {
              return reader.id === current.core_id && reader.slot === slot.id;
            })) {
          selectReader(current.core_id);
        }
      });
      // /api/slots is polled every 1.5 seconds. Rebuilding an open native
      // select on each poll would close the OS dropdown mid-choice.
      var focused = document.activeElement;
      var preservePicker = focused && focused.classList &&
        focused.classList.contains("slot-manual-select") &&
        previousSlots.length === data.slots.length &&
        data.slots.every(function (slot) {
          return previousSlots.some(function (prior) {
            return prior.id === slot.id && prior.status === slot.status;
          });
        }) && data.slots.some(function (slot) {
          return slot.id === focused.getAttribute("data-slot") &&
            slot.status === "occupied" && !slotIdentification(slot) &&
            (slot.detection || {}).state !== "detecting" &&
            (slot.detection || {}).state !== "pending";
        });
      if (!preservePicker) renderSlots();
      var chosen = selectedSlotId();
      if (chosen) {
        var detected = autoDetection(chosen);
        var name = detected && detected.state === "detected" &&
          detected.core_id === selectedReader && detected.result &&
          detected.result.system_detected !== false && detected.result.title;
        if (name && autoNames[chosen] !== name) {
          if (!$("filename").value || /^[a-z0-9_-]+-Dump$/i.test($("filename").value) ||
              $("filename").value === autoNames[chosen]) $("filename").value = name;
          autoNames[chosen] = name;
        }
      }
      renderSelectedProbe();
    }).catch(function (error) {
      text($("slots-summary"), t("slot_unavailable"));
      fail(error);
    });
  }
  function loadCapabilities() {
    return api("/api/capabilities").then(function (data) {
      capabilities = data;
      text($("connection"), t("connected"));
      var select = $("system"), previous = selectedReader;
      select.innerHTML = "";
      var initial = document.createElement("option");
      initial.value = ""; text(initial, t("choose_reader")); select.appendChild(initial);
      readers().forEach(function (reader) {
        var option = document.createElement("option");
        option.value = reader.id; text(option, reader.name); select.appendChild(option);
      });
      selectReader(previous);
      updateWriterReaders();
      if (!activeJob) slotFingerprint = null;
      return refreshSlots();
    }).catch(function (error) {
      text($("connection"), t("offline"));
      $("probe").disabled = $("read").disabled = true;
      fail(error);
    });
  }
  function renderProbe(data, updateFilename) {
    var box = $("game-info");
    while (box.firstChild) box.removeChild(box.firstChild);
    var fields = [
      ["detected_title", data.title || t("unknown")],
      ["detected_mapping", data.mapping || t("unknown")],
      ["detected_size", humanSize(data.size_bytes)]
    ];
    fields.forEach(function (pair) {
      var row = document.createElement("div"), left = document.createElement("span"), right = document.createElement("strong");
      row.className = "keyval"; text(left, t(pair[0])); text(right, pair[1]);
      row.appendChild(left); row.appendChild(right); box.appendChild(row);
    });
    if (updateFilename !== false && data.title) $("filename").value = data.title;
    renderGenericOptions();
  }
  function flashReader() {
    return readerById($("writer-system").value);
  }
  function flashSupports(reader, action) {
    return !!reader && (reader.capabilities.commands || []).indexOf(action) !== -1;
  }
  function updateWriterReaders() {
    var select = $("writer-system"), preferred = select.value;
    select.innerHTML = "";
    var empty = document.createElement("option");
    empty.value = ""; text(empty, t("choose_reader")); select.appendChild(empty);
    readers().forEach(function (reader) {
      if (!flashSupports(reader, "probe_flash")) return;
      var option = document.createElement("option");
      option.value = reader.id; text(option, reader.name); select.appendChild(option);
    });
    if (readerById(preferred) && flashSupports(readerById(preferred), "probe_flash"))
      select.value = preferred;
    else if (readerById(selectedReader) &&
             flashSupports(readerById(selectedReader), "probe_flash"))
      select.value = selectedReader;
    else if (select.options.length === 2) select.value = select.options[1].value;
    renderWriterState();
  }
  function renderWriterState() {
    var reader = flashReader();
    var id = reader && reader.id;
    var slot = reader && slotData && slotData.slots.filter(function (entry) {
      return entry.id === reader.slot;
    })[0];
    var occupied = slot && slot.status === "occupied";
    if (!reader || !writerIdentified ||
        writerIdentified.reader !== id || writerIdentified.slot !== reader.slot)
      writerIdentified = null;
    text($("writer-slot-status"), reader ?
      (reader.name + " · " + reader.slot + " · " +
       t(occupied ? "writer_cart_inserted" : "writer_insert_cart")) :
      t("writer_missing_core"));
    var info = writerIdentified && writerIdentified.data;
    text($("writer-flash-status"), info ?
      t("writer_detected") + ": 0x" + Number(info.manufacturer_id).toString(16) +
      " / 0x" + Number(info.device_id).toString(16) +
      " · " + humanSize(info.capacity_bytes) +
      " · " + info.sector_count + " " + t("progress_sectors") :
      t("writer_not_detected"));
    var erase = $("writer-erase").checked;
    var write = $("writer-program").checked;
    var verify = $("writer-check").checked;
    var passes = Number($("writer-verify-passes").value);
    var validPasses = !verify || (Number.isInteger(passes) && passes >= 1 &&
                                  passes <= 99);
    var selected = erase || write || verify;
    var sourceReady = Boolean(writerSourcePath) && !writerUploading;
    var sourceRequired = write || verify;
    $("writer-verify-passes").disabled = !verify || Boolean(activeJob);
    $("writer-detect").disabled = !flashSupports(reader, "probe_flash") ||
      Boolean(activeJob);
    $("writer-start").disabled = !writerIdentified || !selected || !validPasses ||
      (sourceRequired && !sourceReady) || writerUploading || Boolean(activeJob) ||
      !flashSupports(reader, "flash_operation");
    text($("writer-operation-hint"), !selected ? t("writer_choose_operation") :
      !validPasses ? t("writer_bad_passes") :
      sourceRequired && !sourceReady ? t("writer_upload_required") :
      erase && !writerSourcePath ? t("writer_erase_all_hint") :
      !verify ? t("writer_not_verified_hint") : "");
  }
  function uploadWriterFile() {
    var reader = flashReader();
    var selected = $("writer-file").files && $("writer-file").files[0];
    var serial = ++writerUploadSerial;
    writerSourcePath = "";
    text($("writer-upload-status"), "");
    renderWriterState();
    if (!selected) return;
    if (!reader) return notify(t("writer_missing_core"));
    if (selected.size < 512 || selected.size > 4194304 ||
        selected.size % 2 !== 0) {
      text($("writer-upload-status"), t("writer_upload_bad_size"));
      return;
    }
    if (activeJob || writerUploading) return;
    writerUploading = true;
    renderWriterState();
    text($("writer-upload-status"), t("writer_uploading"));
    var data, url, headers = {"X-CSRF-Token": csrf};
    if (direct) {
      url = "/api/files/upload?folder=" + encodeURIComponent(reader.folder) +
        "&filename=" + encodeURIComponent(selected.name);
      headers["Content-Type"] = "application/octet-stream";
      data = selected;
    } else {
      url = "rom-upload.php";
      data = new FormData();
      data.append("folder", reader.folder);
      data.append("rom", selected, selected.name);
    }
    fetch(url, {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: headers, body: data
    }).then(function (reply) {
      return reply.json().then(function (result) {
        if (!reply.ok || !result.ok || !result.path)
          throw new Error(result.message || result.error || t("writer_upload_failed"));
        return result;
      });
    }).then(function (result) {
      if (serial !== writerUploadSerial ||
          !flashReader() || flashReader().id !== reader.id) return;
      writerSourcePath = result.path;
      text($("writer-upload-status"), t("writer_uploaded") + ": " +
        selected.name + " (" + humanSize(result.size) + ")");
    }).catch(function (err) {
      if (serial !== writerUploadSerial) return;
      text($("writer-upload-status"), err.message || t("writer_upload_failed"));
    }).then(function () {
      writerUploading = false;
      renderWriterState();
    });
  }
  function startFlashJob(action) {
    var reader = flashReader();
    if (!reader || !flashSupports(reader, action) || activeJob) return;
    var payload = {system: reader.id, command: action};
    if (action === "probe_flash") {
      writerIdentified = null;
    } else if (action === "flash_operation") {
      var erase = Boolean($("writer-erase").checked);
      var write = Boolean($("writer-program").checked);
      var verify = Boolean($("writer-check").checked);
      var passes = verify ? Number($("writer-verify-passes").value) : 0;
      if (!writerIdentified || !(erase || write || verify) ||
          (verify && (!Number.isInteger(passes) || passes < 1 || passes > 99)) ||
          ((write || verify) && !writerSourcePath) || writerUploading) {
        renderWriterState();
        return;
      }
      payload.erase = erase;
      payload.write = write;
      payload.verify = verify;
      payload.verify_passes = passes;
      // Erase alone with no ROM erases the entire chip. If a ROM was
      // uploaded, erase just the sectors covering its length.
      if (writerSourcePath) payload.source = writerSourcePath;
    } else return;
    renderWriterState();
    api("/api/jobs", payload).then(function (job) {
      activeJob = job.id;
      $("job-panel").hidden = false;
      $("cancel").disabled = false;
      $("writer-progress-anchor").appendChild($("job-panel"));
      renderJob(job);
      renderWriterState();
      schedulePoll();
    }).catch(function (err) { renderWriterState(); fail(err); });
  }
  function startJob(command) {
    var reader = readerById(selectedReader);
    if (!reader || (reader.capabilities.commands || []).indexOf(command) === -1)
      return notify(t("choose_reader"));
    var payload = {system: selectedReader, command: command};
    if (command === "read_rom") {
      payload.filename = $("filename").value;
      if (!genericSchema() || !genericWidget || !genericWidget.allowed())
        return notify(t("generic_invalid"));
      payload.selection = genericWidget.selection();
    }
    $("read").disabled = $("probe").disabled = true;
    if (command === "probe") {
      var target = selectedSlotId();
      probeTarget = target ? {slot: target, reader: selectedReader,
        fingerprint: slotData && slotData.slots.filter(function (s) { return s.id === target; })[0]} : null;
      if (probeTarget) {
        probeTarget.status = probeTarget.fingerprint && probeTarget.fingerprint.status;
        delete detectedBySlot[target];
        renderSlots();
      }
    }
    api("/api/jobs", payload).then(function (job) {
      activeJob = job.id;
      renderCores();
      $("job-panel").hidden = false;
      $("cancel").disabled = false;
      renderJob(job);
      schedulePoll();
    }).catch(function (err) {
      if (command === "probe") probeTarget = null;
      $("read").disabled = $("probe").disabled = false; fail(err);
    });
  }
  function renderJob(job) {
    var progress = job.progress || {};
    // Same progress widget for ROM reads and future Flash jobs.
    // Flash progress is phase-local: erase sectors, program bytes, verify bytes.
    var phases = {
      read_rom: "progress_phase_read_rom",
      erase: "progress_phase_erase",
      program: "progress_phase_program",
      verify: "progress_phase_verify"
    };
    var phase = Object.prototype.hasOwnProperty.call(phases, progress.phase) ?
      phases[progress.phase] : null;
    var busy = job.status === "running" || job.status === "cancelling";
    var label = busy && phase ? t(phase) : t(job.status);
    if (busy && phase && job.status === "cancelling")
      label += " · " + t("cancelling");
    text($("job-label"), label);
    var percent = typeof progress.percent === "number" && isFinite(progress.percent) ?
      Math.floor(Math.max(0, Math.min(100, progress.percent))) : 0;
    text($("job-percent"), percent + "%");
    $("job-fill").style.width = percent + "%";
    var detail = "";
    if (progress.units === "sectors" &&
        typeof progress.units_done === "number" &&
        typeof progress.units_total === "number" &&
        isFinite(progress.units_done) && isFinite(progress.units_total) &&
        progress.units_done >= 0 && progress.units_total > 0 &&
        progress.units_done <= progress.units_total) {
      detail = progress.units_done + " / " + progress.units_total +
        " " + t("progress_sectors");
    } else if (typeof progress.bytes_total === "number" &&
               typeof progress.bytes_done === "number" &&
               isFinite(progress.bytes_total) && isFinite(progress.bytes_done) &&
               progress.bytes_total > 0 && progress.bytes_done >= 0 &&
               progress.bytes_done <= progress.bytes_total) {
      detail = humanSize(progress.bytes_done) + " / " +
        humanSize(progress.bytes_total);
    }
    if (progress.phase === "verify" &&
        Number.isInteger(progress.verify_pass) &&
        Number.isInteger(progress.verify_passes) &&
        progress.verify_passes > 1)
      detail += " · " + t("writer_verify_pass") + " " +
        progress.verify_pass + "/" + progress.verify_passes;
    // The CLI reports an elapsed-phase monotonic throughput figure,
    // independent of browser polling or network response timing.
    var rateAvailable = (progress.phase === "program" || progress.phase === "verify") &&
      typeof progress.bytes_per_second === "number" &&
      isFinite(progress.bytes_per_second) && progress.bytes_per_second > 0;
    var speedDisplay = $("job-speed");
    if (rateAvailable) {
      var kibPerSecond = progress.bytes_per_second / 1024;
      text(speedDisplay, kibPerSecond.toLocaleString(undefined, {
        minimumFractionDigits: 1, maximumFractionDigits: 1
      }) + " KiB/s");
      speedDisplay.hidden = false;
    } else {
      speedDisplay.hidden = true;
      text(speedDisplay, "");
    }
    text($("job-detail"), detail);
    var result = job.command === "read_rom" && job.status === "done" && job.result || null;
    var identity = result && result.identity || {};
    var verification = result && result.verification || {};
    var title = result && (identity.title || result.title) || "";
    var configuration = result && result.read_configuration;
    var configurationText = configuration && typeof configuration === "object" &&
      !Array.isArray(configuration) ? Object.keys(configuration).map(function (id) {
        return id + ": " + configuration[id];
      }).join(" · ") : "";
    var verifyText = verification.status ?
      t("verification_" + verification.status) : "";
    if ((job.command === "write_flash" || job.command === "verify_flash" ||
         job.command === "flash_operation") &&
        job.status === "done" && job.result && job.result.flash_verification) {
      var flashResult = job.result.flash_verification;
      text($("job-result-details"), flashResult.verified ?
        t("writer_verified") + ": " +
          humanSize(flashResult.bytes_compared) + " (" +
          flashResult.passes_completed + " " + t("writer_verify_passes_label") + ")" :
        t("writer_finished_unverified"));
    } else text($("job-result-details"), result ?
      (title ? title + " · " : "") +
      (result.layout_id ? result.layout_id + " · " : "") +
      (configurationText ? configurationText + " · " : "") +
      (result.crc32 ? "CRC32 " + result.crc32 : "") +
      (verifyText ? " · " + verifyText : "") +
      (verification.status === "mismatch" && verification.expected && verification.actual ?
        " (" + verification.expected + " / " + verification.actual + ")" : "") : "");
    if (job.status === "done") {
      if (job.command === "probe") {
        var target = probeTarget;
        var current = target && slotData && slotData.slots.filter(function (s) { return s.id === target.slot; })[0];
        if (target && current && current.status === "occupied" && current.status === target.status) {
          detectedBySlot[target.slot] = {reader: target.reader, data: job.result || {}};
          if (target.reader === selectedReader) renderProbe(job.result || {}, true);
          renderSlots();
        }
        probeTarget = null;
        notify(t("probe_finished"));
      } else if (job.command === "probe_flash") {
        writerIdentified = {reader: job.system, slot: (readerById(job.system) || {}).slot,
          data: job.result || {}};
        renderWriterState();
        notify(t("writer_detected"));
      } else if (job.command === "write_flash" ||
                 job.command === "verify_flash" ||
                 job.command === "flash_operation") {
        notify(job.result && job.result.flash_verification &&
          job.result.flash_verification.verified ?
          t("writer_verified") : t("writer_finished_unverified"));
      } else {
        var verify = job.result && job.result.verification;
        notify(t("read_finished") + (verify && verify.status ?
          " · " + t("verification_" + verify.status) : ""));
      }
    } else if (job.status === "failed") {
      if (job.command === "probe") probeTarget = null;
      if (job.command === "probe_flash") writerIdentified = null;
      renderWriterState();
      notify(t("failed") + ": " + (job.error && (job.error.message || job.error.code) || t("unknown")));
    } else if (job.status === "cancelled") {
      if (job.command === "probe") probeTarget = null;
      notify(t("cancelled"));
    }
  }
  function schedulePoll() {
    if (jobTimer) clearTimeout(jobTimer);
    jobTimer = setTimeout(pollJob, 650);
  }
  function pollJob() {
    if (!activeJob) return;
    api("/api/jobs/" + activeJob).then(function (job) {
      renderJob(job);
      if (["done", "failed", "cancelled"].indexOf(job.status) === -1) schedulePoll();
      else {
        activeJob = null;
        renderCores();
        renderWriterState();
        $("cancel").disabled = true;
        loadCapabilities();
        loadCores();
      }
    }).catch(function (err) {
      fail(err); schedulePoll();
    });
  }
  function listFiles() {
    api("/api/files", undefined, fileFolder).then(function (data) {
      fileFolder = data.path;
      var breadcrumbs = $("breadcrumb");
      breadcrumbs.innerHTML = "";
      var rootButton = button("ROMs", function () { fileFolder = ""; listFiles(); });
      breadcrumbs.appendChild(rootButton);
      var fragments = fileFolder ? fileFolder.split("/") : [], prefix = "";
      fragments.forEach(function (part) {
        prefix += (prefix ? "/" : "") + part;
        var next = prefix;
        var slash = document.createTextNode(" / "); breadcrumbs.appendChild(slash);
        breadcrumbs.appendChild(button(part, function () { fileFolder = next; listFiles(); }));
      });
      var body = $("file-rows");
      body.innerHTML = "";
      if (!data.items.length) {
        var empty = document.createElement("tr"), cell = document.createElement("td");
        cell.colSpan = 4; cell.className = "muted"; text(cell, t("no_files"));
        empty.appendChild(cell); body.appendChild(empty);
      }
      data.items.forEach(function (item) {
        var row = document.createElement("tr");
        var name = document.createElement("td");
        if (item.directory) {
          name.appendChild(button("📁 " + item.name, function () { fileFolder = item.path; listFiles(); }));
        } else text(name, "📄 " + item.name);
        row.appendChild(name);
        var size = document.createElement("td"); text(size, humanSize(item.size)); row.appendChild(size);
        var time = document.createElement("td");
        text(time, new Date(item.modified * 1000).toLocaleString(locale)); row.appendChild(time);
        var actions = document.createElement("td");
        if (!item.directory) {
          actions.appendChild(button(t("download"), function () {
            window.location.href = apiUrl("/api/files/download", item.path);
          }));
        }
        actions.appendChild(button(t("rename"), function () {
          var destination = prompt(t("prompt_move"), item.path);
          if (!destination || destination === item.path) return;
          api("/api/files/move", {source: item.path, destination: destination})
            .then(function () { notify(t("file_updated")); listFiles(); }).catch(fail);
        }));
        actions.appendChild(button(t("delete"), function () {
          if (!confirm(t("confirm_delete"))) return;
          api("/api/files/delete", {path: item.path})
            .then(function () { notify(t("file_deleted")); listFiles(); }).catch(fail);
        }));
        row.appendChild(actions); body.appendChild(row);
      });
    }).catch(fail);
  }

  function renderCores() {
    var list = $("core-list");
    list.innerHTML = "";
    if (!coreState) {
      text($("cores-summary"), t("checking"));
      return;
    }
    if (!coreState.available) {
      text($("cores-summary"), t(coreState.reason === "cli_not_executable" ?
        "core_cli_not_executable" : coreState.reason === "cli_missing" ?
        "core_cli_missing" : "core_cli_error"));
      return;
    }
    text($("cores-summary"), coreState.cores.length ?
      coreState.cores.length + " " + t("core_found") +
      (!coreState.control_enabled ? " · " + t("core_readonly") : "") :
      t("core_none_installed"));
    coreState.cores.forEach(function (core) {
      var card = document.createElement("div");
      card.className = "core-card";
      var header = document.createElement("div");
      header.className = "core-head";
      var name = document.createElement("strong");
      text(name, core.name);
      header.appendChild(name);
      var badge = document.createElement("span");
      badge.className = "tag";
      text(badge, t(core.enabled ? "core_enabled" : "core_disabled"));
      header.appendChild(badge);
      card.appendChild(header);
      var detail = document.createElement("p");
      detail.className = "muted small";
      var stateKey = "core_status_" + core.status;
      text(detail, t("core_version") + ": " + core.version +
        " · " + t("core_slot") + ": " + core.slot +
        " · " + (messages[stateKey] ? t(stateKey) : core.status) +
        " · " + t(core.usable ? "core_usable" : "core_not_usable"));
      card.appendChild(detail);
      var actions = document.createElement("p");
      actions.className = "muted small";
      text(actions, t("core_actions") + ": " +
        (core.actions.length ? core.actions.join(", ") : t("core_no_actions")));
      card.appendChild(actions);
      var toggle = button(t(core.enabled ? "core_disable" : "core_enable"), function () {
        if (core.enabled && !confirm(t("core_confirm_disable"))) return;
        corePending = true;
        renderCores();
        api("/api/cores/toggle", {id: core.id, enabled: !core.enabled})
          .then(function () { notify(t("core_saved")); }).catch(fail)
          .then(function () {
            corePending = false;
            loadCores();
            loadCapabilities();
          });
      });
      toggle.className = "btn secondary";
      toggle.disabled = !coreState.control_enabled || corePending || Boolean(activeJob) ||
        (core.enabled ? ["ready", "discovered", "incompatible"].indexOf(core.status) === -1 :
                        core.status !== "disabled");
      card.appendChild(toggle);
      list.appendChild(card);
    });
  }
  function loadCores() {
    return api("/api/cores").then(function (result) {
      if (!result || !Array.isArray(result.cores)) throw new Error(t("error_generic"));
      coreState = result;
      renderCores();
    }).catch(function (error) {
      coreState = {available: false, control_enabled: false, cores: [], reason: "cli_error"};
      renderCores();
      fail(error);
    });
  }
  function loadDeveloper() {
    if (!direct || !$("developer-panel")) return;
    $("developer-panel").hidden = false;
    api("/api/developer/ssh").then(function (data) {
      $("developer-locked").hidden = data.configured || data.setup_allowed;
      $("developer-setup").hidden = !data.setup_allowed;
      $("developer-controls").hidden = !data.configured;
      text($("ssh-status"), data.running ? t("status_connected") : t("status_disconnected"));
      $("ssh-enable").disabled = data.running;
      $("ssh-disable").disabled = !data.enabled && !data.running;
    }).catch(fail);
  }
  function saveDeveloperPassword(initial) {
    var p = $(initial ? "developer-new" : "developer-change-new");
    var r = $(initial ? "developer-repeat" : "developer-change-repeat");
    var data = {action: initial ? "setup" : "change_password",
                new_password: p.value, repeat_password: r.value};
    if (!initial) data.developer_password = $("developer-password").value;
    p.value = ""; r.value = ""; $("developer-password").value = "";
    api("/api/developer/ssh", data).then(function () {
      notify(t("developer_saved")); loadDeveloper();
    }).catch(fail);
  }
  function changeSSH(action) {
    var data = {action: action, developer_password: $("developer-password").value};
    $("developer-password").value = "";
    api("/api/developer/ssh", data).then(loadDeveloper).catch(fail);
  }
  function loadSettings() {
    loadDeveloper();
    loadCores();
    api("/api/settings").then(function (data) {
      text($("device-time"), data.time); text($("device-timezone"), data.timezone);
    }).catch(fail);
    api("/api/wifi/status").then(function (data) {
      text($("wifi-status"), !data.available ? t("status_no_wifi") :
        data.connected ? t("status_connected") + (data.ssid ? " · " + data.ssid : "") :
        data.associated ? t("wifi_associated_no_ip") : t("status_disconnected"));
      text($("wifi-ip"), data.ipv4 || "—");
      text($("wifi-interface"), data.interface || "—");
      var hint = data.warning === "legacy_helper_does_not_detect_interface" ?
        t("wifi_legacy_warning") :
        data.warning === "legacy_helper_unavailable" ? t("wifi_helper_warning") :
        !data.available ? t("wifi_not_found_detail") : "";
      text($("wifi-diagnostic"), hint);
    }).catch(fail);
  }
  function bind() {
    if (direct && $("ssh-enable")) {
      $("developer-save").addEventListener("click", function () { saveDeveloperPassword(true); });
      $("developer-change-save").addEventListener("click", function () { saveDeveloperPassword(false); });
      $("ssh-enable").addEventListener("click", function () { changeSSH("enable"); });
      $("ssh-disable").addEventListener("click", function () { changeSSH("disable"); });
    }
    $("locale").addEventListener("change", function () { setLocale(this.value); });
    $("refresh-cores").addEventListener("click", loadCores);
    document.querySelectorAll(".tab").forEach(function (tab) {
      tab.addEventListener("click", function () { showTab(tab.getAttribute("data-tab")); });
    });
    $("advanced-toggle").addEventListener("click", function () {
      var expanded = $("advanced").hidden;
      $("advanced").hidden = !expanded;
      $("advanced-toggle").setAttribute("aria-expanded", String(expanded));
    });
    $("system").addEventListener("change", function () { selectReader(this.value); });
    genericWidget = window.RetrodeSelection.create({
      panel: $("generic-selection"),
      choiceBox: $("generic-choice-control"), choice: $("generic-choice"),
      overrideBox: $("generic-override-box"), override: $("generic-override"),
      fields: $("generic-override-fields"), hint: $("generic-selection-hint"),
      overrideHint: $("generic-override-hint"), translate: t,
      onChange: renderReaderState,
      onCandidateTitle: function (title, probe) {
        var current = $("filename").value;
        if (!current || current === probe.title ||
            /^[a-z0-9_-]+-Dump$/i.test(current) ||
            current === autoNames[selectedSlotId()])
          $("filename").value = title;
      }
    });
    $("probe").addEventListener("click", function () { startJob("probe"); });
    $("read").addEventListener("click", function () { startJob("read_rom"); });
    $("writer-system").addEventListener("change", function () {
      writerIdentified = null;
      writerSourcePath = "";
      ++writerUploadSerial;
      $("writer-file").value = "";
      text($("writer-upload-status"), "");
      renderWriterState();
    });
    $("writer-file").addEventListener("change", uploadWriterFile);
    $("writer-detect").addEventListener("click", function () { startFlashJob("probe_flash"); });
    $("writer-start").addEventListener("click", function () { startFlashJob("flash_operation"); });
    ["writer-erase", "writer-program", "writer-check", "writer-verify-passes"].forEach(function (id) {
      $(id).addEventListener("change", renderWriterState);
      $(id).addEventListener("input", renderWriterState);
    });
    $("cancel").addEventListener("click", function () {
      if (activeJob) api("/api/jobs/" + activeJob + "/cancel", {}).catch(fail);
    });
    $("refresh-files").addEventListener("click", listFiles);
    $("new-folder").addEventListener("click", function () {
      var folder = prompt(t("prompt_folder"));
      if (!folder) return;
      api("/api/files/mkdir", {path: fileFolder ? fileFolder + "/" + folder : folder})
        .then(function () { notify(t("folder_created")); listFiles(); }).catch(fail);
    });
    $("scan-wifi").addEventListener("click", function () {
      api("/api/wifi/scan").then(function (data) {
        var list = $("wifi-networks"); list.innerHTML = "";
        if (!data.networks || !data.networks.length) {
          notify(t("wifi_scan_empty"));
          return;
        }
        data.networks.forEach(function (network) {
          var row = document.createElement("div"), btn = button(network.ssid, function () {
            $("wifi-ssid").value = network.ssid;
          });
          row.className = "network"; row.appendChild(btn);
          var signal = document.createElement("small");
          text(signal, network.dbm + " dBm"); row.appendChild(signal); list.appendChild(row);
        });
      }).catch(fail);
    });
    $("connect-wifi").addEventListener("click", function () {
      api("/api/wifi/connect", {ssid: $("wifi-ssid").value, password: $("wifi-password").value})
        .then(function () { $("wifi-password").value = ""; loadSettings(); }).catch(fail);
    });
    $("disconnect-wifi").addEventListener("click", function () {
      if (!confirm(t("confirm_disconnect"))) return;
      api("/api/wifi/disconnect", {}).then(loadSettings).catch(fail);
    });
  }
  function resumeJob() {
    api("/api/jobs/active").then(function (job) {
      if (!job.id || job.automatic) return;
      if (["probe_flash", "write_flash", "verify_flash", "flash_operation"].indexOf(job.command) !== -1) {
        showTab("writer");
        $("writer-system").value = job.system;
      }
      $("job-panel").hidden = false;
      renderJob(job);
      if (["done", "failed", "cancelled"].indexOf(job.status) === -1) {
        activeJob = job.id;
        $("cancel").disabled = false;
        $("read").disabled = $("probe").disabled = true;
        schedulePoll();
      } else $("cancel").disabled = true;
    }).catch(function () { /* Older backends may not support /active. */ });
  }
  function start() {
    bind();
    var saved = (navigator.language || "").toLowerCase().indexOf("de") === 0 ? "de" : "en";
    setLocale(saved);
    loadCapabilities().then(resumeJob);
    window.setInterval(refreshSlots, 1500);
  }
  if (direct) {
    api("/api/session").then(function (session) {
      if (!/^[0-9a-f]{64}$/.test(session.csrf || "")) throw new Error("Invalid session");
      csrf = session.csrf;
      start();
    }).catch(fail);
  } else {
    start();
  }
})();
