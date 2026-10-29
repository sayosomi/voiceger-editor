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
  var playbackRequestId = 0;
  var playback = null;
  var captionEditMode = false;
  var takeCountEditMode = false;
  var takeMenuOpen = false;
  var pronunciationOpening = null;
  var pronunciationItemId = "";
  var pronunciationStale = false;
  var pronunciationComposing = false;
  var pronunciationHistoryActive = false;
  var pronunciationExitPending = null;
  var pronunciationReturnView = "item";
  var pronunciationSelection = { start: 0, end: 0 };
  var autoPrepareFailures = new Set();
  var SESSION_KEY = "voiceger-web-session-id";
  var $ = function (id) { return document.getElementById(id); };
  var viewNames = ["connect", "list", "add", "item", "pronunciation", "session"];
  var screenTitles = {
    connect: "接続", list: "Batch List", add: "Caption追加",
    item: "Batch Item", pronunciation: "発音編集", session: "接続・設定"
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
  function pronunciationDirty() {
    return currentView === "pronunciation" && pronunciationOpening !== null &&
      $("pronunciation-text").value !== pronunciationOpening;
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
    if (pronunciationDirty()) {
      return window.confirm("未反映の発音変更を破棄して移動しますか？");
    }
    return true;
  }
  function showView(name, bypassDraftGuard) {
    if ((busy && !bypassDraftGuard) || viewNames.indexOf(name) === -1) return false;
    if (!bypassDraftGuard && name !== currentView && !guardDraft()) return false;
    if (currentView === "pronunciation" && name !== currentView &&
        pronunciationHistoryActive) {
      // Consume the editor-only history entry before switching screens.
      pronunciationExitPending = { destination: name,
        message: pronunciationExitPending ? pronunciationExitPending.message : "" };
      window.history.back();
      return true;
    }
    if (name !== "list" && reorderMode) endReorderMode();
    if (name !== "list" && deleteMode) endDeleteMode();
    if ((currentView === "item" && name !== "item") ||
        (currentView === "pronunciation" && name !== "pronunciation")) clearPlayer();
    if (currentView === "pronunciation" && name !== "pronunciation") {
      pronunciationHistoryActive = false;
      pronunciationExitPending = null;
      pronunciationOpening = null;
      pronunciationItemId = "";
      pronunciationStale = false;
    }
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
  function pronunciationHistoryState() {
    return {
      voicegerPronunciationEditor: true,
      sessionId: sessionId,
      itemId: pronunciationItemId
    };
  }
  // Android Back/Forward both traverse the real browser history. Forward
  // restores a fresh server-owned pronunciation, never a discarded draft.
  window.addEventListener("popstate", function (event) {
    if (pronunciationHistoryActive && currentView === "pronunciation") {
      if ((!pronunciationExitPending && busy) ||
          (!pronunciationExitPending && !guardDraft())) {
        window.history.pushState(pronunciationHistoryState(), "");
        if (busy) feedback("処理完了後に戻ってください。");
        return;
      }
      var pending = pronunciationExitPending;
      pronunciationHistoryActive = false;
      pronunciationExitPending = null;
      showView(pending ? pending.destination : pronunciationReturnView, true);
      if (pending && pending.message) feedback(pending.message);
      return;
    }
    var state = event && event.state;
    if (!state || !state.voicegerPronunciationEditor) return;
    if (busy || !sessionId || !batch || state.sessionId !== sessionId) {
      // An obsolete editor entry must never restore a previous session.
      window.history.back();
      return;
    }
    var item = batch.items.find(function (row) { return row.id === state.itemId; });
    if (!item || typeof item.pronunciation !== "string") {
      window.history.back();
      return;
    }
    if (!guardDraft()) {
      window.history.back();
      return;
    }
    selectedId = item.id;
    enterPronunciation(item, true);
  });
  window.addEventListener("beforeunload", function (event) {
    if (!pronunciationDirty()) return;
    event.preventDefault();
    // Browser text is intentionally controlled by the browser, not this app.
    event.returnValue = "";
  });
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
      var conflictCode = "";
      if (response.status === 409 || response.status === 422) {
        try {
          var problem = await response.json();
          if (problem && problem.detail && typeof problem.detail.code === "string") {
            conflictCode = problem.detail.code;
          }
        } catch (_ignored) { /* Invalid server response stays generic. */ }
      }
      // Allowlist user-facing explanations; never render untrusted server errors.
      var conflictMessages = {
        revision_conflict: "別の画面で変更されています。最新の一覧を取得してください。",
        worker_busy: "Mac側で別の処理を実行中です。完了後に再試行してください。",
        terms_required: "Mac側で最新のVoiceger利用規約への承諾が必要です。",
        accepted_take_protected: "採用済みTakeを保護しました。Take数を増やすか採用状態を確認してください。",
        already_accepted: "このTakeはすでに採用済みです。",
        conflict: "この操作は現在実行できません。状態を確認してください。"
      };
      var invalidPronunciation = {
        invalid_pronunciation: "発音形式が正しくありません。各アクセント句に ' または正しい [ ] を指定し、句の区切りには空白を使ってください。",
        unsupported_pronunciation: "日本語以外・日英混在の発音編集は次のSliceで対応します。"
      };
      var error = new Error(
        response.status === 401 ? "認証できません。トークンを確認してください。" :
        response.status === 503 ? "Mac側の接続設定を確認してください。" :
        response.status === 409 ?
          (conflictMessages[conflictCode] || conflictMessages.conflict) :
        response.status === 404 ? "セッションが見つかりません。再接続してください。" :
        response.status === 422 ?
          (invalidPronunciation[conflictCode] || "入力内容を確認してください。") :
        "操作を完了できませんでした。"
      );
      error.code = response.status;
      error.conflictCode = conflictCode;
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
  // Only first-time preparation is automatic; failures require an explicit retry.
  function maybePrepareOnOpen(item) {
    if (!item || item.is_prepared || autoPrepareFailures.has(item.id)) return;
    startAudio(item.id, "/audio/prepare", { rebuild: false }, true);
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
    $("caption-text").textContent = item.caption;
    $("caption-display").hidden = captionEditMode;
    $("edit-caption-form").hidden = !captionEditMode;
    if (!keepCaptionDraft) $("edit-caption").value = item.caption;
    $("item-takes-mode").value = item.take_count_override === null ? "default" : "custom";
    $("item-takes").value = String(item.take_count_override === null ?
      batch.default_take_count : item.take_count_override);
    $("item-takes").hidden = item.take_count_override === null;
    $("item-takes-form").hidden = !takeCountEditMode;
    $("edit-take-count").hidden = takeCountEditMode;
    $("edit-take-count").textContent = "Take数 " + item.effective_take_count;
    $("item-pronunciation").hidden = !item.is_prepared;
    $("pronunciation-value").textContent = item.pronunciation ||
      "日本語以外・日英混在の編集は次のSliceで対応します。";
    $("open-pronunciation").hidden = !item.pronunciation;
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
      captionEditMode = false;
      takeCountEditMode = false;
      takeMenuOpen = false;
    }
    selectedId = id;
    renderItem(false);
    showView("item", true);
    maybePrepareOnOpen(batch.items.find(function (item) { return item.id === id; }));
  }
  function resetLocal(clearSessionId) {
    clearPlayer();
    audioOperation = null;
    autoPrepareFailures.clear();
    captionEditMode = false;
    takeCountEditMode = false;
    takeMenuOpen = false;
    pronunciationOpening = null;
    pronunciationItemId = "";
    pronunciationStale = false;
    pronunciationComposing = false;
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
      if (options && options.saveCaption) captionEditMode = false;
      if (options && options.saveCount) takeCountEditMode = false;
      renderList();
      if (selectedId) renderItem(!options || !options.saveCaption);
      feedback(success);
      return true;
    } catch (error) {
      if (error.conflictCode === "revision_conflict") {
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
    // Invalidate outstanding fetches and play() promises before releasing audio.
    playbackRequestId += 1;
    playback = null;
    var player = $("phone-player");
    player.pause();
    player.removeAttribute("src");
    player.load();
    player.hidden = true;
    // A fresh media element prevents old-source events from reaching new playback.
    var fresh = player.cloneNode(false);
    fresh.removeAttribute("src");
    fresh.hidden = true;
    player.replaceWith(fresh);
    bindPlayerEvents(fresh, playbackRequestId);
    if (playingUrl) URL.revokeObjectURL(playingUrl);
    playingUrl = "";
    updatePlaybackUI();
  }
  function updatePlaybackUI() {
    var player = $("phone-player");
    var active = playback && playback.itemId === selectedId &&
      (currentView === "item" || currentView === "pronunciation");
    var phase = active ? playback.phase : "";
    var playing = phase === "playing" && !player.paused && !player.ended;
    var preview = Boolean(active && playback.kind === "preview");
    // Visible and accessible labels share the same playback-phase definition.
    var previewLabels = {
      loading: ["Preview取得中", "Preview音声を取得中"],
      starting: ["Preview再生待ち", "Previewの再生開始待ち"],
      ready: ["▶ Preview再生", "Previewを再生"],
      playing: ["⏸ Preview再生中", "Previewを一時停止"],
      paused: ["▶ Preview再開", "Previewを再開"],
      failed: ["▶ Preview再試行", "Previewを再取得して再生"]
    };
    var previewLabel = preview ?
      (previewLabels[playing ? "playing" : phase] || ["▶ Preview", "Previewを生成して再生"]) :
      ["▶ Preview", "Previewを生成して再生"];
    $("preview-audio").textContent = previewLabel[0];
    $("preview-audio").setAttribute("aria-label", previewLabel[1]);
    // Pending play() during resume must not allow another Preview request.
    var awaitingPlayback = phase === "loading" || phase === "starting";
    var previewControl = $("preview-audio");
    previewControl.disabled = busy ||
      (previewControl.dataset && previewControl.dataset.fixedDisabled === "true") ||
      (preview && awaitingPlayback);
    var editorPreview = $("preview-pronunciation");
    if (editorPreview) {
      editorPreview.textContent = previewLabel[0];
      editorPreview.setAttribute("aria-label", previewLabel[1]);
      editorPreview.disabled = busy || (preview && awaitingPlayback);
    }
    $("take-list").querySelectorAll(".take-card").forEach(function (row) {
      var match = Boolean(active && playback.kind === "take" &&
        row.dataset.takeNumber === String(playback.takeNumber));
      var state = match ? phase : "";
      var isPlaying = match && playing;
      row.classList.toggle("is-playing", isPlaying);
      row.classList.toggle("is-paused", match && state === "paused");
      row.classList.toggle("is-loading", match &&
        (state === "loading" || state === "starting" || state === "ready"));
      row.classList.toggle("is-failed", match && state === "failed");
      var button = row.querySelector(".take-play");
      button.querySelector(".take-play-icon").textContent = isPlaying ? "⏸" : "▶";
      var indicator = row.querySelector(".take-play-state");
      var states = {
        loading: "取得中", starting: "再生待ち", ready: "再生待ち",
        playing: "再生中", paused: "一時停止", failed: "再生失敗"
      };
      indicator.hidden = !match;
      indicator.textContent = match ? states[state] || "" : "";
      var action = isPlaying ? "を一時停止" :
        state === "paused" ? "を再開" :
        state === "failed" ? "を再取得して再生" :
        state === "loading" || state === "starting" ? "を読み込み中" : "を再生";
      button.setAttribute("aria-label", "Take " + row.dataset.takeNumber + action);
      button.disabled = busy || (button.dataset && button.dataset.fixedDisabled === "true") ||
        (match && awaitingPlayback);
      var progress = row.querySelector(".take-progress");
      progress.hidden = !match || state === "loading" || state === "failed";
      var duration = player.duration;
      var fraction = match && Number.isFinite(duration) && duration > 0 ?
        Math.max(0, Math.min(1, player.currentTime / duration)) : 0;
      progress.firstElementChild.style.width = (fraction * 100) + "%";
    });
  }
  async function beginPlayback(requestId) {
    if (!playback || requestId !== playbackRequestId) return;
    var player = $("phone-player");
    playback.phase = "starting";
    updatePlaybackUI();
    try {
      await player.play();
      if (requestId !== playbackRequestId || !playback ||
          playback.phase === "failed") return;
      if (player.ended) playback = null;
      else if (player.paused) playback.phase = playback.started ? "paused" : "ready";
      else {
        playback.started = true;
        playback.phase = "playing";
      }
    } catch (_ignored) {
      if (requestId !== playbackRequestId || !playback) return;
      playback.phase = "failed";
      player.hidden = false;
      feedback("音声の再生を開始できませんでした。プレイヤーから再生するか、再試行してください。");
    }
    updatePlaybackUI();
  }
  function togglePlayback(kind, itemId, takeNumber) {
    if (!playback || itemId !== selectedId ||
        playback.kind !== kind || playback.itemId !== itemId ||
        (kind === "take" && playback.takeNumber !== takeNumber)) return false;
    // A pending play() is already handling this tap; never fall through to
    // a new Preview generation or Take audio fetch.
    if (playback.phase === "loading" || playback.phase === "starting") return true;
    if (busy || !playingUrl || playback.phase === "failed") return false;
    var player = $("phone-player");
    if (player.paused) {
      // beginPlayback handles the rejected play() case and updates the row.
      void beginPlayback(playbackRequestId);
    } else {
      player.pause();
      if (playback) playback.phase = "paused";
      updatePlaybackUI();
    }
    return true;
  }
  function makeRefreshIcon() {
    var namespace = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(namespace, "svg");
    svg.setAttribute("width", "20");
    svg.setAttribute("height", "20");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    // Lucide refresh-cw.
    ["M20 11a8.1 8.1 0 0 0-15.5-2M4 4v5h5",
      "M4 13a8.1 8.1 0 0 0 15.5 2M20 20v-5h-5"].forEach(function (d) {
      var path = document.createElementNS(namespace, "path");
      path.setAttribute("d", d);
      svg.append(path);
    });
    return svg;
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
    $("preview-audio").hidden = !prepared;
    $("generate-audio").hidden = !prepared || takes.length !== 0;
    $("generate-audio").textContent = item.effective_take_count + "本生成";
    $("prepare-retry").hidden = prepared || !autoPrepareFailures.has(item.id);
    $("take-count-label").textContent = takes.length ? takes.length + "本" : "";
    $("open-take-menu").hidden = !prepared;
    $("open-take-menu").setAttribute("aria-expanded", String(takeMenuOpen));
    $("take-menu").hidden = !prepared || !takeMenuOpen;
    $("regenerate-unaccepted").hidden = takes.length === 0;
    $("clear-takes").hidden = takes.length === 0;
    var list = $("take-list");
    list.replaceChildren();
    takes.forEach(function (take) {
      var row = document.createElement("li");
      row.className = "take-card";
      row.dataset.takeNumber = String(take.number);
      var play = takeButton("", function () {
        if (!togglePlayback("take", item.id, take.number)) {
          playAudio(itemAudioPath(item.id) + "/takes/" + take.number + "/audio",
            item.id, "take", take.number);
        }
      }, false);
      play.className = "take-play";
      var icon = document.createElement("span");
      icon.className = "take-play-icon";
      icon.textContent = "▶";
      icon.setAttribute("aria-hidden", "true");
      var label = document.createElement("span");
      label.textContent = "Take " + take.number;
      var state = document.createElement("span");
      state.className = "take-play-state";
      state.hidden = true;
      play.append(icon, label, state);
      var duration = document.createElement("span");
      duration.className = "take-duration";
      duration.textContent = take.duration_seconds + "秒";
      row.append(play, duration);
      if (take.accepted) {
        var accepted = document.createElement("span");
        accepted.className = "take-accepted";
        accepted.textContent = "✓ 採用済み";
        row.append(accepted);
      } else {
        var accept = takeButton("採用", function () {
          startAudio(item.id, "/takes/" + take.number + "/accept");
        }, false);
        accept.className = "take-accept";
        row.append(accept);
        var regenerate = takeButton("", function () {
          startAudio(item.id, "/takes/" + take.number + "/regenerate");
        }, false);
        regenerate.className = "take-regenerate";
        regenerate.append(makeRefreshIcon());
        regenerate.setAttribute("aria-label", "Take " + take.number + "を再生成");
        regenerate.setAttribute("title", "再生成");
        row.append(regenerate);
      }
      var progress = document.createElement("div");
      progress.className = "take-progress";
      progress.hidden = true;
      progress.setAttribute("aria-hidden", "true");
      var fill = document.createElement("div");
      fill.className = "take-progress-fill";
      progress.append(fill);
      row.append(progress);
      list.append(row);
    });
    setFixed("prepare-retry", prepared);
    setFixed("preview-audio", !prepared);
    setFixed("generate-audio", !prepared || takes.length !== 0);
    setFixed("open-take-menu", !prepared);
    setFixed("regenerate-unaccepted", takes.length === 0);
    setFixed("clear-takes", takes.length === 0);
    updatePlaybackUI();
  }
  async function playAudio(path, itemId, kind, takeNumber) {
    if (busy || !token || itemId !== selectedId) return;
    clearPlayer();
    var requestId = playbackRequestId;
    playback = {
      kind: kind, itemId: itemId, takeNumber: takeNumber,
      phase: "loading", started: false
    };
    setBusy(true);
    updatePlaybackUI();
    var ready = false;
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
      if (requestId !== playbackRequestId || selectedId !== itemId || !token) return;
      playingUrl = URL.createObjectURL(bytes);
      $("phone-player").src = playingUrl;
      ready = true;
    } catch (error) {
      if (requestId === playbackRequestId) {
        clearPlayer();
        feedback(error.message);
      }
    } finally {
      // Fetch is globally exclusive, but play() may remain pending indefinitely.
      setBusy(false);
      updatePlaybackUI();
    }
    if (ready && requestId === playbackRequestId && playback) {
      void beginPlayback(requestId);
    }
  }
  function bindPlayerEvents(player, requestId) {
    function current() {
      return player === $("phone-player") && requestId === playbackRequestId;
    }
    player.addEventListener("play", function () {
      if (current()) updatePlaybackUI();
    });
    player.addEventListener("playing", function () {
      if (!current()) return;
      if (playback && playingUrl && player.src === playingUrl &&
          !player.paused && !player.ended && playback.phase !== "loading") {
        playback.started = true;
        playback.phase = "playing";
      }
      updatePlaybackUI();
    });
    player.addEventListener("pause", function () {
      if (!current()) return;
      if (playback && player.paused && playback.phase === "playing")
        playback.phase = "paused";
      updatePlaybackUI();
    });
    player.addEventListener("timeupdate", function () {
      if (current()) updatePlaybackUI();
    });
    player.addEventListener("loadedmetadata", function () {
      if (current()) updatePlaybackUI();
    });
    player.addEventListener("ended", function () {
      if (!current()) return;
      if (playback && playingUrl && player.ended) playback = null;
      updatePlaybackUI();
    });
    player.addEventListener("error", function () {
      if (!current() || !playback || !playingUrl) return;
      playback.phase = "failed";
      player.hidden = false;
      feedback("音声を再生できませんでした。再試行してください。");
      updatePlaybackUI();
    });
  }
  bindPlayerEvents($("phone-player"), playbackRequestId);
  function displayAudioProgress(op) {
    $("operation-panel").hidden = false;
    var names = {
      prepare: "発音を解析中", preview: "Preview",
      "pronunciation-preview": "編集中の発音をPreview", generate: "Take生成",
      "regenerate-one": "Take再生成", "regenerate-all": "未採用Take再生成",
      accept: "Take採用"
    };
    $("operation-progress").textContent =
      (names[op.kind] || "音声操作") + ": " + op.completed + "/" + op.total +
      (op.status === "cancelling" ? " キャンセル処理中" : "");
    $("cancel-audio").hidden = !op.cancellable ||
      op.status !== "running";
    $("cancel-audio").disabled = op.status !== "running";
    var editorPanel = $("pronunciation-operation-panel");
    if (editorPanel) {
      editorPanel.hidden = currentView !== "pronunciation";
      $("pronunciation-operation-progress").textContent =
        $("operation-progress").textContent;
      $("cancel-pronunciation-audio").hidden = !op.cancellable ||
        op.status !== "running";
      $("cancel-pronunciation-audio").disabled = op.status !== "running";
    }
  }
  async function startAudio(itemId, suffix, payload, automaticPrepare) {
    if (busy || !batch || !selectedId || itemId !== selectedId) return;
    var item = batch.items.find(function (entry) { return entry.id === itemId; });
    if (!item) return;
    if ($("edit-caption").value !== item.caption) {
      feedback("未保存のCaptionを先に保存してください。");
      return;
    }
    clearPlayer();
    takeMenuOpen = false;
    $("take-menu").hidden = true;
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
      if (suffix === "/audio/prepare") {
        if (op.status === "succeeded") autoPrepareFailures.delete(itemId);
        else autoPrepareFailures.add(itemId);
      }
      await refresh();
      if (op.status === "succeeded") {
        feedback(op.kind === "accept" ?
          "保存しました: " + op.result.audio_name :
          (op.kind === "preview" || op.kind === "pronunciation-preview") ?
          "Previewを生成しました。" : "音声操作が完了しました。");
      } else {
        feedback(op.status === "cancelled" ?
          "キャンセルしました。生成済みのTakeは保持されています。" :
          (op.error || "音声操作に失敗しました。"));
      }
      if (op.status === "succeeded" &&
          (op.kind === "preview" || op.kind === "pronunciation-preview") &&
          op.result && op.result.preview_id) {
        setBusy(false);
        await playAudio(itemAudioPath(itemId) + "/audio/preview/" +
          encodeURIComponent(op.result.preview_id), itemId, "preview");
      }
    } catch (error) {
      if (suffix === "/audio/prepare") autoPrepareFailures.add(itemId);
      if (error.conflictCode === "revision_conflict") {
        if (currentView === "pronunciation") {
          pronunciationStale = true;
          setFixed("apply-pronunciation", true);
        }
        try { await refresh(); } catch (_ignored) { /* Preserve original error. */ }
      }
      if (error.code === 404 || error.code === 401) resetLocal(error.code === 404);
      feedback(error.conflictCode === "revision_conflict" && pronunciationStale ?
        "別の画面で変更されています。編集をキャンセルし、最新の発音を開き直してください。" :
        error.message);
    } finally {
      audioOperation = null;
      $("operation-panel").hidden = true;
      $("pronunciation-operation-panel").hidden = true;
      setBusy(false);
      if (batch && currentView === "item") renderItem(true);
      updatePlaybackUI();
    }
  }

  function rememberPronunciationSelection() {
    var input = $("pronunciation-text");
    pronunciationSelection = { start: input.selectionStart, end: input.selectionEnd };
  }
  function editPronunciationAtCaret(mark, backspace) {
    if (busy || pronunciationComposing || currentView !== "pronunciation" ||
        pronunciationStale) return;
    var input = $("pronunciation-text");
    var a = Math.min(pronunciationSelection.start, input.value.length);
    var b = Math.min(pronunciationSelection.end, input.value.length);
    if (backspace && a === b && a > 0) {
      // The Intl grapheme boundary preserves emoji, combining sequences, etc.
      var previous = 0;
      if (typeof Intl.Segmenter === "function") {
        var segments = new Intl.Segmenter("ja", { granularity: "grapheme" }).segment(
          input.value.slice(0, a));
        for (var segment of segments) previous = segment.index;
      } else {
        previous = Array.from(input.value.slice(0, a)).slice(0, -1).join("").length;
      }
      a = previous;
    }
    input.setRangeText(backspace ? "" : mark, a, b, "end");
    input.focus({ preventScroll: true });
    rememberPronunciationSelection();
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }
  function enterPronunciation(item, fromHistory) {
    pronunciationReturnView = currentView;
    // A confirmed discarded Caption draft must not reappear on return.
    captionEditMode = false;
    takeCountEditMode = false;
    $("edit-caption").value = item.caption;
    if (!showView("pronunciation", true)) return false;
    pronunciationOpening = item.pronunciation;
    pronunciationItemId = item.id;
    pronunciationStale = false;
    $("pronunciation-text").value = pronunciationOpening;
    $("pronunciation-caption").textContent = item.caption;
    setFixed("apply-pronunciation", false);
    $("pronunciation-text").focus({ preventScroll: true });
    $("pronunciation-text").setSelectionRange(pronunciationOpening.length, pronunciationOpening.length);
    rememberPronunciationSelection();
    if (fromHistory) {
      // Forward is already on the editor entry; do not add another one.
      pronunciationHistoryActive = true;
    } else {
      try {
        window.history.pushState(pronunciationHistoryState(), "");
        pronunciationHistoryActive = true;
      } catch (_ignored) { pronunciationHistoryActive = false; }
    }
    return true;
  }
  function openPronunciation() {
    if (busy || !batch || !selectedId || !guardDraft()) return;
    var item = batch.items.find(function (row) { return row.id === selectedId; });
    if (item && typeof item.pronunciation === "string") enterPronunciation(item, false);
  }
  async function applyPronunciation(event) {
    event.preventDefault();
    if (busy || pronunciationStale || !batch || !pronunciationItemId ||
        pronunciationItemId !== selectedId) return;
    var item = batch.items.find(function (row) { return row.id === selectedId; });
    if (!item) return;
    var notation = $("pronunciation-text").value;
    if (notation !== pronunciationOpening && item.candidate_count > 0 && !window.confirm(
      "発音が実際に変更される場合はTake候補と採用状態がクリアされます。保存済み音声は残ります。反映しますか？"
    )) return;
    setBusy(true);
    try {
      var response = await request("PATCH", itemAudioPath(selectedId) +
        "/pronunciation?expected_revision=" + batch.revision, { notation: notation });
      clearPlayer();
      batch = response.batch;
      renderList();
      var message = response.changed ?
        "発音を反映しました。Take候補はクリアされました。" :
        "発音は変更されていません。Take候補は維持されました。";
      if (pronunciationHistoryActive) pronunciationExitPending = { message: message };
      showView("item", true);
      if (!pronunciationHistoryActive) feedback(message);
    } catch (error) {
      if (error.conflictCode === "revision_conflict") {
        pronunciationStale = true;
        try { await refresh(); } catch (_ignored) { /* Keep conflict feedback. */ }
        feedback("別の画面で変更されています。編集をキャンセルし、最新の発音を開き直してください。");
        setFixed("apply-pronunciation", true);
      } else {
        if (error.code === 404 || error.code === 401) resetLocal(error.code === 404);
        feedback(error.message);
      }
    } finally { setBusy(false); }
  }
  $("open-pronunciation").addEventListener("click", openPronunciation);
  $("pronunciation-back").addEventListener("click", function () { showView("item"); });
  $("cancel-pronunciation").addEventListener("click", function () { showView("item"); });
  $("pronunciation-text").addEventListener("compositionstart", function () {
    pronunciationComposing = true;
  });
  $("pronunciation-text").addEventListener("compositionend", function () {
    pronunciationComposing = false;
    rememberPronunciationSelection();
  });
  ["select", "keyup", "mouseup", "touchend", "input"].forEach(function (type) {
    $("pronunciation-text").addEventListener(type, rememberPronunciationSelection);
  });
  $("pronunciation-text").addEventListener("input", function () {
    if (currentView === "pronunciation" && playback && playback.kind === "preview") {
      // A modified draft must never replay audio for its previous contents.
      clearPlayer();
    }
  });
  $("view-pronunciation").querySelectorAll("[data-pronunciation-insert], [data-pronunciation-backspace]")
    .forEach(function (button) {
      // Mouse buttons must not steal textarea focus. Touch preserves selection
      // before the system keyboard may dismiss on button activation.
      button.addEventListener("mousedown", function (event) { event.preventDefault(); });
      var beganDuringComposition = false;
      button.addEventListener("pointerdown", function () {
        // compositionend may fire between pointerdown and click on Android.
        beganDuringComposition = pronunciationComposing;
        if (!pronunciationComposing) rememberPronunciationSelection();
      });
      button.addEventListener("pointercancel", function () {
        beganDuringComposition = false;
      });
      button.addEventListener("click", function () {
        var suppress = beganDuringComposition;
        beganDuringComposition = false;
        if (suppress || pronunciationComposing) return;
        editPronunciationAtCaret(button.dataset.pronunciationInsert || "",
          button.hasAttribute("data-pronunciation-backspace"));
      });
    });
  $("reset-pronunciation").addEventListener("click", function () {
    if (busy || pronunciationOpening === null) return;
    if (playback && playback.kind === "preview") clearPlayer();
    $("pronunciation-text").value = pronunciationOpening;
    $("pronunciation-text").focus({ preventScroll: true });
    $("pronunciation-text").setSelectionRange(pronunciationOpening.length, pronunciationOpening.length);
    rememberPronunciationSelection();
  });
  $("preview-pronunciation").addEventListener("click", function () {
    if (pronunciationStale || pronunciationItemId !== selectedId) return;
    if (togglePlayback("preview", selectedId)) return;
    startAudio(selectedId, "/pronunciation/preview", {
      notation: $("pronunciation-text").value
    });
  });
  $("pronunciation-form").addEventListener("submit", applyPronunciation);

  $("prepare-retry").addEventListener("click", function () {
    if (!selectedId) return;
    autoPrepareFailures.delete(selectedId);
    startAudio(selectedId, "/audio/prepare", { rebuild: false });
  });
  $("reprepare-audio").addEventListener("click", function () {
    if (!batch || !selectedId) return;
    var item = batch.items.find(function (entry) { return entry.id === selectedId; });
    if (!item || !item.is_prepared || !window.confirm(
      "発音を再準備すると、既存のTake候補と採用状態がクリアされます。保存済み音声は残ります。続けますか？"
    )) return;
    startAudio(selectedId, "/audio/prepare", { rebuild: true });
  });
  $("open-take-menu").addEventListener("click", function () {
    if (busy) return;
    takeMenuOpen = !takeMenuOpen;
    $("take-menu").hidden = !takeMenuOpen;
    this.setAttribute("aria-expanded", String(takeMenuOpen));
  });
  $("preview-audio").addEventListener("click", function () {
    if (!togglePlayback("preview", selectedId)) startAudio(selectedId, "/audio/preview");
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
    takeMenuOpen = false;
    $("take-menu").hidden = true;
    await mutate("DELETE", "/items/" + encodeURIComponent(selectedId) + "/takes",
      undefined, "候補をクリアしました。");
  });
  async function cancelActiveAudio() {
    if (!audioOperation || !audioOperation.cancellable ||
        audioOperation.status !== "running") return;
    try {
      audioOperation = await request("POST", "/api/web/sessions/" +
        encodeURIComponent(sessionId) + "/operations/" +
        encodeURIComponent(audioOperation.id) + "/cancel");
      displayAudioProgress(audioOperation);
    } catch (error) { feedback(error.message); }
  }
  $("cancel-audio").addEventListener("click", cancelActiveAudio);
  $("cancel-pronunciation-audio").addEventListener("click", cancelActiveAudio);

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
  function shouldSubmitCaptions(event) {
    return event.key === "Enter" && event.metaKey &&
      !event.isComposing && event.keyCode !== 229 && !event.repeat;
  }
  $("new-captions").addEventListener("keydown", function (event) {
    if (!shouldSubmitCaptions(event)) return;
    event.preventDefault();
    if (!busy) $("add-form").requestSubmit();
  });
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
  $("open-caption-edit").addEventListener("click", function () {
    if (busy) return;
    captionEditMode = true;
    $("edit-caption-form").hidden = false;
    $("caption-display").hidden = true;
    $("edit-caption").focus();
  });
  $("cancel-caption-edit").addEventListener("click", function () {
    if (busy) return;
    var item = batch && batch.items.find(function (entry) { return entry.id === selectedId; });
    if (!item) return;
    $("edit-caption").value = item.caption;
    captionEditMode = false;
    renderItem(false);
  });
  $("edit-caption-form").addEventListener("submit", function (event) {
    event.preventDefault();
    if (!selectedId) return;
    mutate("PATCH", "/items/" + encodeURIComponent(selectedId) + "/caption",
      { caption: $("edit-caption").value }, "Captionを保存しました。", { saveCaption: true });
  });
  $("edit-take-count").addEventListener("click", function () {
    if (busy) return;
    takeCountEditMode = true;
    renderItem(true);
  });
  $("cancel-take-count").addEventListener("click", function () {
    if (busy) return;
    takeCountEditMode = false;
    renderItem(true);
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
        { count: count }, "Take数を更新しました。", { saveCount: true });
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
