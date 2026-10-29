"""Media liveness and source-isolation behavior tests for the Web editor."""

from pathlib import Path
import shutil
import subprocess
import unittest


class MediaOwnershipTests(unittest.TestCase):
    def test_pending_initial_play_does_not_lock_ui_or_accept_stale_media_events(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node required for DOM media state execution")
        path = Path(__file__).resolve().parents[1] / "voiceger_editor" / "web_assets" / "app.js"
        script = r"""const fs=require("fs");
const source=fs.readFileSync(process.argv[1],"utf8");
function slice(start,end){
 const a=source.indexOf(start),b=source.indexOf(end,a+start.length);
 if(a<0||b<a)throw new Error("Missing source "+start);
 return source.slice(a,b);
}
const lockSource=slice("  function setBusy(value) {","  function guardDraft()");
const viewSource=slice("  function guardDraft()","  async function request(");
const stateSource=slice("  function clearPlayer() {","  function makeRefreshIcon()");
const audioSource=slice("  async function playAudio(","  function displayAudioProgress(");
function assert(ok,message){if(!ok)throw new Error(message);}
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
function environment(){
 const nodes={};const feedbacks=[], revoked=[],controls=[];
 let serial=0;
 const get=id=>nodes[id]||=makeNode();
 function makeNode(){
   return {
     disabled:false,hidden:false,dataset:{fixedDisabled:"false"},
     children:[],textContent:"",attrs:{},
     setAttribute(k,v){this.attrs[k]=v;},
     querySelector(){return null;},
     querySelectorAll(){return [];},
     classList:{toggle(){}}
   };
 }
 const nav=get("nav"),preview=get("preview-audio");
 controls.push(nav,preview);
 const gates=[];
 function makeMedia(){
   const node=makeNode();
   Object.assign(node,{
     src:"",paused:true,ended:false,currentTime:0,duration:10,events:{},
     addEventListener(kind,listener){(this.events[kind]||=[]).push(listener);},
     emit(kind){for(const cb of(this.events[kind]||[]))cb();},
     pause(){this.paused=true;this.emit("pause");},
     removeAttribute(k){if(k==="src")this.src="";},
     load(){this.ended=false;this.currentTime=0;},
     cloneNode(){return makeMedia();},
     replaceWith(fresh){nodes["phone-player"]=fresh;},
     play(){const gate=gates.shift();return gate?gate.promise:Promise.resolve();}
   });
   return node;
 }
 nodes["phone-player"]=makeMedia();
 const document={querySelectorAll(){return controls;}};
 const window={scrollTo(){},confirm(){return true;},addEventListener(){}};
 const URL={createObjectURL(){return "blob:take-"+(++serial);},revokeObjectURL(u){revoked.push(u);}};
 const fetch=async()=>({ok:true,blob:async()=>({size:16,type:"audio/wav"})});
 const factory=new Function("$","document","window","URL","fetch","feedback",
   "let busy=false;let token='token';let selectedId='item';let currentView='item';"+
   "let playingUrl='';let playbackRequestId=0;let playback=null;"+
   "let reorderMode=false;let deleteMode=false;let sessionId='sid';let batch=null;"+
   "let autoPrepareFailures=new Set();"+
   "const viewNames=['connect','list','add','item','session'];"+
   "function renderItem(){} function endReorderMode(){} function endDeleteMode(){}"+
   lockSource+viewSource+stateSource+audioSource+
   ";return {showView,playAudio,clearPlayer,read:()=>({busy,playback,playingUrl}),"+
   "setView(v){currentView=v;}};");
 const app=factory(get,document,window,URL,fetch,m=>feedbacks.push(m));
 return {app,nav,preview,getPlayer:()=>get("phone-player"),gates,feedbacks,revoked};
}
(async()=>{
 const env=environment(),{app,nav,gates}=env;
 // F-09: initial play() Promise can remain unresolved, but the view must work.
 const first=deferred();gates.push(first);
 await app.playAudio("/a","item","take",1);
 assert(app.read().playback?.phase==="starting","Initial play() did not enter starting");
 assert(app.read().busy===false,"Global busy lock is stuck on play()");
 assert(nav.disabled===false,"Navigation control disabled while play pending");
 const old=env.getPlayer();
 assert(app.showView("list")===true,"Navigation blocked by pending play()");
 assert(app.read().playback===null,"Navigation left stale playback");
 assert(old!==env.getPlayer(),"Navigation reused old media element");
 first.resolve();await Promise.resolve();await Promise.resolve();
 assert(app.read().playback===null,"Obsolete play() settled into newer state");

 // F-10: old element's error and playing events cannot mutate next source.
 app.setView("item");
 const sourceA=deferred();gates.push(sourceA);
 await app.playAudio("/a","item","take",1);
 const elementA=env.getPlayer();
 const sourceB=deferred();gates.push(sourceB);
 await app.playAudio("/b","item","take",2);
 const elementB=env.getPlayer();
 assert(elementA!==elementB,"Two audio requests share one HTMLMediaElement");
 assert(app.read().playback.phase==="starting","New source not starting");
 const count=env.feedbacks.length;
 elementA.emit("error");elementA.paused=false;elementA.emit("playing");
 elementA.ended=true;elementA.emit("ended");elementA.emit("pause");
 assert(app.read().playback.phase==="starting","Stale old events corrupted new source");
 assert(env.feedbacks.length===count,"Stale error surfaced as current failure");
 elementB.emit("error");
 assert(app.read().playback.phase==="failed","Current source error ignored");
 sourceB.resolve();await Promise.resolve();await Promise.resolve();
 assert(app.read().playback.phase==="failed","Current failure incorrectly cleared");
 sourceA.reject(new Error("stale"));await Promise.resolve();await Promise.resolve();
 assert(app.read().playback.phase==="failed","Old play rejection modified current source");
 console.log("F09_F10_MEDIA_LIVENESS_AND_ISOLATION_PASS");
})().catch(e=>{console.error(e);process.exitCode=1;});"""
        result = subprocess.run(
            [node, "-e", script, str(path)], capture_output=True,
            text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("F09_F10_MEDIA_LIVENESS_AND_ISOLATION_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
