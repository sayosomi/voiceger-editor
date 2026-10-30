"use strict";
const fs=require("node:fs"),assert=require("node:assert/strict");
const js=fs.readFileSync(process.argv[2],"utf8");
function cut(start,end){
  let a=js.indexOf(start),b=js.indexOf(end,a);
  assert(a>=0&&b>a,"real source missing: "+start);
  return js.slice(a,b);
}
const calls=[],listeners={},nodes={};
const $=id=>nodes[id] ||= {
 value:"",textContent:"",hidden:false,dataset:{},attributes:{},disabled:false,
 setAttribute(k,v){this.attributes[k]=v;},removeAttribute(k){delete this.attributes[k];},
 scrollIntoView(o){calls.push(["scroll",o.block]);},
 focus(){calls.push(["focus",id]);},
 play:async()=>{calls.push(["play"]);}
};
const state={revision:"r".repeat(64),failGenerate:false,failPreview:false,failSave:false};
let saved=null;
const request=async(method,url,data)=>{
 calls.push(["request",method,url,data]);
 if(method==="GET"&&url.includes("/matches?surface="))
   return {entries:[],revision:state.revision};
 if(url.endsWith("/pronunciation/generate")){
   if(state.failGenerate)throw Error("generate failed");
   return {status:"succeeded",result:{notation:"ア'メ"}};
 }
 if(url.endsWith("/pronunciation/preview")){
   if(state.failPreview)throw Error("preview failed");
   return {status:"succeeded",result:{preview_id:"preview-id"}};
 }
 if(method==="POST"&&url.endsWith("/words")){
   if(state.failSave)throw Error("save failed");
   saved=data;return {changed:true};
 }
 throw Error("unexpected request "+method+" "+url);
};
const fetch=async url=>({ok:true,blob:async()=>({size:12,type:"audio/wav"})});
const URL={createObjectURL:blob=>"blob:preview"};
const document={querySelectorAll:()=>[{},{}]};
const window={confirm:()=>true};
const run=new Function("$","request","fetch","URL","document","window","calls",
'let currentView="pronunciation", busy=false,dictQuickPriorityEdited=false,dictQuickMatches=[],'+
'dictQuickPronSurface=null,pronunciationTarget={language:"ja"},playingUrl="",token="valid-token";'+
'function setBusy(v){busy=v;}' +
'function dictionaryPath(){return "/dictionary";}' +
'function feedback(s){calls.push(["feedback",s]);}' +
'function clearPlayer(){calls.push(["clearPlayer"]);}' +
'async function waitDictionaryOperation(op){if(op.status!=="succeeded")throw Error("operation failed");return op.result;}' +
cut('  function dictionaryQuickMatches(language, surface) {','  $("dictionary-back").addEventListener("click", dictionaryBack);') +
'return {openDictionaryQuick,dictionaryQuickSurfaceChanged,dictionaryQuickNotationChanged,'+
'generateDictionaryQuick,previewDictionaryQuick,saveDictionaryQuick,dictionaryQuickDraft,'+
'getAssociation:()=>dictQuickPronSurface};');
const app=run($,request,fetch,URL,document,window,calls);
$("dictionary-quick-form").hidden=true;
$("pronunciation-caption").textContent="雨が降っているのだ";
$("pronunciation-text").value="ア'メ ガ フ'ッテイルノダ";
$("dictionary-quick-type").value="PROPER_NOUN";
(async()=>{
 await app.openDictionaryQuick();
 assert.equal($("dictionary-quick-surface").value,"雨が降っているのだ");
 assert.equal($("dictionary-quick-notation").value,"ア'メ ガ フ'ッテイルノダ");
 assert.equal(app.getAssociation(),"雨が降っているのだ");
 $("dictionary-quick-surface").value="雨";
 app.dictionaryQuickSurfaceChanged();
 assert.equal($("dictionary-quick-notation").value,"","source pronunciation must be discarded");
 assert.equal(app.getAssociation(),null);
 await app.saveDictionaryQuick({preventDefault(){}});
 assert.equal(saved,null,"cannot save whole-sentence reading as a different word");
 assert.equal($("dictionary-quick-error").hidden,false);
 assert(calls.some(x=>x[0]==="scroll"&&x[1]==="center"));
 await app.generateDictionaryQuick();
 assert.equal($("dictionary-quick-notation").value,"ア'メ");
 assert.equal(app.getAssociation(),"雨");
 await app.previewDictionaryQuick();
 assert(calls.some(x=>x[0]==="play"));
 assert(calls.some(x=>x[0]==="request"&&x[2].endsWith("/pronunciation/preview")&&x[3].surface==="雨"&&x[3].notation==="ア'メ"));
 await app.saveDictionaryQuick({preventDefault(){}});
 assert.equal(saved.surface,"雨");
 assert.equal(saved.notation,"ア'メ");
 assert.equal($("dictionary-quick-form").hidden,true);
 assert.equal($("pronunciation-text").value,"ア'メ ガ フ'ッテイルノダ","source edit unchanged");
 assert(!calls.some(x=>/\/batch\/items/.test(x[2]||"")),"no Batch mutations");
 // Full-source entry keeps current draft until Surface is changed.
 await app.openDictionaryQuick();
 assert.equal($("dictionary-quick-notation").value,$("pronunciation-text").value);
 // A stale generated reading must not survive editing Surface twice.
 $("dictionary-quick-surface").value="雪";
 app.dictionaryQuickSurfaceChanged();
 $("dictionary-quick-notation").value="ユ'キ";
 app.dictionaryQuickNotationChanged();
 assert.equal(app.getAssociation(),"雪");
 $("dictionary-quick-surface").value="雨";
 app.dictionaryQuickSurfaceChanged();
 assert.equal($("dictionary-quick-notation").value,"");
 assert.equal(app.getAssociation(),null);
 // Manual word pronunciation is allowed after changing Surface.
 $("dictionary-quick-notation").value="アメ'";
 app.dictionaryQuickNotationChanged();
 assert.equal(app.getAssociation(),"雨");
 await app.saveDictionaryQuick({preventDefault(){}});
 assert.equal(saved.notation,"アメ'");
 await app.openDictionaryQuick();
 $("dictionary-quick-surface").value="雨";
 app.dictionaryQuickSurfaceChanged();
 state.failGenerate=true;
 await app.generateDictionaryQuick();
 assert.equal($("dictionary-quick-error").hidden,false);
 assert.equal($("dictionary-quick-notation").value,"");
 state.failGenerate=false;
 await app.generateDictionaryQuick();
 state.failPreview=true;
 await app.previewDictionaryQuick();
 assert.equal($("dictionary-quick-error").hidden,false);
 state.failPreview=false;
 state.failSave=true;
 await app.saveDictionaryQuick({preventDefault(){}});
 assert.equal($("dictionary-quick-error").hidden,false);
 assert.equal($("dictionary-quick-notation").value,"ア'メ","failed persistence retains draft");
 state.failSave=false;
 console.log("DICTIONARY_QUICK_PARTIAL_PASS");
})().catch(e=>{console.error(e);process.exitCode=1;});