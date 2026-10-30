"""Web Slice 8 actual assisted input function and DOM contract."""
from __future__ import annotations
import re
import shutil
import subprocess
import unittest
from pathlib import Path


class DictionaryBrowserTests(unittest.TestCase):
    def test_markup_and_shared_caret(self):
        root = Path(__file__).resolve().parents[1] / "voiceger_editor" / "web_assets"
        html = (root / "index.html").read_text(encoding="utf-8")
        js = (root / "app.js").read_text(encoding="utf-8")
        for key in ("view-dictionary", "view-dictionary-entry",
                    "view-dictionary-pron", "dictionary-quick-form"):
            self.assertIn('id="' + key + '"', html)
        section = re.search(r'id="dictionary-pron-assists"[^>]*>[\s\S]*?</div>', html)
        self.assertIsNotNone(section)
        self.assertEqual(re.findall(r'data-dictionary-insert="([^"]+)"',
                         section.group()), ["'", "[", "]", " "])
        self.assertIn("data-dictionary-backspace", section.group())
        self.assertIn('aria-label="バックスペース"', section.group())
        self.assertIn("replaceAtCaret(", js)
        node = shutil.which("node")
        if not node:
            self.skipTest("Node not available")
        code = r"""
const fs = require("fs");
const js = fs.readFileSync(process.argv[1], "utf8");
const a = js.indexOf("  function rememberPronunciationSelection() {");
const b = js.indexOf("  function enterPronunciation(", a);
if (a < 0 || b < a) throw Error("Production helper unavailable");
const input = {
  value:"A🙂 B", selectionStart:3, selectionEnd:3,
  focus(){}, dispatchEvent(){},
  setRangeText(mark,start,end) {
    this.value = this.value.slice(0,start)+mark+this.value.slice(end);
    this.selectionStart = this.selectionEnd = start+mark.length;
  }
};
const f = new Function("$","Event", 'let pronunciationSelection={start:0,end:0};' +
 'let busy=false,pronunciationComposing=false,pronunciationStale=false,currentView="pronunciation";' +
 js.slice(a,b) + "return replaceAtCaret;");
const replace = f(()=>input, class Event{});
replace(input,{start:3,end:3},"",true);
if(input.value!=="A B") throw Error("Grapheme backspace failed");
replace(input,{start:1,end:2},"[",false);
if(input.value!=="A[B") throw Error("Selection replacement failed");
replace(input,{start:2,end:2}," ",false);
if(input.value!=="A[ B") throw Error("ASCII space failed");
console.log("DICTIONARY_ASSISTS_PASS");
"""
        result = subprocess.run([node, "-e", code, str(root / "app.js")],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DICTIONARY_ASSISTS_PASS", result.stdout)


    def test_approved_global_navigation_and_no_duplicate_dictionary_entry(self):
        html = (Path(__file__).resolve().parents[1] /
                "voiceger_editor" / "web_assets" / "index.html").read_text(encoding="utf-8")
        js = (Path(__file__).resolve().parents[1] /
              "voiceger_editor" / "web_assets" / "app.js").read_text(encoding="utf-8")
        # Global domains are visible in all authenticated screens, not
        # hidden in the Batch File menu or duplicated in Batch Item.
        self.assertIn('id="header-batch"', html)
        self.assertIn('id="header-dictionary"', html)
        self.assertIn('id="header-session"', html)
        batch_menu = html.split('id="batch-menu"', 1)[1].split("</div>", 1)[0]
        self.assertNotIn("辞書", batch_menu)
        self.assertNotIn('id="open-dictionary-list"', html)
        self.assertNotIn('id="open-dictionary-item"', html)
        self.assertIn('id="open-dictionary-quick"', html)
        self.assertIn('aria-label="Batchファイル"', html)
        self.assertNotIn("このCaptionの生成条件", html)
        self.assertIn('id="dictionary-pron-assists"', html)
        self.assertIn('dictionaryHistoryDestination', js)
        self.assertIn('navigateGlobal("dictionary")', js)

        node = shutil.which("node")
        if not node:
            self.skipTest("Node not installed")
        source = r"""
const fs = require("fs");
const js = fs.readFileSync(process.argv[1], "utf8");
const a = js.indexOf("  function navigateGlobal(destination) {");
const b = js.indexOf("  function openDictionaryEntry(row) {",a);
if (a < 0 || b <= a) throw Error("Production global navigation absent");
let currentView = "item", busy = false, sessionId = "s", dictEntry={id:"1"};
let dictEntryOriginal = {foo:1}, dictPronOpening = null, dictReturnView="item";
let dictionaryHistoryDepth = 0, dictionaryHistoryDestination=null;
let messages=[], allowed = true;
const browser = {history:{back(){messages.push("back")},go(n){messages.push("go:"+n)}}};
function showView(view) { currentView=view; messages.push("view:"+view); return true; }
function guardDraft() { return allowed; }
const f = new Function("window","showView","guardDraft","state", js.slice(a,b) +
 "return {navigateGlobal,dictionaryBack};");
const state = {};
// This creates a real evaluation of the code lifted unchanged from app.js.
// Globals in the production function are supplied through lexical declarations.
const factory = new Function("window","showView","guardDraft",
  'let currentView="item",busy=false,sessionId="s",dictEntry={id:"1"},' +
  'dictEntryOriginal={foo:1},dictPronOpening=null,dictReturnView="item";' +
  'let dictionaryHistoryDepth=0,dictionaryHistoryDestination=null;' +
  'const calls=[];' +
  'const fshow=showView;' +
  js.slice(a,b) +
  'return {navigateGlobal,dictionaryBack,setView(v){currentView=v},' +
  'setDepth(n){dictionaryHistoryDepth=n},setAllow:()=>{}};'
);
const nav = factory(browser,showView,guardDraft);
nav.navigateGlobal("dictionary");
if(messages.join("|")!=="view:dictionary") throw Error("Global dictionary direct navigation");
messages=[];
nav.setView("dictionary-pron");
nav.setDepth(3);
nav.navigateGlobal("list");
if(messages.join("|")!=="go:-3") throw Error("Nested navigation must unwind history");
messages=[];
nav.dictionaryBack();
if(messages.join("|")!=="back") throw Error("Dictionary Back must follow browser history");
console.log("GLOBAL_DICTIONARY_NAV_PASS");
"""
        result = subprocess.run(
            [node, "-e", source, str(Path(__file__).resolve().parents[1] /
                                      "voiceger_editor" / "web_assets" / "app.js")],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("GLOBAL_DICTIONARY_NAV_PASS", result.stdout)


    def test_apply_rejects_bad_draft_and_global_navigation_checks_parent_entry(self):
        root = Path(__file__).resolve().parents[1] / "voiceger_editor" / "web_assets"
        node = shutil.which("node")
        if not node:
            self.skipTest("Node not available")
        code = r"""
const fs = require("fs"), assert = require("node:assert/strict");
const js = fs.readFileSync(process.argv[1], "utf8");
function cut(start,end) {
  const a=js.indexOf(start), b=js.indexOf(end,a);
  assert(a>=0 && b>a,start);
  return js.slice(a,b);
}
let log=[], allow=false, shouldReject=true;
const window = {confirm(message){log.push(message);return allow;},
                history:{back(){log.push("back");}}};
const nodes = {
 "dictionary-pron-text": {value:"シ' コク"},
 "dictionary-surface": {value:"四国めたん"},
 "dictionary-word-type": {value:"PROPER_NOUN"},
 "dictionary-priority": {value:"5"},
 "dictionary-pron-value": {textContent:""}
};
const $ = name => nodes[name] ||= {};
const base = [
 'let currentView="dictionary-pron",dictPronOpening="シ\\'コク",',
 'dictEntry={notation:"シ\\'コク",id:"id"},',
 'dictEntryOriginal={surface:"元",notation:"シ\\'コク",word_type:"PROPER_NOUN",priority:5},',
 'busy=false,dictLanguage="ja",dictionaryHistoryDepth=0;',
 'function setBusy(v){busy=v;}', 'function showView(v){currentView=v;return true;}',
 'function feedback(m){log.push(m);}',
 'function dictionaryPath(){return "/api/test/dictionary";}',
 'async function request(method,path,payload){',
 '  log.push(path); if(shouldReject)throw Error("invalid_dictionary");',
 '  return {valid:true};',
 '}',
 cut('  function dictionaryPronunciationDirty() {','  function dictionaryTypeLabel(value) {'),
 cut('  function guardDraft() {','  function showView(name, bypassDraftGuard) {'),
 cut('  async function applyDictionaryPronunciation(event) {',
     '  function rememberDictionarySelection() {'),
 'return {applyDictionaryPronunciation,guardDraft,',
 'setReject(v){shouldReject=v;},setAllow(v){allow=v;},',
 'setText(v){$("dictionary-pron-text").value=v;},',
 'state(){return {currentView,notation:dictEntry.notation,busy}}};'
].join("\n");
const f = new Function("$","window","log","getReject",
 'let shouldReject=getReject();' + base);
const app = f($,window,log,()=>shouldReject);
(async()=>{
 const e={preventDefault(){}};
 await app.applyDictionaryPronunciation(e);
 assert.equal(app.state().currentView,"dictionary-pron");
 assert.equal(app.state().notation,"シ'コク");
 assert.equal(app.state().busy,false);
 assert(log.some(m=>m==="invalid_dictionary"));
 app.setText("シ'コク");
 // Pronunciation unchanged, but Surface differs from the parent opening.
 assert.equal(app.guardDraft(),false,"global navigation must guard parent draft");
 assert(log.some(m=>m.includes("未保存の単語変更")));
 console.log("DICTIONARY_APPLY_GUARD_PASS");
})().catch(e=>{console.error(e);process.exitCode=1});
"""
        result = subprocess.run([node, "-e", code, str(root / "app.js")],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DICTIONARY_APPLY_GUARD_PASS", result.stdout)

if __name__ == "__main__":
    unittest.main()
