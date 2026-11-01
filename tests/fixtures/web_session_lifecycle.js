"use strict";
const fs=require("fs"),assert=require("node:assert/strict");
const js=fs.readFileSync(process.argv[2],"utf8");
const html=fs.readFileSync(process.argv[3],"utf8");
function part(a,b){const i=js.indexOf(a),j=js.indexOf(b,i);
  assert(i>=0&&j>i,"Production code missing: "+a);return js.slice(i,j);}
const core=part("  function savedSession() {","  function setBusy(value) {");
const requestCode=part("  async function request(method, path, payload) {","  function batchPath() {");
const lifecycle=part("  function resetLocal(clearSessionId) {","  async function mutate(");
const settingsLoader=part("  function loadSessionForms() {","  function pronunciationHistoryState() {");
const auth=part('  $("auth-form").addEventListener("submit"',
                '  $("open-batch-menu").addEventListener');
const retry=part('  $("retry-connection").addEventListener("click"',
                 '  $("close-session").addEventListener("click"');
const actions=part('  $("close-session").addEventListener("click"',
                   '  var dictionarySortModes');
assert(html.includes('id="retry-connection"'));
assert(html.includes('id="close-session"'));
assert(html.includes('>作業を終了</button>'));
assert(!html.includes('id="refresh-batch"'));
assert(!html.includes('id="disconnect-session"'));
assert(!html.includes('id="connection-status"'));
const storage={data:new Map(),getItem(k){return this.data.get(k)||null;},
  setItem(k,v){this.data.set(k,v);},removeItem(k){this.data.delete(k);}};
const TOKEN="test-token-at-least-thirty-two-characters";
const sessions=new Map(),creationKeys=new Map(),calls=[];
let counter=0,nonceCounter=0,mode="normal",delayed=null;
function success(data,status=200){return {ok:true,status,json:async()=>data};}
function failure(status){return {ok:false,status,json:async()=>({detail:"private"})};}
async function server(path,options){
  const method=options.method;
  calls.push({path,method,authorization:options.headers.Authorization});
  if(mode==="offline")throw TypeError("network disconnected");
  if(mode==="unavailable")return failure(503);
  if(mode==="unauthorized")return failure(401);
  if(mode==="forbidden")return failure(403);
  if(path==="/api/web/sessions"&&method==="POST"){
    const key=JSON.parse(options.body).idempotency_key;
    assert.match(key,/^[0-9a-f]{48}$/);
    let id=creationKeys.get(key);
    if(!id || !sessions.has(id)){
      id="sid-"+(++counter);
      creationKeys.set(key,id);
      sessions.set(id,{revision:1,items:[{id:"caption-1"}],
        active_operation:null,latest_operation:null});
    }
    if(mode==="lost-create-response"){
      mode="normal";
      throw TypeError("response lost after Mac committed creation");
    }
    return success({id},201);
  }
  const parts=path.match(/^\/api\/web\/sessions\/([^/]+)(\/batch)?$/);
  if(!parts)return failure(404);
  const sid=decodeURIComponent(parts[1]);
  if(!sessions.has(sid))return failure(404);
  if(method==="DELETE"&&!parts[2]){sessions.delete(sid);return {ok:true,status:204};}
  if(method!=="GET")return failure(405);
  if(!parts[2])return success({id:sid,ephemeral:true,restart_recovery:false,
    latest_operation:sessions.get(sid).latest_operation});
  if(mode==="defer-batch"){
    return await new Promise(resolve=>{delayed=()=>resolve(success(sessions.get(sid)));});
  }
  return success(sessions.get(sid));
}
function boot(){
  const nodes={};
  function $(id){
    return nodes[id] ||= {
      value:"",textContent:"",hidden:false,disabled:false,listeners:{},
      addEventListener(event,fn){this.listeners[event]=fn;}
    };
  }
  const confirmations=[];
  let confirmAllowed=true;
  const win={sessionStorage:storage,confirmations:confirmations,
    confirm(message){confirmations.push(message);return confirmAllowed;},
    setConfirmAllowed(value){confirmAllowed=value;},
    crypto:{getRandomValues(bytes){const seed=++nonceCounter;
      bytes.forEach((_,i)=>{bytes[i]=(seed+i)%256;});return bytes;}}
  };
  const body=[
    'var token="",sessionId="",batch=null,selectedId="",currentView="connect",busy=false;',
    'var connectionEpoch=0,refreshSequence=0,expiredSession=false,generationUnconfirmed=false;',
    'var audioUnconfirmed=null,creationRequestId="",latestSessionOperation=null;',
    'var audioOperation=null,batchOperation=null,batchPolling=false,audioPolling=false;',
    'var outputPreviewSequence=0,outputPreviewTimer=null;',
    'var autoPrepareFailures=new Set(),SESSION_KEY="voiceger-web-session-id";',
    'var settingsLoads=0,sessionFormsLoadSequence=0;',
    'function commonDirty(){return false;} function defaultTakesDirty(){return false;}',
    'function outputDirty(){return false;}',
    'async function loadWebSettings(){settingsLoads++;',
    '  if(getMode()==="offline")throw Object.assign(new Error("Macに接続できません。再試行してください。"),{code:0});}',
    'async function loadWebOutputSettings(){}',
    'function setBusy(v){busy=v;}',
    'function clearPlayer(){} function closeBatchMenu(){} function endDeleteMode(){}',
    'function renderList(){} function renderItem(){}',
    'function showView(v){currentView=v;return true;}',
    'function guardDraft(){return true;}',
    'function batchPath(){return "/api/web/sessions/"+encodeURIComponent(sessionId)+"/batch";}',
    'var resumed=0;function resumeSessionOperations(){resumed++;}',
    'function reconcileAudioStart(s){latestSessionOperation=s.latest_operation||null;audioUnconfirmed=null;}',
    core,requestCode,lifecycle,settingsLoader,auth,retry,actions,
    'return {state:()=>({token,sessionId,batch,currentView,busy,expiredSession,resumed,settingsLoads}),',
    'submit:()=> $("auth-form").listeners.submit({preventDefault(){}}),',
    'openSettings:()=>{currentView="session"; $("common-settings-form").hidden=true;',
    '  $("output-settings-form").hidden=true;return loadSessionForms();},',
    'setConfirmAllowed:value=>window.setConfirmAllowed(value),',
    'confirmations:window.confirmations,',
    'close:()=> $("close-session").listeners.click(),',
    'retry:()=> $("retry-connection").listeners.click(),',
    'refresh,reset:()=>resetLocal(true),check:handleSessionFailure};'
  ].join("\n");
  const app=new Function("$","window","fetch","getMode",body)($,win,server,()=>mode);
  return {app,$};
}
async function run(){
  const one=boot();one.$("web-token").value=TOKEN;
  await one.app.submit();
  const sid=one.app.state().sessionId;
  assert.equal(one.app.state().currentView,"list");
  assert.equal(storage.getItem("voiceger-web-session-id"),sid);
  assert.equal(storage.data.size,1,"Only tab-scoped session id may persist");
  assert(![...storage.data.values()].includes(TOKEN));
  const created=counter;
  // Reload loses the credential but retains only the session id.
  const two=boot();assert.equal(two.app.state().token,"");
  mode="offline";two.$("web-token").value=TOKEN;
  await two.app.submit();
  assert.equal(two.app.state().token,TOKEN);
  assert.equal(storage.getItem("voiceger-web-session-id"),sid);
  assert.equal(two.app.state().currentView,"connect");
  assert.equal(two.$("connect-button").textContent,"再試行");
  mode="normal";await two.app.submit();
  assert.equal(two.app.state().currentView,"list");
  assert.equal(two.app.state().resumed,1);
  assert.equal(counter,created,"Offline reload must not create an empty Batch");
  // An expired operation (404) must not be mistaken for session deletion.
  assert.equal(await two.app.check(Object.assign(Error("missing op"),{code:404})),false);
  assert.equal(two.app.state().sessionId,sid);
  assert(sessions.has(sid));
  // Reuse the old id for a separate reload after a genuine Mac restart.
  sessions.delete(sid);
  const three=boot();three.$("web-token").value=TOKEN;
  await three.app.submit();
  assert.equal(three.app.state().expiredSession,true);
  assert.equal(three.app.state().currentView,"connect");
  assert.equal(three.$("connect-button").textContent,"新しいセッションを開始");
  assert.equal(counter,created,"Expired session must require explicit new start");
  assert.equal(storage.getItem("voiceger-web-session-id"),null);
  await three.app.submit();
  assert.equal(counter,created+1);
  assert.equal(three.app.state().currentView,"list");
  // 503 is a temporary failure, not session expiry.
  const four=boot();mode="unavailable";four.$("web-token").value=TOKEN;
  await four.app.submit();
  assert.equal(four.app.state().token,TOKEN);
  assert.equal(four.app.state().expiredSession,false);
  mode="normal";await four.app.submit();
  assert.equal(counter,created+1);
  assert.equal(four.app.state().currentView,"list");
  // A settings-load outage offers retry; retry restores the settings forms.
  mode="offline";await four.app.openSettings();
  assert.equal(four.$("retry-connection").hidden,false);
  assert.equal(four.$("common-settings-form").hidden,true);
  mode="normal";await four.app.retry();
  await new Promise(setImmediate);
  assert.equal(four.$("retry-connection").hidden,true);
  assert.equal(four.$("common-settings-form").hidden,false);
  assert.equal(four.$("output-settings-form").hidden,false);
  assert(four.app.state().settingsLoads>=2);
  // 401 and 403 fail closed but retain the session identifier for re-auth.
  for(const rejected of ["unauthorized","forbidden"]){
    const page=boot();mode=rejected;page.$("web-token").value=TOKEN;
    await page.app.submit();assert.equal(page.app.state().token,"");
    assert(storage.getItem("voiceger-web-session-id"));
    mode="normal";page.$("web-token").value=TOKEN;
    await page.app.submit();assert.equal(page.app.state().currentView,"list");
  }
  // Delayed GET issued before disconnect must never restore an old Batch.
  const five=boot();five.$("web-token").value=TOKEN;await five.app.submit();
  mode="defer-batch";const pending=five.app.refresh();
  assert(delayed,"Missing delayed GET");
  five.app.reset();mode="normal";delayed();
  await pending;
  assert.equal(five.app.state().batch,null);
  assert.equal(five.app.state().sessionId,"");
  // The sole end-work button has one destructive confirmation.
  const six=boot();six.$("web-token").value=TOKEN;await six.app.submit();
  await six.app.openSettings();
  const closing=six.app.state().sessionId;
  six.app.setConfirmAllowed(false);
  await six.app.close();
  assert(sessions.has(closing),"Cancelling the end-work prompt must keep the session");
  six.app.setConfirmAllowed(true);
  await six.app.close();
  assert(!sessions.has(closing));
  assert.equal(storage.getItem("voiceger-web-session-id"),null);
  assert.equal(six.app.confirmations.length,2);
  assert(six.app.confirmations[1].includes("保存済み音声は残ります"));
  // A server-committed creation with lost response is replayed with the
  // original one-time key and never consumes a second bounded slot.
  const beforeLoss=counter;
  storage.removeItem("voiceger-web-session-id");
  const seven=boot();seven.$("web-token").value=TOKEN;
  mode="lost-create-response";
  await seven.app.submit();
  assert.equal(counter,beforeLoss+1);
  assert.equal(seven.app.state().sessionId,"");
  assert.equal(storage.getItem("voiceger-web-session-id"),null);
  assert.equal(seven.$("connect-button").textContent,"再試行");
  await seven.app.submit();
  assert.equal(counter,beforeLoss+1,"Ambiguous creation POST must use same key");
  assert.equal(seven.app.state().currentView,"list");
  assert.equal(storage.data.size,1,"Only the session id is stored");
  console.log("WEB_SESSION_LIFECYCLE_BROWSER_PASS");
}
run().catch(e=>{console.error(e);process.exitCode=1;});
