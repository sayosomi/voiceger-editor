"use strict";
const fs = require("fs");
const assert = require("node:assert/strict");
const source = fs.readFileSync(process.argv[2], "utf8");
const first = source.indexOf("  function renderDictionaryImportReview() {");
const last = source.indexOf("  async function updateDictionaryImportSelection(", first);
assert(first >= 0 && last > first, "Missing production import renderer");

class Node {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.listeners = {};
    this.attrs = {};
    this._text = "";
    this.open = false;
  }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map(x => x.textContent).join(""); }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = [...items]; this._text = ""; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener(k, f) { (this.listeners[k] ??= []).push(f); }
  emit(k) { for (const f of this.listeners[k] || []) f(); }
}
const document = {createElement: tag => new Node(tag)};
const nodes = new Map();
function $(id) {
  if (!nodes.has(id)) nodes.set(id, new Node("div"));
  return nodes.get(id);
}
const program = source.slice(first, last) + [
  'let busy=false, dictionaryImportReview=data;',
  'const dictionaryImportExpanded=new Set();',
  'let selection=null, typed=null;',
  'function setFixed(id, disabled) { $(id).disabled=disabled; }',
  'function dictionaryTypeLabel(v) { return v; }',
  'function updateDictionaryImportSelection(language,identity,checked) {',
  '  selection={language,identity,checked}; }',
  'function updateDictionaryImportWordType(identity,wordType) {',
  '  typed={identity,wordType}; }',
  'return {render:renderDictionaryImportReview,',
  '  getSelection:()=>selection, getWordType:()=>typed};'
].join("\n");
const app = new Function("document", "$", "data", program)(document, $, {
  filename: "sample.zip", new: 1, conflicts: 2, exact: 3, selected: 1,
  items: [
    {language: "ja", identity: "new-id", surface: "太陽", relation: "new",
      selected: true, pronunciation: "タイヨー", existing_pronunciation: null,
      word_type: "COMMON_NOUN", existing_word_type: null,
      priority: 5, existing_priority: null},
    {language: "ja", identity: "conflict-id", surface: "雨", relation: "conflict",
      selected: false, pronunciation: "アメ", existing_pronunciation: "ア'メ",
      word_type: "COMMON_NOUN", existing_word_type: "COMMON_NOUN",
      priority: 3, existing_priority: 5},
    {language: "en", identity: "sweet", surface: "sweet", relation: "conflict",
      selected: false, pronunciation: "S W EH1 T",
      existing_pronunciation: "S W IY1 T",
      word_type: null, existing_word_type: null,
      priority: null, existing_priority: null}
  ]
});
function parts(li) {
  const row = li.children[0];
  return {check:row.children[0], detail:row.children[1],
    summary:row.children[1].children[0], status:row.children[2]};
}
app.render();
assert.equal($("dictionary-import-summary").textContent, "新規 1件 · 変更 2件 · 一致 3件");
assert.equal($("dictionary-import-commit").textContent, "選択した1件を取り込む");
assert.equal($("dictionary-import-commit").disabled, false);
const entries = $("dictionary-import-entries").children;
assert.equal(entries.length, 3);
const fresh=parts(entries[0]), changed=parts(entries[1]), english=parts(entries[2]);
assert.equal(fresh.check.checked, true);
assert.equal(fresh.summary.textContent, "太陽タイヨー");
assert.equal(fresh.status.textContent, "新規");
assert.equal(changed.check.checked, false);
assert.equal(changed.summary.textContent, "雨ア'メ→アメ");
assert.equal(changed.status.textContent, "変更");
assert.equal(changed.status.tagName, "span");
changed.status.emit("click");
assert.equal(changed.detail.open, false, "Status is not an interactive trigger");
assert.equal(changed.detail.tagName, "details");
assert.equal(changed.detail.open, false);
assert.equal(english.summary.textContent, "sweetS W IY1 T→S W EH1 T");
assert.equal(english.status.textContent, "変更");
assert.equal(english.detail.tagName, "div");

changed.check.checked = true;
changed.check.emit("change");
assert.deepEqual(app.getSelection(), {
  language:"ja", identity:"conflict-id", checked:true
});
assert.equal(changed.detail.open, false);
assert.equal(changed.summary.listeners.change, undefined);
changed.detail.open=true;
changed.detail.emit("toggle");
app.render();
const expanded = parts($("dictionary-import-entries").children[1]);
assert.equal(expanded.detail.open, true);
const extra=expanded.detail.children[1];
assert.equal(extra.children[0]._text, "品詞");
assert.equal(extra.children[1].textContent, "優先度：5 → 3");
const picker=extra.children[0].children[0];
picker.value="PROPER_NOUN";
picker.emit("change");
assert.deepEqual(app.getWordType(), {identity:"conflict-id",wordType:"PROPER_NOUN"});
assert(!source.includes('summary.textContent = "発音・品詞を比較";'));
console.log("DICT_IMPORT_REVIEW_PASS");
