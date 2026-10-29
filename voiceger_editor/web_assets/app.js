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
  var reorderMode = false;
  var deleteMode = false;
  var selectedForDelete = new Set();
  var dragState = null;
  var audioOperation = null;
  var playingUrl = "";
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
    if (name !== "list" && reorderMode) endReorderMode();
    if (name !== "list" && deleteMode) endDeleteMode();
    if (currentView === "item" && name !== "item") clearPlayer();
    currentView = name;
    viewNames.forEach(function (viewName) {
      $("view-" + viewName).hidden = viewName !== name;
    });

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
  // Reordering happens in the list, never inside Batch Item. The server's
  // existing versioned move endpoint remains the authoritative owner.
  function clearDropMarker() {
    $("caption-list").querySelectorAll(".drop-before, .drop-after").forEach(function (node) {
      node.classList.remove("drop-before", "drop-after");
    });
  }
  function cleanupDrag() {
    if (!dragState) return;
    var state = dragState;
    dragState = null;
    clearDropMarker();
    state.row.classList.remove("drag-source");
    if (state.ghost.parentNode) state.ghost.remove();
    try {
      if (state.handle.hasPointerCapture(state.pointerId)) {
        state.handle.releasePointerCapture(state.pointerId);
      }
    } catch (_ignored) { /* Pointer capture may already be gone. */ }
  }
  function cancelDrag(event) {
    if (!dragState || (event && event.pointerId !== dragState.pointerId)) return;
    cleanupDrag();
  }
  function endReorderMode() {
    cancelDrag();
    reorderMode = false;
    if (batch) renderList();
  }
  async function moveToIndex(itemId, index) {
    if (!reorderMode || !batch || busy || dragState) return;
    var from = batch.items.findIndex(function (item) { return item.id === itemId; });
    if (from < 0 || index < 0 || index >= batch.items.length || index === from) return;
    var ok = await mutate(
      "PATCH", "/items/" + encodeURIComponent(itemId) + "/position",
      { index: index }, "Captionの順序を変更しました。"
    );
    if (ok && reorderMode) {
      var row = Array.from($("caption-list").children).find(function (node) {
        return node.dataset.itemId === itemId;
      });
      if (row) row.querySelector(".reorder-handle").focus();
    }
  }
  function moveByKeyboard(event, itemId, index) {
    var destination = index;
    if (event.key === "ArrowUp") destination--;
    else if (event.key === "ArrowDown") destination++;
    else if (event.key === "Home") destination = 0;
    else if (event.key === "End" && batch) destination = batch.items.length - 1;
    else return;
    event.preventDefault();
    moveToIndex(itemId, destination);
  }
  function positionGhost(event) {
    if (!dragState) return;
    var width = Math.min(280, Math.max(160, window.innerWidth - 48));
    dragState.ghost.style.width = width + "px";
    dragState.ghost.style.left = Math.max(8, Math.min(window.innerWidth - width - 8,
      event.clientX - width / 2)) + "px";
    dragState.ghost.style.top = Math.max(8, Math.min(window.innerHeight - 60,
      event.clientY - 28)) + "px";
  }
  function beginDrag(event, item, index) {
    if (!reorderMode || busy || dragState || !event.isPrimary ||
        (event.pointerType === "mouse" && event.button !== 0)) return;
    event.preventDefault();
    var handle = event.currentTarget;
    var row = handle.closest(".caption-card");
    if (!row) return;
    var ghost = document.createElement("div");
    ghost.className = "reorder-ghost";
    ghost.textContent = item.caption;
    ghost.setAttribute("aria-hidden", "true");
    document.body.append(ghost);
    dragState = {
      id: item.id, from: index, destination: index,
      pointerId: event.pointerId, handle: handle, row: row, ghost: ghost
    };
    row.classList.add("drag-source");
    positionGhost(event);
    try { handle.setPointerCapture(event.pointerId); }
    catch (_ignored) { cancelDrag(); }
  }
  function trackDrag(event) {
    if (!dragState || dragState.pointerId !== event.pointerId) return;
    event.preventDefault();
    positionGhost(event);
    // Keep the list scrollable with normal gestures; only the grip blocks panning.
    if (event.clientY < 88) window.scrollBy(0, -15);
    else if (event.clientY > window.innerHeight - 88) window.scrollBy(0, 15);
    var hit = document.elementFromPoint(event.clientX, event.clientY);
    var target = hit ? hit.closest(".caption-card") : null;
    if (!target || !target.hasAttribute("data-index")) return;
    var targetIndex = Number(target.dataset.index);
    clearDropMarker();
    if (targetIndex === dragState.from) {
      dragState.destination = dragState.from;
      return;
    }
    var rectangle = target.getBoundingClientRect();
    var before = event.clientY < rectangle.top + rectangle.height / 2;
    var destination = dragState.from < targetIndex ?
      targetIndex - (before ? 1 : 0) : targetIndex + (before ? 0 : 1);
    dragState.destination = Math.max(0, Math.min(batch.items.length - 1, destination));
    target.classList.add(before ? "drop-before" : "drop-after");
  }
  function dropDrag(event) {
    if (!dragState || event.pointerId !== dragState.pointerId) return;
    event.preventDefault();
    var id = dragState.id;
    var from = dragState.from;
    var to = dragState.destination;
    cleanupDrag();
    if (to !== from) moveToIndex(id, to);
  }

  function endDeleteMode() {
    deleteMode = false;
    selectedForDelete.clear();
    if (batch) renderList();
  }
  function updateDeleteAction() {
    var count = selectedForDelete.size;
    $("delete-selected").textContent = count + "件を削除";
    setFixed("delete-selected", count === 0);
  }
  function renderList() {
    if (!batch) return;
    var count = batch.items.length;
    $("batch-count").textContent = count + "件";
    $("batch-count").hidden = count === 0 || deleteMode;
    $("empty-state").hidden = count !== 0;
    $("batch-title").textContent = deleteMode ? "削除" : "Batch List";
    $("toggle-reorder").hidden = deleteMode;
    $("toggle-delete").hidden = reorderMode;
    $("toggle-delete").textContent = deleteMode ? "キャンセル" : "削除";
    $("toggle-delete").setAttribute("aria-pressed", String(deleteMode));
    $("add-action").hidden = reorderMode || deleteMode;
    $("delete-action").hidden = !deleteMode;
    $("reorder-help").hidden = !reorderMode;
    var list = $("caption-list");
    list.replaceChildren();
    list.classList.toggle("reorder-mode", reorderMode);
    list.classList.toggle("delete-mode", deleteMode);
    setFixed("toggle-reorder", !reorderMode && count < 2);
    setFixed("toggle-delete", !deleteMode && count === 0);

    batch.items.forEach(function (item, index) {
      var li = document.createElement("li");
      li.className = "caption-card" + (item.included ? "" : " is-excluded");
      li.dataset.index = String(index);
      li.dataset.itemId = item.id;

      if (deleteMode) {
        var choice = document.createElement("label");
        choice.className = "delete-select-row";
        var mark = document.createElement("input");
        mark.type = "checkbox";
        mark.className = "delete-check";
        mark.checked = selectedForDelete.has(item.id);
        mark.disabled = busy;
        mark.setAttribute("aria-label", item.caption + "を削除対象に選ぶ");
        mark.addEventListener("change", function () {
          if (this.checked) selectedForDelete.add(item.id);
          else selectedForDelete.delete(item.id);
          updateDeleteAction();
        });
        var labelText = document.createElement("span");
        labelText.className = "caption-text";
        labelText.textContent = String(index + 1).padStart(2, "0") + "　" + item.caption;
        choice.append(mark, labelText);
        li.append(choice);
        list.append(li);
        return;
      }

      if (!reorderMode) {
        var included = document.createElement("input");
        included.type = "checkbox";
        included.className = "include-check";
        included.checked = item.included;
        included.disabled = busy;
        included.setAttribute("aria-label", item.caption + "を生成対象に含める");
        included.addEventListener("change", function () {
          mutate("PATCH", "/items/" + encodeURIComponent(item.id) + "/included",
            { included: this.checked }, "生成対象を更新しました。");
        });
        var includeControl = document.createElement("label");
        includeControl.className = "include-control";
        includeControl.append(included);
        li.append(includeControl);
      }
      var button = document.createElement("button");
      button.type = "button";
      button.className = "caption-open";
      button.dataset.fixedDisabled = reorderMode ? "true" : "false";
      button.disabled = busy || reorderMode;
      button.setAttribute("aria-label", (index + 1) + "番目のCaptionを編集: " + item.caption);
      var number = document.createElement("span");
      number.className = "caption-index";
      number.textContent = String(index + 1).padStart(2, "0");
      var content = document.createElement("span");
      content.className = "caption-content";
      var caption = document.createElement("span");
      caption.className = "caption-text";
      caption.textContent = item.caption;
      content.append(caption);
      if (item.take_count_override !== null) {
        var meta = document.createElement("span");
        meta.className = "caption-meta";
        meta.textContent = "Take " + item.take_count_override;
        content.append(meta);
      }
      var chevron = document.createElement("span");
      chevron.className = "caption-chevron";
      chevron.setAttribute("aria-hidden", "true");
      chevron.textContent = "›";
      button.append(number, content, chevron);
      button.addEventListener("click", function () { openItem(item.id); });
      li.append(button);
      if (reorderMode) {
        var grip = document.createElement("button");
        grip.type = "button";
        grip.className = "reorder-handle";
        grip.textContent = "⠿";
        grip.disabled = busy;
        grip.setAttribute("aria-label", (index + 1) + "番目のCaptionを移動: " + item.caption);
        grip.setAttribute("aria-keyshortcuts", "ArrowUp ArrowDown Home End");
        grip.addEventListener("pointerdown", function (event) { beginDrag(event, item, index); });
        grip.addEventListener("pointermove", trackDrag);
        grip.addEventListener("pointerup", dropDrag);
        grip.addEventListener("pointercancel", cancelDrag);
        grip.addEventListener("keydown", function (event) { moveByKeyboard(event, item.id, index); });
        li.append(grip);
      }
      list.append(li);
    });
    updateDeleteAction();
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
    $("item-title").textContent = (index + 1) + " / " + batch.items.length;
    if (!keepCaptionDraft) $("edit-caption").value = item.caption;
    $("item-takes-mode").value = item.take_count_override === null ? "default" : "custom";
    $("item-takes").value = String(item.take_count_override === null ?
      batch.default_take_count : item.take_count_override);
    $("item-takes").hidden = item.take_count_override === null;
    setFixed("previous-item", index === 0);
    setFixed("next-item", index === batch.items.length - 1);
    renderTakes(item);
  }
  function setFixed(id, disabled) {
    var control = $(id);
    control.dataset.fixedDisabled = disabled ? "true" : "false";
    control.disabled = busy || disabled;
  }
  function openItem(id) {
    if (busy || !batch) return;
    if (!guardDraft()) return;
    if (selectedId !== id) {
      clearPlayer();
      $("operation-panel").hidden = true;
    }
    selectedId = id;
    renderItem(false);
    showView("item", true);
  }
  function resetLocal(clearSessionId) {
    clearPlayer();
    audioOperation = null;
    endDeleteMode();
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
        // A stale deletion selection must not be applied to a refreshed Batch.
        if (deleteMode) selectedForDelete.clear();
        try { await refresh(); } catch (_ignored) { /* Keep conflict feedback. */ }
      }
      if (error.code === 404 || error.code === 401) {
        resetLocal(error.code === 404);
      } else if (batch) {
        // Restore server-owned values for controls such as the include checkbox.
        renderList();
        if (selectedId) renderItem(true);
      }
      feedback(error.message);
      return false;
    } finally { setBusy(false); }
  }


  function itemAudioPath(id) {
    return batchPath() + "/items/" + encodeURIComponent(id);
  }
  function clearPlayer() {
    var player = $("phone-player");
    player.pause();
    player.removeAttribute("src");
    player.load();
    player.hidden = true;
    if (playingUrl) URL.revokeObjectURL(playingUrl);
    playingUrl = "";
  }
  function takeButton(text, action, disabled) {
    var button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    button.dataset.fixedDisabled = disabled ? "true" : "false";
    button.disabled = busy || disabled;
    button.addEventListener("click", action);
    return button;
  }
  function renderTakes(item) {
    var prepared = Boolean(item.is_prepared);
    var takes = item.takes || [];
    $("prepare-audio").textContent = prepared ? "発音を再準備" : "発音を準備";
    $("preview-audio").hidden = !prepared;
    $("generate-audio").hidden = !prepared || takes.length !== 0;
    $("spoken-source").hidden = !prepared;
    if (prepared) {
      var spoken = item.spoken_text || "";
      $("spoken-source").textContent = spoken === item.caption ?
        "発音準備済み" : "読み上げ: " + spoken;
    }
    $("take-actions").hidden = takes.length === 0;
    var list = $("take-list");
    list.replaceChildren();
    takes.forEach(function (take) {
      var row = document.createElement("li");
      row.className = "take-card";
      var heading = document.createElement("div");
      heading.className = "take-head";
      var name = document.createElement("strong");
      name.textContent = "Take " + take.number;
      var detail = document.createElement("span");
      detail.textContent = take.accepted ? "採用済み" : take.duration_seconds + "秒";
      heading.append(name, detail);
      var actions = document.createElement("div");
      actions.className = "button-row";
      actions.append(
        takeButton("再生", function () {
          playAudio(itemAudioPath(item.id) + "/takes/" + take.number + "/audio", item.id);
        }, false),
        takeButton("採用", function () {
          startAudio(item.id, "/takes/" + take.number + "/accept");
        }, take.accepted),
        takeButton("再生成", function () {
          startAudio(item.id, "/takes/" + take.number + "/regenerate");
        }, take.accepted)
      );
      row.append(heading, actions);
      list.append(row);
    });
    setFixed("prepare-audio", false);
    setFixed("preview-audio", !prepared);
    setFixed("generate-audio", !prepared || takes.length !== 0);
    setFixed("regenerate-unaccepted", takes.length === 0);
    setFixed("clear-takes", takes.length === 0);
  }
  async function playAudio(path, itemId) {
    if (busy || !token || itemId !== selectedId) return;
    setBusy(true);
    try {
      var response = await fetch(path, {
        headers: { Authorization: "Bearer " + token },
        cache: "no-store", credentials: "same-origin"
      });
      if (!response.ok) throw new Error("音声を取得できませんでした。");
      var bytes = await response.blob();
      if (bytes.type.indexOf("audio/") !== 0 || !bytes.size) {
        throw new Error("音声データが無効です。");
      }
      if (selectedId !== itemId) return;
      clearPlayer();
      playingUrl = URL.createObjectURL(bytes);
      var player = $("phone-player");
      player.src = playingUrl;
      player.hidden = false;
      try { await player.play(); }
      catch (_ignored) { feedback("音声プレイヤーの再生ボタンを押してください。"); }
    } catch (error) { feedback(error.message); }
    finally { setBusy(false); }
  }
  function displayAudioProgress(op) {
    $("operation-panel").hidden = false;
    var names = {
      prepare: "発音を準備", preview: "Preview", generate: "Take生成",
      "regenerate-one": "Take再生成", "regenerate-all": "未採用Take再生成",
      accept: "Take採用"
    };
    $("operation-progress").textContent =
      (names[op.kind] || "音声操作") + ": " + op.completed + "/" + op.total +
      (op.status === "cancelling" ? " キャンセル処理中" : "");
    $("cancel-audio").hidden = !op.cancellable ||
      op.status !== "running";
    $("cancel-audio").disabled = op.status !== "running";
  }
  async function startAudio(itemId, suffix, payload) {
    if (busy || !batch || !selectedId || itemId !== selectedId) return;
    var item = batch.items.find(function (entry) { return entry.id === itemId; });
    if (!item) return;
    if ($("edit-caption").value !== item.caption) {
      feedback("未保存のCaptionを先に保存してください。");
      return;
    }
    clearPlayer();
    setBusy(true);
    try {
      var op = await request("POST", itemAudioPath(itemId) + suffix +
        "?expected_revision=" + batch.revision, payload);
      audioOperation = op;
      displayAudioProgress(op);
      while (op.status === "running" || op.status === "cancelling") {
        await new Promise(function (resolve) { setTimeout(resolve, 650); });
        op = await request("GET", "/api/web/sessions/" +
          encodeURIComponent(sessionId) + "/operations/" + encodeURIComponent(op.id));
        audioOperation = op;
        displayAudioProgress(op);
      }
      await refresh();
      if (op.status === "succeeded") {
        feedback(op.kind === "accept" ?
          "保存しました: " + op.result.audio_name :
          op.kind === "preview" ? "Previewを生成しました。" : "音声操作が完了しました。");
      } else {
        feedback(op.status === "cancelled" ?
          "キャンセルしました。生成済みのTakeは保持されています。" :
          (op.error || "音声操作に失敗しました。"));
      }
      if (op.status === "succeeded" && op.kind === "preview" &&
          op.result && op.result.preview_id) {
        setBusy(false);
        await playAudio(itemAudioPath(itemId) + "/audio/preview/" +
          encodeURIComponent(op.result.preview_id), itemId);
      }
    } catch (error) {
      if (error.code === 409) {
        try { await refresh(); } catch (_ignored) { /* Preserve original error. */ }
      }
      if (error.code === 404 || error.code === 401) resetLocal(error.code === 404);
      feedback(error.message);
    } finally {
      audioOperation = null;
      setBusy(false);
      if (batch && currentView === "item") renderItem(true);
    }
  }
  $("prepare-audio").addEventListener("click", function () {
    if (!batch || !selectedId) return;
    var item = batch.items.find(function (entry) { return entry.id === selectedId; });
    if (!item) return;
    if (item.is_prepared && !window.confirm(
      "発音を再準備すると、既存のTake候補と採用状態がクリアされます。保存済み音声は残ります。続けますか？"
    )) return;
    startAudio(selectedId, "/audio/prepare", { rebuild: Boolean(item.is_prepared) });
  });
  $("preview-audio").addEventListener("click", function () {
    startAudio(selectedId, "/audio/preview");
  });
  $("generate-audio").addEventListener("click", function () {
    startAudio(selectedId, "/takes/generate");
  });
  $("regenerate-unaccepted").addEventListener("click", function () {
    startAudio(selectedId, "/takes/regenerate");
  });
  $("clear-takes").addEventListener("click", async function () {
    if (busy || !selectedId || !window.confirm(
      "Take候補と採用状態をクリアしますか？保存済み音声は削除されません。"
    )) return;
    clearPlayer();
    await mutate("DELETE", "/items/" + encodeURIComponent(selectedId) + "/takes",
      undefined, "候補をクリアしました。");
  });
  $("cancel-audio").addEventListener("click", async function () {
    if (!audioOperation || !audioOperation.cancellable ||
        audioOperation.status !== "running") return;
    try {
      audioOperation = await request("POST", "/api/web/sessions/" +
        encodeURIComponent(sessionId) + "/operations/" +
        encodeURIComponent(audioOperation.id) + "/cancel");
      displayAudioProgress(audioOperation);
    } catch (error) { feedback(error.message); }
  });

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
  $("toggle-reorder").addEventListener("click", function () {
    if (busy || !batch || dragState) return;
    if (!reorderMode && batch.items.length < 2) return;
    if (reorderMode) endReorderMode();
    else { reorderMode = true; renderList(); }
    feedback(reorderMode ? "右端のハンドルを上下へドラッグして並べ替えます。" : "");
  });
  $("toggle-delete").addEventListener("click", function () {
    if (busy || !batch || reorderMode || dragState) return;
    if (deleteMode) endDeleteMode();
    else {
      if (!batch.items.length) return;
      deleteMode = true;
      selectedForDelete.clear();
      renderList();
    }
  });
  $("delete-selected").addEventListener("click", async function () {
    if (busy || !deleteMode || !batch || selectedForDelete.size === 0) return;
    var ids = Array.from(selectedForDelete);
    if (!window.confirm(ids.length + "件のCaptionを削除しますか？\nこの操作は取り消せません。")) return;
    var ok = await mutate("POST", "/items/bulk-delete", { ids: ids },
      ids.length + "件のCaptionを削除しました。");
    if (ok) {
      endDeleteMode();
      feedback(ids.length + "件のCaptionを削除しました。");
    }
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
  function adjacent(delta) {
    if (!batch || !selectedId || busy) return;
    var position = batch.items.findIndex(function (item) { return item.id === selectedId; });
    if (position < 0 || position + delta < 0 || position + delta >= batch.items.length) return;
    openItem(batch.items[position + delta].id);
  }
  $("previous-item").addEventListener("click", function () { adjacent(-1); });
  $("next-item").addEventListener("click", function () { adjacent(1); });
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
