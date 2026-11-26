"use strict";
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const path = require("path");
const source = fs.readFileSync(path.join(__dirname, "../web/assets/app.js"), "utf8");
const nodes = {};
const timers = new Map();
let timer = 0, complete, failRequest;
const ctx = {
  $: id => nodes[id] ||= {value:"", hidden:true, disabled:false, textContent:"",
    classList:{visible:false, add(){this.visible=true;}, remove(){this.visible=false;}},
    appendChild(){}},
  t: key => key,
  text: (node,value) => {node.textContent=String(value);},
  toastTimer:null, developerPending:false, developerState:null, developerSerial:0,
  setTimeout: (fn,ms) => {assert.strictEqual(ms,12000); timers.set(++timer,fn); return timer;},
  clearTimeout: id => timers.delete(id),
  api: (route,data) => {assert.strictEqual(route,"/api/developer/ssh"); return new Promise((resolve,reject)=>{complete=resolve;failRequest=reject;});},
  document:{createElement:()=>({})},
  fail: err => ctx.notify(err.message)
};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf("  function dismissToast()"),source.indexOf("  function api(")),ctx);
vm.runInContext(source.slice(source.indexOf("  function renderDeveloper("),source.indexOf("  function loadSettings()")),ctx);
async function run(){
  ctx.notify("first");
  ctx.notify("second");
  assert.strictEqual(timers.size,1);
  assert.strictEqual(nodes["toast-message"].textContent,"second");
  ctx.dismissToast();
  assert(!nodes.toast.classList.visible && timers.size===0);
  ctx.notify("auto");
  [...timers.values()][0]();
  assert(!nodes.toast.classList.visible);
  ctx.renderDeveloper({configured:false,setup_allowed:true,keys:[]});
  nodes["developer-new"]= {value:"x"};
  nodes["developer-repeat"]= {value:"x"};
  const setup=ctx.saveDeveloperPassword(true);
  assert(nodes["developer-save"].disabled);
  assert.strictEqual(nodes["developer-feedback"].textContent,"developer_saving");
  complete({configured:true,running:false,enabled:false,keys:[]});
  await setup;
  assert(nodes["developer-setup"].hidden && !nodes["developer-controls"].hidden);
  assert(!nodes["ssh-enable"].disabled && !nodes["ssh-key-add"].disabled);
  assert.strictEqual(nodes["toast-message"].textContent,"developer_saved");
  const enable=ctx.changeSSH("enable");
  assert(nodes["ssh-enable"].disabled);
  failRequest(new Error("SSH start failed"));
  await enable;
  assert(!nodes["ssh-enable"].disabled);
  assert.strictEqual(nodes["toast-message"].textContent,"SSH start failed");
  console.log("Developer setup feedback and notification dismissal passed");
}
run().catch(err=>{console.error(err);process.exitCode=1;});
