/* Retrode3 web v2: browser never talks to cartridge devices or shell. */
(function () {
  "use strict";
  var locale = "en", messages = {}, capabilities = null, activeJob = null;
  var fileFolder = "", jobTimer = null, slotData = null, slotFingerprint = null;
  var selectedReader = "";
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
          if (!response.ok) throw new Error(body.error || body.message || t("error_generic"));
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
  }
  function setLocale(lang) {
    if (!/^(en|de)$/.test(lang)) lang = "en";
    locale = lang; $("locale").value = lang;
    $("help-online-link").href = "https://github.com/DragonBox-Shop/retrode3/blob/feature/web-control-v2/retrode3-web-control/v2/docs/user-guide." + lang + ".md";
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
    if (id === "settings") loadSettings();
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
    $("probe").disabled = $("read").disabled = !reader || Boolean(activeJob);
    var summary = readers().map(function (item) { return item.name; }).join(", ");
    var mdLegacy = capabilities && capabilities.systems &&
      capabilities.systems.some(function (item) {
        return item.id === "md" && !item.available && item.reason === "native_protocol_unavailable";
      });
    text($("availability"), (summary ? t("readers_available") + ": " + summary :
      t("no_readers_available")) + (mdLegacy ? " · " + t("md_protocol_pending") : ""));
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
    var reader = readerById(id);
    selectedReader = reader ? id : "";
    $("system").value = selectedReader;
    if (reader && (!$("filename").value || /^(SNES|MD)-Dump$/.test($("filename").value))) {
      $("filename").value = reader.id.toUpperCase() + "-Dump";
    }
    configureReaderOptions();
    renderReaderState();
    if (slotData) renderSlots();
  }
  function renderSlots() {
    if (!slotData) return;
    var list = $("slot-list"); list.innerHTML = "";
    var occupied = slotData.slots.filter(function (slot) { return slot.status === "occupied"; });
    text($("slots-summary"), occupied.length ? occupied.length + " " + t("slots_occupied") : t("no_occupied_slots"));
    slotData.slots.forEach(function (slot) {
      var matching = readers().filter(function (reader) { return reader.slot === slot.id; });
      var card = document.createElement("button");
      card.type = "button";
      card.className = "slot-card" + (slot.status === "occupied" ? " occupied" : "");
      if (matching.length === 1 && matching[0].id === selectedReader)
        card.className += " selected";
      var title = document.createElement("strong");
      text(title, slot.name); card.appendChild(title);
      var state = document.createElement("span");
      text(state, slot.status === "occupied" ? t("slot_occupied") :
        slot.status === "empty" ? t("slot_empty") :
        slot.status === "unavailable" ? t("slot_unavailable") : t("slot_unknown"));
      card.appendChild(state);
      var hint = document.createElement("small");
      text(hint, matching.length ? matching.map(function (r) { return r.name; }).join(", ") :
        t("slot_no_reader")); card.appendChild(hint);
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
      slotData = data;
      var fingerprint = data.slots.map(function (slot) { return slot.id + ":" + slot.status; }).join("|");
      if (fingerprint !== slotFingerprint && !activeJob) {
        slotFingerprint = fingerprint;
        var occupied = data.slots.filter(function (slot) { return slot.status === "occupied"; });
        var matches = readers().filter(function (reader) {
          return occupied.some(function (slot) { return slot.id === reader.slot; });
        });
        selectReader(matches.length === 1 ? matches[0].id : "");
      }
      renderSlots();
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
  function renderProbe(data) {
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
    if (data.title) $("filename").value = data.title;
  }
  function startJob(command) {
    if (!readerById(selectedReader)) return notify(t("choose_reader"));
    var payload = {system: selectedReader, command: command};
    if (command === "read_rom") {
      payload.filename = $("filename").value;
      if ($("mapping").value) payload.mapping = $("mapping").value;
      if ($("rom-size").value) payload.size_bytes = Number($("rom-size").value);
    }
    $("read").disabled = $("probe").disabled = true;
    api("/api/jobs", payload).then(function (job) {
      activeJob = job.id;
      $("job-panel").hidden = false;
      $("cancel").disabled = false;
      renderJob(job);
      schedulePoll();
    }).catch(function (err) {
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
      if (job.command === "probe") { renderProbe(job.result || {}); notify(t("probe_finished")); }
      else { notify(t("read_finished")); }
    } else if (job.status === "failed") {
      notify(t("failed") + ": " + (job.error && job.error.code || t("unknown")));
    } else if (job.status === "cancelled") notify(t("cancelled"));
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
        $("cancel").disabled = true;
        loadCapabilities();
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
  function loadSettings() {
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
      if (!job.id) return;
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
  window.setInterval(refreshSlots, 3000);
})();
