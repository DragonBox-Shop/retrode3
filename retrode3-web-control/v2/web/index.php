<?php
require __DIR__ . '/auth.php';
retrode_auth();
$csrf = retrode_session();
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
header("Content-Security-Policy: default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'");
?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="csrf-token" content="<?php echo htmlspecialchars($csrf, ENT_QUOTES, 'UTF-8'); ?>">
<title>Retrode3 Control</title>
<link rel="stylesheet" href="assets/style.css">
<script src="assets/app.js" defer></script>
</head>
<body>
<header class="topbar"><div class="brand"><span class="brand-icon">R3</span><div><strong>Retrode3</strong><small data-i18n="subtitle">Cartridge Control</small></div></div><div class="top-right"><span id="connection" class="pill" data-i18n="connecting">Connecting…</span><select id="locale" aria-label="Language"><option value="en">English</option><option value="de">Deutsch</option></select></div></header>
<div class="layout">
<nav class="tabs" aria-label="Navigation">
<button class="tab active" data-tab="reader" data-i18n="reader">Read Cartridge</button>
<button class="tab" data-tab="files" data-i18n="files">File Manager</button>
<button class="tab" data-tab="writer" data-i18n="writer">Write Cartridge</button>
<button class="tab" data-tab="plugins" data-i18n="plugins_tab">Plugins</button>
<button class="tab" data-tab="settings" data-i18n="settings">General Settings</button>
<button class="tab" data-tab="help" data-i18n="help_tab">Help &amp; Documentation</button>
</nav>
<main>
<section id="reader" class="page active">
<div class="section-head"><div><p class="eyebrow" data-i18n="reader_small">ROM DUMPING</p><h1 data-i18n="reader_title">Read your cartridge</h1><p class="muted" data-i18n="reader_desc">Detect a game and save a ROM dump to shared storage.</p></div></div>
<div class="panel"><div class="panel-head"><h2 data-i18n="slots_title">Cartridge slots</h2><span class="tag" id="slots-summary" data-i18n="checking">Checking…</span></div>
<div id="slot-list" class="slot-grid" aria-live="polite"></div>
<p class="muted small" data-i18n="slots_note">Slot presence is passive detection. The game or adapter type is not automatically identified.</p></div>
<div class="two-col">
<div class="panel"><div class="panel-head"><h2 data-i18n="cartridge">Cartridge</h2><span class="tag" id="reader-support" data-i18n="checking">Checking…</span></div>
<div class="keyval"><span data-i18n="selected_reader">Selected reader</span><strong id="selected-reader" data-i18n="choose_reader">No supported reader selected</strong></div>
<p class="muted small" data-i18n="systems_note">Select a detected slot, or use Advanced Settings for an unrecognized cartridge.</p>
<button id="probe" class="btn secondary" data-i18n="detect">Detect cartridge</button>
<div id="game-info" class="game-info"><p class="muted" data-i18n="not_detected">No cartridge examined yet.</p></div>
</div>
<div class="panel"><h2 data-i18n="read_options">Read options</h2>
<label for="filename" data-i18n="filename">File name</label><input id="filename" maxlength="64" value="SNES-Dump" autocomplete="off">
<button id="advanced-toggle" type="button" class="btn secondary" aria-expanded="false" data-i18n="advanced_toggle">Advanced settings</button>
<div id="advanced" hidden>
<p class="muted small" data-i18n="advanced_note">Only readers with confirmed read operations are selectable. Selecting a system does not detect an adapter or change the voltage.</p>
<label for="system" data-i18n="system">Reader / system</label><select id="system"><option value="">—</option></select>
<div id="mapping-control"><label for="mapping" data-i18n="mapping">Mapping</label><select id="mapping"><option value="" data-i18n="auto">Automatic</option></select></div>
<div id="size-control"><label for="rom-size" data-i18n="rom_size">ROM size override</label><select id="rom-size"><option value="" data-i18n="auto">Automatic</option></select></div>
<p class="muted small" data-i18n="overrides_note">Overrides are optional. Use detected settings unless you know the cartridge's layout.</p>
</div>
<div id="nes-options" hidden>
  <div id="nes-choice-control" hidden>
    <label for="nes-choice" data-i18n="nes_choice">Detected NES game / mapper</label>
    <select id="nes-choice"><option value="" data-i18n="auto">Automatic</option></select>
  </div>
  <p id="nes-choice-hint" class="muted small" role="status"></p>
  <label for="nes-manual-toggle" class="nes-manual-label">
    <input type="checkbox" id="nes-manual-toggle">
    <span data-i18n="nes_manual">Choose NES mapper and ROM sizes manually</span>
  </label>
  <div id="nes-manual-control" hidden>
    <label for="nes-mapper" data-i18n="nes_mapper">NES mapper / submapper</label>
    <select id="nes-mapper"></select>
    <label for="nes-prg" data-i18n="nes_prg">PRG-ROM size</label>
    <select id="nes-prg"></select>
    <label for="nes-chr" data-i18n="nes_chr">CHR-ROM size</label>
    <select id="nes-chr"></select>
    <label for="nes-mirroring" data-i18n="nes_mirroring">Mirroring (when unknown)</label>
    <select id="nes-mirroring">
      <option value="horizontal" data-i18n="nes_horizontal">Horizontal</option>
      <option value="vertical" data-i18n="nes_vertical">Vertical</option>
      <option value="four_screen" data-i18n="nes_four_screen">Four-screen</option>
    </select>
    <label for="nes-battery">
      <input type="checkbox" id="nes-battery">
      <span data-i18n="nes_battery">Battery-backed cartridge</span>
    </label>
  </div>
</div>
<button id="read" class="btn primary" data-i18n="start_read">Read ROM</button>
<div id="job-panel" class="job-panel" hidden><div class="progress-line"><strong id="job-label"></strong><span id="job-percent"></span></div><div class="progress"><div id="job-fill"></div></div><p id="job-detail" class="muted small"></p><button id="cancel" class="btn danger" data-i18n="cancel">Cancel</button></div>
</div></div>
</section>
<section id="files" class="page"><p class="eyebrow" data-i18n="shared_storage">SHARED STORAGE</p><h1 data-i18n="files_title">Your game library</h1><p class="muted" data-i18n="files_desc">Browse, rename, move, download or delete ROM files in shared storage.</p>
<div class="panel"><div class="file-head"><div id="breadcrumb" class="breadcrumb"></div><div class="actions"><button id="new-folder" class="btn secondary" data-i18n="new_folder">New folder</button><button id="refresh-files" class="btn secondary" data-i18n="refresh">Refresh</button></div></div>
<div class="file-table-wrap"><table class="file-table"><thead><tr><th data-i18n="name">Name</th><th data-i18n="size">Size</th><th data-i18n="modified">Modified</th><th data-i18n="actions">Actions</th></tr></thead><tbody id="file-rows"></tbody></table></div></div></section>
<section id="writer" class="page"><p class="eyebrow" data-i18n="future">FUTURE FEATURE</p><h1 data-i18n="writer_title">Write a cartridge</h1><div class="panel empty"><span class="big-icon">↗</span><h2 data-i18n="writer_unavailable">Writing isn't available yet</h2><p class="muted" data-i18n="writer_desc">This area is reserved for future flash and save operations, with explicit safety checks.</p></div></section>
<section id="settings" class="page"><p class="eyebrow" data-i18n="device">DEVICE</p><h1 data-i18n="settings_title">General settings</h1><div class="two-col"><div class="panel"><h2 data-i18n="wifi">Wi-Fi connection</h2><div class="keyval"><span data-i18n="wifi_status">Status</span><strong id="wifi-status">…</strong></div><div class="keyval"><span data-i18n="ip_address">IP address</span><strong id="wifi-ip">…</strong></div>
<div class="keyval"><span data-i18n="wifi_interface">Wireless interface</span><strong id="wifi-interface">…</strong></div><p id="wifi-diagnostic" class="muted small" role="status"></p>
<div class="actions"><button id="scan-wifi" class="btn secondary" data-i18n="scan">Scan networks</button><button id="disconnect-wifi" class="btn danger" data-i18n="disconnect">Disconnect</button></div><div id="wifi-networks"></div>
<label for="wifi-ssid" data-i18n="ssid">Network name (SSID)</label><input id="wifi-ssid" maxlength="32" autocomplete="off">
<label for="wifi-password" data-i18n="password">Password</label><input id="wifi-password" type="password" maxlength="128" autocomplete="new-password">
<button id="connect-wifi" class="btn primary" data-i18n="connect">Connect</button><p class="muted small" data-i18n="wifi_warning">Changing network settings may interrupt your connection.</p></div>
<div class="panel"><h2 data-i18n="localization">Language &amp; time</h2><div class="keyval"><span data-i18n="device_time">Device time</span><strong id="device-time">…</strong></div><div class="keyval"><span data-i18n="timezone">Time zone</span><strong id="device-timezone">…</strong></div><p class="muted small" data-i18n="time_note">Time and time zone are currently read-only. Language files can be added without changing the backend.</p></div></div></section>
<section id="plugins" class="page"><p class="eyebrow" data-i18n="plugins_small">PLUGIN MANAGEMENT</p><h1 data-i18n="plugins_title">Installed plugins</h1><p class="muted" data-i18n="plugins_desc">Manage installed software cores without downloading or reinstalling them.</p><div class="panel"><div class="panel-head"><h2 data-i18n="core_title">Software cores</h2><button id="refresh-cores" type="button" class="btn secondary" data-i18n="refresh">Refresh</button></div><p class="muted small" data-i18n="core_intro">Core availability comes from the CLI. Enabled does not mean usable.</p><p id="cores-summary" class="muted small" role="status"></p><div id="core-list" class="core-list"></div></div></section>
<section id="help" class="page">
<p class="eyebrow" data-i18n="help_small">DOCUMENTATION</p>
<h1 data-i18n="help_title">Help &amp; documentation</h1>
<p class="muted" data-i18n="help_intro">Quick start guide for reading cartridges and managing ROMs. The full instructions are available online.</p>
<div class="two-col">
<div class="panel">
<h2 data-i18n="help_quick_title">Quick start</h2>
<ol class="help-steps">
<li data-i18n="help_step_one">Connect Retrode3 to your computer and open its web page.</li>
<li data-i18n="help_step_two">Insert a cartridge. The slot indicator shows whether a cartridge is physically present.</li>
<li data-i18n="help_step_three">Select a supported reader and use Detect Cartridge, then Read ROM.</li>
<li data-i18n="help_step_four">Access completed dumps in the File Manager or via Samba.</li>
</ol>
</div>
<div class="panel">
<h2 data-i18n="help_web_title">Online documentation</h2>
<p class="muted" data-i18n="help_web_desc">The complete guide covers connection methods, supported systems, troubleshooting and limitations. It can later be moved into the public Wiki without changing this page.</p>
<a id="help-online-link" class="btn primary help-link" href="https://github.com/DragonBox-Shop/retrode3/blob/master/retrode3-web-control/v2/docs/user-guide.en.md" target="_blank" rel="noopener noreferrer" data-i18n="help_open_online">Open online guide</a>
<a id="help-developer-link" class="btn secondary help-link" href="https://github.com/DragonBox-Shop/retrode3/blob/master/retrode3-web-control/v2/docs/developer-guide.en.md" target="_blank" rel="noopener noreferrer" data-i18n="help_open_developer">Developer guide (CLI)</a>
<p class="muted small" data-i18n="help_note">Only documented read-only operations are currently supported. Do not remove cartridges during a read.</p>
</div>
</div>
</section>
<div id="toast" role="status" aria-live="polite"></div>
</main></div></body></html>
