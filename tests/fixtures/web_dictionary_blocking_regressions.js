"use strict";
const fs = require("fs"), assert = require("node:assert/strict");
const js = fs.readFileSync(process.argv[2], "utf8");
function cut(start, end) {
  const a = js.indexOf(start), b = js.indexOf(end, a);
  assert(a >= 0 && b > a, "Missing production function: " + start);
  return js.slice(a, b);
}
const dirtyFunctions = cut('  function dictionaryPronunciationDirty() {',
                           '  function dictionaryTypeLabel(value) {');
const unloadHandler = cut('  window.addEventListener("beforeunload"',
                          '  async function request(method, path, payload) {');
{
  const events = {};
  const inputs = {
    "dictionary-pron-text": {value:"ア'メ"},
    "dictionary-surface": {value:"変更後"},
    "dictionary-word-type": {value:"PROPER_NOUN"},
    "dictionary-priority": {value:"9"}
  };
  const setup = [
    'let currentView="dictionary-pron",dictPronOpening="ア\'メ";',
    'let dictEntry={notation:"ア\'メ"},',
    'dictEntryOriginal={surface:"変更前",notation:"ア\'メ",word_type:"PROPER_NOUN",priority:9};',
    'function pronunciationDirty(){return false;}',
    'function sectionDirty(){return false;}',
    dirtyFunctions, unloadHandler,
    'return {setView(v){currentView=v},setOriginal(v){dictEntryOriginal.surface=v},',
    'setText(v){$("dictionary-pron-text").value=v}};'
  ].join("\n");
  const h = new Function("$","window",setup)(
    id=>inputs[id],{addEventListener:(type,cb)=>events[type]=cb}
  );
  function unload() {
    let prevented=false, event={preventDefault(){prevented=true}};
    events.beforeunload(event);
    return prevented && event.returnValue==="";
  }
  assert(unload(),"Parent Surface edit must guard reload from nested pronunciation");
  h.setOriginal("変更後");
  assert(!unload(),"Clean nested pronunciation should not block reload");
  h.setText("アメ'");
  assert(unload(),"Pronunciation edit alone must guard reload");
  h.setView("dictionary-entry");
  h.setText("ア'メ");
  h.setOriginal("変更前");
  assert(unload(),"Parent form must guard reload when its screen is visible");
  console.log("F01_UNLOAD_PASS");
}
{
  const events = {}, entries=[null], calls=[];
  let i=0;
  const win = {
    addEventListener(type,fn){events[type]=fn;},
    scrollTo(){}, confirm(){return true;},
    history: {
      pushState(state){entries.splice(i+1);entries.push(state);i++;},
      replaceState(state){entries[i]=state;calls.push("replace");},
      back(){this.go(-1);},
      forward(){this.go(1);},
      go(delta){const next=i+delta;if(next<0||next>=entries.length)return;
        i=next;events.popstate({state:entries[i]});}
    }
  };
  const setup=[
    'let currentView="list",sessionId="session",busy=false;',
    'let dictReturnView="list",dictEntry=null,dictEntryOriginal=null,dictPronOpening=null;',
    'let dictionaryHistoryDepth=0,dictionaryHistoryDestination=null, dictionaryHistoryNotice="";',
    'let settingsReturnView="list",settingsHistoryActive=false,settingsHistoryDestination=null;',
    'let sectionHistoryActive=false,pronunciationHistoryActive=false;',
    'function guardDraft(){return true;}',
    'function guardDictionaryPronunciationDraft(){return true;}',
    'function showView(view){currentView=view;return true;}',
    'function feedback(m){calls.push(m);}',
    cut('  window.addEventListener("popstate"', '  window.addEventListener("beforeunload"'),
    cut('  function dictionaryPushHistory(view) {','  function navigateGlobal(destination) {'),
    cut('  function dictionaryBack() {','  function openDictionaryEntry(row) {'),
    'return {push:dictionaryPushHistory,back:dictionaryBack,setView(v){currentView=v},',
    'setEntry(v){dictEntry=v;dictEntryOriginal=v},',
    'state(){return {view:currentView,depth:dictionaryHistoryDepth,entry:dictEntry}}};'
  ].join("\n");
  const h = new Function("window","calls",setup)(win,calls);
  h.setView("dictionary");h.push("dictionary");
  assert.equal(i,1);assert.equal(h.state().depth,1);
  h.setView("dictionary-entry");h.push("dictionary-entry");h.setEntry({id:"x"});
  assert.equal(i,2);
  win.history.back();
  assert.equal(h.state().view,"dictionary");
  assert.equal(h.state().depth,1);
  win.history.forward();
  assert.equal(i,2);
  assert.equal(h.state().view,"dictionary","Forward must not restore discarded word editor");
  assert.equal(entries[2].view,"dictionary","Stale history entry normalized in-place");
  assert.equal(h.state().depth,2);
  assert.equal(h.state().entry,null);
  win.history.back();
  assert.equal(i,1);assert.equal(h.state().view,"dictionary");
  assert.equal(h.state().depth,1,"Back from normalized Forward stays in dictionary");
  win.history.back();
  assert.equal(i,0);assert.equal(h.state().view,"list");
  win.history.forward();
  assert.equal(i,1);assert.equal(h.state().view,"dictionary");
  win.history.forward();
  assert.equal(i,2);assert.equal(h.state().view,"dictionary");
  win.history.back();
  assert.equal(i,1);assert.equal(h.state().view,"dictionary");
  assert.deepEqual(calls.filter(x=>x==="replace"),["replace"]);
  // UI Back must agree with Android/browser Back after Forward normalization.
  win.history.forward();
  assert.equal(i,2);assert.equal(h.state().depth,2);
  win.history.back();
  assert.equal(i,1);assert.equal(h.state().view,"dictionary");
  win.history.forward();
  h.back();
  assert.equal(i,1,"UI Back must consume only the actual history step");
  assert.equal(h.state().view,"dictionary","UI and browser Back agree");
  assert.equal(h.state().depth,1);
  h.back();
  assert.equal(i,0);assert.equal(h.state().view,"list");
  assert.equal(h.state().depth,0,"second UI Back reaches Batch entry");
  win.history.forward();
  assert.equal(i,1);assert.equal(h.state().view,"dictionary");
  win.history.back();
  assert.equal(i,0);assert.equal(h.state().view,"list");
  // Normal nested Back must continue preserving the parent editor draft.
  h.setView("dictionary");h.push("dictionary");
  h.setView("dictionary-entry");h.push("dictionary-entry");
  h.setEntry({id:"word"});
  h.setView("dictionary-pron");h.push("dictionary-pron");
  assert.equal(i,3);
  h.back();
  assert.equal(i,2);assert.equal(h.state().view,"dictionary-entry");
  assert.equal(h.state().entry.id,"word");
  h.back();
  assert.equal(i,1);assert.equal(h.state().view,"dictionary");
  assert.equal(h.state().entry,null);
  h.back();
  assert.equal(i,0);assert.equal(h.state().view,"list");
  console.log("F02_HISTORY_PASS");
}
async function quickTests() {
  const quickSource = cut("  function dictionaryQuickMatches(language, surface) {",
                         '  $("dictionary-back").addEventListener("click", dictionaryBack);');
  const elements={};
  const $=id=>elements[id] ||= {value:"",dataset:{},hidden:true,attributes:{},removeAttribute(k){delete this.attributes[k];},setAttribute(k,v){this.attributes[k]=v;},scrollIntoView(){},focus(){}};
  const calls=[];
  let activeLanguage="ja", responses=[], confirms=0, manualPriority=false;
  const window={confirm(){confirms++;return true;}};
  const document={querySelectorAll(){return [];}};
  const setup=[
    'let busy=false,currentView="pronunciation",dictQuickMatches=[],',
    'dictQuickPriorityEdited=false,dictQuickPronSurface=null,pronunciationTarget={language:"ja"};',
    'function dictionaryPath(){return "/api/web/sessions/s/dictionary";}',
    'function setBusy(v){busy=v;}', 'function feedback(){}', 'function clearPlayer(){}',
    'async function request(method,path,payload){',
    '  record(method,path,payload);',
    '  if(method==="GET")return getMatches(path);',
    '  return {changed:true};',
    '}',
    quickSource,
    'return {openDictionaryQuick,saveDictionaryQuick,setLanguage(v){pronunciationTarget.language=v},',
    'setEdited(v){dictQuickPriorityEdited=v},priority:()=>$("dictionary-quick-priority").value};'
  ].join("\n");
  const getMatches=path=>{
    const language=path.includes("/en/")?"en":"ja";
    const surface=decodeURIComponent(path.split("surface=")[1]||"");
    if(language==="ja" && (surface==="ABC"||surface==="ＡＢＣ")) {
      return {revision:"r1",entries:[
        {id:"ja9",surface:"ＡＢＣ",word_type:"PROPER_NOUN",priority:9},
        {id:"ja4",surface:"ＡＢＣ",word_type:"COMMON_NOUN",priority:4}]};
    }
    if(language==="en" && surface.toLowerCase().trim()==="sweet")
      return {revision:"r1",entries:[{id:"sweet",surface:"sweet"}]};
    return {revision:"r1",entries:[]};
  };
  const h=new Function("$","window","document","record","getMatches",setup)(
    $,window,document,(method,path,payload)=>calls.push({method,path,payload}),getMatches);
  $("pronunciation-caption").textContent="ABC";
  $("pronunciation-text").value="エービーシー'";
  await h.openDictionaryQuick();
  assert.equal(h.priority(),"9","existing Japanese priority must be shown");
  await h.saveDictionaryQuick({preventDefault(){}});
  let write=calls.find(x=>x.method==="PUT");
  assert(write && write.path.endsWith("/ja9"),"existing Japanese entry must be updated");
  assert.equal(write.payload.priority,9,"existing priority must not reset");
  assert.equal($("pronunciation-text").value,"エービーシー'","source pronunciation stays intact");
  assert.equal(confirms,1);
  console.log("F03_PRIORITY_PASS");
  calls.length=0;
  $("pronunciation-caption").textContent="Sweet";
  $("pronunciation-text").value="S W IY1 T";
  h.setLanguage("en");
  await h.openDictionaryQuick();
  await h.saveDictionaryQuick({preventDefault(){}});
  write=calls.find(x=>x.method==="PUT");
  assert(write && write.path.endsWith("/sweet"),"English casefold match must PUT existing entry");
  assert(!calls.some(x=>x.method==="POST"),"English casefold must not POST duplicate");
  console.log("F04_CASEFOLD_PASS");
}
quickTests().catch(e=>{console.error(e);process.exitCode=1;});
