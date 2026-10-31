"use strict";
const fs=require("node:fs");
const assert=require("node:assert/strict");
const js=fs.readFileSync(process.argv[2],"utf8");
const first=(start,end)=>{
  const a=js.indexOf(start),b=js.indexOf(end,a);
  assert(a>=0&&b>a,"Production function not found: "+start);
  return js.slice(a,b);
};
const els={};
const $=id=>els[id]||={
  value:"",textContent:"",hidden:true,focus(){calls.focus.push(id);},
  scrollIntoView(opts){calls.scroll.push({id,opts});}
};
const flags={permitNavigation:false,postFailure:null};
const calls={reads:[],writes:[],back:0,confirm:0,finished:[],feedback:[],matches:[],
  focus:[],scroll:[]};
const window={history:{back(){calls.back++;}}};
const create=new Function("$","window","flags","calls",
  'let busy=false,dictLanguage="en",dictEntry={id:null,notation:"HH AH0 L OW1"},'+
  'dictData={revision:"rev1"},dictQuery="",dictType="ALL",dictSort="surface_asc",'+
  'dictDuplicate=null,dictionaryHistoryDepth=2,dictionaryHistoryDestination=null;'+
  'function setBusy(value){busy=value;}'+
  'function dictionaryPath(){return "/api/web/sessions/id/dictionary";}'+
  'function feedback(value){calls.feedback.push(value);}'+
  'function dictionaryTypeLabel(value){return value==="PROPER_NOUN"?"固有名詞":"普通名詞";}'+
  'function guardDraft(){calls.confirm++;return flags.permitNavigation;}'+
  'function showView(value){calls.finished.push("view:"+value);}'+
  'function dictionaryFinish(value){calls.finished.push(value);}'+
  'async function dictionaryQuickMatches(language,surface){'+
  ' calls.reads.push({language,surface});return {entries:calls.matches.shift()||[]};}'+
  'async function request(method,url,payload){'+
  ' calls.writes.push({method,url,payload});'+
  ' if(flags.postFailure)throw flags.postFailure;return {changed:true};}'+
  first('  function dictionaryFormValue() {','  function dictionaryTypeLabel(value) {')+
  first('  function requestDictionaryHistoryExit(destination, delta) {',
        '  function revealDictionaryRegistrationError(id) {')+
  first('  function revealDictionaryRegistrationError(id) {','  function renderDictionaryEntryLanguage() {')+
  first('  async function dictionarySave(event) {','  async function dictionaryDelete() {')+
  'return {dictionarySave,dictionaryDuplicateFor,viewDictionaryDuplicate,'+
  'hideDictionaryDuplicate,state(){return {busy,dictQuery,dictLanguage,'+
  'dictionaryHistoryDestination,dictEntry,dictDuplicate}},'+
  'setLanguage(value){dictLanguage=value},setWordType(value){$("dictionary-word-type").value=value},'+
  'setId(value){dictEntry.id=value},completeHistory(){dictionaryHistoryDestination=null;}};'
);
const app=create($,window,flags,calls);
$("dictionary-surface").value="hello";
$("dictionary-word-type").value="PROPER_NOUN";
$("dictionary-priority").value="5";
const submit={preventDefault(){}};
async function run(){
  // Casefold duplicate: never overwrite, identify the saved spelling.
  calls.matches.push([{id:"Hello",surface:"Hello"}]);
  await app.dictionarySave(submit);
  assert.equal(calls.writes.length,0);
  assert.equal(els["dictionary-duplicate"].hidden,false);
  assert.equal(calls.scroll.at(-1).id,"dictionary-duplicate");
  assert.equal(calls.scroll.at(-1).opts.block,"center");
  assert.equal(calls.focus.at(-1),"dictionary-duplicate");
  assert.equal(els["dictionary-duplicate-title"].textContent,"「Hello」は登録済みです");
  assert(els["dictionary-duplicate-description"].textContent.includes("大文字・小文字"));
  assert.equal(app.state().busy,false);
  assert.equal(app.state().dictEntry.notation,"HH AH0 L OW1");
  flags.permitNavigation=false;
  app.viewDictionaryDuplicate();
  assert.equal(calls.back,0);
  assert.equal(app.state().dictQuery,"");
  flags.permitNavigation=true;
  app.viewDictionaryDuplicate();
  assert.equal(calls.back,1);
  assert.equal(app.state().dictQuery,"Hello");
  assert.equal(app.state().dictionaryHistoryDestination,"dictionary");
  assert.equal(els["dictionary-duplicate"].hidden,true);
  // The previous navigation has completed before testing another entry.
  app.completeHistory();
  // Japanese different part of speech is not a duplicate.
  app.setLanguage("ja");app.setWordType("COMMON_NOUN");
  $("dictionary-surface").value="雨";
  calls.matches.push([{id:"same-surface-other-type",surface:"雨",word_type:"PROPER_NOUN"}]);
  await app.dictionarySave(submit);
  assert.equal(calls.writes.length,1);
  assert.equal(calls.writes[0].payload.language,"ja");
  // Same Japanese Surface and word type is a duplicate.
  calls.matches.push([{id:"same-type",surface:"雨",word_type:"COMMON_NOUN"}]);
  await app.dictionarySave(submit);
  assert.equal(calls.writes.length,1);
  assert(els["dictionary-duplicate-description"].textContent.includes("品詞"));
  // A write-side race also resolves to the same explanatory UI.
  app.hideDictionaryDuplicate();
  calls.matches.push([],[{id:"newer",surface:"雨",word_type:"COMMON_NOUN"}]);
  flags.postFailure=Object.assign(new Error("invalid dictionary"),{conflictCode:"invalid_dictionary"});
  await app.dictionarySave(submit);
  assert.equal(calls.writes.length,2);
  assert.equal(els["dictionary-duplicate"].hidden,false);
  flags.postFailure=null;
  app.hideDictionaryDuplicate();
  // The saved-word edit path must still PUT, without duplicate lookup.
  app.setId("word-existing");
  const reads=calls.reads.length;
  await app.dictionarySave(submit);
  assert.equal(calls.reads.length,reads);
  assert.equal(calls.writes[calls.writes.length-1].method,"PUT");
  app.setId(null);
  app.state().dictEntry.notation="";
  await app.dictionarySave(submit);
  assert.equal(els["dictionary-save-error"].hidden,false);
  assert.equal(els["dictionary-save-error"].textContent,"発音を入力してください。");
  assert.equal(calls.scroll.at(-1).id,"dictionary-save-error");
  assert.equal(calls.focus.at(-1),"dictionary-save-error");
  app.state().dictEntry.notation="ア'メ";
  app.setWordType("PROPER_NOUN");
  $("dictionary-priority").value="99";
  await app.dictionarySave(submit);
  assert(els["dictionary-save-error"].textContent.includes("優先度"));
  app.setLanguage("en");
  $("dictionary-priority").value="5";
  flags.postFailure=Object.assign(new Error("通信エラー"),{conflictCode:""});
  calls.matches.push([]);
  await app.dictionarySave(submit);
  assert.equal(els["dictionary-save-error"].textContent,"通信エラー");
  assert.equal(calls.scroll.at(-1).id,"dictionary-save-error");
  assert.equal(calls.focus.at(-1),"dictionary-save-error");
  assert.equal(calls.writes.length,4);
  assert.equal(els["dictionary-duplicate"].hidden,true);
  console.log("DICTIONARY_DUPLICATE_UI_PASS");
}
run().catch(error=>{console.error(error);process.exitCode=1;});