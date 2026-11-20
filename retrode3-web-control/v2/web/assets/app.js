/* Retrode3 web v2: browser never talks to cartridge devices or shell. */
(function () {
  "use strict";
  var locale = "en", messages = {}, capabilities = null, activeJob = null;
  var fileFolder = "", jobTimer = null, slotData = null, slotFingerprint = null;
  var selectedReader = "";
  var detectedBySlot = {}, probeTarget = null, autoNames = {};
  var coreState = null, corePending = false;
  var csrf = document.querySelector('meta[name="csrf-token"]').content;
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
    var url = "api.php?route=" + encodeURIComponent(route);
    if (query !== undefined) url += "&path=" + encodeURIComponent(query);
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
    if (id === "files") listFiles();
    if (id === "reader") loadCapabilities();
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
  function renderReaderState() {
    var reader = readerById(selectedReader);
    text($("selected-reader"), reader ? reader.name : t("choose_reader"));
    text($("reader-support"), reader ? reader.name : t("reader_unavailable"));
    var commands = reader && reader.capabilities && reader.capabilities.commands || [];
    $("probe").disabled = !reader || commands.indexOf("probe") === -1 || Boolean(activeJob);
    $("read").disabled = !reader || commands.indexOf("read_rom") === -1 || Boolean(activeJob);

  }
  function configureReaderOptions() {
    var reader = readerById(selectedReader), caps = reader && reader.capabilities || {};
    var mapping = $("mapping"), size = $("rom-size");
    mapping.innerHTML = ""; size.innerHTML = "";
    var a = document.createElement("option"); a.value = ""; text(a, t("auto")); mapping.appendChild(a);
    var b = document.createElement("option"); b.value = ""; text(b, t("auto")); size.appendChild(b);
    (caps.mappings || []).forEach(function (mappingId) {
      if (typeof mappingId !== "string" || mappingId.length > 32) return;
      var opt = document.createElement("option");
      opt.value = mappingId;
      text(opt, mappingId === "lo" ? "LoROM" : mappingId === "hi" ? "HiROM" : mappingId);
      mapping.appendChild(opt);
    });
    $("mapping-control").hidden = !(caps.mappings && caps.mappings.length);
    $("size-control").hidden = !caps.size_override;
    if (caps.size_override) {
      var choices = Array.isArray(caps.size_choices_bytes) ? caps.size_choices_bytes.slice() : [];
      if (!choices.length) {
        for (var n = 131072; n <= Math.min(caps.max_rom_bytes || 4194304, 4194304); n *= 2)
          choices.push(n);
      }
      choices.forEach(function (bytes) {
        if (typeof bytes !== "number" || bytes < 131072 || bytes > 4194304) return;
        var opt = document.createElement("option");
        opt.value = String(bytes); text(opt, humanSize(bytes)); size.appendChild(opt);
      });
    }
  }
  function selectReader(id) {
    var previous = selectedReader;
    var reader = readerById(id);
    selectedReader = reader ? id : "";
    $("system").value = selectedReader;
    // A filename belongs to a reader/cartridge, not to the global dialog.
    // Preserve manual edits only when the same reader stays selected.
    if (selectedReader !== previous) {
      $("filename").value = reader ? suggestedFilename(reader) : "";
    } else if (reader && !$("filename").value) {
      $("filename").value = suggestedFilename(reader);
    }
    configureReaderOptions();
    renderReaderState();
    if (slotData) renderSlots();
    renderSelectedProbe();
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
        detected.core_id === reader.id && detected.result && detected.result.title)
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
        detected.core_id === selectedReader && detected.result) {
      renderProbe(detected.result, false);
    } else if (!detected && cached && cached.reader === selectedReader) {
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
  }
  function renderSlots() {
    if (!slotData) return;
    var list = $("slot-list"); list.innerHTML = "";
    var occupied = slotData.slots.filter(function (slot) { return slot.status === "occupied"; });
    text($("slots-summary"), occupied.length ? occupied.length + " " + t("slots_occupied") : t("no_occupied_slots"));
    slotData.slots.forEach(function (slot) {
      var matching = readers().filter(function (reader) { return reader.slot === slot.id; });
      var isSelected = matching.some(function (reader) { return reader.id === selectedReader; });
      var card = document.createElement("button");
      card.type = "button";
      card.className = "slot-card" + (slot.status === "occupied" ? " occupied" : "") +
        (isSelected ? " selected" : "");
      card.setAttribute("aria-pressed", isSelected ? "true" : "false");
      var title = document.createElement("strong");
      text(title, slot.name); card.appendChild(title);
      var state = document.createElement("span");
      text(state, slot.status === "occupied" ? t("slot_occupied") :
        slot.status === "empty" ? t("slot_empty") :
        slot.status === "unavailable" ? t("slot_unavailable") : t("slot_unknown"));
      card.appendChild(state);
      var hint = document.createElement("small");
      var systemName = matching.length ? matching.map(function (r) { return r.name; }).join(", ") :
        (slot.status === "occupied" ? t("slot_no_reader") : "");
      text(hint, systemName);
      card.appendChild(hint);
      if (slot.status === "occupied" && matching.length) {
        var game = document.createElement("span");
        game.className = "slot-game";
        var automatic = slot.detection || {};
        var isKnown = automatic.state === "detected" && automatic.result &&
          matching.some(function (r) { return r.id === automatic.core_id; });
        var title = isKnown && automatic.result.title;
        text(game, title || (automatic.state === "detecting" ||
          automatic.state === "pending" ? t("detecting_automatically") :
          automatic.state === "choose_reader" ? t("choose_reader") : t("unknown")));
        card.appendChild(game);
      }
      card.addEventListener("click", function () {
        if (matching.length === 1) selectReader(matching[0].id);
        else {
          $("advanced").hidden = false;
          $("advanced-toggle").setAttribute("aria-expanded", "true");
          notify(t("manual_reader_hint"));
        }
      });
      list.appendChild(card);
    });
  }
  function refreshSlots() {
    return api("/api/slots").then(function (data) {
      if (!data || !Array.isArray(data.slots)) return;
      var previousSlots = slotData && slotData.slots || [];
      data.slots.forEach(function (slot) {
        var previous = previousSlots.filter(function (entry) { return entry.id === slot.id; })[0];
        if (!previous || previous.status !== slot.status || slot.status !== "occupied") {
          delete detectedBySlot[slot.id];
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
        var matches = readers().filter(function (reader) {
          return occupied.some(function (slot) { return slot.id === reader.slot; });
        });
        if (matches.some(function (reader) { return reader.id === selectedReader; }))
          selectReader(selectedReader);
        else selectReader(matches.length ? matches[0].id : "");
      }
      renderSlots();
      var chosen = selectedSlotId();
      if (chosen) {
        var detected = autoDetection(chosen);
        var name = detected && detected.state === "detected" &&
          detected.core_id === selectedReader && detected.result && detected.result.title;
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
    var info = document.createElement("p"); info.className = "muted small";
    text(info, t("not_integrated")); box.appendChild(info);
    if (updateFilename !== false && data.title) $("filename").value = data.title;
  }
  function startJob(command) {
    var reader = readerById(selectedReader);
    if (!reader || (reader.capabilities.commands || []).indexOf(command) === -1)
      return notify(t("choose_reader"));
    var payload = {system: selectedReader, command: command};
    if (command === "read_rom") {
      payload.filename = $("filename").value;
      if ($("mapping").value) payload.mapping = $("mapping").value;
      if ($("rom-size").value) payload.size_bytes = Number($("rom-size").value);
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
    text($("job-label"), t(job.status));
    var progress = job.progress || {};
    var percent = typeof progress.percent === "number" ? progress.percent : 0;
    text($("job-percent"), percent + "%");
    $("job-fill").style.width = percent + "%";
    text($("job-detail"), progress.bytes_total ?
      humanSize(progress.bytes_done) + " / " + humanSize(progress.bytes_total) : "");
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
      }
      else { notify(t("read_finished")); }
    } else if (job.status === "failed") {
      if (job.command === "probe") probeTarget = null;
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
            window.location.href = "api.php?route=" +
              encodeURIComponent("/api/files/download") + "&path=" + encodeURIComponent(item.path);
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
  function loadSettings() {
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
    $("probe").addEventListener("click", function () { startJob("probe"); });
    $("read").addEventListener("click", function () { startJob("read_rom"); });
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
  bind();
  var saved = (navigator.language || "").toLowerCase().indexOf("de") === 0 ? "de" : "en";
  setLocale(saved);
  loadCapabilities().then(resumeJob);
  window.setInterval(refreshSlots, 1500);
})();
