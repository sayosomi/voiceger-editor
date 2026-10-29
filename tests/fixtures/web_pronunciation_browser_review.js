"use strict";

// Execute production handlers against controlled DOM/history/IME event doubles.
const fs = require("fs");
const assert = require("assert").strict;
const js = fs.readFileSync(process.argv[2], "utf8");

function slice(start, end) {
  const a = js.indexOf(start), b = js.indexOf(end, a);
  assert(a >= 0 && b > a, "Production source boundary not found: " + start);
  return js.slice(a, b);
}
function node(value = "") {
  return {
    value, hidden:false, disabled:false, dataset:{}, listeners:{}, focusCount:0,
    addEventListener(type, callback) {
      (this.listeners[type] ||= []).push(callback);
    },
    emit(type, event = {}) {
      for (const fn of this.listeners[type] || []) fn(event);
    },
    focus() { this.focusCount++; },
    setSelectionRange(a,b) { this.selectionStart=a; this.selectionEnd=b; },
    setRangeText(mark,a,b) {
      this.value=this.value.slice(0,a)+mark+this.value.slice(b);
      this.selectionStart=this.selectionEnd=a+mark.length;
    },
    dispatchEvent(e) { this.emit(e.type, e); },
    querySelector() { return {focus(){}}; },
    querySelectorAll() { return []; },
    setAttribute() {}
  };
}
function assistHarness() {
  const input = node("アメ");
  input.selectionStart=input.selectionEnd=1;
  const buttons = ["'", "[", "]", " ", null].map(mark => {
    const b = node();
    b.dataset.pronunciationInsert=mark===null?undefined:mark;
    b.hasAttribute=name=>name==="data-pronunciation-backspace" && mark===null;
    return b;
  });
  const reset = node();
  const byId = {"pronunciation-text":input, "reset-pronunciation":reset,
    "view-pronunciation":{querySelectorAll:()=>buttons}};
  let clears=0;
  const code = [
    "let busy=false,pronunciationComposing=false,pronunciationStale=false;",
    'let currentView="pronunciation",pronunciationOpening="アメ";',
    "let pronunciationSelection={start:0,end:0};",
    'let playback=null;',
    "function clearPlayer(){clears++;playback=null;}",
    slice("  function rememberPronunciationSelection() {",
          "  function openPronunciation() {"),
    slice('  $("pronunciation-text").addEventListener("compositionstart"',
          '  $("preview-pronunciation").addEventListener("click"'),
    "return {input,buttons,reset,rememberPronunciationSelection,",
    " editPronunciationAtCaret, getClears:()=>clears, setPlayback:p=>{playback=p;}};"
  ].join("\n");
  return new Function("$","input","buttons","reset","Event","clears",code)(
    id=>byId[id],input,buttons,reset,class Event {constructor(type){this.type=type;}},clears
  );
}
{
  const a=assistHarness();
  const touch=a.buttons[0];
  a.input.emit("compositionstart");
  touch.emit("pointerdown"); // IME active when finger lands
  a.input.emit("compositionend"); // Android commits before click
  touch.emit("click");
  assert.equal(a.input.value,"アメ","IME-origin gesture must not insert mark");
  touch.emit("pointerdown");
  touch.emit("click");
  assert.equal(a.input.value,"ア'メ","fresh post-IME gesture should insert once");
  assert.equal(a.input.selectionStart,2);
  a.input.selectionStart=0;
  a.input.selectionEnd=2;
  a.buttons[1].emit("pointerdown");
  a.buttons[1].emit("click");
  assert.equal(a.input.value,"[メ","selection must be replaced");
  a.buttons[4].emit("pointerdown");
  a.buttons[4].emit("click");
  assert.equal(a.input.value,"メ","Backspace removes preceding character");
  a.input.value="アメ";
  a.input.setSelectionRange(1,1);
  let prevented=false;
  a.buttons[3].emit("mousedown",{preventDefault(){prevented=true;}});
  a.buttons[3].emit("pointerdown");
  a.buttons[3].emit("click");
  assert(prevented,"mouse focus should stay on textarea");
  assert.equal(a.input.value,"ア メ","space inserted at preserved caret");
  assert(a.input.focusCount>0,"textarea refocused after assist");
  // Preview from prior draft must not survive input, reset, or old event.
  a.setPlayback({kind:"preview",phase:"playing"});
  a.input.emit("input");
  assert.equal(a.getClears(),1);
  a.setPlayback({kind:"preview",phase:"ready"});
  a.reset.emit("click");
  assert.equal(a.getClears(),2);
  assert.equal(a.input.value,"アメ");
}

function historyHarness() {
  const events={};
  const nodes={};
  const $=id=>(nodes[id] ||= node(id==="pronunciation-text"?"アメ'":""));
  let responses=[false,true];
  let prompts=[], pushCount=0, backCount=0, cleared=0, notes=[];
  const win={
    addEventListener(name,cb){events[name]=cb;},
    confirm(text){prompts.push(text);return responses.shift();},
    history:{
      pushState(){pushCount++;},
      back(){backCount++;events.popstate();}
    },
    scrollTo(){}
  };
  const setup=[
    'let currentView="pronunciation",pronunciationOpening="ア\'メ";',
    'let pronunciationHistoryActive=true,pronunciationExitPending=null;',
    'let pronunciationItemId="i",pronunciationStale=false;',
    'let busy=false, selectedId="i",batch={items:[{id:"i",caption:"雨"}]};',
    'let sessionId="s",reorderMode=false,deleteMode=false;',
    'let viewNames=["connect","list","add","item","pronunciation","session"];',
    'function endReorderMode(){} function endDeleteMode(){}',
    'function clearPlayer(){recordClear();}',
    'function renderItem(){}',
    'function feedback(message){recordNote(message);}',
    slice('  function pronunciationDirty() {','  async function request(method, path, payload) {'),
    'return {showView,guardDraft,pronunciationDirty,',
    ' getView:()=>currentView, getHistory:()=>pronunciationHistoryActive,',
    ' setBusy:v=>{busy=v;}, setExit:p=>{pronunciationExitPending=p;}};'
  ].join("\n");
  const h=new Function("$","window","recordClear","recordNote",setup)(
    $,win,()=>cleared++,s=>notes.push(s)
  );
  return {h,events,$,win,setResponses:values=>{responses=values;},
    getPrompts:()=>prompts, getPushes:()=>pushCount,
    getBacks:()=>backCount,getCleared:()=>cleared,getNotes:()=>notes};
}
{
  const v=historyHarness();
  let prevented=false;
  const event={preventDefault(){prevented=true;},returnValue:null};
  v.events.beforeunload(event);
  assert(prevented && event.returnValue==="","reload requires unsaved confirmation");
  v.win.history.back(); // User refuses to discard draft.
  assert.equal(v.h.getView(),"pronunciation");
  assert.equal(v.h.getHistory(),true);
  assert.equal(v.getPushes(),1,"re-push history sentinel on canceled Back");
  v.win.history.back(); // User accepts.
  assert.equal(v.h.getView(),"item");
  assert.equal(v.h.getHistory(),false);
  assert.equal(v.getCleared(),1);
}
{
  const v=historyHarness();
  v.setResponses([true]);
  assert.equal(v.h.showView("session"),true);
  assert.equal(v.h.getView(),"session","app navigation must consume editor history");
  assert.equal(v.getBacks(),1);
  assert.equal(v.getPrompts().length,1,"confirm once");
}
{
  const v=historyHarness();
  v.h.setBusy(true);
  v.win.history.back();
  assert.equal(v.h.getView(),"pronunciation","busy work blocks Android Back");
  assert.equal(v.getPushes(),1);
  v.h.setExit({destination:"item",message:"発音を反映しました。"});
  v.win.history.back(); // completed Apply may unwind while busy flag settles
  assert.equal(v.h.getView(),"item");
  assert.equal(v.getNotes().at(-1),"発音を反映しました。");
}

async function applyTests() {
  const sourceFn=slice("  async function applyPronunciation(event) {",
                       '  $("open-pronunciation").addEventListener("click"');
  async function run(fails) {
    const candidates={revision:7,items:[{id:"i",candidate_count:4}]};
    let requests=0, prompts=[], messages=[], fixed=[];
    const input=node("ア'メ.");
    const code=[
      'let busy=false,pronunciationStale=false;',
      'let pronunciationItemId="i",selectedId="i",pronunciationOpening="ア\'メ。";',
      'let pronunciationHistoryActive=false,pronunciationExitPending=null;',
      'let batch={revision:7,items:[{id:"i",candidate_count:4}]};',
      'function setBusy(v){busy=v;}',
      'function clearPlayer(){} function renderList(){} function showView(){}',
      'function feedback(s){messages.push(s);}',
      'function setFixed(a,b){fixed.push([a,b]);}',
      'function itemAudioPath(){return "/items/i";}',
      'async function refresh(){}',
      sourceFn,
      'return {applyPronunciation, getStale:()=>pronunciationStale};'
    ].join("\n");
    const fn=new Function("$","window","request","messages","fixed",code)(
      id=>id==="pronunciation-text"?input:node(),
      {confirm:s=>{prompts.push(s);return true;}},
      async()=>{requests++;if(fails)throw {code:409,conflictCode:"revision_conflict",message:"stale"};return {changed:false,batch:candidates};},
      messages,fixed
    );
    await fn.applyPronunciation({preventDefault(){}});
    return {fn,prompts,messages,fixed,getRequests:()=>requests};
  }
  const noop=await run(false);
  assert.equal(noop.getRequests(),1);
  assert.match(noop.prompts[0],/場合/,"no-op confirmation must be conditional");
  assert.match(noop.messages.at(-1),/維持されました/);
  const stale=await run(true);
  assert(stale.fn.getStale(),"Apply revision conflict must mark editor stale");
  assert.deepEqual(stale.fixed.at(-1),["apply-pronunciation",true]);
  await stale.fn.applyPronunciation({preventDefault(){}});
  assert.equal(stale.getRequests(),1,"no stale re-Apply");
}
applyTests().then(()=>console.log("WEB_PRONUNCIATION_BROWSER_REVIEW_PASS"))
  .catch(e=>{console.error(e);process.exitCode=1;});
