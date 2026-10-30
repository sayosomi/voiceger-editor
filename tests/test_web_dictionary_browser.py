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


if __name__ == "__main__":
    unittest.main()
