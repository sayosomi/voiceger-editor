"""Browser playback Preview control state contract against real served HTML."""

from pathlib import Path
import shutil
import subprocess
import unittest


class PreviewDomStateTests(unittest.TestCase):
    def test_preview_button_visible_aria_and_disabled_states(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node required for browser-like DOM behavior")
        assets = Path(__file__).resolve().parents[1] / "voiceger_editor" / "web_assets"
        script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const html = fs.readFileSync(process.argv[2], "utf8");
const match = html.match(/<button\b[^>]*\bid="preview-audio"[^>]*>([^<]*)<\/button>/);
if (!match) throw new Error("Preview button markup missing");
const button = {
  id:"preview-audio", tagName:"BUTTON",
  textContent:match[1], disabled:false, dataset:{fixedDisabled:"false"}, attrs:{},
  setAttribute(name,value){this.attrs[name]=value;},
  getAttribute(name){return this.attrs[name]||null;}
};
const player = {paused:true,ended:false,duration:10,currentTime:0};
const nodes = {
  "phone-player":player, "preview-audio":button,
  "take-list":{querySelectorAll(){return [];}}
};
const busyStart = source.indexOf("  function setBusy(value) {");
const busyEnd = source.indexOf("  function guardDraft()", busyStart);
const renderStart = source.indexOf("  function updatePlaybackUI() {");
const renderEnd = source.indexOf("  async function beginPlayback(", renderStart);
if (Math.min(busyStart,busyEnd,renderStart,renderEnd)<0)
  throw new Error("Actual browser source functions missing");
const setBusy = new Function("document",
  "let busy=false;" + source.slice(busyStart,busyEnd) + ";return setBusy;")({
    querySelectorAll(){return [button];}
  });
function check(phase, visible, accessible, disabled) {
  player.paused = phase !== "playing";
  const playback = phase === null ? null : {
    itemId:"item", kind:"preview", phase,
    started:phase === "paused"
  };
  // Derive disabled from the production phase, not a test-supplied expected value.
  setBusy(false);
  const render = new Function("$","playback","selectedId","currentView",
    source.slice(renderStart,renderEnd) + ";return updatePlaybackUI;")(
      key=>nodes[key], playback, "item", "item");
  render();
  if (button.textContent !== visible ||
      button.getAttribute("aria-label") !== accessible ||
      button.disabled !== disabled)
    throw new Error("Preview DOM state mismatch: " + JSON.stringify({
      phase, text:button.textContent,
      aria:button.getAttribute("aria-label"), disabled:button.disabled
    }));
}
check(null,"▶ Preview","Previewを生成して再生",false);
check("loading","Preview取得中","Preview音声を取得中",true);
check("starting","Preview再生待ち","Previewの再生開始待ち",true);
check("ready","▶ Preview再生","Previewを再生",false);
check("playing","⏸ Preview再生中","Previewを一時停止",false);
check("paused","▶ Preview再開","Previewを再開",false);
check("failed","▶ Preview再試行","Previewを再取得して再生",false);
console.log("PREVIEW_DOM_STATE_PASS");
"""
        result = subprocess.run(
            [node, "-e", script, str(assets / "app.js"), str(assets / "index.html")],
            capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PREVIEW_DOM_STATE_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
