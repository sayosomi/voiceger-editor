"use strict";
// Exercise real settings loader/render code, including DOM field assignments,
// with a rejected sibling GET followed by an authoritative retry.
const fs=require("fs");
const assert=require("node:assert/strict");
const source=fs.readFileSync(process.argv[2],"utf8");
function part(start,end){
  const a=source.indexOf(start),b=source.indexOf(end,a);
  assert(a>=0&&b>a,"Production function not found: "+start);
  return source.slice(a,b);
}
const formCode=part("  function loadSessionForms() {",
                    "  function pronunciationHistoryState() {");
const settingsCode=part("  function setStyleOptions(",
                        "  function validSpeed(raw) {");
function node(){
  return {value:"",textContent:"",hidden:false,disabled:false,
    checked:false,children:[],replaceChildren(){this.children=[];},
    append(el){this.children.push(el);},appendChild(el){this.children.push(el);}};
}
const nodes=new Map();
const $=id=>{
  if(!nodes.has(id))nodes.set(id,node());
  return nodes.get(id);
};
const document={createElement:()=>node(),activeElement:null};
let commonPending=[],outputPending=[],requests=[],messages=[];
let view="session";
function deferred(){
  let resolve,reject;
  const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});
  return {promise,resolve,reject};
}
function common(speed,revision){
  return {styles:[{id:1,name:"Style 1"}],settings_revision:revision,
    values:{style_id:1,speed,top_k:30,top_p:0.8,temperature:0.8}};
}
function output(path,revision){
  return {settings_revision:revision,formats:["wav","flac","mp3"],
    encodings:{wav:["pcm16"],flac:["pcm16"],mp3:["128k"]},
    values:{output_dir:path,filename_template:"{text}",
      output_format:"wav",wav_encoding:"pcm16",flac_encoding:"pcm16",
      mp3_bitrate:"128k",save_text:false,save_lab:false}};
}
const pending={common:[],output:[]};
function request(method,path){
  assert.equal(method,"GET");
  const key=path.endsWith("/output")?"output":"common";
  requests.push({key,path});
  assert(pending[key].length,"Unexpected "+key+" GET");
  return pending[key].shift();
}
function queue(c,o){pending.common.push(c);pending.output.push(o);}
const factory=new Function("$","document","request","feedback","retryable",
  "setTimeout","clearTimeout",
  "var sessionId='sid',connectionEpoch=1,currentView='session'," +
  "selectedId='',batch=null,outputPreviewTimer=null,outputPreviewSequence=0;" +
  "var commonSettingsData=null,outputSettingsData=null;" +
  "var commonSettingsLoadSequence=0,outputSettingsLoadSequence=0," +
  "sessionFormsLoadSequence=0;" +
  "function settingsPath(){return '/api/web/sessions/'+sessionId+'/settings';}" +
  "function renderItemVoice(){}" +
  formCode+settingsCode+
  ";return {loadSessionForms,loadWebSettings,loadWebOutputSettings," +
  "changeSession:()=>{sessionId='new';connectionEpoch++;}," +
  "getData:()=>({common:commonSettingsData,output:outputSettingsData})," +
  "getView:()=>currentView};"
);
const app=factory($,document,request,(message,retry)=>messages.push({message,retry}),
  e=>e.code===0,()=>1,()=>{});
async function settle(){for(let i=0;i<4;i++)await Promise.resolve();}
function failure(){return Object.assign(new Error("Macに接続できません"),{code:0});}
async function run(){
  // First form request: Output errors, old Common remains in flight.
  const oldCommon=deferred();
  queue(oldCommon.promise,Promise.reject(failure()));
  await app.loadSessionForms();
  assert.equal(messages.at(-1).retry,true);
  assert.equal($("common-settings-form").hidden,false); // loader only opens after success
  // Match the app's on-entry state (forms are initially hidden).
  $("common-settings-form").hidden=true;
  $("output-settings-form").hidden=true;
  queue(Promise.resolve(common(1.25,2)),Promise.resolve(output("/new",2)));
  await app.loadSessionForms();
  assert.equal($("common-settings-form").hidden,false);
  assert.equal($("output-settings-form").hidden,false);
  assert.equal($("common-speed").value,"1.25");
  assert.equal($("output-dir").value,"/new");
  $("common-speed").value="1.99";
  $("output-dir").value="/edited";
  oldCommon.resolve(common(0.5,1));
  await settle();
  assert.equal($("common-speed").value,"1.99",
    "Old Common GET overwrote edited Speed after successful retry");
  assert.equal(app.getData().common.settings_revision,2);

  // Mirror the race: old Output arrives after a failed Common and retry.
  const oldOutput=deferred();
  queue(Promise.reject(failure()),oldOutput.promise);
  await app.loadSessionForms();
  assert.equal(messages.at(-1).retry,true);
  queue(Promise.resolve(common(1.75,4)),Promise.resolve(output("/newer",4)));
  await app.loadSessionForms();
  assert.equal($("output-dir").value,"/newer");
  $("output-dir").value="/user-edit";
  $("common-speed").value="1.88";
  oldOutput.resolve(output("/old",3));
  await settle();
  assert.equal($("output-dir").value,"/user-edit",
    "Old Output GET overwrote edited Output folder after retry");
  assert.equal($("common-speed").value,"1.88");
  assert.equal(app.getData().output.settings_revision,4);
  assert.equal(app.getData().common.settings_revision,4);

  // Stale failed form round must not re-enable error feedback after success.
  const delayedFailure=deferred();
  queue(delayedFailure.promise,Promise.resolve(output("/tmp",5)));
  const first=app.loadSessionForms();
  queue(Promise.resolve(common(2,6)),Promise.resolve(output("/stable",6)));
  await app.loadSessionForms();
  const numberOfNotices=messages.length;
  delayedFailure.reject(failure());
  await first;
  assert.equal(messages.length,numberOfNotices,
    "Old failure showed retry after newer successful load");
  assert.equal($("common-speed").value,"2.00");
  assert.equal($("output-dir").value,"/stable");
  console.log("WEB_SETTINGS_RETRY_STALE_RESPONSE_PASS");
}
run().catch(e=>{console.error(e);process.exitCode=1;});
