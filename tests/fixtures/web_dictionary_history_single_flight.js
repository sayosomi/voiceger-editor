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

// NAV-02: Save/Delete HTTP updates stay single-flight until history settles.
function saveDeleteHarness(entryId) {
  const historyCalls = [], requests = [], notifications = [], views = [], pending = [];
  let currentIndex = 2, confirmCount = 0, failNext = false;
  const entries = [
    null,
    {voicegerDictionary:true,sessionId:"s",view:"dictionary",depth:1},
    {voicegerDictionary:true,sessionId:"s",view:"dictionary-entry",depth:2}
  ];
  const events = {};
  const window = {
    confirm() {confirmCount++;return true;},
    addEventListener(type, listener) {events[type] = listener;},
    history: {
      back() {historyCalls.push("back");pending.push(-1);},
      go(delta) {historyCalls.push("go:"+delta);pending.push(delta);},
      pushState(state) {entries.splice(currentIndex+1);entries.push(state);currentIndex++;},
      replaceState(state) {entries[currentIndex] = state;}
    }
  };
  const code = [
    'let busy=false,currentView="dictionary-entry",sessionId="s",',
    'dictionaryHistoryDepth=2,dictionaryHistoryDestination=null,',
    'dictionaryHistoryNotice="",dictReturnView="list",',
    'dictEntry={id:entryId,notation:"アメ"},dictEntryOriginal={id:entryId},',
    'dictData={revision:"r1"},dictLanguage="ja",dictPronOpening=null,dictDuplicate=null;',
    'let settingsHistoryActive=false,settingsHistoryDestination=null,settingsReturnView="list";',
    'let sectionHistoryActive=false,pronunciationHistoryActive=false;',
    'function guardDraft(){return true;}',
    'function guardDictionaryPronunciationDraft(){return true;}',
    'function showView(view){views.push(view);currentView=view;return true;}',
    'function setBusy(value){busy=value;}',
    'function feedback(message){notifications.push(message);}',
    'function hideDictionaryDuplicate(){}',
    'function showDictionaryDuplicate(){}',
    'function showDictionarySaveError(message){notifications.push("error:"+message);}',
    'function dictionaryPath(){return "/api/dictionary";}',
    'function dictionaryFormValue(){return {surface:"雨",notation:"アメ",',
    'word_type:"PROPER_NOUN",priority:5};}',
    'async function dictionaryQuickMatches(){return {entries:[]};}',
    'function dictionaryDuplicateFor(){return null;}',
    'async function request(method,path,payload){',
    '  requests.push({method,path,payload});',
    '  if(failState.fail){failState.fail=false;throw Error("network rejected");}',
    '  return {changed:true};',
    '}',
    cut('  window.addEventListener("popstate"', '  window.addEventListener("beforeunload"'),
    cut('  function requestDictionaryHistoryExit(destination, delta) {',
        '  function revealDictionaryRegistrationError(id) {'),
    cut('  function dictionaryFinish(message) {',
        '  // Quick Save never Applies the source pronunciation'),
    'return {save:dictionarySave,remove:dictionaryDelete,',
    'state(){return {busy,currentView,dictionaryHistoryDepth,',
    'dictionaryHistoryDestination,dictEntry,dictEntryOriginal};}};'
  ].join("\n");
  const failState = {fail:false};
  const h = new Function("window","requests","notifications","views","entryId",
    "failState",code)(window,requests,notifications,views,entryId,failState);
  function flush() {
    assert.equal(pending.length,1,"Only one history exit may be pending");
    currentIndex += pending.shift();
    assert(currentIndex >= 0 && currentIndex < entries.length);
    events.popstate({state:entries[currentIndex]});
  }
  return {...h,historyCalls,requests,notifications,views,flush,pending,
    confirmCount:()=>confirmCount,failNext(){failState.fail=true;}};
}

async function runSaveDelete() {
  const submit = {preventDefault(){}};

  // An updated word remains in memory until popstate, but cannot be PUT twice.
  {
    const h = saveDeleteHarness("word");
    await h.save(submit);
    assert.equal(h.requests.length,1);
    assert.equal(h.requests[0].method,"PUT");
    assert.equal(h.state().busy,false,"setBusy(false) re-enables form controls");
    assert.equal(h.state().dictionaryHistoryDestination,"dictionary");
    assert.equal(h.state().dictEntry.id,"word","Parent entry remains until popstate");
    await h.save(submit);
    await h.remove();
    assert.equal(h.requests.length,1,"No second PUT or DELETE while Back is pending");
    assert.equal(h.confirmCount(),0,"Delete prompt must not appear while exiting");
    assert.deepEqual(h.historyCalls,["back"]);
    h.flush();
    assert.equal(h.state().dictionaryHistoryDestination,null);
    assert.equal(h.state().dictEntry,null);
    assert.equal(h.state().currentView,"dictionary");
    assert.deepEqual(h.notifications,["辞書に保存しました。"]);
  }

  // A newly created word must not be POSTed twice either.
  {
    const h = saveDeleteHarness(null);
    await h.save(submit);
    await h.save(submit);
    assert.deepEqual(h.requests.map(x=>x.method),["POST"]);
    assert.equal(h.state().dictionaryHistoryDestination,"dictionary");
    h.flush();
    assert.equal(h.state().currentView,"dictionary");
  }

  // DELETE must be single-flight during delayed history navigation.
  {
    const h = saveDeleteHarness("word");
    await h.remove();
    assert.equal(h.confirmCount(),1);
    await h.remove();
    await h.save(submit);
    assert.deepEqual(h.requests.map(x=>x.method),["DELETE"]);
    assert.equal(h.confirmCount(),1);
    assert.deepEqual(h.historyCalls,["back"]);
    h.flush();
    assert.equal(h.state().dictEntry,null);
    assert.equal(h.state().dictionaryHistoryDestination,null);
    assert.deepEqual(h.notifications,["単語を削除しました。"]);
  }

  // A failed HTTP write leaves navigation unlocked, preserving a retry path.
  {
    const h = saveDeleteHarness("word");
    h.failNext();
    await h.save(submit);
    assert.equal(h.state().dictionaryHistoryDestination,null);
    assert.equal(h.state().dictEntry.id,"word");
    await h.save(submit);
    assert.deepEqual(h.requests.map(x=>x.method),["PUT","PUT"]);
    assert.deepEqual(h.historyCalls,["back"]);
    h.flush();
    assert.equal(h.state().currentView,"dictionary");
  }

  console.log("DICT_SAVE_DELETE_HISTORY_PASS");
}
runSaveDelete().catch(error=>{console.error(error);process.exitCode=1;});