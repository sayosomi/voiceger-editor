"""Web Slice 6b real-production mobile DOM behavior checks under Node."""
from pathlib import Path
import shutil
import subprocess
import unittest


class SectionBrowserTests(unittest.TestCase):
    def test_section_menus_and_draft_navigation(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node needed for real JS handler testing")
        assets = Path(__file__).resolve().parents[1] / "voiceger_editor" / "web_assets"
        source = r"""
const fs = require("fs"), assert = require("assert").strict;
const js = fs.readFileSync(process.argv[1], "utf8");
const html = fs.readFileSync(process.argv[2], "utf8");
function cut(a,b) {
  const x=js.indexOf(a),y=js.indexOf(b,x);
  assert(x>=0&&y>x,"Missing production boundary: "+a);
  return js.slice(x,y);
}
function node(tag="div") {
  return {tag, children:[],listeners:{},dataset:{},value:"",
    textContent:"",hidden:false,disabled:false,attrs:{},
    appendChild(n){this.children.push(n);return n;},
    append(n){this.children.push(n);return n;},
    replaceChildren(){this.children=[];},
    setAttribute(n,v){this.attrs[n]=v;},
    addEventListener(event,cb){(this.listeners[event] ||= []).push(cb);},
    click(){for(const fn of this.listeners.click||[])fn();},
    focus(){this.focused=true;}
  };
}
const walk=(n)=>[n,...n.children.flatMap(walk)];
assert.equal((html.match(/id="view-section"/g)||[]).length,1);
assert.equal((html.match(/id="add-section"/g)||[]).length,1);
{
  const nodes={},$=id=>nodes[id] ||= node();
  const selected=[];
  const document={createElement:node};
  const f=new Function("$","document","selected",
    'let busy=false,pronunciationTarget=null;'+
    'function guardDraft(){return true;}' +
    'function enterPronunciation(){}' +
    'function enterSection(item,section){selected.push(section.index);}' +
    'function deleteSection(item,section){selected.push("delete"+section.index);}' +
    cut('  function renderPronunciationSections(item) {',
        '  function renderItem(keepCaptionDraft) {')+
    'return renderPronunciationSections;'
  )($,document,selected);
  const item={id:"i",pronunciation_sections:[
    {index:0,language:"ja",text:"雨",notation:"ア'メ。"},
    {index:1,language:"en",text:"very!",groups:[
      {index:0,label:"very",display:"V [EH1] R IY0",editable:true}
    ]},
    {index:2,language:"ja",text:"咲く",notation:"サ'ク。"}
  ]};
  f(item);
  let dom=walk(nodes["pronunciation-sections"]);
  let menus=dom.filter(n=>n.attrs["aria-label"]?.includes("セクションの操作"));
  assert.equal(menus.length,3,"one menu per section");
  assert.equal(dom.filter(n=>n.textContent==="読み上げ文を変更").length,3);
  assert.equal(dom.filter(n=>n.textContent==="セクションを削除").length,3);
  menus[1].click();
  assert.equal(menus[1].attrs["aria-expanded"],"true");
  let edit=dom.find(n=>n.textContent==="読み上げ文を変更" &&
    n.listeners.click);
  edit.click();
  assert.deepEqual(selected,[0]);
  let del=dom.find(n=>n.textContent==="セクションを削除");
  del.click();
  assert.deepEqual(selected,[0,"delete0"]);
  item.pronunciation_sections=[{index:null,language:"ja",text:"雨",notation:"ア'メ。"}];
  f(item);
  dom=walk(nodes["pronunciation-sections"]);
  assert.equal(dom.filter(n=>n.textContent==="セクションを削除").length,0);
  assert.equal(dom.filter(n=>n.textContent==="読み上げ文を変更").length,1);
}
{
  const nodes={},$=id=>nodes[id] ||= node();
  const pushes=[];
  const win={history:{pushState(s){pushes.push(s);}}};
  const radios=[{value:"ja",checked:true},{value:"en",checked:false}];
  const document={querySelectorAll(){return radios;},querySelector(){
    return radios.find(r=>r.checked) || null;
  }};
  const code=[
    'let busy=false,currentView="item",sectionTarget=null,sectionOpening=null,sectionItemId="",sectionStale=false,sectionHistoryActive=false;',
    'function showView(v){currentView=v;return true;}',
    'function sectionHistoryState(){return {id:sectionItemId};}',
    'function setFixed(){}',
    cut('  function selectedSectionLanguage() {',
        '  function deleteSection(item, section) {'),
    'return {enterSection,get:()=>({sectionTarget,sectionOpening,sectionItemId,sectionHistoryActive,currentView})};'
  ].join("\n");
  const f=new Function("$","window","document",code)($,win,document);
  const item={id:"item",is_prepared:true,pronunciation_sections:[
    {index:1,language:"en",text:"very sweet!"}
  ]};
  assert(f.enterSection(item,item.pronunciation_sections[0],false,false));
  assert.equal(nodes["section-text"].value,"very sweet!");
  assert.equal(nodes["section-language-field"].hidden,true);
  assert.equal(nodes["section-title"].textContent,"読み上げ文を変更");
  assert.equal(pushes.length,1);
  assert.equal(f.get().sectionTarget.index,1);
  assert(f.enterSection(item,null,true,false));
  assert.equal(nodes["section-language-field"].hidden,false);
  assert.equal(nodes["preview-section"].hidden,true);
  assert.equal(nodes["apply-section"].textContent,"追加");
  assert.equal(f.get().sectionTarget.language,"ja");
  assert.equal(radios[0].checked,true);
  assert.equal(radios[1].checked,false);
}
{
  const $=id=>({value:id==="section-text"?"draft":"ja"});
  let decisions=[false,true];
  const win={confirm(){return decisions.shift();}};
  const code=[
    'let batch=null,selectedId="",currentView="section",sectionOpening="original",sectionTarget={mode:"edit",language:"ja"};',
    'function pronunciationDirty(){return false;}',
    cut('  function sectionDirty() {','  function showView(name, bypassDraftGuard) {'),
    'return {guardDraft,sectionDirty};'
  ].join("\n");
  const f=new Function("$","window",code)($,win);
  assert(f.sectionDirty());
  assert.equal(f.guardDraft(),false,"refusing discard retains draft");
  assert.equal(f.guardDraft(),true,"accepting discard allows return");
}
console.log("WEB_SECTION_BROWSER_PASS");
""";
        result = subprocess.run(
            [node, "-e", source, str(assets / "app.js"), str(assets / "index.html")],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        self.assertIn("WEB_SECTION_BROWSER_PASS", result.stdout)
