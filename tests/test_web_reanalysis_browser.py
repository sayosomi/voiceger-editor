"""Exercise the real Web pronunciation reanalysis control with Node."""

from pathlib import Path
import shutil
import subprocess
import unittest


class WebReanalysisBrowserTests(unittest.TestCase):
    def test_compact_heading_reanalysis_confirm_and_cancel(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for browser interaction tests")
        assets = Path(__file__).resolve().parents[1] / "voiceger_editor" / "web_assets"
        script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const js = fs.readFileSync(process.argv[1], "utf8");
const html = fs.readFileSync(process.argv[2], "utf8");
const css = fs.readFileSync(process.argv[3], "utf8");
const start = js.indexOf('  $("reprepare-audio").addEventListener("click",');
const end = js.indexOf('  $("open-take-menu").addEventListener("click",', start);
assert(start >= 0 && end > start, "Production reanalysis handler missing");
const headingStart = html.indexOf('<section id="item-pronunciation"');
const headingEnd = html.indexOf('<div id="pronunciation-sections"', headingStart);
const menuStart = html.indexOf('<div id="take-menu"');
const menuEnd = html.indexOf('</div>', menuStart);
assert(headingStart >= 0 && headingEnd > headingStart && menuEnd > menuStart);
assert(html.slice(headingStart, headingEnd).includes('id="reprepare-audio"'),
       "Reanalysis must be visible beside pronunciation");
assert(html.slice(headingStart, headingEnd).includes('> 再解析</button>'));
assert(!html.slice(menuStart, menuEnd).includes('reprepare-audio'),
       "Reanalysis must not be inside the Takes menu");
assert.equal((html.match(/id="reprepare-audio"/g) || []).length, 1);
assert(/\.pronunciation-header-actions\s*\{[^}]*display:\s*flex/.test(css));
assert(js.includes('$("reprepare-audio").hidden = !item.is_prepared'));
assert(js.includes('setFixed("reprepare-audio", !prepared)'));
const events = {};
const $ = id => ({
  addEventListener(event, handler) { events[id + ":" + event] = handler; }
});
let confirmations = [], prompts = [], actions = [];
const window = {confirm(message) {
  prompts.push(message);
  return confirmations.shift();
}};
const startAudio = (...args) => actions.push(args);
const batch = {items: [{id: "item1", is_prepared: true}]};
const selectedId = "item1";
new Function("$", "window", "startAudio", "batch", "selectedId",
             js.slice(start, end))($, window, startAudio, batch, selectedId);
const click = events["reprepare-audio:click"];
assert.equal(typeof click, "function");
confirmations.push(false);
click();
assert.equal(actions.length, 0, "Cancel must not rebuild pronunciation");
assert(prompts[0].includes("現在のCaptionから発音を再解析しますか？"));
assert(prompts[0].includes("手動で調整した発音"));
assert(prompts[0].includes("Take候補・採用状態"));
assert(prompts[0].includes("保存済み音声は残ります"));
confirmations.push(true);
click();
assert.deepEqual(actions, [["item1", "/audio/prepare", {rebuild: true}]]);
batch.items[0].is_prepared = false;
click();
assert.equal(actions.length, 1, "Unprepared item must not invoke rebuild");
console.log("WEB_REANALYSIS_BROWSER_INTERACTION_PASS");
"""
        result = subprocess.run(
            [node, "-e", script, str(assets / "app.js"),
             str(assets / "index.html"), str(assets / "app.css")],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        self.assertIn("WEB_REANALYSIS_BROWSER_INTERACTION_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
