"""Execute the real Slice 7b browser handlers and touch-oriented controls with Node."""

from pathlib import Path
import shutil
import subprocess
import unittest


class WebRecipeBrowserTests(unittest.TestCase):
    def test_recipe_menu_list_confirmation_cancel_conflict_and_navigation(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for browser interaction tests")
        assets = Path(__file__).resolve().parents[1] / "voiceger_editor" / "web_assets"
        source = r"""
const fs=require("fs"), assert=require("assert").strict;
const js=fs.readFileSync(process.argv[1],"utf8");
const html=fs.readFileSync(process.argv[2],"utf8");
function cut(a,b,includeEnd=false) {
  const i=js.indexOf(a),j=js.indexOf(b,i);
  assert(i>=0 && j>i,"Production handler missing: "+a);
  return js.slice(i,j+(includeEnd?b.length:0));
}
function node(tag="div") {
  return {
    tag,hidden:false,value:"",textContent:"",children:[],listeners:{},attrs:{},
    appendChild(n){this.children.push(n);return n;},
    replaceChildren(){this.children=[];},
    setAttribute(k,v){this.attrs[k]=v;},
    addEventListener(k,fn){(this.listeners[k] ||= []).push(fn);},
    click(){for(const f of this.listeners.click||[])f.call(this);},
    submit(){for(const f of this.listeners.submit||[])f.call(this,{preventDefault(){}});},
    focus(){this.focused=true;}
  };
}
const nodes={},$=id=>nodes[id] ||= node();
const document={createElement:node};
let requests=[],feedbacks=[],views=[],prompts=[],decisions=[];
let list=["first.voiceger.json"],existing=false,failCommit=false;
const window={confirm(message){prompts.push(message);return decisions.shift();}};
async function request(method,path,payload) {
  requests.push({method,path,payload});
  if(path.endsWith("/recipes"))return {files:list};
  if(path.includes("/read/review"))
    return {token:"read-token",filename:payload.filename,replace_required:true};
  if(path.includes("/save/review"))
    return {token:"save-token",filename:payload.filename,exists:existing};
  if(path.includes("/read/commit")) {
    if(failCommit) {let error=new Error("Mac側のファイルが変更されました");error.conflictCode="recipe_changed";throw error;}
    return {revision:4,items:[]};
  }
  return {cancelled:true,saved:true};
}
const init=[
 'let busy=false,reorderMode=false,deleteMode=false,batchMenuOpen=false,recipeMode="";',
 'let batch={revision:3,items:[{id:"old"}]},sessionId="sid",selectedId="old";',
 'let captionEditMode=true,takeCountEditMode=true,takeMenuOpen=true;',
 'const autoPrepareFailures=new Set(["old"]);',
 'function batchPath(){return "/api/web/sessions/sid/batch";}',
 'function showView(v){views.push(v);return true;}',
 'function setBusy(v){busy=v;}',
 'function feedback(s){feedbacks.push(s);}',
 'function clearPlayer(){}',
 'function renderList(){}',
 'async function refresh(){}',
 cut('  function closeBatchMenu() {','  async function startBatchGeneration() {'),
 cut('  $("open-batch-menu").addEventListener("click",',
     '  $("recipe-save-form").addEventListener("submit", saveRecipe);',true),
 'return {openRecipe,readRecipe,saveRecipe,', 
 ' get:()=>({batch,selectedId,recipeMode,busy,batchMenuOpen})};'
].join("\n");
const ui=new Function("$","document","window","request","views","feedbacks",init)(
  $,document,window,request,views,feedbacks);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 assert.equal((html.match(/id="open-batch-menu"/g)||[]).length,1);
 assert.equal((html.match(/id="recipe-filename"/g)||[]).length,1);
 assert(html.includes("Macから読み込む") && html.includes("Batchを保存"));
 $("recipe-filename").value="first.voiceger.json";
 $("open-batch-menu").click();
 assert.equal($("batch-menu").hidden,false);
 assert.equal(nodes["open-batch-menu"].attrs["aria-expanded"],"true");
 $("recipe-open-read").click();
 await tick();
 assert.equal($("batch-menu").hidden,true);
 assert.equal($("recipe-files").children.length,1);
 assert.equal($("recipe-files").children[0].children[0].textContent,"first.voiceger.json");
 assert.equal($("recipe-empty").hidden,true);
 assert(requests.some(c=>c.method==="GET" && c.path.endsWith("/recipes")));
 // Tap a listed file, decline the explicit replace warning, and do not commit.
 decisions.push(false);
 $("recipe-files").children[0].children[0].click();
 await tick();
 assert(prompts.some(p=>p.includes("生成済みTake・採用状態")
                     && p.includes("保存済みの音声ファイル")));
 assert(requests.some(c=>c.path.includes("/cancel")));
 assert.equal(requests.filter(c=>c.path.includes("/read/commit")).length,0);
 assert.equal(ui.get().batch.revision,3);
 // A stale-file error must not navigate or replace the current Batch.
 decisions.push(true);failCommit=true;
 await ui.readRecipe("first.voiceger.json");
 assert.equal(ui.get().batch.revision,3);
 assert.equal(views.at(-1),"recipe");
 assert(feedbacks.at(-1).includes("変更"));
 // Confirmed replacement moves to Batch List and clears local selection.
 failCommit=false;decisions.push(true);
 await ui.readRecipe("first.voiceger.json");
 assert.equal(ui.get().batch.revision,4);
 assert.equal(ui.get().selectedId,"");
 assert.equal(views.at(-1),"list");
 // Return to menu, open Save, and require confirmation on overwrite.
 $("open-batch-menu").click();
 $("recipe-open-save").click();
 assert.equal(ui.get().recipeMode,"save");
 assert.equal($("recipe-save-form").hidden,false);
 assert.equal($("recipe-read-panel").hidden,true);
 assert.equal($("recipe-filename").focused,true);
 existing=true;decisions.push(false);
 $("recipe-save-form").submit();
 await tick();
 assert.equal(requests.filter(c=>c.path.includes("/save/commit")).length,0);
 assert(feedbacks.at(-1).includes("キャンセル"));
 existing=true;decisions.push(true);
 await ui.saveRecipe({preventDefault(){}});
 const saves=requests.filter(c=>c.path.includes("/save/commit"));
 assert.equal(saves.length,1);
 assert.equal(saves[0].payload.confirmed_overwrite,true);
 assert.equal(saves[0].path.includes("expected_revision=4"),true);
 assert.equal(views.at(-1),"list");
 // Empty output list renders an explicit empty state.
 list=[];
 await ui.openRecipe("read");
 assert.equal($("recipe-files").children.length,0);
 assert.equal($("recipe-empty").hidden,false);
 console.log("WEB_RECIPE_BROWSER_INTERACTION_PASS");
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result = subprocess.run(
            [node, "-e", source, str(assets / "app.js"), str(assets / "index.html")],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        self.assertIn("WEB_RECIPE_BROWSER_INTERACTION_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
