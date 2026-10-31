"use strict";
const fs = require("fs"), assert = require("node:assert/strict");
const js = fs.readFileSync(process.argv[2], "utf8");
function cut(start, end) {
  const a = js.indexOf(start), b = js.indexOf(end, a);
  assert(a >= 0 && b > a, "Missing production function: " + start);
  return js.slice(a, b);
}
assert(js.includes('$("dictionary-manage").addEventListener("click", openDictionaryManagement)'));
assert(js.includes('$("dictionary-management-back").addEventListener("click", dictionaryBack)'));
assert(js.includes('"dictionary-management"'));

// Use real browser-history handlers; only DOM/showView and native history are faked.
function harness() {
  const events = {}, pending = [], entries = [null], views = [], notices = [];
  let index = 0, allowed = true;
  const window = {
    addEventListener(name, fn) { events[name] = fn; },
    history: {
      pushState(state) { entries.splice(index + 1); entries.push(state); index++; },
      replaceState(state) { entries[index] = state; },
      back() { pending.push(-1); },
      go(delta) { pending.push(delta); },
      forward() { pending.push(1); }
    }
  };
  const setup = [
    'let currentView="list",sessionId="s",busy=false;',
    'let dictionaryHistoryDepth=0,dictionaryHistoryDestination=null,',
    'dictionaryHistoryNotice="",dictReturnView="list";',
    'let dictEntry=null,dictEntryOriginal=null,dictPronOpening=null;',
    'let dictionaryImportReview=null;',
    'let settingsHistoryActive=false,settingsHistoryDestination=null,settingsReturnView="list";',
    'let sectionHistoryActive=false,pronunciationHistoryActive=false;',
    'function guardDraft(){return isAllowed();}',
    'function guardDictionaryPronunciationDraft(){return isAllowed();}',
    'function showView(view){currentView=view;views.push(view);return true;}',
    'function dictionaryExportNotice(message){notices.push(message);}',
    'function feedback(message){notices.push(message);}',
    cut('  window.addEventListener("popstate"', '  window.addEventListener("beforeunload"'),
    cut('  function dictionaryPushHistory(view) {', '  function openDictionaryEntry(row) {'),
    cut('  function openDictionaryManagement() {', '  function dictionaryExportNotice(text, isError) {'),
    'return {open:openDictionaryManagement,back:dictionaryBack,global:navigateGlobal,',
    'push:dictionaryPushHistory,setView(v){currentView=v},',
    'setReview(v){dictionaryImportReview=v},',
    'state(){return {currentView,dictionaryHistoryDepth,dictionaryHistoryDestination};}};'
  ].join("\n");
  const app = new Function("window","views","notices","isAllowed",setup)(
    window,views,notices,()=>allowed);
  function flush() {
    assert.equal(pending.length,1,"Only one pending browser navigation is allowed");
    const next = index + pending.shift();
    assert(next >= 0 && next < entries.length,"Navigation crossed document boundary");
    index = next;
    events.popstate({state:entries[index]});
  }
  function entry() { return entries[index]; }
  return {...app,window,views,notices,pending,flush,entry,
    allow(value){allowed=value;},setReview(value){app.setReview(value);}};
}
{
  const h = harness();
  h.setView("dictionary"); h.push("dictionary");
  h.open();
  assert.deepEqual(h.state(),{
    currentView:"dictionary-management",
    dictionaryHistoryDepth:2,
    dictionaryHistoryDestination:null
  });
  assert.equal(h.entry().view,"dictionary-management");
  h.back(); h.back();
  assert.equal(h.pending.length,1,"Repeated UI Back must be single-flight");
  h.flush();
  assert.equal(h.state().currentView,"dictionary");
  assert.equal(h.state().dictionaryHistoryDepth,1);
  // Forward into management is safe; unlike a discarded word draft.
  h.window.history.forward(); h.flush();
  assert.equal(h.state().currentView,"dictionary-management");
  assert.equal(h.state().dictionaryHistoryDepth,2);
  // Android/Chrome system Back (not the in-app button).
  h.window.history.back(); h.flush();
  assert.equal(h.state().currentView,"dictionary");
  h.open(); h.global("dictionary");
  assert.equal(h.pending.length,1);
  h.flush();
  assert.equal(h.state().currentView,"dictionary");
  assert.equal(h.state().dictionaryHistoryDepth,1);
  // Leaving the nested view for Batch consumes the exact two dictionary entries.
  h.open(); h.global("list");
  assert.equal(h.pending.length,1);
  h.flush();
  assert.equal(h.state().currentView,"list");
  assert.equal(h.state().dictionaryHistoryDepth,0);
}
{
  const h = harness();
  h.setView("dictionary");h.push("dictionary");h.open();
  h.allow(false);h.back();h.global("list");
  assert.equal(h.pending.length,0);
  assert.equal(h.state().currentView,"dictionary-management");
  h.allow(true);h.back();h.flush();
  assert.equal(h.state().currentView,"dictionary");
}
console.log("DICT_MANAGEMENT_NAV_PASS");
