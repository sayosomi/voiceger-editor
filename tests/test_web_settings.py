"""Slice 10a: common and item-local Web settings regression coverage."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from voiceger_editor.settings import Settings
from voiceger_editor.styles import VoicegerStyle
from voiceger_editor.web import ASSETS, create_web_app
from voiceger_editor.web_sessions import WebSessionOperations


TOKEN = "web-settings-test-token-long-enough-for-authentication"
STYLES = (
    VoicegerStyle(3, "Neutral", "neutral.wav"),
    VoicegerStyle(1, "Sweet", "sweet.wav"),
)


class FakeSpeech:
    """A minimal UtteranceSession for Web state and retention checks."""

    def __init__(self, caption: str, settings: Settings):
        self.caption = caption
        self.settings = settings
        self.is_prepared = False
        self.candidates = []
        self.synthesis_source_text = None

    @property
    def style(self):
        return SimpleNamespace(name={3: "Neutral", 1: "Sweet"}[self.settings.style_id])

    @property
    def active_candidate_count(self):
        return len(self.candidates)

    def replace_caption(self, caption):
        self.caption = caption

    def replace_settings(self, settings, *, preserve_takes=False):
        old = self.settings
        changed = any(
            getattr(old, key) != getattr(settings, key)
            for key in ("style_id", "speed", "top_k", "top_p", "temperature")
        )
        if changed and not preserve_takes:
            self.discard_takes()
        self.settings = settings

    def discard_takes(self):
        self.candidates.clear()


class WebSynthesisSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Settings(output_dir=Path(self.temp.name))
        self.auth = patch.dict(os.environ, {"VOICEGER_WEB_TOKEN": TOKEN})
        self.auth.start()
        self.saved = patch("voiceger_editor.web_settings.save_settings")
        self.save_mock = self.saved.start()
        self.service = WebSessionOperations(
            caption_factory=lambda caption: FakeSpeech(caption, self.config)
        )
        self.service._batch_settings = self.config
        self.service._styles = lambda: STYLES
        self.client = TestClient(create_web_app(service=self.service))
        self.read_headers = {"Authorization": "Bearer " + TOKEN}
        self.write_headers = {
            **self.read_headers, "X-Voiceger-Web-Request": "1"
        }
        self.sid = self.client.post(
            "/api/web/sessions", headers=self.write_headers
        ).json()["id"]

    def tearDown(self):
        self.service.shutdown()
        self.client.close()
        self.saved.stop()
        self.auth.stop()
        self.temp.cleanup()

    @property
    def base(self):
        return "/api/web/sessions/" + self.sid

    def add(self, caption="こんにちは"):
        rev = self.batch()["revision"]
        response = self.client.post(
            self.base + "/batch/items?expected_revision=" + str(rev),
            headers=self.write_headers, json={"text": caption},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return self.service._sessions[self.sid].batch.items[-1]

    def batch(self):
        response = self.client.get(self.base + "/batch", headers=self.read_headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def settings(self):
        response = self.client.get(self.base + "/settings", headers=self.read_headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def item_voice(self, item, *, style_id=1, speed=1.25, revision=None):
        if revision is None:
            revision = self.batch()["revision"]
        return self.client.patch(
            self.base + "/batch/items/" + item.item_id +
            "/voice?expected_revision=" + str(revision),
            headers=self.write_headers,
            json={"style_id": style_id, "speed": speed},
        )

    def common(self, *, style_id=3, speed=1.0, top_k=20,
               top_p=1.0, temperature=1.0, confirmed=False,
               revision=None, settings_revision=None):
        data = self.settings()
        rev = data["revision"] if revision is None else revision
        shared_rev = (
            data["settings_revision"]
            if settings_revision is None else settings_revision
        )
        return self.client.patch(
            self.base + "/settings?expected_revision=" + str(rev) +
            "&expected_settings_revision=" + str(shared_rev),
            headers=self.write_headers,
            json={
                "style_id": style_id, "speed": speed, "top_k": top_k,
                "top_p": top_p, "temperature": temperature,
                "confirm_take_invalidation": confirmed,
            },
        )

    def test_approved_two_column_ui_contract(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        css = (ASSETS / "app.css").read_text(encoding="utf-8")
        self.assertIn('class="item-voice-grid"', html)
        self.assertIn('id="item-style"', html)
        self.assertIn('id="item-speed"', html)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", css)
        self.assertIn('id="edit-take-count"', html)
        self.assertNotIn("このCaptionの生成条件", html)
        self.assertIn('id="common-settings-form" class="setting-section" novalidate', html)
        self.assertIn('id="item-speed" type="number" inputmode="decimal" min="0" step="0.01"', html)
        self.assertIn('id="common-speed" type="number" inputmode="decimal" min="0" step="0.01"', html)
        self.assertIn('class="sampling-settings-group"', html)
        self.assertIn('class="settings-screen-heading"', html)
        self.assertIn('id="reset-settings">設定値を初期化</button>', html)
        self.assertNotIn('id="reset-sampling"', html)
        self.assertIn('id="common-settings-status"', html)
        self.assertIn('id="default-takes-status"', html)
        self.assertNotIn('id="reset-common-draft"', html)
        self.assertNotIn('<button type="submit">保存</button>\n        </form>\n        <div class="setting-section">\n          <h3>セッション', html)
        self.assertIn('border-top: 1px solid #cbdcd2', css)
        self.assertLess(html.index('id="common-speed"'),
                        html.index('class="sampling-settings-group"'))
        self.assertLess(html.index('class="sampling-settings-group"'),
                        html.index('id="common-top-k"'))

    def test_actual_browser_settings_draft_guards(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node required for browser guard verification")
        source = r"""
const fs=require("fs"),assert=require("assert").strict;
const js=fs.readFileSync(process.argv[1],"utf8");
const begin=js.indexOf("  function itemVoiceDirty(item) {");
const end=js.indexOf("  function guardDraft() {",begin);
assert(begin>=0 && end>begin,"settings guard source not found");
const nodes={
  "item-style":{value:"3"},
  "item-speed":{value:"1.00"},
  "common-style":{value:"3"},
  "common-speed":{value:"1.00"},
  "common-top-k":{value:"20"},
  "common-top-p":{value:"1.00"},
  "common-temperature":{value:"1.00"},
};
const data={values:{style_id:3,speed:1,top_k:20,top_p:1,temperature:1}};
const make=data=>new Function("$","commonSettingsData",
  js.slice(begin,end)+"return {itemVoiceDirty,commonDirty};"
)(id=>nodes[id],data);
const guards=make(data),item={style_id:3,speed:1};
assert.equal(guards.itemVoiceDirty(item),false);
assert.equal(guards.commonDirty(),false);
nodes["item-speed"].value="1.25";
assert.equal(guards.itemVoiceDirty(item),true);
nodes["item-speed"].value="1.00";
nodes["item-style"].value="1";
assert.equal(guards.itemVoiceDirty(item),true);
nodes["item-style"].value="3";
nodes["common-temperature"].value="0.85";
assert.equal(guards.commonDirty(),true);
nodes["common-temperature"].value="";
assert.equal(guards.commonDirty(),true);
nodes["common-temperature"].value="1.00";
assert.equal(make(null).commonDirty(),false);
assert.equal(make(null).itemVoiceDirty(item),false);
const speedStart=js.indexOf("  function validSpeed(raw) {");
const speedEnd=js.indexOf("  async function saveItemVoice() {",speedStart);
assert(speedStart>=0 && speedEnd>speedStart,"speed validation source not found");
const precision=new Function(js.slice(speedStart,speedEnd)+
  "return {validSpeed,validSampling};")();
assert.equal(precision.validSpeed("1.234567"),1.234567);
assert.equal(precision.validSampling({
  style_id:3,speed:1.234567,top_k:20,top_p:1,temperature:1
}).speed,1.234567);
console.log("WEB_SETTINGS_BROWSER_GUARDS_PASS");
"""
        result = subprocess.run(
            [node, "-e", source, str(ASSETS / "app.js")],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        self.assertIn("WEB_SETTINGS_BROWSER_GUARDS_PASS", result.stdout)

    def test_browser_auto_save_confirmation_and_reset(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node required for browser auto-save verification")
        source = r"""
const fs=require("fs"),assert=require("assert").strict;
const js=fs.readFileSync(process.argv[1],"utf8");
const start=js.indexOf("  function checkedCommonValues() {");
const end=js.indexOf('  $("refresh-batch").addEventListener(',start);
assert(start>=0 && end>start,"auto-save source not found");
const listeners={},nodes={},requests=[];
for(const id of ["common-settings-form","common-style","common-speed",
  "common-top-k","common-top-p","common-temperature","reset-settings",
  "common-settings-error","common-settings-status","default-takes",
  "default-takes-form","default-takes-error","default-takes-status"]){
  nodes[id]={value:"",hidden:true,textContent:"",
    addEventListener(type,callback){listeners[id+":"+type]=callback;}};
}
Object.assign(nodes["common-style"],{value:"3"});
Object.assign(nodes["common-speed"],{value:"1.00"});
Object.assign(nodes["common-top-k"],{value:"20"});
Object.assign(nodes["common-top-p"],{value:"1.00"});
Object.assign(nodes["common-temperature"],{value:"1.00"});
Object.assign(nodes["default-takes"],{value:"4"});
const runtime={
  data:{styles:[{id:3},{id:1}],settings_revision:0,
    values:{style_id:3,speed:1,top_k:20,top_p:1,temperature:1}},
  batch:{revision:0,default_take_count:4},
  confirm:false,shouldWarn:false,failSave:false,busy:false
};
const prefix=`
var busy=false,batch=runtime.batch,commonSettingsData=runtime.data,
  currentView="session",window={confirm:()=>runtime.confirm};
function setBusy(v){busy=v;runtime.busy=v;}
function commonValues(){return {
  style_id:Number($("common-style").value),
  speed:Number($("common-speed").value),
  top_k:Number($("common-top-k").value),
  top_p:Number($("common-top-p").value),
  temperature:Number($("common-temperature").value)
};}
function commonDirty(){const vals=commonValues();return Object.keys(vals).some(
  key=>vals[key]!==commonSettingsData.values[key]);}
function validSpeed(raw){const value=Number(raw);
  if(!raw.trim()||!Number.isFinite(value)||value<=0)throw Error("invalid speed");
  return value;}
function validSampling(values){if(!Number.isInteger(values.top_k)||
  values.top_k<1||values.top_k>100||
  !Number.isFinite(values.top_p)||values.top_p<0||values.top_p>1||
  !Number.isFinite(values.temperature)||values.temperature<0||
  values.temperature>1)throw Error("invalid sampling");return values;}
function validCount(raw){const n=Number(raw);
  if(raw===""||!Number.isInteger(n)||n<1||n>100)throw Error("invalid count");
  return n;}
function settingsPath(){return "/settings";}
function batchPath(){return "/batch";}
function renderList(){}
function refresh(){return Promise.resolve();}
function feedback(){}
function renderCommonSettings(result){
  Object.assign(commonSettingsData,result);
  for(const [key,value] of Object.entries(commonSettingsData.values))
    $(key==="style_id"?"common-style":"common-"+key.replace("_","-")).value=String(value);
  $("common-settings-error").hidden=true;
}
async function request(method,path,payload){
  requests.push({method,path,payload});
  if(runtime.failSave)throw Error("disk failure");
  if(runtime.shouldWarn&&!payload.confirm_take_invalidation){
    const error=Error("confirmation required");
    error.conflictCode="take_invalidation_confirmation_required";
    throw error;
  }
  if(path.startsWith("/batch")){
    const next={revision:batch.revision+1,default_take_count:payload.count};
    Object.assign(runtime.batch,next);return next;
  }
  if(path.endsWith("/reset?expected_revision="+runtime.batch.revision+
    "&expected_settings_revision="+runtime.data.settings_revision)){
    const next={...commonSettingsData,
      settings_revision:commonSettingsData.settings_revision+1,
      values:{style_id:3,speed:1,top_k:20,top_p:1,temperature:1}};
    Object.assign(runtime.data,next);
    runtime.batch.revision++;
    runtime.batch.default_take_count=4;
    return {settings:next,batch:runtime.batch};
  }
  const next={...commonSettingsData,settings_revision:commonSettingsData.settings_revision+1,
    values:{style_id:payload.style_id,speed:payload.speed,top_k:payload.top_k,
    top_p:payload.top_p,temperature:payload.temperature}};
  Object.assign(runtime.data,next);
  runtime.batch.revision++;
  return next;
}
`;
const make=new Function("$","runtime","requests","listeners",
  prefix+js.slice(start,end)+"return {autoSaveCommon,autoSaveDefaultTakes};");
const controls=make(id=>nodes[id],runtime,requests,listeners);
(async()=>{
  nodes["common-speed"].value="1.23";
  await controls.autoSaveCommon();
  assert.equal(requests.length,1);
  assert.equal(requests[0].payload.speed,1.23);
  assert.equal(nodes["common-settings-status"].textContent,"保存済み");
  runtime.shouldWarn=true;runtime.confirm=false;
  nodes["common-top-k"].value="21";
  await controls.autoSaveCommon();
  assert.equal(requests.length,2);
  assert.equal(runtime.data.values.top_k,20,"cancel does not apply");
  assert.equal(nodes["common-top-k"].value,"20","cancel restores field");
  runtime.confirm=true;
  nodes["common-top-k"].value="22";
  await controls.autoSaveCommon();
  assert.equal(requests.length,4);
  assert.equal(requests[3].payload.confirm_take_invalidation,true);
  assert.equal(runtime.data.values.top_k,22);
  runtime.shouldWarn=false;
  nodes["common-top-p"].value="0.5";
  runtime.failSave=true;
  await controls.autoSaveCommon();
  assert.equal(runtime.data.values.top_p,1);
  assert.equal(nodes["common-top-p"].value,"0.5","failed save retains input");
  assert.equal(nodes["common-settings-status"].textContent,"保存失敗");
  runtime.failSave=false;
  nodes["default-takes"].value="5";
  await controls.autoSaveDefaultTakes();
  assert.equal(requests.at(-1).payload.count,5);
  assert.equal(nodes["default-takes-status"].textContent,"保存済み");
  runtime.shouldWarn=false;
  runtime.confirm=false;
  const beforeReset=requests.length;
  listeners["reset-settings:click"]();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(requests.length,beforeReset,"cancel must not request reset");
  runtime.confirm=true;
  listeners["reset-settings:click"]();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(requests.length,beforeReset+1);
  assert.equal(requests.at(-1).method,"POST");
  assert.equal(requests.at(-1).payload.confirm_take_invalidation,true);
  assert.equal(runtime.data.values.top_k,20);
  assert.equal(runtime.data.values.top_p,1);
  assert.equal(runtime.data.values.temperature,1);
  assert.equal(runtime.data.values.speed,1);
  assert.equal(runtime.batch.default_take_count,4);
  assert.equal(nodes["default-takes"].value,"4");
  console.log("WEB_SETTINGS_AUTOSAVE_PASS");
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result = subprocess.run(
            [node, "-e", source, str(ASSETS / "app.js")],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        self.assertIn("WEB_SETTINGS_AUTOSAVE_PASS", result.stdout)

    def reset(self, *, confirmed=False, revision=None, settings_revision=None):
        data = self.settings()
        return self.client.post(
            self.base + "/settings/reset?expected_revision=" +
            str(data["revision"] if revision is None else revision) +
            "&expected_settings_revision=" +
            str(data["settings_revision"] if settings_revision is None
                else settings_revision),
            headers=self.write_headers,
            json={"confirm_take_invalidation": confirmed},
        )

    def test_reset_generation_defaults_preserves_user_output_and_item_voice(self):
        custom = Settings(
            output_dir=Path(self.temp.name) / "my-output",
            filename_template="{YYYYMMDDHHmm}_{caption}",
            output_format="mp3", save_text=True, save_lab=True,
            style_id=1, speed=1.4, top_k=31, top_p=0.8,
            temperature=0.6, take_count=7,
        )
        self.config = custom
        self.service._batch_settings = custom
        item = self.add()
        item.take_count_override = 9
        saved_output = custom.output_dir / "accepted.wav"
        saved_output.parent.mkdir(parents=True)
        saved_output.write_bytes(b"accepted-audio-placeholder")
        self.assertEqual(self.service.set_default_take_count(
            self.sid, self.batch()["revision"], 7
        )["default_take_count"], 7)
        item.session.candidates.append(
            SimpleNamespace(number=1, frame_count=16000,
                            sampling_rate=16000, style_name="Sweet")
        )
        item.mark_accepted(1)
        before = self.settings()
        unconfirmed = self.reset()
        self.assertEqual(unconfirmed.status_code, 409, unconfirmed.text)
        self.assertEqual(unconfirmed.json()["detail"]["code"],
                         "take_invalidation_confirmation_required")
        self.assertEqual(self.batch()["default_take_count"], 7)
        self.assertEqual(self.settings()["settings_revision"],
                         before["settings_revision"])
        self.save_mock.assert_not_called()

        result = self.reset(confirmed=True)
        self.assertEqual(result.status_code, 200, result.text)
        payload = result.json()
        self.assertEqual(payload["settings"]["values"], {
            "style_id": 3, "speed": 1.0, "top_k": 20,
            "top_p": 1.0, "temperature": 1.0,
        })
        self.assertEqual(payload["batch"]["default_take_count"], 4)
        self.assertEqual(self.batch()["default_take_count"], 4)
        self.assertEqual(item.session.settings.style_id, 1)
        self.assertEqual(item.session.settings.speed, 1.4)
        self.assertEqual(item.take_count_override, 9)
        self.assertEqual(saved_output.read_bytes(), b"accepted-audio-placeholder")
        self.assertEqual(item.session.candidates, [])
        self.assertEqual(item.accepted_take_numbers, frozenset())
        current = self.service._batch_settings
        self.assertEqual(current.output_dir, custom.output_dir)
        self.assertEqual(current.filename_template, custom.filename_template)
        self.assertEqual(current.output_format, "mp3")
        self.assertTrue(current.save_text)
        self.assertTrue(current.save_lab)
        self.assertEqual(self.save_mock.call_count, 1)

    def test_reset_rolls_back_on_save_failure(self):
        self.service._batch_settings = Settings(
            output_dir=Path(self.temp.name), speed=1.35,
        )
        self.assertEqual(self.service.set_default_take_count(
            self.sid, self.batch()["revision"], 7
        )["default_take_count"], 7)
        self.save_mock.side_effect = PermissionError("private Mac path")
        before = self.settings()
        response = self.reset(confirmed=True)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(self.batch()["default_take_count"], 7)
        self.assertEqual(self.settings()["settings_revision"],
                         before["settings_revision"])
        self.assertEqual(self.service._batch_settings.speed, 1.35)
        self.assertNotIn("private Mac path", response.text)

    def test_reset_take_count_only_does_not_modify_shared_settings(self):
        self.assertEqual(self.service.set_default_take_count(
            self.sid, self.batch()["revision"], 8
        )["default_take_count"], 8)
        before = self.settings()
        response = self.reset(confirmed=True)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["batch"]["default_take_count"], 4)
        self.assertEqual(self.settings()["settings_revision"],
                         before["settings_revision"])
        self.save_mock.assert_not_called()

    def test_reset_stale_revision_and_missing_csrf_are_rejected(self):
        previous = self.settings()
        self.assertEqual(self.common(speed=1.2).status_code, 200)
        stale = self.reset(
            revision=self.batch()["revision"],
            settings_revision=previous["settings_revision"],
            confirmed=True,
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["detail"]["code"], "settings_revision_conflict")
        unauthorized = self.client.post(
            self.base + "/settings/reset?expected_revision=" +
            str(self.batch()["revision"]) + "&expected_settings_revision=" +
            str(self.settings()["settings_revision"]),
            headers=self.read_headers,
            json={"confirm_take_invalidation": True},
        )
        self.assertEqual(unauthorized.status_code, 403)
        wrong_type = self.client.post(
            self.base + "/settings/reset?expected_revision=" +
            str(self.batch()["revision"]) + "&expected_settings_revision=" +
            str(self.settings()["settings_revision"]),
            headers=self.write_headers,
            json={"confirm_take_invalidation": "yes"},
        )
        self.assertEqual(wrong_type.status_code, 422)

    def test_authenticated_values_and_style_catalog(self):
        data = self.settings()
        self.assertEqual(data["values"]["style_id"], 3)
        self.assertEqual([x["name"] for x in data["styles"]], ["Neutral", "Sweet"])
        self.assertNotIn("output_dir", str(data))
        self.assertEqual(
            self.client.get(self.base + "/settings").status_code, 401
        )

    def test_item_voice_keeps_accepted_takes_and_siblings(self):
        item = self.add()
        sibling = self.add("ふたつめ")
        item.session.candidates.append(
            SimpleNamespace(number=1, frame_count=16000, sampling_rate=16000,
                            style_name="Neutral")
        )
        item.mark_accepted(1)
        previous_revision = self.batch()["revision"]
        response = self.item_voice(item)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["revision"], previous_revision + 1)
        self.assertEqual(len(item.session.candidates), 1)
        self.assertEqual(item.accepted_take_numbers, frozenset({1}))
        self.assertEqual(sibling.session.settings.style_id, 3)
        self.assertEqual(item.session.settings.speed, 1.25)
        second = self.item_voice(item)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["revision"], previous_revision + 1)

    def test_item_voice_validation_and_revision_conflict(self):
        item = self.add()
        revision = self.batch()["revision"]
        self.assertEqual(
            self.item_voice(item, speed=-1, revision=revision).status_code, 422
        )
        self.assertEqual(
            self.item_voice(item, style_id=999, revision=revision).status_code, 422
        )
        self.assertEqual(
            self.item_voice(item, revision=revision - 1).status_code, 409
        )
        self.assertEqual(item.session.settings, self.config)

    def test_common_noop_preserves_high_precision_values(self):
        precise = Settings(
            output_dir=Path(self.temp.name),
            speed=1.2345, top_p=0.125, temperature=0.98765,
        )
        self.service._batch_settings = precise
        previous = self.settings()
        result = self.common(
            speed=1.2345, top_p=0.125, temperature=0.98765,
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["settings_revision"],
                         previous["settings_revision"])
        self.save_mock.assert_not_called()
        self.assertEqual(self.service._batch_settings, precise)

    def test_common_sampling_clears_candidates_and_keeps_local_style(self):
        item = self.add()
        other = self.add("ふたつめ")
        self.assertEqual(self.item_voice(item).status_code, 200)
        for entry in (item, other):
            entry.session.candidates.append(
                SimpleNamespace(number=1, frame_count=16000,
                                sampling_rate=16000, style_name="Neutral")
            )
            entry.mark_accepted(1)
        refused = self.common(top_k=30)
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertEqual(
            refused.json()["detail"]["code"], "take_invalidation_confirmation_required"
        )
        self.assertEqual(len(item.session.candidates), 1)
        self.save_mock.assert_not_called()
        result = self.common(top_k=30, confirmed=True)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(item.session.settings.style_id, 1)
        self.assertEqual(item.session.settings.speed, 1.25)
        self.assertEqual(other.session.settings.style_id, 3)
        self.assertEqual(item.session.settings.top_k, 30)
        for entry in (item, other):
            self.assertEqual(entry.session.candidates, [])
            self.assertEqual(entry.accepted_take_numbers, frozenset())
        self.assertEqual(self.save_mock.call_count, 1)
        self.assertEqual(self.common(style_id=1, top_k=30).status_code, 200)
        self.assertEqual(other.session.settings.style_id, 1)

    def test_confirmation_covers_other_web_sessions(self):
        other_sid = self.client.post(
            "/api/web/sessions", headers=self.write_headers
        ).json()["id"]
        self.service.add_captions(other_sid, 0, "別セッション")
        other = self.service._sessions[other_sid].batch.items[0]
        other.session.candidates.append(
            SimpleNamespace(number=1, frame_count=16000,
                            sampling_rate=16000, style_name="Neutral")
        )
        revision = self.settings()["settings_revision"]
        response = self.common(top_p=0.8)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(len(other.session.candidates), 1)
        self.assertEqual(self.settings()["settings_revision"], revision)
        self.save_mock.assert_not_called()
        confirmed = self.common(top_p=0.8, confirmed=True)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(other.session.candidates, [])

    def test_nonboolean_confirmation_is_rejected(self):
        response = self.client.patch(
            self.base + "/settings?expected_revision=" +
            str(self.batch()["revision"]) + "&expected_settings_revision=0",
            headers=self.write_headers,
            json={"style_id": 3, "speed": 1, "top_k": 20,
                  "top_p": 1, "temperature": 1,
                  "confirm_take_invalidation": "yes"},
        )
        self.assertEqual(response.status_code, 422)
        self.save_mock.assert_not_called()

    def test_failed_save_and_busy_worker_do_not_mutate(self):
        item = self.add()
        item.session.candidates.append(
            SimpleNamespace(number=1, frame_count=16000,
                            sampling_rate=16000, style_name="Neutral")
        )
        self.save_mock.side_effect = PermissionError("private Mac path")
        response = self.common(top_k=30, confirmed=True)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("private Mac path", response.text)
        self.assertEqual(self.service._batch_settings.top_k, 20)
        self.assertEqual(len(item.session.candidates), 1)
        self.save_mock.side_effect = None
        self.service._active = (self.sid, "operation")
        try:
            self.assertEqual(self.common(top_k=30).status_code, 409)
            self.assertEqual(self.item_voice(item).status_code, 409)
        finally:
            self.service._active = None

    def test_independent_settings_revision_and_csrf(self):
        old = self.settings()
        self.assertEqual(self.common(top_k=25).status_code, 200)
        stale = self.common(
            top_k=30, revision=self.batch()["revision"],
            settings_revision=old["settings_revision"],
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["detail"]["code"], "settings_revision_conflict")
        unauthorized = self.client.patch(
            self.base + "/settings?expected_revision=" +
            str(self.batch()["revision"]) + "&expected_settings_revision=1",
            headers=self.read_headers,
            json={"style_id": 3, "speed": 1, "top_k": 20,
                  "top_p": 1, "temperature": 1},
        )
        self.assertEqual(unauthorized.status_code, 403)


if __name__ == "__main__":
    unittest.main()
