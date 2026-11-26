/* Retrode3 web v2: browser never talks to cartridge devices or shell. */
(function () {
  "use strict";
  var locale = "en", messages = {}, capabilities = null, activeJob = null;
  var fileFolder = "", jobTimer = null, slotData = null, slotFingerprint = null;
  var selectedReader = "", currentPage = "reader", currentJob = null;
  var slotPollSerial = 0, slotAppliedSerial = 0, resuming = true;
  var detectedBySlot = {}, probeTarget = null, autoNames = {};
  var manualReaderBySlot = {};
  var coreState = null, corePending = false, registryRevision = null;
  var wifiOperation = null, wifiStatusSerial = 0;
  var pluginSlotFilter = "";
  var toastTimer = null, developerPending = false, developerState = null, developerSerial = 0;
  var updateState = null, updatePending = false, updateTimer = null, updatePolling = false;
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
  function dismissToast() {
    if (toastTimer !== null) clearTimeout(toastTimer);
    toastTimer = null;
    $("toast").classList.remove("visible");
  }
  function notify(message) {
    dismissToast();
    text($("toast-message"), message);
    $("toast").classList.add("visible");
    toastTimer = setTimeout(dismissToast, 12000);
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
    if ($("toast-close")) {
      $("toast-close").setAttribute("aria-label", t("notification_close"));
      $("toast-close").title = t("notification_close");
    }
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      var key = el.getAttribute("data-i18n");
      if (messages[key]) text(el, messages[key]);
    });
    renderReaderState();
    if (slotData) renderSlots();
    renderSelectedProbe();
    renderCores();
    renderWriterState();
    renderGlobalStatus();
    if (updateState && $("update-panel")) renderUpdate(updateState);
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
  function showTab(id, slotFilter) {
    if (id === "plugins") pluginSlotFilter = slotFilter || "";
    document.querySelectorAll(".tab").forEach(function (el) {
      el.classList.toggle("active", el.getAttribute("data-tab") === id);
    });
    document.querySelectorAll(".page").forEach(function (el) {
      el.classList.toggle("active", el.id === id);
    });
    currentPage = id;
    syncJobPanel();
    renderGlobalStatus();
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
  function busyJob() {
    return activeJob ? currentJob : slotData && slotData.busy_job || null;
  }
  function hardwareBusy() {
    return resuming || Boolean(activeJob || (slotData && slotData.busy_job)) ||
      (typeof updateState !== "undefined" && updateState && ["checking", "downloading", "installing", "restarting"].indexOf(updateState.phase) !== -1);
  }
  function isWriterJob(job) {
    return !!job && ["probe_flash", "write_flash", "verify_flash", "flash_operation"].indexOf(job.command) !== -1;
  }
  function jobTerminal(job) {
    return !!job && ["done", "failed", "cancelled"].indexOf(job.status) !== -1;
  }
  function jobSlot(job) {
    return job && (job.slot || (readerById(job.system) || {}).slot) || "";
  }
  function syncJobPanel() {
    var job = currentJob, panel = $("job-panel");
    if (!job) { panel.hidden = true; if ($("reader-activity-idle")) $("reader-activity-idle").hidden = false; return; }
    var writer = isWriterJob(job);
    var show = writer ? currentPage === "writer" :
      currentPage === "reader" && !jobTerminal(job);
    // Writer keeps its terminal verification result, reader replaces progress
    // with the slot-specific ROM result. Never move a read into the writer.
    var anchor = writer ? $("writer-progress-anchor") : $("reader-progress-anchor");
    if (panel.parentNode !== anchor) anchor.appendChild(panel);
    panel.hidden = !show;
    if ($("reader-activity-idle")) $("reader-activity-idle").hidden = show && !writer;
    $("cancel").disabled = !activeJob || activeJob === "pending" || jobTerminal(job);
  }
  function renderGlobalStatus() {
    var job = busyJob(), busy = hardwareBusy(), status = $("global-job-status");
    var label = job && job.command === "read_rom" ? t("read_busy") : t("hardware_busy");
    var reader = job && readerById(job.system);
    var progress = job && job.progress && job.progress.percent;
    if (reader) label = reader.name + " · " + label;
    if (typeof progress === "number" && isFinite(progress))
      label += " · " + Math.floor(Math.max(0, Math.min(100, progress))) + "%";
    status.hidden = !busy || (currentPage === "reader" && !isWriterJob(job));
    if ($("reader-activity-label")) text($("reader-activity-label"), busy ? label : t("hardware_idle"));
    if ($("reader-activity-idle")) text($("reader-activity-idle"), busy ? t("hardware_busy_hint") : t("slots_idle_hint"));
    text($("global-job-label"), label);
    $("global-job-cancel").hidden = status.hidden || !activeJob || activeJob === "pending" || !job || jobTerminal(job);
    text($("read-busy-hint"), busy ? (job && job.command === "read_rom" ? t("read_busy_hint") : t("hardware_busy_hint")) : "");
    $("read-busy-hint").hidden = !busy;
  }
  function renderReaderState() {
    var reader = readerById(selectedReader);
    text($("selected-reader"), reader ? reader.name : t("choose_reader"));
    text($("reader-support"), reader ? reader.name : t("reader_unavailable"));
    var commands = reader && reader.capabilities && reader.capabilities.commands || [];
    $("probe").disabled = !reader || commands.indexOf("probe") === -1 || hardwareBusy();
    $("read").disabled = !reader || commands.indexOf("read_rom") === -1 ||
      hardwareBusy() || readerOptionsLoading || !genericSchema() ||
      !genericWidget || !genericWidget.allowed();
    renderWriterState();
    renderGlobalStatus();
    syncJobPanel();
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
    renderReadResult();
  }
  function renderReadResult() {
    var box = $("slot-read-result");
    box.innerHTML = "";
    var slot = slotData && slotData.slots.filter(function (s) { return s.id === selectedSlotId(); })[0];
    var result = slot && slot.status === "occupied" && slot.read_result;
    var running = busyJob();
    box.hidden = !result || result.system !== selectedReader ||
      Boolean(running && running.command === "read_rom" && jobSlot(running) === selectedSlotId());
    var placeholder = $("rom-result-empty");
    if (placeholder) {
      placeholder.hidden = !box.hidden;
      text(placeholder, running && running.command === "read_rom" && jobSlot(running) === selectedSlotId() ?
        t("read_busy") : t("rom_result_empty"));
    }
    if (box.hidden) return;
    var verification = result.verification || {};
    var heading = document.createElement("strong");
    heading.className = verification.status === "mismatch" ? "read-result-warning" : "read-result-ok";
    text(heading, t(verification.status === "mismatch" ? "read_complete_mismatch" : "read_complete"));
    box.appendChild(heading);
    var fields = [["detected_title", result.title], ["filename", result.filename],
      ["detected_size", result.size_bytes == null ? null : humanSize(result.size_bytes)],
      ["read_crc32", result.crc32], ["read_verification", verification.status ? t("verification_" + verification.status) : t("verification_not_checked")],
      ["read_layout", result.layout_id]];
    if (verification.status === "mismatch" && verification.expected && verification.actual)
      fields.push(["read_checksum_compare", verification.expected + " / " + verification.actual]);
    if (result.read_configuration && typeof result.read_configuration === "object")
      fields.push(["read_configuration", Object.keys(result.read_configuration).map(function (key) {
        return key + ": " + result.read_configuration[key];
      }).join(" · ")]);
    fields.forEach(function (pair) {
      if (pair[1] == null || pair[1] === "") return;
      var row = document.createElement("div"), left = document.createElement("span"), right = document.createElement("strong");
      row.className = "keyval"; text(left, t(pair[0])); text(right, pair[1]);
      row.appendChild(left); row.appendChild(right); box.appendChild(row);
    });
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
  function disabledSlotCores(slot) {
    if (!coreState || !coreState.available) return [];
    return coreState.cores.filter(function (core) {
      return core.slot === slot.id && core.installed !== false && !core.enabled &&
        core.status === "disabled";
    });
  }
  function disabledPluginPreview(cores) {
    var limit = 64, suffix = ", …", preview = "";
    for (var i = 0; i < cores.length; i++) {
      var candidate = preview + (preview ? ", " : "") + cores[i].name;
      var reserve = i + 1 < cores.length ? suffix.length : 0;
      if (Array.from(candidate).length + reserve > limit) {
        return preview ? preview + suffix :
          Array.from(cores[i].name).slice(0, limit - 1).join("") + "…";
      }
      preview = candidate;
    }
    return preview;
  }
  function renderSlots() {
    if (!slotData) return;
    var list = $("slot-list");
    var scrollPositions = {};
    Array.prototype.forEach.call(list.children, function (card) {
      if (card.retR3Slot) scrollPositions[card.retR3Slot] = card.scrollTop;
    });
    list.innerHTML = "";
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
      card.retR3Slot = slot.id;
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
      var operation = busyJob();
      if (operation && operation.command === "read_rom" && jobSlot(operation) === slot.id) {
        var activity = document.createElement("small");
        activity.className = "slot-read-busy";
        text(activity, t("read_busy"));
        main.appendChild(activity);
      } else if (slot.status === "occupied" && slot.read_result &&
                 (!identified || identified.reader.id === slot.read_result.system)) {
        var complete = document.createElement("small");
        var mismatch = (slot.read_result.verification || {}).status === "mismatch";
        complete.className = mismatch ? "read-result-warning" : "read-result-ok";
        text(complete, t(mismatch ? "read_complete_mismatch" : "read_complete"));
        main.appendChild(complete);
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
        picker.disabled = hardwareBusy();
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
      if (!identified && !waiting && slot.status === "occupied") {
        var disabled = disabledSlotCores(slot);
        if (disabled.length) {
          var pluginHint = document.createElement("p");
          pluginHint.className = "slot-plugin-hint";
          text(pluginHint, t("slot_disabled_plugins") + ": " +
            disabledPluginPreview(disabled));
          card.appendChild(pluginHint);
          var pluginLink = document.createElement("button");
          pluginLink.type = "button";
          text(pluginLink, t("slot_open_plugins") + " (" +
            t("slot_disabled_count").replace("{count}", disabled.length) + ")");
          pluginLink.addEventListener("click", function () { showTab("plugins", slot.id); });
          pluginLink.className = "slot-plugin-link";
          card.appendChild(pluginLink);
        }
      }
      main.addEventListener("click", function () {
        if (identified) selectReader(identified.reader.id);
        else if (picker && picker.disabled && chosenManually) selectReader(chosenManually);
        else if (picker) picker.focus();
        else if (waiting) notify(t("detecting_automatically"));
        else if (matching.length === 1) selectReader(matching[0].id);
        else notify(t("slot_no_reader"));
      });
      list.appendChild(card);
      if (scrollPositions[slot.id]) card.scrollTop = scrollPositions[slot.id];
    });
  }
  function refreshSlots() {
    var serial = ++slotPollSerial;
    return api("/api/slots").then(function (data) {
      if (!data || !Array.isArray(data.slots) || serial < slotAppliedSerial) return;
      slotAppliedSerial = serial;
      var wasBusy = hardwareBusy();
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
          adoptBusyJob(data);
          if (wasBusy !== hardwareBusy()) renderCores();
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
      adoptBusyJob(data);
      if (wasBusy !== hardwareBusy()) renderCores();
      var fingerprint = data.slots.map(function (slot) { return slot.id + ":" + slot.status; }).join("|");
      if (probeTarget && data.slots.some(function (slot) {
        return slot.id === probeTarget.slot && slot.status !== probeTarget.status;
      })) probeTarget = null;
      if (fingerprint !== slotFingerprint && !activeJob && !(data.busy_job && !data.busy_job.automatic)) {
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
        if (!activeJob && !(data.busy_job && !data.busy_job.automatic) && slot.status === "occupied" &&
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
    $("writer-verify-passes").disabled = !verify || hardwareBusy();
    $("writer-detect").disabled = !flashSupports(reader, "probe_flash") ||
      hardwareBusy();
    $("writer-start").disabled = !writerIdentified || !selected || !validPasses ||
      (sourceRequired && !sourceReady) || writerUploading || hardwareBusy() ||
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
    if (hardwareBusy() || writerUploading) return;
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
    if (!reader || !flashSupports(reader, action) || hardwareBusy()) return;
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
    submitJob(payload, reader);
  }
  function startJob(command) {
    var reader = readerById(selectedReader);
    if (hardwareBusy()) return;
    if (!reader || (reader.capabilities.commands || []).indexOf(command) === -1)
      return notify(t("choose_reader"));
    var payload = {system: selectedReader, command: command};
    if (command === "read_rom") {
      payload.filename = $("filename").value;
      if (!genericSchema() || !genericWidget || !genericWidget.allowed())
        return notify(t("generic_invalid"));
      payload.selection = genericWidget.selection();
    }
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
    submitJob(payload, reader);
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
  function adoptBusyJob(data) {
    var job = data.busy_job;
    if (!activeJob && job && !job.automatic && !jobTerminal(job)) {
      activeJob = job.id;
      currentJob = job;
      // A browser opened during a read should see its correct slot by default.
      if (!selectedReader && readerById(job.system)) selectReader(job.system);
      renderJob(job);
      schedulePoll();
    }
    renderReaderState();
  }
  function submitJob(payload, reader) {
    // Set busy before POST; slot switching/polling cannot reopen the controls.
    activeJob = "pending";
    currentJob = {system: reader.id, slot: reader.slot, command: payload.command, status: "queued"};
    if (payload.command === "read_rom" || payload.command === "write_flash" ||
        payload.command === "flash_operation") {
      var slot = slotData && slotData.slots.filter(function (s) { return s.id === reader.slot; })[0];
      if (slot) slot.read_result = null;
    }
    renderJob(currentJob);
    renderReaderState();
    renderCores();
    api("/api/jobs", payload).then(function (job) {
      activeJob = job.id;
      currentJob = job;
      renderJob(job);
      renderReaderState();
      renderCores();
      schedulePoll();
    }).catch(function (err) {
      activeJob = null;
      currentJob = null;
      if (payload.command === "probe") probeTarget = null;
      renderReaderState(); renderCores();
      refreshSlots(); fail(err);
    });
  }
  function schedulePoll() {
    if (jobTimer) clearTimeout(jobTimer);
    jobTimer = setTimeout(pollJob, 650);
  }
  function pollJob() {
    if (!activeJob || activeJob === "pending") return;
    var id = activeJob;
    api("/api/jobs/" + id).then(function (job) {
      if (activeJob !== id) return;
      currentJob = job;
      renderJob(job);
      renderReaderState();
      if (["done", "failed", "cancelled"].indexOf(job.status) === -1) schedulePoll();
      else {
        activeJob = null;
        if (!isWriterJob(job)) currentJob = null;
        renderCores();
        renderReaderState();
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
    var filter = $("core-slot-filter");
    if (filter) {
      filter.innerHTML = "";
      var all = document.createElement("option");
      all.value = ""; text(all, t("core_all_slots")); filter.appendChild(all);
      var slots = Array.from(new Set(coreState.cores.map(function (core) { return core.slot; }))).sort();
      slots.forEach(function (id) {
        var option = document.createElement("option"); option.value = id;
        var physical = slotData && slotData.slots.find(function (slot) { return slot.id === id; });
        text(option, physical ? physical.name : id.toUpperCase()); filter.appendChild(option);
      });
      if (pluginSlotFilter && slots.indexOf(pluginSlotFilter) === -1) pluginSlotFilter = "";
      filter.value = pluginSlotFilter;
    }
    var visible = coreState.cores.filter(function (core) {
      return !pluginSlotFilter || core.slot === pluginSlotFilter;
    });
    text($("cores-summary"), visible.length ?
      visible.length + " " + t("core_found") +
      (!coreState.control_enabled ? " · " + t("core_readonly") : "") :
      t("core_none_installed"));
    visible.forEach(function (core) {
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
      toggle.disabled = !coreState.control_enabled || corePending || hardwareBusy() ||
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
      if (slotData && !(document.activeElement && document.activeElement.classList &&
          document.activeElement.classList.contains("slot-manual-select"))) renderSlots();
    }).catch(function (error) {
      coreState = {available: false, control_enabled: false, cores: [], reason: "cli_error"};
      renderCores();
      fail(error);
    });
  }
  function renderDeveloper(data) {
    developerState = data;
    $("developer-locked").hidden = data.configured || data.setup_allowed;
    $("developer-setup").hidden = !data.setup_allowed;
    $("developer-controls").hidden = !data.configured;
    text($("ssh-status"), data.running ? t("status_connected") : t("status_disconnected"));
    if ($("ssh-key-list")) {
      var list = $("ssh-key-list");
      list.textContent = "";
      (data.keys || []).forEach(function (key) {
        var option = document.createElement("option");
        option.value = key.fingerprint;
        text(option, key.type + " " + key.fingerprint + (key.comment ? " " + key.comment : ""));
        list.appendChild(option);
      });
    }
    if ($("ssh-password-status")) {
      text($("ssh-password-status"), t(data.password_login === false ? "ssh_password_off" : "ssh_password_on"));
      $("ssh-password-key-hint").hidden = (data.keys || []).length > 0;
    }
    developerButtons();
  }
  function developerButtons() {
    var data = developerState || {};
    $("developer-save").disabled = developerPending || !data.setup_allowed;
    $("developer-change-save").disabled = developerPending || !data.configured;
    $("ssh-enable").disabled = developerPending || !data.configured || data.running;
    $("ssh-disable").disabled = developerPending || !data.configured || (!data.enabled && !data.running);
    if ($("ssh-key-add")) $("ssh-key-add").disabled = developerPending || !data.configured;
    var keyCount = (data.keys || []).length;
    if ($("ssh-key-remove")) $("ssh-key-remove").disabled = developerPending || !keyCount || (data.password_login === false && keyCount === 1);
    if ($("ssh-password-enable")) $("ssh-password-enable").disabled = developerPending || !data.configured || data.password_login !== false;
    if ($("ssh-password-disable")) $("ssh-password-disable").disabled = developerPending || !data.configured || data.password_login === false || !keyCount;
  }
  function loadDeveloper() {
    if (!direct || !$("developer-panel") || developerPending) return;
    $("developer-panel").hidden = false;
    var serial = ++developerSerial;
    return api("/api/developer/ssh").then(function (data) {
      if (serial === developerSerial) renderDeveloper(data);
    }).catch(fail);
  }
  function developerAction(data, progress, success, onSuccess) {
    if (developerPending) return;
    developerPending = true;
    ++developerSerial;
    developerButtons();
    text($("developer-feedback"), t(progress));
    return api("/api/developer/ssh", data).then(function (result) {
      renderDeveloper(result);
      if (onSuccess) onSuccess();
      notify(t(success));
    }).catch(fail).then(function () {
      developerPending = false;
      developerButtons();
      text($("developer-feedback"), "");
    });
  }
  function saveDeveloperPassword(initial) {
    if (developerPending) return;
    var p = $(initial ? "developer-new" : "developer-change-new");
    var r = $(initial ? "developer-repeat" : "developer-change-repeat");
    if (!p.value || p.value !== r.value) {
      notify(t("developer_password_mismatch")); return;
    }
    var data = {action: initial ? "setup" : "change_password",
                new_password: p.value, repeat_password: r.value};
    if (!initial) data.developer_password = $("developer-password").value;
    p.value = ""; r.value = ""; $("developer-password").value = "";
    return developerAction(data, "developer_saving", "developer_saved");
  }
  function changeSSH(action) {
    if (developerPending) return;
    var data = {action: action, developer_password: $("developer-password").value};
    $("developer-password").value = "";
    return developerAction(data, "ssh_updating", action === "enable" ? "ssh_enabled_notice" : "ssh_disabled_notice");
  }
  function changeSSHPasswordLogin(enabled) {
    if (developerPending) return;
    if (!enabled && !confirm(t("ssh_password_confirm"))) return;
    var data = {action: "set_password_login", enabled: enabled,
                developer_password: $("developer-password").value};
    $("developer-password").value = "";
    return developerAction(data, "ssh_updating", enabled ? "ssh_password_enabled_notice" : "ssh_password_disabled_notice");
  }
  function changeSSHKey(action) {
    if (developerPending) return;
    var data = {action: action, developer_password: $("developer-password").value};
    if (action === "add_key") {
      data.public_key = $("ssh-key-text").value;
      if (/PRIVATE KEY/.test(data.public_key)) { fail(new Error(t("ssh_key_invalid"))); return; }
    } else {
      data.fingerprint = $("ssh-key-list").value;
      if (!data.fingerprint) return;
    }
    $("developer-password").value = "";
    return developerAction(data, "ssh_updating", action === "add_key" ? "ssh_key_added" : "ssh_key_removed", function () {
      $("ssh-key-text").value = ""; $("ssh-key-file").value = "";
    });
  }
  function updateInProgress(state) {
    return !!state && ["checking", "downloading", "installing", "restarting"].indexOf(state.phase) !== -1;
  }
  function renderUpdate(data) {
    updateState = data;
    var status = t("update_" + data.phase);
    if (data.message) status += " " + data.message;
    text($("update-status"), status);
    var list = $("update-packages");
    list.textContent = "";
    (data.packages || []).forEach(function (pkg) {
      var row = document.createElement("p");
      text(row, pkg.name + ": " + (pkg.installed || t("update_new_package")) + " → " + pkg.candidate);
      list.appendChild(row);
    });
    var busy = updatePending || updateInProgress(data);
    $("update-check").disabled = busy || hardwareBusy();
    $("update-install").disabled = busy || data.phase !== "available" || hardwareBusy();
    renderReaderState();
    renderCores();
  }
  function scheduleUpdatePoll() {
    if (updateTimer !== null) clearTimeout(updateTimer);
    updateTimer = setTimeout(function () { updateTimer = null; pollUpdate(); }, 2000);
  }
  function pollUpdate() {
    if (!direct || !$("update-panel") || updatePolling || updatePending) return;
    updatePolling = true;
    return api("/api/update").then(function (data) {
      var wasInstalling = updateInProgress(updateState) && updateState.phase !== "checking";
      renderUpdate(data);
      if (wasInstalling && data.phase === "done") {
        // Reload new frontend after its backend and assets were replaced.
        try { sessionStorage.setItem("retrode3-update-complete", "1"); } catch (_) {}
        window.location.reload();
      }
    }).catch(function (err) {
      if (updateInProgress(updateState)) {
        text($("update-status"), t("update_reconnecting"));
      } else if (currentPage === "settings") {
        text($("update-status"), t("update_unavailable"));
      }
    }).then(function () {
      updatePolling = false;
      if (currentPage === "settings" || updateInProgress(updateState)) scheduleUpdatePoll();
    });
  }
  function startUpdate(action) {
    if (updatePending || updateInProgress(updateState)) return;
    if (hardwareBusy() || (action === "install" && !confirm(t("update_confirm")))) return;
    updatePending = true;
    if (updateTimer !== null) { clearTimeout(updateTimer); updateTimer = null; }
    $("update-check").disabled = $("update-install").disabled = true;
    text($("update-status"), t(action === "check" ? "update_checking" : "update_downloading"));
    return api("/api/update", {action: action}).then(function (data) {
      updatePending = false;
      renderUpdate(data);
    }).catch(function (err) {
      updatePending = false;
      fail(err);
    }).then(pollUpdate);
  }
  function loadSettings() {
    pollUpdate();
    loadDeveloper();
    loadCores();
    api("/api/settings").then(function (data) {
      text($("device-time"), data.time); text($("device-timezone"), data.timezone);
    }).catch(fail);
    if (!wifiOperation) loadWifiStatus().catch(fail);
  }
  function renderWifiStatus(data) {
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
    return data;
  }
  function loadWifiStatus() {
    var serial = ++wifiStatusSerial;
    return api("/api/wifi/status").then(function (data) {
      if (serial === wifiStatusSerial) renderWifiStatus(data);
      return data;
    });
  }
  function setWifiOperation(operation, message) {
    wifiOperation = operation;
    ++wifiStatusSerial;
    ["scan-wifi", "connect-wifi", "disconnect-wifi"].forEach(function (id) {
      $(id).disabled = Boolean(operation);
    });
    text($("wifi-operation"), message);
  }
  function wifiFailed(error) {
    setWifiOperation(null, t("wifi_operation_failed") + ": " + (error.message || t("error_generic")));
    fail(error);
  }
  function waitForWifi(ssid, deadline) {
    return loadWifiStatus().then(function (data) {
      if (data.connected && data.ssid === ssid) {
        setWifiOperation(null, t("wifi_connect_done"));
      } else if (Date.now() >= deadline) {
        setWifiOperation(null, t("wifi_connect_timeout"));
      } else {
        text($("wifi-operation"), t(data.associated ? "wifi_wait_ip" : "wifi_connecting"));
        setTimeout(function () { waitForWifi(ssid, deadline).catch(wifiFailed); }, 1500);
      }
    });
  }

  function bind() {
    if ($("update-panel")) {
      $("update-check").addEventListener("click", function () { startUpdate("check"); });
      $("update-install").addEventListener("click", function () { startUpdate("install"); });
    }
    $("toast-close").addEventListener("click", dismissToast);
    if ($("core-slot-filter")) $("core-slot-filter").addEventListener("change", function () {
      pluginSlotFilter = this.value; renderCores();
    });
    if (direct && $("ssh-enable")) {
      $("developer-save").addEventListener("click", function () { saveDeveloperPassword(true); });
      $("developer-change-save").addEventListener("click", function () { saveDeveloperPassword(false); });
      $("ssh-enable").addEventListener("click", function () { changeSSH("enable"); });
      $("ssh-disable").addEventListener("click", function () { changeSSH("disable"); });
      if ($("ssh-password-enable")) {
        $("ssh-password-enable").addEventListener("click", function () { changeSSHPasswordLogin(true); });
        $("ssh-password-disable").addEventListener("click", function () { changeSSHPasswordLogin(false); });
      }
      if ($("ssh-key-file")) {
        $("ssh-key-file").addEventListener("change", function () {
          var file = this.files[0];
          if (!file) return;
          if (file.size > 4096) { this.value = ""; fail(new Error(t("ssh_key_invalid"))); return; }
          file.text().then(function (value) {
            if (/PRIVATE KEY/.test(value)) throw new Error(t("ssh_key_invalid"));
            $("ssh-key-text").value = value;
          }).catch(fail);
        });
        $("ssh-key-add").addEventListener("click", function () { changeSSHKey("add_key"); });
        $("ssh-key-remove").addEventListener("click", function () { changeSSHKey("remove_key"); });
      }
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
      if (activeJob && activeJob !== "pending") api("/api/jobs/" + activeJob + "/cancel", {}).catch(fail);
    });
    $("global-job-cancel").addEventListener("click", function () {
      if (activeJob && activeJob !== "pending") api("/api/jobs/" + activeJob + "/cancel", {}).catch(fail);
    });
    $("refresh-files").addEventListener("click", listFiles);
    $("new-folder").addEventListener("click", function () {
      var folder = prompt(t("prompt_folder"));
      if (!folder) return;
      api("/api/files/mkdir", {path: fileFolder ? fileFolder + "/" + folder : folder})
        .then(function () { notify(t("folder_created")); listFiles(); }).catch(fail);
    });
    $("scan-wifi").addEventListener("click", function () {
      if (wifiOperation) return;
      setWifiOperation("scan", t("wifi_scanning"));
      api("/api/wifi/scan").then(function (data) {
        var list = $("wifi-networks"); list.innerHTML = "";
        if (!data.networks || !data.networks.length) {
          setWifiOperation(null, t("wifi_scan_empty"));
          return;
        }
        data.networks.forEach(function (network) {
          var row = document.createElement("div"), btn = button(network.ssid, function () {
            $("wifi-ssid").value = network.ssid;
          });
          row.className = "network"; row.appendChild(btn);
          var signal = document.createElement("small");
          text(signal, network.dbm + " dBm" + (network.security ? " · " + network.security : "")); row.appendChild(signal); list.appendChild(row);
        });
        setWifiOperation(null, t("wifi_scan_done").replace("{count}", data.networks.length));
      }).catch(wifiFailed);
    });
    $("connect-wifi").addEventListener("click", function () {
      if (wifiOperation) return;
      var ssid = $("wifi-ssid").value;
      setWifiOperation("connect", t("wifi_connecting"));
      api("/api/wifi/connect", {ssid: ssid, password: $("wifi-password").value})
        .then(function () {
          $("wifi-password").value = "";
          return waitForWifi(ssid, Date.now() + 45000);
        }).catch(wifiFailed);
    });
    $("disconnect-wifi").addEventListener("click", function () {
      if (wifiOperation || !confirm(t("confirm_disconnect"))) return;
      setWifiOperation("disconnect", t("wifi_disconnecting"));
      api("/api/wifi/disconnect", {}).then(loadWifiStatus).then(function () {
        setWifiOperation(null, t("wifi_disconnect_done"));
      }).catch(wifiFailed);
    });
  }
  function resumeJob() {
    return api("/api/jobs/active").then(function (job) {
      if (!activeJob && job.id && !job.automatic && !jobTerminal(job)) {
        activeJob = job.id;
        currentJob = job;
        if (isWriterJob(job)) {
          showTab("writer");
          $("writer-system").value = job.system;
        } else if (readerById(job.system)) selectReader(job.system);
        renderJob(job);
        schedulePoll();
      }
    }).catch(fail).then(function () {
      resuming = false;
      renderReaderState();
    });
  }
  function start() {
    bind();
    var saved = (navigator.language || "").toLowerCase().indexOf("de") === 0 ? "de" : "en";
    setLocale(saved);
    loadCores();
    try {
      if (sessionStorage.getItem("retrode3-update-complete") === "1") {
        sessionStorage.removeItem("retrode3-update-complete");
        showTab("settings");
      }
    } catch (_) {}
    pollUpdate();
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
