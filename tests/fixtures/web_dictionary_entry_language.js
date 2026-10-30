"use strict";
const fs = require("node:fs");
const assert = require("node:assert/strict");
const js = fs.readFileSync(process.argv[2], "utf8");
function cut(begin, end) {
  const start = js.indexOf(begin), stop = js.indexOf(end, start);
  assert(start >= 0 && stop > start, "missing production handler " + begin);
  return js.slice(start, stop);
}
const controls = {};
const $ = id => controls[id] ||= {
  value: "", hidden: false, textContent: "", attrs: {},
  setAttribute(k,v){this.attrs[k]=v;}
};
const flags={allowDiscard:true,failFetch:false};
const prompts=[], writes=[], fetches=[];
const window={confirm(message){prompts.push(message);return flags.allowDiscard;}};
const source=[
  'let busy=false,currentView="dictionary",dictLanguage="ja",dictEntry=null,dictEntryOriginal=null,',
  'dictData={revision:"rev-ja",entries:[]},dictSort="surface_asc",dictQuery="",dictType="ALL",',
  'dictListRequest=0,sessionId="session";',
  'function setBusy(v){busy=v;}',
  'function feedback(v){$("feedback").textContent=v;}',
  'function dictionaryPath(){return "/api/web/sessions/session/dictionary";}',
  'function renderDictionary(){$("[render]").textContent=dictLanguage;}',
  'function showView(view){currentView=view;}',
  'function dictionaryPushHistory(view){$("[history]").value++;}',
  'function dictionaryFinish(message){$("[finish]").textContent=message;}',
  'async function request(method,url,payload){',
  ' if(method==="GET"){fetches.push(url);if(flags.failFetch)throw Error("network failed");',
  '   return {revision:url.includes("/en?")?"rev-en":"rev-ja",entries:[]};}',
  ' writes.push({method,url,payload});return {changed:true};',
  '}',
  cut('  function dictionaryEntryDirty() {','  function dictionaryTypeLabel(value) {'),
  cut('  function renderDictionaryEntryLanguage() {','  function enterDictionaryPronunciation() {'),
  cut('  async function dictionarySave(event) {','  async function dictionaryDelete() {'),
  'return {openDictionaryEntry,switchDictionaryEntryLanguage,dictionarySave,',
  'state(){return {lang:dictLanguage,form:dictionaryFormValue(),',
  'entry:dictEntry,original:dictEntryOriginal,revision:dictData.revision,busy,currentView};}};'
].join("\n");
const app=new Function("$","window","flags","writes","fetches",source)(
  $,window,flags,writes,fetches);
(async()=>{
  const submit={preventDefault(){}};
  app.openDictionaryEntry(null);
  assert.equal(app.state().currentView,"dictionary-entry");
  assert.equal($("dictionary-entry-tabs").hidden,false);
  assert.equal($("dictionary-entry-ja").attrs["aria-pressed"],"true");
  assert.equal($("dictionary-ja-fields").hidden,false);
  assert.equal($("[history]").value,1);
  await app.switchDictionaryEntryLanguage("en");
  assert.equal(prompts.length,0);
  assert.equal(app.state().lang,"en");
  assert.equal(app.state().revision,"rev-en");
  assert.equal($("dictionary-entry-en").attrs["aria-pressed"],"true");
  assert.equal($("dictionary-ja-fields").hidden,true);
  assert.equal($("[history]").value,1);
  assert.equal(app.state().form.surface,"");
  $("dictionary-surface").value="Sweet";
  flags.allowDiscard=false;
  await app.switchDictionaryEntryLanguage("ja");
  assert.equal(app.state().lang,"en");
  assert.equal($("dictionary-surface").value,"Sweet");
  assert.equal(app.state().revision,"rev-en");
  assert.equal(prompts.length,1);
  assert(prompts[0].includes("破棄"));
  flags.allowDiscard=true;
  flags.failFetch=true;
  await app.switchDictionaryEntryLanguage("ja");
  assert.equal(app.state().lang,"en");
  assert.equal($("dictionary-surface").value,"Sweet");
  assert.equal(app.state().busy,false);
  assert.equal($("feedback").textContent,"network failed");
  flags.failFetch=false;
  await app.switchDictionaryEntryLanguage("ja");
  assert.equal(app.state().lang,"ja");
  assert.equal(app.state().revision,"rev-ja");
  assert.equal($("dictionary-surface").value,"");
  assert.equal($("dictionary-ja-fields").hidden,false);
  assert.equal($("dictionary-word-type").value,"PROPER_NOUN");
  assert.equal($("dictionary-priority").value,"5");
  assert.equal($("[history]").value,1);
  $("dictionary-surface").value="雨";
  app.state().entry.notation="ア'メ";
  await app.dictionarySave(submit);
  assert.equal(writes.length,1);
  assert.equal(writes[0].method,"POST");
  assert.equal(writes[0].payload.language,"ja");
  assert.equal(writes[0].payload.expected_revision,"rev-ja");
  assert.equal(writes[0].payload.surface,"雨");
  app.openDictionaryEntry({id:"existing",surface:"既存",notation:"キ'ソン",
    word_type:"COMMON_NOUN",priority:9});
  assert.equal($("dictionary-entry-tabs").hidden,true);
  const reads=fetches.length;
  await app.switchDictionaryEntryLanguage("en");
  assert.equal(fetches.length,reads);
  assert.equal(app.state().lang,"ja");
  assert.equal(app.state().entry.id,"existing");
  assert.equal($("dictionary-priority").value,"9");
  console.log("DICTIONARY_ENTRY_LANGUAGE_PASS");
})().catch(error=>{console.error(error);process.exitCode=1;});