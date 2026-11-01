"use strict";
const fs=require("fs"),assert=require("node:assert/strict");
const js=fs.readFileSync(process.argv[2],"utf8");
function part(a,b){const i=js.indexOf(a),j=js.indexOf(b,i);
  assert(i>=0&&j>i,"Missing production function "+a);
  return js.slice(i,j);}
const settings=part("  async function loadWebSettings() {","  function validSpeed(");
const audio=part("  async function followAudioOperation(","  function renderBatchProgress(");
const recovery=part("  function reconcileAudioStart(","  function closeBatchMenu()");
const retry=part('  $("retry-connection").addEventListener("click"',
                 '  $("close-session").addEventListener("click"');
const $nodes={};function $(id){
  return $nodes[id] ||= {value:"",textContent:"",hidden:false,disabled:false,
    dataset:{fixedDisabled:"false"},listeners:{},
    addEventListener(ev,fn){this.listeners[ev]=fn;}};
}
$("edit-caption").value="hello";
let postCount=0,opGets=0,settingsLoads=0,voiceRenders=0,progress=0;
let finalOp,lateSettings=null,delayedSettings=false;
const notices=[];
const item={id:"row1",caption:"hello"};
const snapshot={revision:3,items:[item],active_operation:null};
function operation(state){
  return {id:"op-1",kind:"preview",detail:{item_id:"row1"},
    status:state,cancellable:true,completed:state==="running"?0:1,total:1,
    result:state==="running"?null:{preview_id:"handle"}};
}
finalOp=operation("running");
async function request(method,path){
  if(method==="POST"&&path.includes("/audio/preview")){
    postCount++;
    finalOp=operation("running");
    throw Object.assign(new Error("Macに接続できません"),{code:0});
  }
  if(method==="GET"&&path==="/api/web/sessions/sid")
    return {id:"sid",latest_operation:finalOp};
  if(method==="GET"&&path.endsWith("/batch"))return snapshot;
  if(method==="GET"&&path==="/settings"){
    settingsLoads++;
    if(delayedSettings)
      return new Promise(resolve=>{lateSettings=resolve;});
    return {settings_revision:1,style:"test",speed:1.25};
  }
  if(method==="GET"&&path.includes("/operations/")){
    opGets++;
    return operation("succeeded");
  }
  throw Error("Unexpected request "+method+" "+path);
}
const harness=new Function("$","request","setTimeout","feedback",
  "renderList","renderItem","showView","clearPlayer","renderTakes",
  "displayAudioProgress","playAudio","updatePlaybackUI",
  "renderCommonSettings","renderItemVoice","setFixed",
  "handleSessionFailure","retryable",
  "let busy=false,sessionId='sid',token='valid-token'," +
  "connectionEpoch=0,refreshSequence=0,selectedId='row1',currentView='item'," +
  "batchPolling=false,audioPolling=false,detachedPolling=false," +
  "audioOperation=null,latestSessionOperation=null,audioUnconfirmed=null," +
  "commonSettingsData=null,pronunciationStale=false,sectionStale=false," +
  "takeMenuOpen=false,generationUnconfirmed=false;" +
  "const autoPrepareFailures=new Set();" +
  "let batch={revision:3,items:[{id:'row1',caption:'hello'}],active_operation:null};" +
  "function setBusy(v){busy=v;}" +
  "function itemAudioPath(id){return '/items/'+id;}" +
  "function batchPath(){return '/api/web/sessions/'+sessionId+'/batch';}" +
  "function settingsPath(){return '/settings';}" +
  "async function refresh(){batch=await request('GET',batchPath());return true;}" +
  settings+audio+recovery+retry+
  ";return {startAudio, resumeSessionOperations, reloadRecoveredItemSettings," +
  "retry:()=> $('retry-connection').listeners.click()," +
  "get:()=>({busy,batch,selectedId,audioUnconfirmed,audioPolling," +
  "commonSettingsData,connectionEpoch,sessionId})," +
  "changeEpoch:()=>{connectionEpoch++;sessionId='different';commonSettingsData=null;}};");
const ui=harness($,request,fn=>Promise.resolve().then(fn),
  message=>notices.push(message),
  ()=>{},()=>{},()=>{},()=>{},
  ()=>{},()=>{progress++;},async()=>{},()=>{},
  data=>{ui.get().commonSettingsData;commonSettingsDataRef=data;},
  ()=>{voiceRenders++;},()=>{},async()=>false,e=>e.code===0);
let commonSettingsDataRef=null;
async function until(predicate){
  for(let n=0;n<80;n++){if(predicate())return;await new Promise(setImmediate);}
  throw Error("Timed out");
}
(async()=>{
  await ui.startAudio("row1","/audio/preview",undefined,false);
  assert.equal(postCount,1);
  assert.equal(ui.get().busy,false);
  assert(ui.get().audioUnconfirmed,"Lost POST result must be remembered");
  await ui.startAudio("row1","/audio/preview",undefined,false);
  assert.equal(postCount,1,"Second tap must not duplicate accepted Preview");
  assert(notices.some(s=>s.includes("再取得")));
  await ui.retry();
  await until(()=>opGets===1&&!ui.get().audioPolling);
  assert.equal(postCount,1);
  assert.equal(ui.get().audioUnconfirmed,null);
  assert.equal(settingsLoads,1,"Restored item must fetch common settings");
  assert.equal(commonSettingsDataRef.speed,1.25);
  assert(voiceRenders>=1,"Restored item voice must render");
  assert.equal(ui.get().selectedId,"row1");
  assert.equal(ui.get().busy,false);
  // A previous asynchronous settings response must not cross a session epoch.
  delayedSettings=true;commonSettingsDataRef=null;
  ui.reloadRecoveredItemSettings("row1");
  await until(()=>lateSettings!==null);
  ui.changeEpoch();
  lateSettings({settings_revision:7,style:"stale",speed:5});
  await new Promise(setImmediate);
  assert.equal(commonSettingsDataRef,null,"Stale settings must not render");
  console.log("WEB_AUDIO_RECONNECT_GUARDS_PASS");
})().catch(e=>{console.error(e);process.exitCode=1;});
