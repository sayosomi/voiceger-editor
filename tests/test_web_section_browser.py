"""Slice 6b: production mobile section source/edit and minimal controls."""
from pathlib import Path
import shutil
import subprocess
import unittest


class SectionBrowserTests(unittest.TestCase):
    def test_direct_tap_section_edit_and_draft_navigation(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node needed for real JS handler testing")
        assets = Path(__file__).resolve().parents[1] / "voiceger_editor" / "web_assets"
        source = r"""
const fs=require("fs"), assert=require("assert").strict;
const js=fs.readFileSync(process.argv[1],"utf8");
const html=fs.readFileSync(process.argv[2],"utf8");
function cut(a,b) {
  const i=js.indexOf(a),j=js.indexOf(b,i);
  assert(i>=0 && j>i,"Missing production boundary: "+a);
  return js.slice(i,j);
}
function node(tag="div") {
  return {tag,children:[],listeners:{},dataset:{},value:"",textContent:"",
    hidden:false,disabled:false,attrs:{},className:"",
    appendChild(n){this.children.push(n);return n;},
    append(n){this.children.push(n);return n;},
    replaceChildren(){this.children=[];},
    setAttribute(k,v){this.attrs[k]=v;},
    addEventListener(e,fn){(this.listeners[e] ||= []).push(fn);},
    emit(e){for(const fn of this.listeners[e]||[])fn();},
    click(){this.emit("click");},
    focus(){this.focused=true;}
  };
}
const walk=n=>[n,...n.children.flatMap(walk)];
assert.equal((html.match(/id="view-section"/g)||[]).length,1);
assert.equal((html.match(/id="add-section"/g)||[]).length,1);
assert.equal((html.match(/id="delete-section"/g)||[]).length,1);
assert(!html.includes('id="cancel-section"'),"Back replaces redundant Cancel");
assert(!html.includes('id="section-context"'),"No duplicate section subtitle");
assert(html.indexOf('id="add-section"') < html.indexOf('id="pronunciation-sections"'),
       "One add control belongs in the pronunciation header");
{
  const nodes={},$=id=>nodes[id] ||= node(),selected=[],pronunciation=[];
  const document={createElement:node};
  const impl=new Function("$","document","selected","pronunciation",
    'let busy=false,pronunciationTarget=null;'+
    'function guardDraft(){return true;}'+
    'function enterSection(item,section){selected.push(section.index);}'+
    'function enterPronunciation(item){pronunciation.push(pronunciationTarget);}'+
    cut('  function renderPronunciationSections(item) {',
        '  function renderItem(keepCaptionDraft) {')+
    'return renderPronunciationSections;'
  )($,document,selected,pronunciation);
  const item={id:"i",pronunciation_sections:[
    {index:0,language:"ja",text:"雨",notation:"ア\u0027メ。"},
    {index:1,language:"en",text:"very sweet!",groups:[
      {index:0,label:"very",display:"V [EH1] R IY0",editable:true}
    ]},
    {index:2,language:"ja",text:"咲く",notation:"サ\u0027ク。"}
  ]};
  impl(item);
  let dom=walk(nodes["pronunciation-sections"]);
  let textButtons=dom.filter(n=>n.className==="pronunciation-source-button");
  assert.equal(textButtons.length,3,"Each spoken text has one direct edit target");
  assert.equal(dom.filter(n=>n.className==="section-menu-button").length,0);
  assert.equal(dom.filter(n=>n.className==="section-action-menu").length,0);
  assert.equal(dom.filter(n=>n.textContent==="編集").length,0,
               "Do not repeat Edit labels beside pronunciation");
  assert.equal(dom.filter(n=>n.className==="pronunciation-entry").length,3);
  assert.equal(dom.filter(n=>n.className==="section-edit-indicator").length,3);
  textButtons[1].click();
  assert.deepEqual(selected,[1],"Tap text => direct text editor");
  dom.filter(n=>n.className==="pronunciation-entry")[1].click();
  assert.deepEqual(pronunciation,
    [{language:"en",segmentIndex:1,groupIndex:0}],
    "Tap pronunciation => existing direct ARPAbet editor");
  item.pronunciation_sections=[{index:null,language:"ja",text:"雨",notation:"ア\u0027メ。"}];
  impl(item);
  dom=walk(nodes["pronunciation-sections"]);
  assert.equal(dom.filter(n=>n.className==="pronunciation-source-button").length,1);
  assert(!dom.some(n=>n.textContent==="セクションを削除"));
}
{
  const nodes={},$=id=>nodes[id] ||= node();
  const pushes=[],win={history:{pushState(s){pushes.push(s);}}};
  const radios=[{value:"ja",checked:true},{value:"en",checked:false}];
  const document={querySelectorAll(){return radios;},querySelector(){
    return radios.find(r=>r.checked)||null;
  }};
  const setup=[
    'let busy=false,currentView="item",sectionTarget=null,sectionOpening=null,',
    'sectionItemId="",sectionStale=false,sectionHistoryActive=false;',
    'function showView(v){currentView=v;return true;}',
    'function sectionHistoryState(){return {id:sectionItemId};}',
    'function setFixed(){}',
    cut('  function selectedSectionLanguage() {',
        '  async function deleteSectionFromEditor() {'),
    'return {enterSection,get:()=>({sectionTarget,sectionOpening,sectionItemId,sectionHistoryActive,currentView})};'
  ].join("\n");
  const f=new Function("$","window","document",setup)($,win,document);
  const single={id:"item",is_prepared:true,pronunciation_sections:[
    {index:null,language:"ja",text:"雨"}
  ]};
  assert(f.enterSection(single,single.pronunciation_sections[0],false,false));
  assert.equal(nodes["section-text"].value,"雨");
  assert.equal(nodes["section-title"].textContent,"読み上げ文");
  assert.equal(nodes["delete-section"].hidden,true,"Only section is protected");
  assert.equal(nodes["reset-section"].hidden,true,"Reset hidden until dirty");
  assert.equal(nodes["section-language-field"].hidden,true);
  assert.equal(pushes.length,1);
  const multi={id:"item",is_prepared:true,pronunciation_sections:[
    {index:0,language:"ja",text:"雨"},
    {index:1,language:"en",text:"very sweet!"}
  ]};
  assert(f.enterSection(multi,multi.pronunciation_sections[1],false,false));
  assert.equal(nodes["delete-section"].hidden,false);
  assert.equal(f.get().sectionTarget.index,1);
  assert(f.enterSection(multi,null,true,false));
  assert.equal(nodes["section-language-field"].hidden,false);
  assert.equal(nodes["preview-section"].hidden,true);
  assert.equal(nodes["delete-section"].hidden,true);
  assert.equal(nodes["reset-section"].hidden,true);
  assert.equal(nodes["apply-section"].textContent,"追加");
  assert.equal(radios[0].checked,true);
  assert.equal(radios[1].checked,false);
}
{
  const nodes={},$=id=>nodes[id] ||= node();
  let playback=null,sectionTarget={mode:"edit"},sectionOpening="雨",
      busy=false,sectionStale=false;
  const setup=[
    'let playback=null,sectionTarget={mode:"edit"},sectionOpening="雨",',
    'busy=false,sectionStale=false;',
    'function clearPlayer(){}',
    cut('  function updateSectionReset() {',
        '  $("preview-section").addEventListener("click"'),
    'return {updateSectionReset};'
  ].join("\n");
  const f=new Function("$",setup)($);
  nodes["section-text"].value="雨";
  f.updateSectionReset();
  assert.equal(nodes["reset-section"].hidden,true);
  nodes["section-text"].value="水";
  nodes["section-text"].emit("input");
  assert.equal(nodes["reset-section"].hidden,false);
  nodes["reset-section"].click();
  assert.equal(nodes["section-text"].value,"雨");
  assert.equal(nodes["reset-section"].hidden,true);
}
{
  let decisions=[false,true],requests=[],messages=[],destinations=[];
  let response={batch:{revision:9,items:[{id:"item",pronunciation_sections:[{index:null,language:"ja",text:"雨"}]}]}};
  const nodes={},$=id=>nodes[id] ||= node();
  const win={confirm(s){messages.push(s);return decisions.shift();}};
  const setup=[
    'let busy=false,sectionStale=false,selectedId="item",sectionItemId="item",',
    'sectionHistoryActive=true,sectionExitPending=null,',
    'sectionTarget={mode:"edit",language:"en",index:1,opening:"very sweet!"},',
    'batch={revision:8,items:[{id:"item",pronunciation_sections:[',
    '{index:0,language:"ja",text:"雨"},',
    '{index:1,language:"en",text:"very sweet!"}]}]};',
    'function setBusy(v){busy=v;} function clearPlayer(){}',
    'function itemAudioPath(){return "/items/item";} function renderList(){}',
    'function feedback(s){messages.push(s);}',
    'function showView(n,bypass){destinations.push([n,bypass]);}',
    'function setFixed(){} async function refresh(){} function resetLocal(){}',
    cut('  async function deleteSectionFromEditor() {',
        '  $("add-section").addEventListener("click"'),
    'return {deleteSectionFromEditor,get:()=>({batch,sectionExitPending}),',
    'setSections:s=>batch.items[0].pronunciation_sections=s};'
  ].join("\n");
  const f=new Function("$","window","request","messages","destinations",setup)(
    $,win,async(method,url,payload)=>{requests.push({method,url,payload});return response;},
    messages,destinations);
  await f.deleteSectionFromEditor();
  assert.equal(requests.length,0,"Cancelled delete must not mutate");
  await f.deleteSectionFromEditor();
  assert.equal(requests.length,1,"Only confirmed delete may submit");
  assert.deepEqual(requests[0],{
    method:"POST",url:"/items/item/sections/delete?expected_revision=8",
    payload:{language:"en",index:1,opening:"very sweet!"}
  });
  assert(messages[0].includes("very sweet!"),"Confirmation shows full source");
  assert(messages[0].includes("Take候補"),"Confirmation discloses Take invalidation");
  assert.deepEqual(destinations,[["item",true]],"Editor exit uses history-aware return");
  assert.equal(f.get().sectionExitPending.destination,"item");
  f.setSections([{index:null,language:"ja",text:"雨"}]);
  await f.deleteSectionFromEditor();
  assert.equal(requests.length,1,"Lone section cannot be deleted");
}
{
  const $=id=>({value:id==="section-text"?"draft":"ja"});
  const decisions=[false,true],win={confirm(){return decisions.shift();}};
  const setup=[
    'let batch=null,selectedId="",currentView="section",sectionOpening="original",',
    'sectionTarget={mode:"edit",language:"ja"};',
    'function pronunciationDirty(){return false;}',
    cut('  function sectionDirty() {','  function showView(name, bypassDraftGuard) {'),
    'return {guardDraft,sectionDirty};'
  ].join("\n");
  const f=new Function("$","window",setup)($,win);
  assert(f.sectionDirty());
  assert.equal(f.guardDraft(),false,"Rejecting discard preserves draft");
  assert.equal(f.guardDraft(),true,"Accepting discard allows navigation");
}
console.log("WEB_SECTION_BROWSER_PASS");
""";
        result = subprocess.run(
            [node, "-e", source, str(assets / "app.js"), str(assets / "index.html")],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        self.assertIn("WEB_SECTION_BROWSER_PASS", result.stdout)
