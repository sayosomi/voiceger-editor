"""Exercise actual JS insertion/Backspace code and HTML assist markup."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


class JapaneseAssistTests(unittest.TestCase):
    def test_dom_and_caret_actions(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node required for browser editor interaction checks")
        root = Path(__file__).resolve().parents[1] / "voiceger_editor" / "web_assets"
        source = r"""
const fs = require("fs");
const js = fs.readFileSync(process.argv[1], "utf8");
const html = fs.readFileSync(process.argv[2], "utf8");
for (const id of ["view-pronunciation", "pronunciation-text",
                  "preview-pronunciation", "apply-pronunciation", "pronunciation-back",
                  "reset-pronunciation", "cancel-pronunciation"]) {
  if (!html.includes('id="' + id + '"')) throw new Error("Missing " + id);
}
const assist = html.match(/<div class="pronunciation-assists"[\s\S]*?<\/div>/)[0];
const codes = [...assist.matchAll(/data-pronunciation-insert="([^"]+)"/g)].map(x=>x[1]);
if (JSON.stringify(codes) !== JSON.stringify(["'", "[", "]", " "]) ||
    !assist.includes("data-pronunciation-backspace") ||
    !assist.includes("⌫") || assist.includes("trash")) throw new Error("Five assists wrong");
const a = js.indexOf("  function rememberPronunciationSelection() {");
const b = js.indexOf("  function openPronunciation() {", a);
if (a < 0 || b <= a) throw new Error("Actual caret functions missing");
const input = {
  value:"アメ", selectionStart:1, selectionEnd:1,
  focus(){}, dispatchEvent(){},
  setRangeText(mark,start,end){
    this.value=this.value.slice(0,start)+mark+this.value.slice(end);
    this.selectionStart=this.selectionEnd=start+mark.length;
  }
};
const create = new Function("$","Event", 'let busy=false,pronunciationComposing=false,' +
 'pronunciationStale=false,currentView="pronunciation";' +
 'let pronunciationSelection={start:0,end:0};' +
 js.slice(a,b) + 'return {rememberPronunciationSelection,editPronunciationAtCaret};');
const functions = create(()=>input, class Event{});
function act(mark,del=false){functions.rememberPronunciationSelection();functions.editPronunciationAtCaret(mark,del);}
act("'");
if (input.value!=="ア'メ" || input.selectionStart!==2) throw new Error("Insert caret");
input.selectionStart=0;input.selectionEnd=2;act("[");
if (input.value!=="[メ" || input.selectionStart!==1) throw new Error("Replace selected");
act("",true);
if (input.value!=="メ" || input.selectionStart!==0) throw new Error("Backspace before cursor");
input.value="キョ🙂";input.selectionStart=input.selectionEnd=input.value.length;
act("",true);
if (input.value!=="キョ") throw new Error("Backspace grapheme");
input.value="アメ";input.selectionStart=input.selectionEnd=1;
act(" ");
if (input.value!=="ア メ" || input.selectionStart!==2) throw new Error("Space");
console.log("JAPANESE_ASSISTS_PASS");
"""
        result = subprocess.run(
            [node, "-e", source, str(root / "app.js"), str(root / "index.html")],
            capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("JAPANESE_ASSISTS_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
