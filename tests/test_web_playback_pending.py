"""Execute the actual Preview/Take resume handlers with pending media Promises."""

from pathlib import Path
import shutil
import subprocess
import unittest


class PendingPlaybackInteractionTests(unittest.TestCase):
    def test_resume_blocks_duplicate_preview_generation_and_take_fetch(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is required for browser media interaction tests")
        path = Path(__file__).resolve().parents[1] / "voiceger_editor" / "web_assets" / "app.js"
        script = r"""const fs = require("fs");
const source = fs.readFileSync(process.argv[1],"utf8");
function extract(startMark,endMark) {
  const a=source.indexOf(startMark);
  const b=source.indexOf(endMark,a+startMark.length);
  if(a<0||b<a)throw Error("Function not found: "+startMark);
  return source.slice(a,b);
}
const core=extract("  function updatePlaybackUI() {","  function makeRefreshIcon() {");
const takes=extract("  function takeButton(","  async function playAudio(");
const events=extract('  $("phone-player").addEventListener("play"',"  function displayAudioProgress(op) {");
const previewClick=extract('  $("preview-audio").addEventListener("click"','  $("generate-audio").addEventListener("click"');
function assert(ok,label){if(!ok)throw Error(label);}
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};}
function element(tag){
  return {
    tagName:tag.toUpperCase(),className:"",style:{},hidden:false,disabled:false,
    dataset:{fixedDisabled:"false"},attributes:{},children:[],listeners:{},
    classList:{values:new Set(),toggle(key,active){if(active)this.values.add(key);else this.values.delete(key);}},
    setAttribute(key,value){this.attributes[key]=value;},
    getAttribute(key){return this.attributes[key];},
    addEventListener(key,fn){this.listeners[key]=fn;},
    append(...nodes){this.children.push(...nodes);},
    replaceChildren(...nodes){this.children=nodes;},
    get firstElementChild(){return this.children[0];},
    querySelector(sel){
      const target=sel.slice(1);
      const visit=node=>{
        for(const child of node.children){
          if(child.className===target)return child;
          const nested=visit(child);if(nested)return nested;
        }
        return null;
      };
      return visit(this);
    },
    querySelectorAll(sel){return sel===".take-card"?this.children:[];},
    click(force=false){if((force||!this.disabled)&&this.listeners.click)this.listeners.click();}
  };
}
const nodes={};const $=id=>(nodes[id] ||= element("button"));
const list=$("take-list"),preview=$("preview-audio"),player=$("phone-player");
Object.assign(player,{
  src:"blob:one",paused:true,ended:false,duration:5,currentTime:0,attempts:0,pending:null,
  play(){this.attempts++;return this.pending?this.pending.promise:Promise.resolve();},
  pause(){this.paused=true;this.fire("pause");},
  fire(name){if(this.listeners[name])this.listeners[name]();}
});
let generates=0,fetches=0;
const runtime=new Function("$","document","feedback","startAudio","playAudio","itemAudioPath","setFixed",
  "let busy=false;let token='token';let selectedId='item';let currentView='item';"+
  "let playback={kind:'preview',itemId:'item',phase:'paused',started:true};"+
  "let playbackRequestId=3;let playingUrl='blob:one';"+
  "let takeMenuOpen=false;let autoPrepareFailures=new Set();"+
  core+takes+events+previewClick+
  ";return {updatePlaybackUI,togglePlayback,renderTakes,getState:()=>playback,"+
  "setKind(kind){playback={kind,itemId:'item',takeNumber:1,phase:'paused',started:true};},"+
  "setPhase(phase){playback.phase=phase;}};");
const app=runtime($,{createElement:element},()=>{},()=>generates++,()=>fetches++,
 id=>"/items/"+id,(id,fixed)=>{
   const button=$(id);button.dataset.fixedDisabled=String(fixed);button.disabled=fixed;
 });
(async()=>{
  app.updatePlaybackUI();
  assert(!preview.disabled,"Preview should start enabled when paused");
  const previewPending=deferred();player.pending=previewPending;
  preview.click();
  assert(app.getState().phase==="starting","Preview did not enter starting");
  assert(preview.disabled,"Pending Preview should disable button");
  preview.click();preview.click(true);
  assert(generates===0&&player.attempts===1,"Second Preview tap launched work");
  player.paused=false;previewPending.resolve();
  await Promise.resolve();await Promise.resolve();
  assert(app.getState().phase==="playing"&&!preview.disabled,
    "Preview did not restore button after play resolved");

  app.setKind("preview");player.paused=true;
  const rejected=deferred();player.pending=rejected;
  preview.click();
  assert(preview.disabled,"Rejected Preview pending should be disabled");
  preview.click(true);
  assert(generates===0,"Preview synthesized while waiting");
  rejected.reject(new Error("not allowed"));
  await Promise.resolve();await Promise.resolve();
  assert(app.getState().phase==="failed"&&!preview.disabled,
    "Preview failure did not release button");

  app.setKind("take");player.paused=true;
  app.renderTakes({id:"item",is_prepared:true,effective_take_count:1,
    takes:[{number:1,accepted:true,duration_seconds:1}]});
  const row=list.children[0];
  const takeButton=row.querySelector(".take-play");
  assert(takeButton&&!takeButton.disabled,"Paused Take button absent");
  const takePending=deferred();player.pending=takePending;
  takeButton.click();
  assert(app.getState().phase==="starting"&&takeButton.disabled,
    "Pending Take button not disabled");
  takeButton.click();takeButton.click(true);
  assert(fetches===0&&player.attempts===3,"Duplicate Take fetch or play");
  // Delayed media callbacks from the previous audio must not mutate loading.
  app.setPhase("loading");player.paused=true;player.ended=false;
  player.fire("playing");player.fire("ended");
  assert(app.getState().phase==="loading","Old media event modified loading Take");
  app.setPhase("starting");player.paused=false;
  takePending.resolve();
  await Promise.resolve();await Promise.resolve();
  assert(app.getState().phase==="playing"&&!takeButton.disabled,
    "Take did not restore control when resume settled");
  console.log("F08_PENDING_RESUME_PASS");
})().catch(e=>{console.error(e);process.exitCode=1;});"""
        result = subprocess.run(
            [node, "-e", script, str(path)], capture_output=True, text=True,
            timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("F08_PENDING_RESUME_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
