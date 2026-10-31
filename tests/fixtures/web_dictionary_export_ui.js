"use strict";
// Execute the exact production Dictionary export handlers, not a second mock implementation.
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");
const source = fs.readFileSync(process.argv[2], "utf8");
const start = source.indexOf("  function dictionaryExportNotice(");
const end = source.indexOf("  function dictionaryPronunciationDirty()", start);
assert(start !== -1 && end > start, "production export handler was not found");
const production = source.slice(start, end);

async function scenario(kind, count, confirmed, fails, view = "dictionary-management") {
  const calls = [];
  const notice = {
    hidden: true, textContent: "", dataset: {},
    scrolled: false, focused: false,
    scrollIntoView() { this.scrolled = true; },
    focus() { this.focused = true; },
  };
  const state = {
    busy: false, currentView: view, sessionId: "session",
    dictLanguage: "ja", dictSort: "surface_asc", dictQuery: "",
    dictType: "ALL", dictData: null, encodeURIComponent,
    $: (id) => {
      assert.strictEqual(id, "dictionary-export-message");
      return notice;
    },
    dictionaryPath: () => "/api/web/sessions/session/dictionary",
    setBusy(value) { state.busy = value; },
    window: {
      confirm(message) {
        calls.push({action: "confirm", message});
        return confirmed;
      },
    },
    async request(method, path, payload) {
      calls.push({action: "request", method, path, payload});
      if (fails && path.endsWith("/export/commit")) {
        const e = new Error("safe error");
        e.conflictCode = "export_io";
        throw e;
      }
      if (method === "GET") return {revision: "a".repeat(64)};
      if (path.endsWith("/export/review")) {
        return {token: "single-use-review-token", lossy_pitch_count: count};
      }
      if (path.endsWith("/export/commit")) {
        return {filename: kind === "native" ? "archive.zip" : "japanese.json"};
      }
      if (path.endsWith("/export/cancel")) return {cancelled: true};
      throw new Error("unexpected path: " + path);
    },
  };
  vm.createContext(state);
  vm.runInContext(production, state);
  await state.exportDictionary(kind);
  assert.strictEqual(state.busy, false);
  return {calls, notice};
}

(async () => {
  const wrongScreen = await scenario("native", 0, false, false, "dictionary");
  assert.strictEqual(wrongScreen.calls.length, 0,
    "Export must be available only from the management screen");
  const native = await scenario("native", 0, false, false);
  assert(native.calls.some(x => x.action === "request" &&
    x.path.endsWith("/export/commit") && x.payload.confirmed_pitch_loss === false));
  assert(!native.calls.some(x => x.action === "confirm"));
  assert(native.notice.textContent.includes("archive.zip"));
  assert(native.notice.scrolled);
  const rejected = await scenario("voicevox", 2, false, false);
  assert(rejected.calls.some(x => x.action === "confirm" &&
    x.message.includes("2件")));
  assert(rejected.calls.some(x => x.action === "request" &&
    x.path.endsWith("/export/cancel")));
  assert(!rejected.calls.some(x => x.action === "request" &&
    x.path.endsWith("/export/commit")));
  assert(rejected.notice.textContent.includes("中止"));
  const accepted = await scenario("voicevox", 2, true, false);
  assert(accepted.calls.some(x => x.action === "request" &&
    x.path.endsWith("/export/commit") && x.payload.confirmed_pitch_loss === true));
  assert(accepted.notice.textContent.includes("japanese.json"));
  const failed = await scenario("native", 0, false, true);
  assert(failed.calls.some(x => x.action === "request" &&
    x.path.endsWith("/export/cancel")));
  assert(failed.notice.focused && failed.notice.dataset.error === "true");
  assert(failed.notice.textContent.includes("Outputフォルダ"));
  process.stdout.write("node_export_ui_pass\n");
})().catch(error => { process.stderr.write(String(error.stack || error)); process.exitCode = 1; });
