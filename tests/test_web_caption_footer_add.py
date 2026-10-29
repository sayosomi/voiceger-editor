"""Exercise actual mobile footer/add handlers with a controlled Node DOM."""
from pathlib import Path
import shutil
import subprocess
import unittest


class WebCaptionFooterAddTests(unittest.TestCase):
    def test_navigation_and_submit_from_last_caption(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node required to test browser navigation")
        assets = Path(__file__).resolve().parents[1] / "voiceger_editor" / "web_assets"
        source = r"""
const fs = require("fs");
const assert = require("assert").strict;
const js = fs.readFileSync(process.argv[1], "utf8");
const html = fs.readFileSync(process.argv[2], "utf8");
function cut(a,b) {
  const start = js.indexOf(a), end = js.indexOf(b,start);
  assert(start >= 0 && end > start,"source missing " + a);
  return js.slice(start,end);
}
assert.equal((html.match(/id="next-item"/g)||[]).length,1);
assert.equal((html.match(/id="add-form"/g)||[]).length,1);
function node() {
  return {value:"",textContent:"",hidden:false,disabled:false,dataset:{},
    focusCount:0,listeners:{},
    focus(){this.focusCount++;},
    addEventListener(type,cb){(this.listeners[type] ||= []).push(cb);},
    async emit(type,event={}) {
      return Promise.all((this.listeners[type]||[]).map(fn=>fn(event)));
    }};
}
function makeRows() {
  return ["one","two","three"].map((text,i)=>({
    id:String(i),caption:text,take_count_override:null,
    effective_take_count:4,is_prepared:false,pronunciation:null
  }));
}
{
  const nodes = {};
  const $ = id => nodes[id] ||= node();
  const setup = [
    'let batch={items:makeRows()},selectedId="0",busy=false;',
    'let captionEditMode=false,takeCountEditMode=false,currentView="item";',
    'function renderTakes(){}',
    cut('  function renderItem(keepCaptionDraft) {','  function openItem(id) {'),
    'return {renderItem, select:id=>selectedId=id,',
    'setRows:rows=>batch.items=rows, setBusy:v=>busy=v};'
  ].join("\n");
  const f = new Function("$","makeRows",setup)($,makeRows);
  f.renderItem(false);
  assert.equal(nodes["next-item"].textContent,"次のCaption →");
  assert.equal(nodes["next-item"].disabled,false);
  assert.equal(nodes["previous-item"].disabled,true);
  f.select("1");f.renderItem(false);
  assert.equal(nodes["next-item"].textContent,"次のCaption →");
  f.select("2");f.renderItem(false);
  assert.equal(nodes["next-item"].textContent,"＋ Caption追加");
  assert.equal(nodes["next-item"].disabled,false);
  assert.equal(nodes["previous-item"].disabled,false);
  f.setRows([makeRows()[0]]);f.select("0");f.renderItem(false);
  assert.equal(nodes["next-item"].textContent,"＋ Caption追加");
  assert.equal(nodes["previous-item"].disabled,true);
  f.setBusy(true);f.renderItem(false);
  assert.equal(nodes["next-item"].disabled,true);
}
{
  const nodes = {};
  const $ = id => nodes[id] ||= node();
  const rows = makeRows();
  let decisions=[], destinations=[], opens=[];
  const win = {confirm(){return decisions.shift();}};
  const setup = [
    'let batch={items:rows},selectedId="2",currentView="item",busy=false;',
    'let addFromItemId="",captionEditMode=false;',
    'function pronunciationDirty(){return false;}',
    cut('  function guardDraft() {','  function showView(name, bypassDraftGuard) {'),
    'function showView(name){if(busy||!guardDraft())return false;currentView=name;',
    'destinations.push(name);return true;}',
    cut('  function openCaptionAdd(fromItem) {',
        '  $("item-back").addEventListener("click"'),
    'function openItem(id){opens.push(id);selectedId=id;currentView="item";}',
    cut('  function adjacent(delta) {',
        '  $("default-takes-form").addEventListener("submit"'),
    'return {setSelected:id=>selectedId=id,getView:()=>currentView,',
    'getOrigin:()=>addFromItemId,setBusy:v=>busy=v};'
  ].join("\n");
  const f = new Function("$","rows","window","decisions","destinations","opens",setup)(
    $,rows,win,decisions,destinations,opens);
  f.setSelected("1");
  nodes["edit-caption"].value="two";
  await nodes["next-item"].emit("click");
  assert.deepEqual(opens,["2"],"middle keeps normal next navigation");
  f.setSelected("2");
  nodes["edit-caption"].value="three";
  await nodes["next-item"].emit("click");
  assert.equal(f.getView(),"add");
  assert.equal(f.getOrigin(),"2");
  assert.equal(nodes["new-captions"].focusCount,1);
  nodes["new-captions"].value="draft";
  decisions.push(false,true);
  await nodes["add-back"].emit("click");
  assert.equal(f.getView(),"add","discard rejection preserves edit");
  assert.equal(nodes["new-captions"].value,"draft");
  await nodes["add-back"].emit("click");
  assert.equal(f.getView(),"item");
  assert.equal(nodes["new-captions"].value,"");
  assert.equal(f.getOrigin(),"");
  // Uncommitted Caption changes on Batch Item retain their existing guard.
  nodes["edit-caption"].value="uncommitted";
  decisions.push(false,true);
  await nodes["next-item"].emit("click");
  assert.equal(f.getView(),"item");
  await nodes["next-item"].emit("click");
  assert.equal(f.getView(),"add");
  await nodes["add-back"].emit("click");
  assert.equal(f.getView(),"item");
  f.setBusy(true);
  await nodes["next-item"].emit("click");
  assert.equal(f.getView(),"item","busy refuses duplicate navigation");
}
async function submitScenario(source, lines, expectedView, expectedSelected) {
  const nodes={};
  const $=id=>nodes[id] ||= node();
  let batch={items:makeRows()},selectedId="2",busy=false;
  let addFromItemId=source==="item"?"2":"";
  let currentView="add",requestCount=0,destinations=[];
  nodes["new-captions"].value=lines;
  let release;
  const gate=new Promise(resolve=>release=resolve);
  async function mutate(method, path, payload) {
    if(busy) return false;
    assert.equal(method,"POST");
    assert.equal(path,"/items");
    requestCount++;
    busy=true;
    await gate;
    for(const caption of payload.text.split(/\r?\n/).filter(s=>s.trim())){
      batch.items.push({id:"new"+batch.items.length,caption});
    }
    busy=false;
    return true;
  }
  function showView(name){currentView=name;destinations.push(name);return true;}
  function openItem(id){selectedId=id;showView("item");}
  function feedback(value){nodes["feedback"].textContent=value;}
  const src=cut('  $("add-form").addEventListener("submit", async function (event) {',
                '  $("open-caption-edit").addEventListener("click"');
  new Function("$","mutate","showView","openItem","feedback","state",
    'let {batch, selectedId, addFromItemId, busy}=state;' +
    src + 'return state;')($,mutate,showView,openItem,feedback,
    {batch,selectedId,addFromItemId,busy});
  // The handler closes over the produced state; expose the resulting view via
  // navigation callbacks instead of expecting direct access to its variables.
  const a=nodes["add-form"].emit("submit",{preventDefault(){}});
  const b=nodes["add-form"].emit("submit",{preventDefault(){}});
  release();
  await Promise.all([a,b]);
  assert.equal(requestCount,1,"double submit creates only one request");
  assert.equal(currentView,expectedView);
  assert.equal(selectedId,expectedSelected);
  assert.equal(nodes["new-captions"].value,"");
  assert.equal(nodes["feedback"].textContent,"Captionを追加しました。");
}
await submitScenario("item","one new","item","new3");
await submitScenario("item","one new\nanother new","list","2");
await submitScenario("list","one new","list","2");
console.log("WEB_CAPTION_FOOTER_ADD_PASS");
""";
        result = subprocess.run(
            [node, "-e", "(async()=>{" + source + "})().catch(e=>{console.error(e);process.exitCode=1})",
             str(assets / "app.js"), str(assets / "index.html")],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        self.assertIn("WEB_CAPTION_FOOTER_ADD_PASS", result.stdout)
