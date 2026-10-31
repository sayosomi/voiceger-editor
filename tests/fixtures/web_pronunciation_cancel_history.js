"use strict";
const fs=require("node:fs"),assert=require("node:assert/strict");
const source=fs.readFileSync(process.argv[2],"utf8");
function cut(start,end){
  const a=source.indexOf(start),b=source.indexOf(end,a);
  assert(a>=0 && b>a,"missing source: "+start);
  return source.slice(a,b);
}
// Actual showView exit branch, in a test DOM. No asynchronous popstate until
// the test explicitly dispatches it, mirroring two rapid Android taps.
const calls=[];
const window={history:{back(){calls.push("back");}},scrollTo(){}};
const create=new Function("window","calls",
 'let busy=false,currentView="pronunciation",sessionId="s",pronunciationHistoryActive=true,'+
 'pronunciationHistoryExitInFlight=false,pronunciationExitPending=null;'+
 'let viewNames=["pronunciation","item","list"];'+
 'function guardDraft(){return true;}'+
 cut('  function showView(name, bypassDraftGuard) {','  function pronunciationHistoryState() {')+
 'return {showView,state(){return {pronunciationExitPending,pronunciationHistoryExitInFlight}}};'
);
const ui=create(window,calls);
assert.equal(ui.showView("item"),true);
assert.equal(ui.showView("item"),false);
assert.deepEqual(calls,["back"],"Two taps must not go back twice");
assert.equal(ui.state().pronunciationHistoryExitInFlight,true);
// Applying a pronunciation sets a completion message before showView. This
// pending message must still trigger exactly one Back.
const apply=create(window,calls);
const applyStateSource=cut('  function showView(name, bypassDraftGuard) {','  function pronunciationHistoryState() {');
const application=new Function("window","calls",
 'let busy=false,currentView="pronunciation",sessionId="s",pronunciationHistoryActive=true,'+
 'pronunciationHistoryExitInFlight=false,pronunciationExitPending={message:"Applied"};'+
 'let viewNames=["pronunciation","item","list"];'+
 'function guardDraft(){return true;}'+applyStateSource+
 'return {showView,state(){return pronunciationExitPending;}};')(window,calls);
assert.equal(application.showView("item",true),true);
assert.deepEqual(calls,["back","back"]);
assert.equal(application.state().message,"Applied");
// The real popstate exit branch owns completion and clears the in-flight
// sentinel even when the pending message existed prior to exit.
const events={};
const runner=new Function("window","calls",
 'let sessionId="s",currentView="pronunciation",busy=false,'+
 'pronunciationHistoryActive=true,pronunciationHistoryExitInFlight=true,'+
 'pronunciationExitPending={destination:"item",message:"Applied"},pronunciationReturnView="item";'+
 'let settingsHistoryActive=false,dictionaryHistoryDestination=null,'+
 'dictionaryHistoryDepth=0,sectionHistoryActive=false;'+
 'function guardDraft(){return true;}'+
 'function showView(name){currentView=name;calls.push("view:"+name);return true;}'+
 'function feedback(m){calls.push("feedback:"+m);}'+
 cut('  window.addEventListener("popstate",','  window.addEventListener("beforeunload",')+
 'return {state(){return {currentView,pronunciationHistoryActive,pronunciationHistoryExitInFlight,pronunciationExitPending}}};'
);
const navWindow={addEventListener:(event,handler)=>events[event]=handler,history:{back(){calls.push("back");}}};
const nav=runner(navWindow,calls);
events.popstate({state:null});
assert.equal(nav.state().currentView,"item");
assert.equal(nav.state().pronunciationHistoryActive,false);
assert.equal(nav.state().pronunciationHistoryExitInFlight,false);
assert.equal(nav.state().pronunciationExitPending,null);
assert.equal(calls.includes("view:connect"),false);
assert(source.includes("    pronunciationHistoryExitInFlight = false;\n    pronunciationExitPending = null;\n    dictionaryHistoryDepth = 0;"),"Reset must clear stale history state");
console.log("PRON_CANCEL_DOUBLE_BACK_PASS");