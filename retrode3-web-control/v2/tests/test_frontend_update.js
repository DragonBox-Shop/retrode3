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
  updateTimer:null, updatePolling:false,
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
console.log("Update preview and state transitions passed");
