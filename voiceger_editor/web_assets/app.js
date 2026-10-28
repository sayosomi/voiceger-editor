"use strict";

// The Web server is the sole Batch state owner. Only the session ID is
// tab-scoped; the bearer token stays in memory and disappears on reload.
(function () {
  var token = "";
  var sessionId = "";
  var batch = null;
  var selectedId = "";
  var currentView = "connect";
  var busy = false;
  var SESSION_KEY = "voiceger-web-session-id";
  var $ = function (id) { return document.getElementById(id); };
  var viewNames = ["connect", "list", "add", "item", "session"];
  var screenTitles = {
    connect: "接続", list: "Batch List", add: "Caption追加",
    item: "Batch Item", session: "接続・設定"
  };

  function savedSession() {
    try { return window.sessionStorage.getItem(SESSION_KEY) || ""; }
    catch (_ignored) { return ""; }
  }
  function remember(id) {
    try {
      if (id) window.sessionStorage.setItem(SESSION_KEY, id);
      else window.sessionStorage.removeItem(SESSION_KEY);
    } catch (_ignored) { /* Storage may be unavailable. */ }
  }
  function feedback(text) {
    $("feedback").textContent = text;
    $("feedback").hidden = !text;
  }
  function setBusy(value) {
    busy = value;
    document.querySelectorAll("button, input, textarea, select").forEach(function (control) {
      control.disabled = value || control.dataset.fixedDisabled === "true";
    });
  }
  function guardDraft() {
    if (currentView === "add" && $("new-captions").value.trim()) {
      return window.confirm("入力中のCaptionを破棄して戻りますか？");
    }
    if (currentView === "item" && selectedId && batch) {
      var item = batch.items.find(function (entry) { return entry.id === selectedId; });
      if (item && $("edit-caption").value !== item.caption) {
        return window.confirm("未保存のCaption変更を破棄して移動しますか？");
      }
    }
    return true;
  }
  function showView(name, bypassDraftGuard) {
    if ((busy && !bypassDraftGuard) || viewNames.indexOf(name) === -1) return false;
    if (!bypassDraftGuard && name !== currentView && !guardDraft()) return false;
    currentView = name;
    viewNames.forEach(function (viewName) {
      $("view-" + viewName).hidden = viewName !== name;
    });
    $("screen-name").textContent = screenTitles[name];
    $("header-session").hidden = !sessionId || name === "connect" || name === "session";
    feedback("");
    if (name === "item") renderItem(false);
    if (name === "session" && batch) $("default-takes").value = String(batch.default_take_count);
    window.scrollTo(0, 0);
    var title = $("view-" + name).querySelector("h2");
    if (title) title.focus({ preventScroll: true });
    return true;
  }
  async function request(method, path, payload) {
    var headers = { Authorization: "Bearer " + token };
    if (method !== "GET") headers["X-Voiceger-Web-Request"] = "1";
    if (payload !== undefined) headers["Content-Type"] = "application/json";
    var response = await fetch(path, {
      method: method, headers: headers, cache: "no-store",
      credentials: "same-origin",
      body: payload === undefined ? undefined : JSON.stringify(payload)
    });
    if (!response.ok) {
      var error = new Error(
        response.status === 401 ? "認証できません。トークンを確認してください。" :
        response.status === 503 ? "Mac側の接続設定を確認してください。" :
        response.status === 409 ? "別の画面で変更されています。最新の一覧を取得しました。" :
        response.status === 404 ? "セッションが見つかりません。再接続してください。" :
        response.status === 422 ? "入力内容を確認してください。" :
        "操作を完了できませんでした。"
      );
      error.code = response.status;
      throw error;
    }
    return response.status === 204 ? null : response.json();
  }
  function batchPath() {
    return "/api/web/sessions/" + encodeURIComponent(sessionId) + "/batch";
  }
  function validCount(value) {
    var number = Number(value);
    if (value === "" || !Number.isInteger(number) || number < 1 || number > 100) {
      throw new Error("Take数は1〜100で指定してください。");
    }
    return number;
  }
  function renderList() {
    if (!batch) return;
    $("batch-count").textContent = batch.items.length + " Captions";
    $("empty-state").hidden = batch.items.length !== 0;
    var list = $("caption-list");
    list.replaceChildren();
    batch.items.forEach(function (item, index) {
      var li = document.createElement("li");
      li.className = "caption-card" + (item.included ? "" : " is-excluded");
      var button = document.createElement("button");
      button.type = "button";
      button.className = "caption-open";
      button.disabled = busy;
      button.setAttribute("aria-label", (index + 1) + "番目のCaptionを編集: " + item.caption);
      var number = document.createElement("span");
      number.className = "caption-index";
      number.textContent = String(index + 1).padStart(2, "0");
      var content = document.createElement("span");
      content.className = "caption-content";
      var caption = document.createElement("span");
      caption.className = "caption-text";
      caption.textContent = item.caption;
      var meta = document.createElement("span");
      meta.className = "caption-meta";
      meta.textContent = (item.included ? "生成対象" : "対象外") +
        " · Take " + item.effective_take_count;
      content.append(caption, meta);
      var chevron = document.createElement("span");
      chevron.className = "caption-chevron";
      chevron.setAttribute("aria-hidden", "true");
      chevron.textContent = "›";
      button.append(number, content, chevron);
      button.addEventListener("click", function () { openItem(item.id); });
      li.append(button);
      list.append(li);
    });
  }
  function renderItem(keepCaptionDraft) {
    if (!batch || !selectedId) return;
    var index = batch.items.findIndex(function (entry) { return entry.id === selectedId; });
    if (index < 0) {
      selectedId = "";
      if (currentView === "item") showView("list", true);
      return;
    }
    var item = batch.items[index];
    $("item-title").textContent = "Caption " + String(index + 1).padStart(2, "0");
    $("item-position").textContent = (index + 1) + " / " + batch.items.length;
    if (!keepCaptionDraft) $("edit-caption").value = item.caption;
    $("item-included").checked = item.included;
    $("item-takes-mode").value = item.take_count_override === null ? "default" : "custom";
    $("item-takes").value = String(item.take_count_override === null ?
      batch.default_take_count : item.take_count_override);
    $("item-takes").hidden = item.take_count_override === null;
    setFixed("move-up", index === 0);
    setFixed("move-down", index === batch.items.length - 1);
    setFixed("previous-item", index === 0);
    setFixed("next-item", index === batch.items.length - 1);
  }
  function setFixed(id, disabled) {
    var control = $(id);
    control.dataset.fixedDisabled = disabled ? "true" : "false";
    control.disabled = busy || disabled;
  }
  function openItem(id) {
    if (busy || !batch) return;
    if (!guardDraft()) return;
    selectedId = id;
    renderItem(false);
    showView("item", true);
  }
  function resetLocal(clearSessionId) {
    token = "";
    sessionId = "";
    batch = null;
    selectedId = "";
    $("web-token").value = "";
    $("new-captions").value = "";
    $("auth-status").textContent = "未接続";
    if (clearSessionId) remember("");
    showView("connect", true);
  }
  async function refresh() {
    batch = await request("GET", batchPath());
    renderList();
    if (currentView === "item") renderItem(true);
  }
  async function mutate(method, suffix, payload, success, options) {
    if (busy || !batch) return false;
    setBusy(true);
    try {
      var path = batchPath() + suffix + "?expected_revision=" +
        encodeURIComponent(batch.revision);
      batch = await request(method, path, payload);
      renderList();
      if (selectedId) renderItem(!options || !options.saveCaption);
      feedback(success);
      return true;
    } catch (error) {
      if (error.code === 409) {
        try { await refresh(); } catch (_ignored) { /* Keep conflict feedback. */ }
      }
      if (error.code === 404 || error.code === 401) resetLocal(error.code === 404);
      feedback(error.message);
      return false;
    } finally { setBusy(false); }
  }

  $("auth-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    if (busy) return;
    var candidate = $("web-token").value;
    if (candidate.length < 32) {
      $("auth-status").textContent = "32文字以上のトークンが必要です。";
      return;
    }
    token = candidate;
    $("web-token").value = "";
    setBusy(true);
    try {
      var existing = savedSession();
      if (existing) {
        sessionId = existing;
        try { await refresh(); }
        catch (error) {
          if (error.code !== 404) throw error;
          sessionId = "";
          remember("");
        }
      }
      if (!sessionId) {
        var created = await request("POST", "/api/web/sessions");
        sessionId = created.id;
        remember(sessionId);
        await refresh();
      }
      $("auth-status").textContent = "接続済み";
    } catch (error) {
      token = "";
      sessionId = "";
      batch = null;
      $("auth-status").textContent = error.message;
      return;
    } finally {
      setBusy(false);
    }
    showView("list", true);
  });
  $("open-add").addEventListener("click", function () { showView("add"); });
  $("add-back").addEventListener("click", function () { showView("list"); });
  $("item-back").addEventListener("click", function () { showView("list"); });
  $("session-back").addEventListener("click", function () { showView("list"); });
  $("header-session").addEventListener("click", function () { showView("session"); });
  $("add-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    if (!$("new-captions").value.trim()) { feedback("Captionを入力してください。"); return; }
    var ok = await mutate("POST", "/items", { text: $("new-captions").value }, "Captionを追加しました。");
    if (ok) {
      $("new-captions").value = "";
      showView("list", true);
      feedback("Captionを追加しました。");
    }
  });
  $("edit-caption-form").addEventListener("submit", function (event) {
    event.preventDefault();
    if (!selectedId) return;
    mutate("PATCH", "/items/" + encodeURIComponent(selectedId) + "/caption",
      { caption: $("edit-caption").value }, "Captionを保存しました。", { saveCaption: true });
  });
  $("item-included").addEventListener("change", function () {
    if (!selectedId) return;
    mutate("PATCH", "/items/" + encodeURIComponent(selectedId) + "/included",
      { included: this.checked }, "生成対象を更新しました。");
  });
  $("item-takes-mode").addEventListener("change", function () {
    $("item-takes").hidden = this.value !== "custom";
  });
  $("item-takes-form").addEventListener("submit", function (event) {
    event.preventDefault();
    if (!selectedId) return;
    try {
      var count = $("item-takes-mode").value === "default" ? null :
        validCount($("item-takes").value);
      mutate("PATCH", "/items/" + encodeURIComponent(selectedId) + "/take-count",
        { count: count }, "Take数を更新しました。");
    } catch (error) { feedback(error.message); }
  });
  function move(delta) {
    if (!batch || !selectedId) return;
    var position = batch.items.findIndex(function (item) { return item.id === selectedId; });
    if (position < 0 || position + delta < 0 || position + delta >= batch.items.length) return;
    mutate("PATCH", "/items/" + encodeURIComponent(selectedId) + "/position",
      { index: position + delta }, "順序を変更しました。");
  }
  $("move-up").addEventListener("click", function () { move(-1); });
  $("move-down").addEventListener("click", function () { move(1); });
  function adjacent(delta) {
    if (!batch || !selectedId || busy) return;
    var position = batch.items.findIndex(function (item) { return item.id === selectedId; });
    if (position < 0 || position + delta < 0 || position + delta >= batch.items.length) return;
    openItem(batch.items[position + delta].id);
  }
  $("previous-item").addEventListener("click", function () { adjacent(-1); });
  $("next-item").addEventListener("click", function () { adjacent(1); });
  $("delete-item").addEventListener("click", async function () {
    if (!selectedId || !window.confirm("このCaptionを削除しますか？")) return;
    var id = selectedId;
    var ok = await mutate("DELETE", "/items/" + encodeURIComponent(id), undefined,
      "Captionを削除しました。");
    if (ok) {
      selectedId = "";
      showView("list", true);
      feedback("Captionを削除しました。");
    }
  });
  $("default-takes-form").addEventListener("submit", function (event) {
    event.preventDefault();
    try {
      mutate("PATCH", "/default-take-count",
        { count: validCount($("default-takes").value) }, "標準Take数を更新しました。");
    } catch (error) { feedback(error.message); }
  });
  $("refresh-batch").addEventListener("click", async function () {
    if (busy) return;
    setBusy(true);
    try {
      await refresh();
      feedback("Batchを更新しました。");
    } catch (error) {
      if (error.code === 404 || error.code === 401) resetLocal(error.code === 404);
      feedback(error.message);
    } finally { setBusy(false); }
  });
  $("disconnect-session").addEventListener("click", function () {
    if (busy) return;
    resetLocal(true);
  });
  $("close-session").addEventListener("click", async function () {
    if (busy || !window.confirm("セッションと未保存のCaptionをすべて破棄しますか？")) return;
    setBusy(true);
    try {
      await request("DELETE", "/api/web/sessions/" + encodeURIComponent(sessionId));
      resetLocal(true);
    } catch (error) { feedback(error.message); }
    finally { setBusy(false); }
  });

  fetch("/api/web/health", { method: "GET", cache: "no-store" })
    .then(function (response) {
      if (!response.ok) throw new Error("Health check failed");
      return response.json();
    })
    .then(function (data) {
      if (!data || data.status !== "ok" || typeof data.version !== "string") {
        throw new Error("Invalid health response");
      }
      $("connection-status").textContent = "Webサーバーに接続済み";
      $("server-version").textContent = "Voiceger Editor " + data.version;
    })
    .catch(function () {
      $("connection-status").textContent = "接続状態を確認できません";
      $("server-version").textContent = "ページを再読み込みしてください";
    });
})();
