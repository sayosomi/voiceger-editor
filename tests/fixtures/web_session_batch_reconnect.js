"use strict";
const fs=require("fs"),assert=require("node:assert/strict");
const source=fs.readFileSync(process.argv[2],"utf8");
function part(start,end){
  const a=source.indexOf(start),b=source.indexOf(end,a);
  assert(a>=0&&b>a,"Production handler missing: "+start);
  return source.slice(a,b);
}
const busySrc=part("  function setBusy(value) {","  function pronunciationDirty()");
const operationSrc=part("  function renderBatchProgress(","  function closeBatchMenu()");
const startSrc=part("  async function startBatchGeneration() {",
                    "  function rememberPronunciationSelection()");
const handlers=part('  $("cancel-batch").addEventListener',
                    '  $("cancel-audio").addEventListener');
const nodes={
  "batch-progress-panel":{hidden:true},
  "batch-progress-total":{textContent:""},
  "batch-progress-bar":{max:1,value:0},
  "batch-progress-item":{textContent:""},
  "cancel-batch":{disabled:false,dataset:{fixedDisabled:"false"},
    addEventListener(_name,fn){this.callback=fn;}},
  "generate-batch":{disabled:false,dataset:{fixedDisabled:"false"},
    addEventListener(_name,fn){this.callback=fn;}}
};
const $=id=>{assert(nodes[id],"Unknown UI element "+id);return nodes[id];};
const document={querySelectorAll(){return [nodes["cancel-batch"],nodes["generate-batch"]];}};
let posts=0,cancels=0,gets=0,mode="offline",release;
const pending=new Promise(resolve=>{release=resolve;});
const messages=[];
function op(status,completed=0){
  return {id:"op1",kind:"batch-generate",status,completed,total:4,
    cancellable:true,detail:{caption_number:1,caption_total:2,
      take_number:1,take_total:4}};
}
async function request(method,path){
  if(method==="POST"&&path.includes("/generate?")){posts++;return op("running");}
  if(method==="POST"&&path.endsWith("/cancel")){cancels++;return op("cancelling");}
  if(method==="GET"&&path.includes("/operations/")){
    gets++;
    if(mode==="offline")throw Object.assign(new Error("Macに接続できません"),{code:0});
    return pending;
  }
  throw Error("Unexpected request "+method+" "+path);
}
const factory=new Function("$","document","request","feedback","refresh",
  "batchPath","renderList","resetLocal","setTimeout","handleSessionFailure",
  "retryable","renderItem","showView","followAudioOperation",
  "let busy=false,batchPolling=false,audioPolling=false,batchOperation=null,"+
  "connectionEpoch=0,generationUnconfirmed=false,sessionId='sid',token='token',"+
  "reorderMode=false,deleteMode=false,selectedId='';"+
  "let batch={revision:1,items:[{id:'one'}],active_operation:null,latest_operation:null};"+
  busySrc+operationSrc+startSrc+handlers+
  ";return {startBatchGeneration,resumeSessionOperations,"+
  "read:()=>({busy,batchPolling,batchOperation,batch})};");
const ui=factory($,document,request,m=>messages.push(m),
  async()=>{},()=>"/api/web/sessions/sid/batch",()=>{},()=>{},
  fn=>setImmediate(fn),async()=>false,e=>e.code===0,()=>{},()=>{},async()=>{});
async function until(fn){
  for(let i=0;i<60;i++){if(fn())return;await new Promise(setImmediate);}
  throw Error("Timed out");
}
(async()=>{
  await ui.startBatchGeneration();
  assert.equal(posts,1);
  assert.equal(ui.read().batchPolling,false,"Offline poll must release UI");
  assert(messages.some(m=>m.includes("接続できません")));
  await ui.startBatchGeneration();
  assert.equal(posts,1,"Ambiguous worker must not be submitted twice");
  assert(messages.some(m=>m.includes("再取得")));
  mode="online";
  ui.resumeSessionOperations();
  ui.resumeSessionOperations();
  await until(()=>gets===2 && ui.read().batchPolling);
  assert.equal(nodes["batch-progress-panel"].hidden,false);
  await nodes["cancel-batch"].callback();
  assert.equal(cancels,1);
  assert.equal(nodes["cancel-batch"].disabled,true);
  release(op("cancelled",1));
  await until(()=>!ui.read().batchPolling);
  assert.equal(nodes["batch-progress-panel"].hidden,true);
  assert.equal(ui.read().busy,false);
  assert.equal(posts,1);
  assert(messages.some(m=>m.includes("キャンセル")));
  console.log("WEB_BATCH_RECONNECT_CANCEL_PASS");
})().catch(e=>{console.error(e);process.exitCode=1;});
