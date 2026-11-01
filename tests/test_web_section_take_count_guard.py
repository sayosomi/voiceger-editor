"""Regression for F-01: section navigation must protect dirty Take count drafts."""

from pathlib import Path
import shutil
import subprocess
import unittest


class SectionTakeCountGuardTests(unittest.TestCase):
    def test_production_header_and_android_forward_guard(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is required for actual browser handler assertions")
        js_path = (Path(__file__).resolve().parents[1] /
                   "voiceger_editor" / "web_assets" / "app.js")
        source = r"""
const fs=require("fs"), assert=require("assert").strict;
const js=fs.readFileSync(process.argv[1],"utf8");
function cut(a,b) {
  const i=js.indexOf(a),j=js.indexOf(b,i);
  assert(i>=0 && j>i,a+" boundary missing");
  return js.slice(i,j);
}
function node(tag="div") {
  return {tag,children:[],handlers:{},attrs:{},value:"",textContent:"",hidden:false,
    appendChild(child){this.children.push(child);return child;},
    replaceChildren(){this.children=[];},
    setAttribute(k,v){this.attrs[k]=v;},
    addEventListener(type,fn){this.handlers[type]=fn;},
    click(){this.handlers.click?.();},
    focus(){}
  };
}
const takeGuard=cut('  function takeCountDirty(item) {',
                    '  function showView(name, bypassDraftGuard) {');
const enter=cut('  function selectedSectionLanguage() {',
                '  async function deleteSectionFromEditor() {');
const render=cut('  function renderPronunciationSections(item) {',
                 '  function renderItem(keepCaptionDraft) {');
function scenario({saved=null,mode="default",value="4",caption="Caption",draft="Caption",
                   editing=true,confirmations=[]}={}) {
  const nodes={},$=id=>nodes[id] ||= node();
  const item={id:"item",is_prepared:true,caption, take_count_override:saved,
    pronunciation_sections:[{language:"ja",index:null,text:"雨",notation:"ア'メ。"}]};
  const decisions=[...confirmations],prompts=[],states=[],pushes=[];
  const win={confirm(message){prompts.push(message);return decisions.shift();},
    history:{pushState(x){pushes.push(x);}}};
  const doc={createElement:node,querySelectorAll(){return [{value:"ja",checked:true}];},
    querySelector(){return {value:"ja",checked:true};}};
  const setup=[
    'let commonSettingsData=null;',
    'let busy=false,batch={items:[item],default_take_count:4},selectedId="item",',
    'currentView="item",takeCountEditMode=editing,captionEditMode=true,',
    'sectionOpening=null,sectionTarget=null,sectionItemId="",sectionStale=false,',
    'sectionHistoryActive=false,pronunciationTarget=null;',
    'function sectionDirty(){return false;} function pronunciationDirty(){return false;}',
    'function showView(name){currentView=name;states.push(name);return true;}',
    'function sectionHistoryState(){return {voicegerSectionEditor:true};}',
    'function setFixed(){} function enterPronunciation(){}',
    takeGuard,enter,render,
    'return {renderPronunciationSections,guardDraft,',
    'getState:()=>({currentView,takeCountEditMode,captionEditMode,',
    'sectionHistoryActive}),setView:v=>currentView=v};'
  ].join("\n");
  const impl=new Function("$","window","document","item","editing","states",setup)(
    $,win,doc,item,editing,states);
  $("item-takes-mode").value=mode;
  $("item-takes").value=value;
  $("edit-caption").value=draft;
  impl.renderPronunciationSections(item);
  const button=nodes["pronunciation-sections"].children[0].children[0].children[0];
  assert.equal(button.className,"pronunciation-source-button");
  return {item,nodes,$,win,doc,impl,button,decisions,prompts,pushes,states};
}
{
  const h=scenario({mode:"custom",value:"7",confirmations:[false,true]});
  h.button.click();
  assert.equal(h.impl.getState().currentView,"item","Reject keeps Batch Item");
  assert.equal(h.impl.getState().takeCountEditMode,true,"Reject keeps editor");
  assert.equal(h.$("item-takes-mode").value,"custom");
  assert.equal(h.$("item-takes").value,"7","Reject keeps typed Take count");
  assert.equal(h.pushes.length,0,"Reject cannot push section history");
  h.button.click();
  assert.equal(h.impl.getState().currentView,"section");
  assert.equal(h.impl.getState().takeCountEditMode,false);
  assert.equal(h.pushes.length,1);
  assert.equal(h.prompts.length,2);
  assert(h.prompts.every(s=>s.includes("Take数")));
}
{
  const h=scenario({mode:"default",value:"4"});
  h.button.click();
  assert.equal(h.prompts.length,0,"Unchanged default must not warn");
  assert.equal(h.impl.getState().currentView,"section");
}
{
  const h=scenario({saved:7,mode:"custom",value:"7"});
  h.button.click();
  assert.equal(h.prompts.length,0,"Unchanged custom override must not warn");
}
{
  const h=scenario({saved:7,mode:"custom",value:"8",confirmations:[false]});
  h.button.click();
  assert.equal(h.impl.getState().currentView,"item");
  assert.equal(h.$("item-takes").value,"8");
  assert.equal(h.prompts.length,1);
}
{
  const h=scenario({saved:7,mode:"default",value:"7",confirmations:[false]});
  h.button.click();
  assert.equal(h.prompts.length,1,"Custom-to-default counts as a change");
}
{
  const h=scenario({mode:"custom",value:"7",draft:"Uncommitted",
                    confirmations:[false,true]});
  h.button.click();
  assert.equal(h.prompts.length,1,"Combined changes need one prompt");
  assert(h.prompts[0].includes("Caption") && h.prompts[0].includes("Take数"));
  assert.equal(h.impl.getState().currentView,"item");
  assert.equal(h.$("edit-caption").value,"Uncommitted");
  assert.equal(h.$("item-takes").value,"7");
  h.button.click();
  assert.equal(h.prompts.length,2,"Combined confirmation is a single dialog per attempt");
  assert.equal(h.impl.getState().currentView,"section");
  assert.equal(h.$("edit-caption").value,"Caption","Confirmed discard resets Caption");
}
{
  const h=scenario({draft:"Uncommitted",confirmations:[false]});
  h.button.click();
  assert.equal(h.prompts.length,1);
  assert(h.prompts[0].includes("Caption") && !h.prompts[0].includes("Take数"));
  assert.equal(h.impl.getState().currentView,"item");
}
// Restore a section from browser Forward: use the actual production popstate
// listener, which must run guardDraft before calling enterSection.
{
  const nodes={},$=id=>nodes[id] ||= node();
  const item={id:"item",is_prepared:true,caption:"Caption",take_count_override:null,
    pronunciation_sections:[{language:"ja",index:null,text:"雨"}]};
  const doc={querySelector(){return {value:"ja"};}};
  const signals={back:0,entered:0},prompts=[],decisions=[false,true];
  const win={handlers:{},history:{back(){signals.back++;}},
    confirm(s){prompts.push(s);return decisions.shift();},
    addEventListener(name,fn){this.handlers[name]=fn;}};
  const setup=[
    'let commonSettingsData=null;',
    'let dictionaryHistoryDestination=null,settingsHistoryActive=false;',
    'let sectionHistoryActive=false,pronunciationHistoryActive=false,',
    'busy=false,batch={items:[item]},sessionId="S",selectedId="item",',
    'currentView="item",takeCountEditMode=true;',
    'function sectionDirty(){return false;} function pronunciationDirty(){return false;}',
    'function showView(){} function feedback(){}',
    'function enterSection(){signals.entered++;return true;}',
    takeGuard,
    cut('  window.addEventListener("popstate", function (event) {',
        '  window.addEventListener("beforeunload", function (event) {'),
    'return {getSelected:()=>selectedId};'
  ].join("\n");
  const impl=new Function("$","window","item","signals",setup)($,win,item,signals);
  $("item-takes-mode").value="custom";
  $("item-takes").value="7";
  $("edit-caption").value="Caption";
  const event={state:{voicegerSectionEditor:true,sessionId:"S",itemId:"item",
    mode:"edit",language:"ja",index:null,opening:"雨"}};
  win.handlers.popstate(event);
  assert.equal(signals.back,1,"Rejected forward restores prior history");
  assert.equal(signals.entered,0,"Rejected forward must not open editor");
  assert.equal($("item-takes").value,"7");
  win.handlers.popstate(event);
  assert.equal(signals.entered,1,"Accepted forward enters editor");
  assert.equal(prompts.length,2);
  assert(prompts.every(s=>s.includes("Take数")));
  assert.equal(impl.getSelected(),"item");
}
console.log("WEB_SECTION_TAKE_COUNT_GUARD_PASS");
""";
        result = subprocess.run(
            [node, "-e", source, str(js_path)],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        self.assertIn("WEB_SECTION_TAKE_COUNT_GUARD_PASS", result.stdout)
