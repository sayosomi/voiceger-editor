"use strict";

// Bearer credential lives in memory only. Only an opaque session ID is kept in
// tab-scoped storage; server memory is authoritative for all Batch state.
(function () {
  var token = "";
  var sessionId = "";
  var batch = null;
  var selectedId = "";
  var pending = false;
  var SESSION_KEY = "voiceger-web-session-id";
  var $ = function (id) { return document.getElementById(id); };

  function message(value) { $("batch-message").textContent = value; }
  function authMessage(value) { $("auth-status").textContent = value; }
  function savedSession() {
    try { return window.sessionStorage.getItem(SESSION_KEY) || ""; }
    catch (_ignored) { return ""; }
  }
  function remember(id) {
    try {
      if (id) window.sessionStorage.setItem(SESSION_KEY, id);
      else window.sessionStorage.removeItem(SESSION_KEY);
    } catch (_ignored) { /* Session storage may be disabled. */ }
  }
  function setPending(value) {
    pending = value;
    var container = $("batch-panel");
    container.querySelectorAll("button, input, textarea, select").forEach(function (control) {
      control.disabled = value;
    });
    $("session-controls").querySelectorAll("button").forEach(function (button) {
      button.disabled = value;
    });
    $("connect-button").disabled = value;
  }
  async function request(method, path, payload) {
    var headers = { Authorization: "Bearer " + token };
    if (method !== "GET") headers["X-Voiceger-Web-Request"] = "1";
    if (payload !== undefined) headers["Content-Type"] = "application/json";
    var response = await fetch(path, {
      method: method, headers: headers, cache: "no-store", credentials: "same-origin",
      body: payload === undefined ? undefined : JSON.stringify(payload)
    });
    if (!response.ok) {
      var error = new Error(
        response.status === 401 ? "認証できません。トークンを確認してください。" :
        response.status === 503 ? "Mac側のWebアクセストークンまたはサーバー設定を確認してください。" :
        response.status === 409 ? "別の画面で変更されています。一覧を更新してください。" :
        response.status === 404 ? "セッションが見つかりません。再接続してください。" :
        response.status === 422 ? "入力内容を確認してください。" : "操作を完了できませんでした。"
      );
      error.code = response.status;
      throw error;
    }
    return response.status === 204 ? null : response.json();
  }
  function batchPath() {
    return "/api/web/sessions/" + encodeURIComponent(sessionId) + "/batch";
  }
  function control(label, action, disabled, className) {
    var button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.disabled = !!disabled;
    if (className) button.className = className;
    button.addEventListener("click", action);
    return button;
  }
  function validCount(value) {
    var number = Number(value);
    if (!Number.isInteger(number) || number < 1 || number > 100) {
      throw new Error("Take数は1〜100で指定してください。");
    }
    return number;
  }
  function render() {
    if (!batch) return;
    $("batch-count").textContent = batch.items.length + " Captions";
    $("empty-message").hidden = batch.items.length !== 0;
    $("default-takes").value = String(batch.default_take_count);
    var list = $("caption-list");
    list.replaceChildren();
    batch.items.forEach(function (item, index) {
      var li = document.createElement("li");
      li.className = "caption-card";
      var row = document.createElement("div");
      row.className = "caption-card-heading";
      var heading = document.createElement("span");
      heading.className = "caption-number";
      heading.textContent = String(index + 1).padStart(2, "0");
      var caption = document.createElement("span");
      caption.className = "caption-text";
      caption.textContent = item.caption;
      row.append(heading, caption);
      li.append(row);
      var meta = document.createElement("p");
      meta.className = "caption-meta";
      meta.textContent = (item.included ? "生成対象" : "生成対象外") +
        " · Take " + item.effective_take_count;
      li.append(meta);
      var actions = document.createElement("div");
      actions.className = "caption-actions";
      actions.append(
        control("編集", function () { selectedId = item.id; renderItem(); }, pending),
        control(item.included ? "対象から外す" : "対象にする", function () {
          mutate("PATCH", "/items/" + encodeURIComponent(item.id) + "/included",
            { included: !item.included }, "生成対象を更新しました。");
        }, pending),
        control("↑", function () {
          mutate("PATCH", "/items/" + encodeURIComponent(item.id) + "/position",
            { index: index - 1 }, "順序を変更しました。");
        }, pending || index === 0),
        control("↓", function () {
          mutate("PATCH", "/items/" + encodeURIComponent(item.id) + "/position",
            { index: index + 1 }, "順序を変更しました。");
        }, pending || index === batch.items.length - 1),
        control("削除", function () {
          if (!window.confirm("このCaptionを削除しますか？")) return;
          mutate("DELETE", "/items/" + encodeURIComponent(item.id), undefined,
            "Captionを削除しました。");
        }, pending, "danger-button")
      );
      li.append(actions);
      list.append(li);
    });
    renderItem();
  }
  function renderItem() {
    var item = batch && batch.items.find(function (entry) { return entry.id === selectedId; });
    $("item-panel").hidden = !item;
    if (!item) { selectedId = ""; return; }
    $("edit-caption").value = item.caption;
    $("item-takes-mode").value = item.take_count_override === null ? "default" : "custom";
    $("item-takes").value = String(
      item.take_count_override === null ? batch.default_take_count : item.take_count_override
    );
    $("item-takes").hidden = item.take_count_override === null;
  }
  async function refresh() {
    batch = await request("GET", batchPath());
    render();
  }
  async function mutate(method, suffix, payload, success) {
    if (!batch || pending) return;
    setPending(true);
    try {
      var path = batchPath() + suffix + "?expected_revision=" + encodeURIComponent(batch.revision);
      batch = await request(method, path, payload);
      render();
      message(success);
      return true;
    } catch (error) {
      message(error.message);
      if (error.code === 409) {
        try { await refresh(); } catch (_ignored) { /* Show original conflict. */ }
      }
      if (error.code === 404) disconnect();
      return false;
    } finally { setPending(false); }
  }
  function disconnect() {
    token = "";
    sessionId = "";
    batch = null;
    selectedId = "";
    remember("");
    $("web-token").value = "";
    $("batch-panel").hidden = true;
    $("session-controls").hidden = true;
    authMessage("未接続");
    message("");
  }
  $("auth-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    if (pending) return;
    var candidate = $("web-token").value;
    if (candidate.length < 32) { authMessage("32文字以上のトークンが必要です。"); return; }
    token = candidate;
    $("web-token").value = "";
    setPending(true);
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
        var session = await request("POST", "/api/web/sessions");
        sessionId = session.id;
        remember(sessionId);
        await refresh();
      }
      $("batch-panel").hidden = false;
      $("session-controls").hidden = false;
      authMessage("接続済み · このブラウザのセッション");
      message("Captionの編集を開始できます。");
    } catch (error) {
      token = "";
      batch = null;
      sessionId = "";
      $("batch-panel").hidden = true;
      $("session-controls").hidden = true;
      authMessage(error.message);
    } finally { setPending(false); }
  });
  $("add-form").addEventListener("submit", function (event) {
    event.preventDefault();
    var value = $("new-captions").value;
    if (!value.trim()) { message("Captionを入力してください。"); return; }
    mutate("POST", "/items", { text: value }, "Captionを追加しました。")
      .then(function (ok) { if (ok) $("new-captions").value = ""; });
  });
  $("default-takes-form").addEventListener("submit", function (event) {
    event.preventDefault();
    try {
      mutate("PATCH", "/default-take-count",
        { count: validCount($("default-takes").value) }, "標準Take数を変更しました。");
    } catch (error) { message(error.message); }
  });
  $("edit-caption-form").addEventListener("submit", function (event) {
    event.preventDefault();
    if (!selectedId) return;
    mutate("PATCH", "/items/" + encodeURIComponent(selectedId) + "/caption",
      { caption: $("edit-caption").value }, "Captionを保存しました。");
  });
  $("item-takes-mode").addEventListener("change", function () {
    $("item-takes").hidden = this.value !== "custom";
  });
  $("item-takes-form").addEventListener("submit", function (event) {
    event.preventDefault();
    if (!selectedId) return;
    try {
      var count = $("item-takes-mode").value === "default" ?
        null : validCount($("item-takes").value);
      mutate("PATCH", "/items/" + encodeURIComponent(selectedId) + "/take-count",
        { count: count }, "Take数を変更しました。");
    } catch (error) { message(error.message); }
  });
  $("back-to-list").addEventListener("click", function () {
    selectedId = "";
    renderItem();
  });
  $("refresh-batch").addEventListener("click", async function () {
    if (pending) return;
    setPending(true);
    try { await refresh(); message("一覧を更新しました。"); }
    catch (error) {
      message(error.message);
      if (error.code === 404) disconnect();
    } finally { setPending(false); }
  });
  $("disconnect-session").addEventListener("click", disconnect);
  $("close-session").addEventListener("click", async function () {
    if (pending || !window.confirm("このセッションと未保存のCaptionを終了しますか？")) return;
    setPending(true);
    try {
      await request("DELETE", "/api/web/sessions/" + encodeURIComponent(sessionId));
      disconnect();
    } catch (error) { message(error.message); }
    finally { setPending(false); }
  });

  fetch("/api/web/health", { method: "GET", cache: "no-store" })
    .then(function (response) {
      if (!response.ok) throw new Error("Health check failed");
      return response.json();
    })
    .then(function (data) {
      if (!data || data.status !== "ok" || typeof data.version !== "string")
        throw new Error("Invalid health response");
      $("connection-status").textContent = "Webサーバーに接続済み";
      $("server-version").textContent = "Voiceger Editor " + data.version;
      document.querySelector(".connection-indicator").classList.add("is-online");
    })
    .catch(function () {
      $("connection-status").textContent = "接続状態を確認できません";
      $("server-version").textContent = "ページを再読み込みしてください";
    });
})();
