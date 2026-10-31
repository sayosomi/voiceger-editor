"use strict";
const fs = require("node:fs"), assert = require("node:assert/strict");
const js = fs.readFileSync(process.argv[2], "utf8");

function cut(start, end) {
  const a = js.indexOf(start), b = js.indexOf(end, a);
  assert(a >= 0 && b > a, "Missing production code: " + start);
  return js.slice(a, b);
}

function harness(initialView, initialDepth) {
  const events = {}, calls = [], views = [], notices = [];
  const entries = [
    null,
    {voicegerDictionary:true, sessionId:"s", view:"dictionary", depth:1},
    {voicegerDictionary:true, sessionId:"s", view:"dictionary-entry", depth:2},
    {voicegerDictionary:true, sessionId:"s", view:"dictionary-pron", depth:3}
  ];
  let index = initialDepth, allowed = true, failNext = false;
  const pending = [];
  const window = {
    addEventListener(type, listener) {events[type] = listener;},
    history: {
      back() {
        calls.push("back");
        if (failNext) {failNext = false; throw Error("history blocked");}
        pending.push(-1);
      },
      go(delta) {
        calls.push("go:" + delta);
        if (failNext) {failNext = false; throw Error("history blocked");}
        pending.push(delta);
      },
      pushState(state) {
        entries.splice(index + 1);
        entries.push(state);
        index++;
        calls.push("push");
      },
      replaceState(state) {entries[index] = state; calls.push("replace");}
    }
  };
  const setup = [
    'let currentView=initialView,sessionId="s",busy=false;',
    'let dictionaryHistoryDepth=initialDepth,dictionaryHistoryDestination=null,',
    'dictionaryHistoryNotice="",dictReturnView="list";',
    'let dictEntry={id:"word",notation:"ア\'メ"},dictEntryOriginal={id:"word",surface:"雨"},',
    'dictPronOpening="ア\'メ",dictDuplicate=null,dictQuery="",dictSort="",dictType="";',
    'let settingsHistoryActive=false,settingsHistoryDestination=null,settingsReturnView="list";',
    'let sectionHistoryActive=false,pronunciationHistoryActive=false;',
    'function guardDraft(){return isAllowed();}',
    'function guardDictionaryPronunciationDraft(){return isAllowed();}',
    'function showView(view){currentView=view;views.push(view);return true;}',
    'function feedback(message){notices.push(message);}',
    cut('  window.addEventListener("popstate"', '  window.addEventListener("beforeunload"'),
    cut('  function dictionaryPushHistory(view) {', '  function openDictionaryEntry(row) {'),
    cut('  function leaveDictionaryPronunciation() {', '  function clearDictionaryPronunciationError() {'),
    cut('  function dictionaryFinish(message) {', '  async function dictionarySave(event) {'),
    'return {leave:leaveDictionaryPronunciation,back:dictionaryBack,',
    'global:navigateGlobal,finish:dictionaryFinish,',
    'state(){return {currentView,dictionaryHistoryDepth,dictionaryHistoryDestination,',
    'dictEntry,dictEntryOriginal,dictPronOpening};}};'
  ].join("\n");
  const app = new Function("window","views","notices","initialView","initialDepth",
    "isAllowed",setup)(window,views,notices,initialView,initialDepth,()=>allowed);
  function flush() {
    assert(pending.length, "Expected queued browser history transition");
    index += pending.shift();
    assert(index >= 0 && index < entries.length, "History crossed document boundary");
    events.popstate({state:entries[index]});
  }
  return {...app,calls,views,notices,flush,
    allow(value){allowed=value;},
    failOnce(){failNext=true;},
    pending(){return pending.length;}
  };
}

// A doubled Cancel before popstate must consume only one entry, then release.
{
  const h = harness("dictionary-pron",3);
  const original = h.state().dictEntry;
  h.leave(); h.leave();
  assert.deepEqual(h.calls,["back"]);
  assert.equal(h.state().dictionaryHistoryDestination,"dictionary-entry");
  h.flush();
  assert.equal(h.state().currentView,"dictionary-entry");
  assert.equal(h.state().dictionaryHistoryDepth,2);
  assert.equal(h.state().dictionaryHistoryDestination,null);
  assert.equal(h.state().dictEntry,original,"Parent word draft preserved");
  assert.equal(h.state().dictPronOpening,null);
  h.back(); h.flush();
  assert.equal(h.state().currentView,"dictionary");
  assert.equal(h.state().dictionaryHistoryDepth,1);
  h.back(); h.flush();
  assert.equal(h.state().currentView,"list");
  assert.equal(h.state().dictionaryHistoryDepth,0);
  assert.deepEqual(h.calls,["back","back","back"]);
}

// UI Back and mixed exit buttons must share the same in-flight guard.
{
  const h = harness("dictionary-pron",3);
  h.back(); h.back(); h.leave(); h.global("list");
  assert.deepEqual(h.calls,["back"]);
  h.flush();
  assert.equal(h.state().currentView,"dictionary-entry");
  assert.equal(h.state().dictEntry.id,"word");
  assert.equal(h.state().dictionaryHistoryDestination,null);
}

// Global exit requests unwind the existing history exactly once.
{
  const h = harness("dictionary-pron",3);
  h.global("list"); h.global("session"); h.back(); h.leave();
  assert.deepEqual(h.calls,["go:-3"]);
  h.flush();
  assert.equal(h.state().currentView,"list");
  assert.equal(h.state().dictionaryHistoryDepth,0);
  assert.equal(h.state().dictionaryHistoryDestination,null);
  h.global("dictionary");
  assert.equal(h.state().currentView,"dictionary","Next navigation must work");
}

// Rejected draft-discard confirmation must not acquire the guard.
{
  const h = harness("dictionary-pron",3);
  h.allow(false);
  h.leave(); h.back(); h.global("list");
  assert.deepEqual(h.calls,[]);
  assert.equal(h.state().dictionaryHistoryDestination,null);
  assert.equal(h.state().dictPronOpening,"ア'メ");
  h.allow(true);
  h.leave(); h.flush();
  assert.equal(h.state().currentView,"dictionary-entry");
}

// Failed history API operation releases the guard and preserves the editor.
{
  const h = harness("dictionary-pron",3);
  h.failOnce(); h.leave();
  assert.equal(h.state().dictionaryHistoryDestination,null);
  assert.equal(h.state().dictPronOpening,"ア'メ");
  assert.equal(h.notices.length,1);
  h.leave(); h.flush();
  assert.equal(h.state().currentView,"dictionary-entry");
}

// Save/Delete completion uses the same navigation owner, retaining feedback.
{
  const h = harness("dictionary-entry",2);
  h.finish("Saved"); h.finish("Saved");
  assert.deepEqual(h.calls,["back"]);
  h.flush();
  assert.equal(h.state().currentView,"dictionary");
  assert.equal(h.state().dictEntry,null);
  assert.equal(h.state().dictionaryHistoryDestination,null);
  assert.deepEqual(h.notices,["Saved"]);
}

const reset = cut('  function resetLocal(clearSessionId) {','  async function refresh() {');
assert(reset.includes('dictionaryHistoryDestination = null;'),
  "Session teardown must release pending dictionary history");
console.log("DICT_HISTORY_SINGLE_FLIGHT_PASS");