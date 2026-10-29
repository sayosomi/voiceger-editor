"""Execute production mobile English/Japanese editor selection and endpoint logic."""
from pathlib import Path
import shutil
import subprocess
import unittest


class MixedPronunciationBrowserTests(unittest.TestCase):
    def test_direct_editor_targets_and_routes(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for browser interaction tests")
        root = Path(__file__).resolve().parents[1] / "voiceger_editor" / "web_assets"
        source = r"""
const fs = require("fs"), assert = require("assert").strict;
const js = fs.readFileSync(process.argv[1],"utf8");
const html = fs.readFileSync(process.argv[2],"utf8");
const css = fs.readFileSync(process.argv[3],"utf8");
function slice(a,b) {
 const start=js.indexOf(a),end=js.indexOf(b,start);
 assert(start>=0 && end>start,"production handler missing "+a);
 return js.slice(start,end);
}
assert(html.includes('id="pronunciation-sections"'));
assert(html.includes('id="pronunciation-assists"'));
assert(css.includes('.pronunciation-assists[hidden]'));
const nodes={};
const $=id=>(nodes[id] ||= {
 value:"",hidden:false,textContent:"",setSelectionRange(a,b){this.start=a;this.end=b;},
 focus(){},
});
const setup=[
 'let currentView="item",pronunciationReturnView="item";',
 'let captionEditMode=false,takeCountEditMode=false;',
 'let pronunciationOpening=null,pronunciationItemId="",pronunciationStale=false;',
 'let pronunciationTarget={language:"en",segmentIndex:1,groupIndex:0};',
 'let pronunciationHistoryActive=false;',
 'function showView(){return true;} function setFixed(){}',
 'function rememberPronunciationSelection(){}',
 'function pronunciationHistoryState(){return {};}',
 slice('  function enterPronunciation(item, fromHistory) {',
       '  async function applyPronunciation(event) {'),
 'return {enterPronunciation,pronunciationEndpoint,',
 ' setTarget:t=>{pronunciationTarget=t;}, getOpening:()=>pronunciationOpening};'
].join("\n");
let pushes=0;
const f=new Function("$","window",setup)($,{history:{pushState(){pushes++;}}});
const item={
 id:"item",caption:"表示用",
 pronunciation:null,
 pronunciation_sections:[
  {language:"ja",index:0,text:"雨",notation:"ア'メ。"},
  {language:"en",index:1,text:"very sweet!",
    groups:[{index:0,label:"very",notation:"V EH1 R IY0",display:"V [EH1] R IY0"},
            {index:1,label:"!",notation:"!",display:"!"}]},
  {language:"ja",index:2,text:"咲く",notation:"サ'ク。"}
 ]
};
assert(f.enterPronunciation(item,false));
assert.equal(nodes["pronunciation-text"].value,"V EH1 R IY0");
assert.equal(nodes["pronunciation-assists"].hidden,true);
assert.equal(nodes["pronunciation-field-label"].textContent,"ARPAbet");
assert.equal(nodes["pronunciation-caption"].textContent,"very");
nodes["pronunciation-text"].value="V EH0 R IY1";
let p=f.pronunciationEndpoint(true);
assert.equal(p.suffix,"/pronunciation/english/1/0/preview");
assert.deepEqual(p.payload,{notation:"V EH0 R IY1",opening:"V EH1 R IY0"});
f.setTarget({language:"en",segmentIndex:1,groupIndex:1});
assert(f.enterPronunciation(item,false));
assert.equal(nodes["pronunciation-text"].value,"!");
nodes["pronunciation-text"].value="?";
p=f.pronunciationEndpoint(false);
assert.equal(p.suffix,"/pronunciation/english/1/1");
assert.equal(p.payload.opening,"!");
f.setTarget({language:"ja",segmentIndex:2,groupIndex:null});
assert(f.enterPronunciation(item,false));
assert.equal(nodes["pronunciation-text"].value,"サ'ク。");
assert.equal(nodes["pronunciation-assists"].hidden,false);
p=f.pronunciationEndpoint(true);
assert.equal(p.suffix,"/pronunciation/preview?segment_index=2");
assert.equal(p.payload.notation,"サ'ク。");
assert.equal(pushes,3);
console.log("MIXED_DIRECT_WEB_BROWSER_PASS");
"""
        r = subprocess.run(
            [node, "-e", source, str(root / "app.js"),
             str(root / "index.html"), str(root / "app.css")],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)
        self.assertIn("MIXED_DIRECT_WEB_BROWSER_PASS", r.stdout)
