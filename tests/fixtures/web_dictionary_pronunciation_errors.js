"use strict";
const fs = require("node:fs");
const assert = require("node:assert/strict");
const src = fs.readFileSync(process.argv[2], "utf8");
function cut(a,b) {
  const start=src.indexOf(a), stop=src.indexOf(b,start);
  assert(start>=0 && stop>start, "Missing production source: "+a);
  return src.slice(start,stop);
}
const trace=[], nodes={};
const $ = key => nodes[key] ||= {
  value:"",hidden:true,textContent:"",attributes:{},
  setAttribute(k,v){this.attributes[k]=v;},
  removeAttribute(k){delete this.attributes[k];},
  scrollIntoView(o){trace.push("scroll:"+o.block);},
  focus(){trace.push("focus:"+key);}
};
const state={reject:true,error:Object.assign(
  new Error("辞書の入力内容を確認してください。"),{conflictCode:"invalid_dictionary"})};
const factory=new Function("$","trace","state",
  'let dictLanguage="ja",dictEntry={notation:"saved"},dictPronOpening="saved",busy=false,dictionaryHistoryDepth=0,dictionaryHistoryDestination=null;' +
  'function feedback(m){trace.push("global:"+m);}' +
  'function setBusy(v){busy=v;}' +
  'function dictionaryPath(){return "/dictionary";}' +
  'function showView(v){trace.push("view:"+v);}' +
  'function clearPlayer(){}' +
  'async function request(method,path,payload){trace.push(path); if(state.reject)throw state.error; return {valid:true};}' +
  cut('  function clearDictionaryPronunciationError() {','  function rememberDictionarySelection() {') +
  cut('  async function dictionaryPreview() {','  function dictionaryFinish(message) {') +
  'return {applyDictionaryPronunciation,dictionaryPreview,clearDictionaryPronunciationError,' +
  'setLanguage(v){dictLanguage=v},getBusy(){return busy},save(){return dictEntry.notation}};');
const app=factory($,trace,state);
$("dictionary-surface").value="雨";
$("dictionary-pron-text").value="ア メ";
(async()=>{
  await app.applyDictionaryPronunciation({preventDefault(){}});
  assert.equal(app.save(),"saved");
  assert.equal(app.getBusy(),false);
  assert.equal($("dictionary-pron-error").hidden,false);
  assert($("dictionary-pron-error").textContent.includes("空白を削除"));
  assert($("dictionary-pron-error").textContent.includes("1つのアクセント句"));
  assert.equal($("dictionary-pron-text").attributes["aria-invalid"],"true");
  assert(trace.includes("scroll:center"));
  assert(trace.includes("focus:dictionary-pron-error"));
  app.clearDictionaryPronunciationError();
  assert.equal($("dictionary-pron-error").hidden,true);
  assert.equal($("dictionary-pron-text").attributes["aria-invalid"],undefined);
  $("dictionary-pron-text").value="アメ";
  await app.applyDictionaryPronunciation({preventDefault(){}});
  assert($("dictionary-pron-error").textContent.includes("アクセント"));
  app.setLanguage("en");
  $("dictionary-pron-text").value="HH UNVALID1";
  await app.applyDictionaryPronunciation({preventDefault(){}});
  assert($("dictionary-pron-error").textContent.includes("ARPAbet"));
  assert($("dictionary-pron-error").textContent.includes("0/1/2"));
  app.setLanguage("ja");
  $("dictionary-pron-text").value="ア メ";
  await app.dictionaryPreview();
  assert($("dictionary-pron-error").textContent.startsWith("Previewできません。"));
  assert($("dictionary-pron-error").textContent.includes("空白を削除"));
  state.error=Object.assign(new Error("通信できません。"),{conflictCode:""});
  await app.applyDictionaryPronunciation({preventDefault(){}});
  assert($("dictionary-pron-error").textContent.includes("通信できません。"));
  state.reject=false;
  $("dictionary-pron-text").value="ア'メ";
  await app.applyDictionaryPronunciation({preventDefault(){}});
  assert.equal($("dictionary-pron-error").hidden,true);
  assert.equal(app.save(),"ア'メ");
  assert.equal($("dictionary-pron-text").attributes["aria-invalid"],undefined);
  console.log("DICTIONARY_PRON_ERROR_PASS");
})().catch(e=>{console.error(e);process.exitCode=1;});