"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const source = fs.readFileSync(path.join(__dirname, "../web/assets/app.js"), "utf8");
const start = source.indexOf("  function renderWifiStatus(");
const end = source.indexOf("  function bind()", start);
assert(start >= 0 && end > start);
const nodes = {};
const timers = [];
let status = {available:true, associated:false, connected:false, ssid:""};
const ctx = {
  $: id => nodes[id] ||= {},
  t: key => key,
  text: (node, value) => { node.textContent = String(value); },
  api: route => { assert.strictEqual(route, "/api/wifi/status"); return Promise.resolve(status); },
  wifiOperation:null, wifiStatusSerial:0,
  setTimeout: fn => timers.push(fn),
  fail: () => {},
};
vm.createContext(ctx);
vm.runInContext(source.slice(start,end), ctx);
async function run() {
  ctx.setWifiOperation("scan", "wifi_scanning");
  assert(nodes["scan-wifi"].disabled && nodes["connect-wifi"].disabled);
  ctx.setWifiOperation(null, "wifi_scan_done");
  assert(!nodes["scan-wifi"].disabled);
  ctx.setWifiOperation("connect", "wifi_connecting");
  status = {available:true, associated:true, connected:false, ssid:"Test"};
  await ctx.waitForWifi("Test", Date.now()+30000);
  assert.strictEqual(nodes["wifi-operation"].textContent,"wifi_wait_ip");
  assert(nodes["connect-wifi"].disabled);
  status = {available:true, associated:true, connected:true, ssid:"Test", ipv4:"192.168.1.2"};
  await ctx.waitForWifi("Test", Date.now()+30000);
  assert.strictEqual(nodes["wifi-operation"].textContent,"wifi_connect_done");
  assert.strictEqual(nodes["wifi-ip"].textContent,"192.168.1.2");
  assert(!nodes["connect-wifi"].disabled);
  ctx.setWifiOperation("connect","wifi_connecting");
  await ctx.waitForWifi("Other", Date.now()-1);
  assert.strictEqual(nodes["wifi-operation"].textContent,"wifi_connect_timeout");
  assert(!nodes["connect-wifi"].disabled);
  ctx.setWifiOperation("disconnect","wifi_disconnecting");
  ctx.wifiFailed(new Error("offline"));
  assert(nodes["wifi-operation"].textContent.includes("offline"));
  assert(!nodes["disconnect-wifi"].disabled);
  console.log("Wi-Fi operation feedback and association/DHCP polling passed");
}
run().catch(err => { console.error(err); process.exitCode=1; });
