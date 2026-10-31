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


    def test_dictionary_word_type_select_matches_form_fields(self):
        root = Path(__file__).resolve().parents[1] / "voiceger_editor" / "web_assets"
        html = (root / "index.html").read_text(encoding="utf-8")
        css = (root / "app.css").read_text(encoding="utf-8")
        self.assertRegex(html, r'id="dictionary-ja-fields" class="field-stack"')
        self.assertRegex(html, r'<select id="dictionary-word-type">')
        # All standard form select elements must share field height, font,
        # full width, border and radius with adjacent text/number inputs.
        match = re.search(r'\.field-stack input,\s*\.field-stack select,'
                          r'\s*\.field-stack textarea,.*?\}', css, re.S)
        self.assertIsNotNone(match)
        style = match.group()
        for required in ("width: 100%", "min-height: 48px",
                         "font: inherit", "font-size: 15px",
                         "border: 1px solid #cbdcd2", "border-radius: 12px"):
            self.assertIn(required, style)


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
  "guardDictionaryPronunciationDraft",
  'let currentView="item",busy=false,sessionId="s",dictEntry={id:"1"},' +
  'dictEntryOriginal={foo:1},dictPronOpening=null,dictReturnView="item";' +
  'let dictionaryHistoryDepth=0,dictionaryHistoryDestination=null;' +
  'const calls=[];' +
  'const fshow=showView;' +
  js.slice(a,b) +
  'return {navigateGlobal,dictionaryBack,setView(v){currentView=v},' +
  'setDepth(n){dictionaryHistoryDepth=n},setAllow:()=>{}};'
);
const nav = factory(browser,showView,guardDraft,guardDraft);
nav.navigateGlobal("dictionary");
if(messages.join("|")!=="view:dictionary") throw Error("Global dictionary direct navigation");
messages=[];
nav.setView("dictionary-pron");
nav.setDepth(3);
nav.navigateGlobal("list");
if(messages.join("|")!=="go:-3") throw Error("Nested navigation must unwind history");
messages=[];
nav.dictionaryBack();
if(messages.length) throw Error("Pending global navigation must suppress duplicate Back");
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
 "dictionary-pron-text": {value:"シ' コク", setAttribute(k,v){this[k]=v;}, removeAttribute(k){delete this[k];}},
 "dictionary-surface": {value:"四国めたん"},
 "dictionary-word-type": {value:"PROPER_NOUN"},
 "dictionary-priority": {value:"5"},
 "dictionary-pron-value": {textContent:""},
 "dictionary-pron-error": {hidden:true,textContent:"",scrollIntoView(o){log.push("scroll:"+o.block);},focus(){log.push("focus:error");}}
};
const $ = name => nodes[name] ||= {};
const base = [
 `let currentView="dictionary-pron",dictPronOpening="シ'コク",`,
 `dictEntry={notation:"シ'コク",id:"id"},`,
 `dictEntryOriginal={surface:"元",notation:"シ'コク",word_type:"PROPER_NOUN",priority:5},`,
 'busy=false,dictLanguage="ja",dictionaryHistoryDepth=0;',
 'function setBusy(v){busy=v;}', 'function showView(v){currentView=v;return true;}',
 'function feedback(m){log.push(m);}',
 'function dictionaryPath(){return "/api/test/dictionary";}',
 'async function request(method,path,payload){',
 '  log.push(path); if(shouldReject)throw Object.assign(new Error("invalid_dictionary"),{conflictCode:"invalid_dictionary"});',
 '  return {valid:true};',
 '}',
 cut('  function dictionaryPronunciationDirty() {','  function dictionaryTypeLabel(value) {'),
 cut('  function guardDraft() {','  function showView(name, bypassDraftGuard) {'),
 cut('  function clearDictionaryPronunciationError() {',
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
 assert.equal(nodes["dictionary-pron-error"].hidden,false);
 assert(nodes["dictionary-pron-error"].textContent.includes("空白を削除"));
 assert(log.includes("scroll:center"));
 assert(log.includes("focus:error"));
 assert.equal(nodes["dictionary-pron-text"]["aria-invalid"],"true");
 app.setText("シ'コク");
 // Pronunciation unchanged, but Surface differs from the parent opening.
 assert.equal(app.guardDraft(),false,"global navigation must guard parent draft");
 assert(log.some(m=>m.includes("未保存の辞書変更")));
 console.log("DICTIONARY_APPLY_GUARD_PASS");
})().catch(e=>{console.error(e);process.exitCode=1});
"""
        result = subprocess.run([node, "-e", code, str(root / "app.js")],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DICTIONARY_APPLY_GUARD_PASS", result.stdout)


    def test_blocking_findings_f01_to_f04_against_production_js(self):
        root = Path(__file__).resolve().parents[1]
        node = shutil.which("node")
        if not node:
            self.skipTest("Node not installed")
        result = subprocess.run([
            node, str(root / "tests" / "fixtures" /
                      "web_dictionary_blocking_regressions.js"),
            str(root / "voiceger_editor" / "web_assets" / "app.js")
        ], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for marker in ("F01_UNLOAD_PASS", "F02_HISTORY_PASS",
                       "F03_PRIORITY_PASS", "F04_CASEFOLD_PASS"):
            self.assertIn(marker, result.stdout)



    def test_quick_dictionary_partial_word_isolated_draft(self):
        root = Path(__file__).resolve().parents[1]
        assets = root / "voiceger_editor" / "web_assets"
        html = (assets / "index.html").read_text(encoding="utf-8")
        css = (assets / "app.css").read_text(encoding="utf-8")
        form = html.split('id="dictionary-quick-form"', 1)[1].split("</form>", 1)[0]
        self.assertLess(form.index('id="dictionary-quick-surface"'),
                        form.index('id="dictionary-quick-generate"'))
        self.assertLess(form.index('id="dictionary-quick-generate"'),
                        form.index('id="dictionary-quick-notation"'))
        self.assertLess(form.index('id="dictionary-quick-error"'),
                        form.index('type="submit"'))
        self.assertIn('id="dictionary-quick-preview"', form)
        self.assertNotIn('spellcheck="false" required', form)
        self.assertIn('role="alert" tabindex="-1" hidden', form)
        self.assertIn('#dictionary-quick-notation', css)
        node = shutil.which("node")
        if not node:
            self.skipTest("Node not installed")
        result = subprocess.run([
            node, str(root / "tests" / "fixtures" /
                      "web_dictionary_quick_partial.js"), str(assets / "app.js")
        ], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DICTIONARY_QUICK_PARTIAL_PASS", result.stdout)

    def test_quick_dictionary_cancel_uses_existing_secondary_button_style(self):
        root = Path(__file__).resolve().parents[1] / "voiceger_editor" / "web_assets"
        html = (root / "index.html").read_text(encoding="utf-8")
        css = (root / "app.css").read_text(encoding="utf-8")
        self.assertRegex(html, r'<button type="button" id="dictionary-quick-cancel">キャンセル</button>')
        # Both secondary controls share the exact same border, radius, colors,
        # height and padding instead of exposing Chrome's default grey button.
        rule = re.search(
            r'\.pronunciation-actions-secondary button,\s*#dictionary-quick-cancel\s*\{([^}]+)\}',
            css, re.S)
        self.assertIsNotNone(rule)
        for expected in ("min-height: 44px", "padding: 10px 13px",
                         "border: 1px solid #d0ded4", "border-radius: 10px",
                         "background: #fff", "color: #285e4f"):
            self.assertIn(expected, rule.group(1))

    def test_new_word_language_toggle_preserves_existing_word_and_drafts(self):
        root = Path(__file__).resolve().parents[1]
        assets = root / "voiceger_editor" / "web_assets"
        html = (assets / "index.html").read_text(encoding="utf-8")
        css = (assets / "app.css").read_text(encoding="utf-8")
        self.assertIn('id="dictionary-entry-tabs"', html)
        self.assertIn('id="dictionary-entry-ja"', html)
        self.assertIn('id="dictionary-entry-en"', html)
        self.assertIn('.dictionary-tabs[hidden] { display: none; }', css)
        node = shutil.which("node")
        if not node:
            self.skipTest("Node not installed")
        result = subprocess.run([
            node, str(root / "tests" / "fixtures" /
                      "web_dictionary_entry_language.js"), str(assets / "app.js")
        ], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DICTIONARY_ENTRY_LANGUAGE_PASS", result.stdout)




    def test_dictionary_history_single_flight_delayed_popstate(self):
        root = Path(__file__).resolve().parents[1]
        node = shutil.which("node")
        if not node:
            self.skipTest("Node not available")
        result = subprocess.run([
            node, str(root / "tests" / "fixtures" /
                      "web_dictionary_history_single_flight.js"),
            str(root / "voiceger_editor" / "web_assets" / "app.js")
        ], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DICT_HISTORY_SINGLE_FLIGHT_PASS", result.stdout)

    def test_pronunciation_cancel_does_not_double_back(self):
        root = Path(__file__).resolve().parents[1]
        node = shutil.which("node")
        if not node:
            self.skipTest("Node not installed")
        result = subprocess.run([
            node, str(root / "tests" / "fixtures" /
                      "web_pronunciation_cancel_history.js"),
            str(root / "voiceger_editor" / "web_assets" / "app.js")
        ], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PRON_CANCEL_DOUBLE_BACK_PASS", result.stdout)

    def test_dictionary_pronunciation_errors_at_apply_and_preview(self):
        root = Path(__file__).resolve().parents[1]
        assets = root / "voiceger_editor" / "web_assets"
        html = (assets / "index.html").read_text(encoding="utf-8")
        css = (assets / "app.css").read_text(encoding="utf-8")
        js = (assets / "app.js").read_text(encoding="utf-8")
        form = html.split('id="dictionary-pron-form"', 1)[1].split("</form>", 1)[0]
        self.assertLess(form.index('id="dictionary-pron-text"'),
                        form.index('id="dictionary-pron-error"'))
        self.assertLess(form.index('id="dictionary-pron-error"'),
                        form.index('id="dictionary-preview"'))
        self.assertIn('class="dictionary-pron-error" role="alert" tabindex="-1" hidden', form)
        self.assertIn("border-left: 4px solid #b93c30", css)
        self.assertIn('addEventListener("input", clearDictionaryPronunciationError)', js)
        self.assertIn('showDictionaryPronunciationError(error, notation, "Preview")', js)
        node = shutil.which("node")
        if not node:
            self.skipTest("Node not installed")
        result = subprocess.run([
            node, str(root / "tests" / "fixtures" /
                      "web_dictionary_pronunciation_errors.js"), str(assets / "app.js"),
        ], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DICTIONARY_PRON_ERROR_PASS", result.stdout)

    def test_dictionary_generate_position_and_duplicate_guidance(self):
        root = Path(__file__).resolve().parents[1]
        assets = root / "voiceger_editor" / "web_assets"
        html = (assets / "index.html").read_text(encoding="utf-8")
        css = (assets / "app.css").read_text(encoding="utf-8")
        form = html.split('id="dictionary-entry-form"', 1)[1].split('</form>', 1)[0]
        self.assertLess(form.index('id="dictionary-surface"'),
                        form.index('id="dictionary-generate"'))
        self.assertLess(form.index('id="dictionary-generate"'),
                        form.index('id="dictionary-pron-value"'))
        self.assertEqual(form.count('id="dictionary-generate"'), 1)
        for key in ("dictionary-duplicate", "dictionary-duplicate-title",
                    "dictionary-duplicate-description", "dictionary-duplicate-view"):
            self.assertIn('id="' + key + '"', form)
        self.assertIn('.dictionary-duplicate[hidden] { display: none; }', css)
        self.assertLess(form.index('id="dictionary-duplicate"'),
                        form.index('type="submit"'))
        self.assertIn('id="dictionary-save-error"', form)
        self.assertLess(form.index('id="dictionary-save-error"'),
                        form.index('type="submit"'))
        self.assertIn('role="alert" tabindex="-1"', form)
        self.assertIn('.dictionary-save-error { margin: 0;', css)
        node = shutil.which("node")
        if not node:
            self.skipTest("Node not installed")
        result = subprocess.run([
            node, str(root / "tests" / "fixtures" /
                      "web_dictionary_duplicate_ui.js"), str(assets / "app.js"),
        ], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DICTIONARY_DUPLICATE_UI_PASS", result.stdout)

if __name__ == "__main__":
    unittest.main()
