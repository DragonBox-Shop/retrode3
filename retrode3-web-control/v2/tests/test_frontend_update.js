"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const src = fs.readFileSync(path.join(__dirname,"../web/assets/app.js"),"utf8");
const nodes = {};
const ctx = {
  $: id => nodes[id] ||= {disabled:false,textContent:"",children:[],appendChild(el){this.children.push(el);}},
  text: (node,value) => {node.textContent=String(value);},
  t: key => key, updateState:null, updatePending:false,
  updateTimer:null, updatePolling:false, updateSerial:0,
  direct:true, currentPage:"settings", dismissToast:()=>{},
  setTimeout:()=>1, clearTimeout:()=>{},
  sessionStorage:{setItem(){}}, window:{location:{reload(){ctx.reloaded=true;}}},
  hardwareBusy: ()=>false, renderReaderState:()=>{}, renderCores:()=>{},
  document:{createElement:()=>({})}
};
vm.createContext(ctx);
vm.runInContext(src.slice(src.indexOf("  function updateInProgress("),src.indexOf("  function loadSettings()")),ctx);
ctx.renderUpdate({phase:"idle",packages:[]});
assert(!nodes["update-check"].disabled && nodes["update-install"].disabled);
ctx.renderUpdate({phase:"available",packages:[{name:"retrode3-tools",installed:"1",candidate:"2"}]});
assert(!nodes["update-install"].disabled);
assert(nodes["update-packages"].children[0].textContent.includes("1 → 2"));
ctx.renderUpdate({phase:"installing",packages:[]});
assert(nodes["update-check"].disabled && nodes["update-install"].disabled);
ctx.renderUpdate({phase:"failed",packages:[],message:"Offline"});
assert(!nodes["update-check"].disabled && nodes["update-install"].disabled);
assert(nodes["update-status"].textContent.includes("Offline"));
ctx.renderUpdate({phase:"done",packages:[{name:"retrode3-tools",installed:"1",candidate:"2"}]});
assert(nodes["update-packages"].hidden);
assert.strictEqual(nodes["update-status"].className,"update-success");
assert.strictEqual(nodes["update-status"].textContent,"update_done");
ctx.renderUpdate({phase:"current",packages:[],reboot_required:true});
assert(nodes["update-status"].textContent.includes("update_kernel_reboot"));
async function reconnect(){
  ctx.renderUpdate({phase:"installing",packages:[]});
  ctx.api=()=>Promise.reject(Object.assign(new Error("offline"),{transport:true}));
  await ctx.pollUpdate();
  assert.strictEqual(ctx.updateState.phase,"installing");
  assert.strictEqual(nodes["update-status"].textContent,"update_reconnecting");
  ctx.api=()=>Promise.resolve({phase:"done",packages:[]});
  await ctx.pollUpdate();
  assert(ctx.reloaded);
  assert(nodes["update-packages"].hidden);
  assert.strictEqual(nodes["update-status"].className,"update-success");
  console.log("Update preview, success, and reconnect transitions passed");
}
reconnect().catch(err=>{console.error(err);process.exitCode=1;});
