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
  var batchOperation = null;
  var batchPolling = false;
  var recipeMode = "";
  var batchMenuOpen = false;
  var playingUrl = "";
  var playbackRequestId = 0;
  var playback = null;
  var captionEditMode = false;
  var takeCountEditMode = false;
  var takeMenuOpen = false;
  // Empty when the Caption add screen was opened from Batch List.
  var addFromItemId = "";
  var pronunciationOpening = null;
  var pronunciationTarget = null;
  var pronunciationItemId = "";
  var pronunciationStale = false;
  var pronunciationComposing = false;
  var pronunciationHistoryActive = false;
  var pronunciationExitPending = null;
  var pronunciationHistoryExitInFlight = false;
  var pronunciationReturnView = "item";
  var pronunciationSelection = { start: 0, end: 0 };
  var sectionTarget = null;
  var sectionOpening = null;
  var sectionItemId = "";
  var sectionHistoryActive = false;
  var sectionExitPending = null;
  var sectionStale = false;
  var autoPrepareFailures = new Set();
  var dictLanguage = "ja", dictSort = "surface_asc", dictQuery = "", dictType = "ALL";
  var dictData = null, dictEntry = null, dictEntryOriginal = null;
  var dictDuplicate = null;
  var dictPronOpening = null, dictSelection = { start: 0, end: 0 }, dictComposing = false;
  var dictListRequest = 0, dictReturnView = "list", dictQuickMatches = [];
  var dictQuickPriorityEdited = false;
  // The quick form's draft is independent from the Batch pronunciation.
  // null means Surface changed and its prior pronunciation is invalid.
  var dictQuickPronSurface = null;
  var dictionaryHistoryDepth = 0;
  var dictionaryHistoryDestination = null;
  var dictionaryHistoryNotice = "";
  var dictionaryImportReview = null;
  var settingsReturnView = "list", settingsHistoryActive = false;
  var settingsHistoryDestination = null;
  var SESSION_KEY = "voiceger-web-session-id";
  var $ = function (id) { return document.getElementById(id); };
  var viewNames = ["connect", "list", "recipe", "add", "item", "pronunciation", "section", "session", "dictionary", "dictionary-management", "dictionary-import-review", "dictionary-entry", "dictionary-pron"];
  var screenTitles = {
    connect: "接続", list: "Batch List", recipe: "ファイル", add: "Caption追加",
    item: "Batch Item", pronunciation: "発音編集", section: "セクション編集", session: "接続・設定",
    dictionary: "辞書", "dictionary-management": "辞書管理",
    "dictionary-import-review": "取り込み内容",
    "dictionary-entry": "辞書の単語", "dictionary-pron": "辞書発音編集"
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
  function sectionDirty() {
    return currentView === "section" && sectionOpening !== null &&
      ($("section-text").value !== sectionOpening ||
       (sectionTarget && sectionTarget.mode === "add" &&
        selectedSectionLanguage() !== "ja"));
  }
  function takeCountDirty(item) {
    if (!takeCountEditMode || !item) return false;
    var selectedMode = $("item-takes-mode").value;
    var savedMode = item.take_count_override === null ? "default" : "custom";
    if (selectedMode !== savedMode) return true;
    return selectedMode === "custom" &&
      Number($("item-takes").value) !== item.take_count_override;
  }
  function guardDraft() {
    if (currentView === "dictionary-pron") {
      var pronChanged = dictionaryPronunciationDirty();
      var entryChanged = dictionaryEntryDirty();
      if (pronChanged && entryChanged)
        return window.confirm("未反映の発音と未保存の単語変更を破棄しますか？");
      if (pronChanged) return window.confirm("未反映の辞書発音変更を破棄しますか？");
      if (entryChanged) return window.confirm("未保存の辞書変更を破棄しますか？");
    }
    if (currentView === "dictionary-entry" && dictionaryEntryDirty())
      return window.confirm("未保存の辞書変更を破棄しますか？");
    if (sectionDirty()) {
      return window.confirm("未反映のセクション変更を破棄して移動しますか？");
    }
    if (currentView === "add" && $("new-captions").value.trim()) {
      return window.confirm("入力中のCaptionを破棄して戻りますか？");
    }
    if (currentView === "item" && selectedId && batch) {
      var item = batch.items.find(function (entry) { return entry.id === selectedId; });
      var captionChanged = Boolean(item && $("edit-caption").value !== item.caption);
      var takeCountChanged = takeCountDirty(item);
      if (captionChanged && takeCountChanged) {
        return window.confirm("未保存のCaption変更とTake数変更を破棄して移動しますか？");
      }
      if (captionChanged) {
        return window.confirm("未保存のCaption変更を破棄して移動しますか？");
      }
      if (takeCountChanged) {
        return window.confirm("未保存のTake数変更を破棄して移動しますか？");
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
    if (currentView === "section" && name !== currentView &&
        sectionHistoryActive) {
      sectionExitPending = { destination: name,
        message: sectionExitPending ? sectionExitPending.message : "" };
      window.history.back();
      return true;
    }
    if (currentView === "pronunciation" && name !== currentView &&
        pronunciationHistoryActive) {
      // Only one browser Back per editor exit. A second tap before popstate
      // must not cross the parent document and lose the in-memory token.
      if (pronunciationHistoryExitInFlight) return false;
      pronunciationHistoryExitInFlight = true;
      pronunciationExitPending = { destination: name,
        message: pronunciationExitPending ? pronunciationExitPending.message : "" };
      window.history.back();
      return true;
    }
    if (name !== "list" && reorderMode) endReorderMode();
    if (name !== "list" && typeof closeBatchMenu === "function") closeBatchMenu();
    if (name !== "list" && deleteMode) endDeleteMode();
    if ((currentView === "dictionary-pron" && name !== "dictionary-pron") ||
        (currentView === "dictionary-entry" && name !== "dictionary-entry") ||
        (currentView === "item" && name !== "item") ||
        (currentView === "pronunciation" && name !== "pronunciation") ||
        (currentView === "section" && name !== "section")) clearPlayer();
    if (currentView === "section" && name !== "section") {
      sectionHistoryActive = false;
      sectionExitPending = null;
      sectionTarget = null;
      sectionOpening = null;
      sectionItemId = "";
      sectionStale = false;
    }
    if (currentView === "pronunciation" && name !== "pronunciation") {
      pronunciationHistoryActive = false;
      pronunciationHistoryExitInFlight = false;
      pronunciationExitPending = null;
      pronunciationOpening = null;
      if (typeof pronunciationTarget !== "undefined") pronunciationTarget = null;
      pronunciationItemId = "";
      pronunciationStale = false;
    }
    var previousView = currentView;
    currentView = name;
    viewNames.forEach(function (viewName) {
      $("view-" + viewName).hidden = viewName !== name;
    });

    $("header-batch").disabled = !sessionId || name === "connect";
    $("global-nav").hidden = !sessionId || name === "connect";
    $("header-session").setAttribute("aria-current", name === "session" ? "page" : "false");
    $("header-batch").setAttribute("aria-current",
      ["list", "item", "add", "recipe", "pronunciation", "section"].includes(name) ?
      "page" : "false");
    $("header-dictionary").setAttribute("aria-current",
      name.indexOf("dictionary") === 0 ? "page" : "false");
    if (name === "dictionary" && previousView.indexOf("dictionary") !== 0 &&
        dictionaryHistoryDepth === 0) {
      dictionaryPushHistory("dictionary");
    }
    if (name === "session" && previousView !== "session" &&
        !settingsHistoryActive) {
      settingsReturnView = previousView === "pronunciation" || previousView === "section" ?
        "item" : previousView.indexOf("dictionary") === 0 ? "dictionary" : previousView;
      settingsHistoryActive = true;
      window.history.pushState({ voicegerSettings: true, sessionId: sessionId }, "");
    }
    if (name === "dictionary" && previousView !== name) {
      void loadDictionary().catch(function (error) { feedback(error.message); });
    }
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
      itemId: pronunciationItemId,
      language: typeof pronunciationTarget !== "undefined" && pronunciationTarget ? pronunciationTarget.language : "ja",
      segmentIndex: typeof pronunciationTarget !== "undefined" && pronunciationTarget ? pronunciationTarget.segmentIndex : null,
      groupIndex: typeof pronunciationTarget !== "undefined" && pronunciationTarget ? pronunciationTarget.groupIndex : null
    };
  }
  function sectionHistoryState() {
    return { voicegerSectionEditor: true, sessionId: sessionId,
      itemId: sectionItemId, mode: sectionTarget && sectionTarget.mode,
      language: sectionTarget && sectionTarget.language,
      index: sectionTarget && sectionTarget.index,
      opening: sectionTarget && sectionTarget.opening };
  }
  // Android Back/Forward both traverse the real browser history. Forward
  // restores a fresh server-owned pronunciation, never a discarded draft.
  window.addEventListener("popstate", function (event) {
    if (dictionaryHistoryDestination) {
      var destination = dictionaryHistoryDestination;
      dictionaryHistoryDestination = null;
      if (destination === "dictionary-back") {
        // The visible Back button must follow the actual browser history state.
        // Forward may have normalized several entries to the Dictionary list.
        var backState = event && event.state;
        destination = backState && backState.voicegerDictionary &&
          backState.sessionId === sessionId &&
          (backState.view === "dictionary" ||
           backState.view === "dictionary-management" ||
           backState.view === "dictionary-entry") ?
          backState.view : dictReturnView;
      }
      dictionaryHistoryDepth = event && event.state &&
        Number.isInteger(event.state.depth) ? event.state.depth :
        destination === "dictionary" ? 1 :
        destination === "dictionary-entry" || destination === "dictionary-management" ? 2 : 0;
      dictPronOpening = null;
      if (destination !== "dictionary-entry") {
        dictEntry = null;
        dictEntryOriginal = null;
      }
      showView(destination, true);
      if (dictionaryHistoryNotice) {
        feedback(dictionaryHistoryNotice);
        dictionaryHistoryNotice = "";
      }
      return;
    }
    if (currentView === "session" && settingsHistoryActive) {
      if (busy || !guardDraft()) {
        window.history.pushState({ voicegerSettings: true, sessionId: sessionId }, "");
        return;
      }
      settingsHistoryActive = false;
      var settingsDestination = settingsHistoryDestination || settingsReturnView;
      settingsHistoryDestination = null;
      showView(settingsDestination, true);
      return;
    }
    var dictionaryTarget = event && event.state && event.state.voicegerDictionary &&
      event.state.sessionId === sessionId ? event.state : null;
    if (dictionaryTarget && currentView === "dictionary" &&
        dictionaryTarget.view === "dictionary-management" &&
        Number.isInteger(dictionaryTarget.depth) &&
        dictionaryTarget.depth > dictionaryHistoryDepth) {
      // Management is safe to reopen on Forward: it holds no editable draft.
      if (busy) { window.history.back(); return; }
      dictionaryHistoryDepth = dictionaryTarget.depth;
      showView("dictionary-management", true);
      return;
    }
    if (dictionaryTarget && currentView === "dictionary-management" &&
        dictionaryTarget.view === "dictionary-import-review" &&
        Number.isInteger(dictionaryTarget.depth) &&
        dictionaryTarget.depth > dictionaryHistoryDepth) {
      if (busy) { window.history.back(); return; }
      dictionaryHistoryDepth = dictionaryTarget.depth;
      if (dictionaryImportReview) showView("dictionary-import-review", true);
      else {
        window.history.replaceState({ voicegerDictionary: true,
          sessionId: sessionId, view: "dictionary-management",
          depth: dictionaryTarget.depth }, "");
      }
      return;
    }
    if (dictionaryTarget && currentView.indexOf("dictionary") === 0 &&
        Number.isInteger(dictionaryTarget.depth) &&
        dictionaryTarget.depth > dictionaryHistoryDepth &&
        dictionaryTarget.view !== "dictionary") {
      // Browser Forward points into an editor whose draft was discarded by Back.
      // Replace that stale history entry with a safe list entry, not a phantom editor.
      if (busy || !guardDraft()) {
        window.history.back();
        return;
      }
      window.history.replaceState({ voicegerDictionary: true,
        sessionId: sessionId, view: "dictionary", depth: dictionaryTarget.depth }, "");
      dictionaryHistoryDepth = dictionaryTarget.depth;
      dictPronOpening = null;
      dictEntry = null;
      dictEntryOriginal = null;
      showView("dictionary", true);
      return;
    }
    if (dictionaryTarget && currentView === "dictionary" &&
        dictionaryTarget.view === "dictionary") {
      // Both Back and Forward may land on the list (including normalized states).
      dictionaryHistoryDepth = Number.isInteger(dictionaryTarget.depth) ?
        dictionaryTarget.depth : Math.max(1, dictionaryHistoryDepth - 1);
      return;
    }
    if (currentView === "dictionary" || currentView === "dictionary-management" ||
        currentView === "dictionary-import-review" || currentView === "dictionary-entry" || currentView === "dictionary-pron") {
      if (busy || !(currentView === "dictionary-pron" &&
          event && event.state && event.state.voicegerDictionary &&
          event.state.view === "dictionary-entry" ?
          guardDictionaryPronunciationDraft() : guardDraft())) {
        try { window.history.pushState({ voicegerDictionary: true,
          sessionId: sessionId, view: currentView, depth: dictionaryHistoryDepth }, ""); }
        catch (_ignored) { /* The draft still stays open. */ }
        return;
      }
      dictionaryHistoryDepth = dictionaryTarget && Number.isInteger(dictionaryTarget.depth) ?
        dictionaryTarget.depth : Math.max(0, dictionaryHistoryDepth - 1);
      if (currentView === "dictionary-pron") {
        dictPronOpening = null;
        showView("dictionary-entry", true);
      } else if (currentView === "dictionary-entry") {
        dictEntry = null;
        dictEntryOriginal = null;
        showView("dictionary", true);
      } else if (currentView === "dictionary-management") {
        showView("dictionary", true);
      } else if (currentView === "dictionary-import-review") {
        showView("dictionary-management", true);
      } else {
        showView(dictReturnView, true);
      }
      return;
    }
    if (event && event.state && event.state.voicegerSettings) {
      if (busy || !sessionId || event.state.sessionId !== sessionId || !guardDraft()) {
        window.history.back();
        return;
      }
      settingsHistoryActive = true;
      showView("session", true);
      return;
    }
    if (event && event.state && event.state.voicegerDictionary) {
      if (busy || !sessionId || event.state.sessionId !== sessionId || !guardDraft() ||
          event.state.view !== "dictionary") {
        // Never restore an old dictionary word/pronunciation draft from Forward.
        window.history.back();
        return;
      }
      dictReturnView = currentView === "item" ? "item" : "list";
      dictionaryHistoryDepth = Number.isInteger(event.state.depth) ?
        event.state.depth : 1;
      showView("dictionary", true);
      return;
    }
    if (sectionHistoryActive && currentView === "section") {
      if ((!sectionExitPending && busy) || (!sectionExitPending && !guardDraft())) {
        window.history.pushState(sectionHistoryState(), "");
        if (busy) feedback("処理完了後に戻ってください。");
        return;
      }
      var leaving = sectionExitPending;
      sectionHistoryActive = false;
      sectionExitPending = null;
      showView(leaving ? leaving.destination : "item", true);
      if (leaving && leaving.message) feedback(leaving.message);
      return;
    }
    if (event && event.state && event.state.voicegerSectionEditor) {
      var state = event.state;
      if (busy || !batch || !sessionId || state.sessionId !== sessionId ||
          !guardDraft()) { window.history.back(); return; }
      var found = batch.items.find(function (row) { return row.id === state.itemId; });
      if (!found || !found.is_prepared) { window.history.back(); return; }
      selectedId = found.id;
      if (!enterSection(found, state.mode === "add" ? null : {
        index: state.index, language: state.language, text: state.opening
      }, state.mode === "add", true)) window.history.back();
      return;
    }
    if (pronunciationHistoryActive && currentView === "pronunciation") {
      if ((!pronunciationExitPending && busy) ||
          (!pronunciationExitPending && !guardDraft())) {
        window.history.pushState(pronunciationHistoryState(), "");
        if (busy) feedback("処理完了後に戻ってください。");
        return;
      }
      var pending = pronunciationExitPending;
      pronunciationHistoryActive = false;
      pronunciationHistoryExitInFlight = false;
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
    if (!item || (!item.pronunciation && !item.pronunciation_sections)) {
      window.history.back();
      return;
    }
    if (!guardDraft()) {
      window.history.back();
      return;
    }
    selectedId = item.id;
    pronunciationTarget = {
      language: state.language || "ja",
      segmentIndex: state.segmentIndex === undefined ? null : state.segmentIndex,
      groupIndex: state.groupIndex === undefined ? null : state.groupIndex
    };
    if (!enterPronunciation(item, true)) window.history.back();
  });
  window.addEventListener("beforeunload", function (event) {
    if (!pronunciationDirty() && !sectionDirty() &&
        !dictionaryPronunciationDirty() &&
        !((currentView === "dictionary-entry" ||
           currentView === "dictionary-pron") && dictionaryEntryDirty())) return;
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
      var problemIndex = null;
      if (response.status === 409 || response.status === 422 || response.status === 503) {
        try {
          var problem = await response.json();
          if (problem && problem.detail && typeof problem.detail.code === "string") {
            conflictCode = problem.detail.code;
            if (Number.isInteger(problem.detail.item_index)) problemIndex = problem.detail.item_index;
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
        conflict: "この操作は現在実行できません。状態を確認してください。",
        recipe_changed: "Mac側のファイルが変更・削除されました。選び直してください。",
        dictionary_changed: "辞書が別の画面で変更されました。最新の一覧を取得してください。",
        review_expired: "確認が古くなりました。最初から操作してください。"
      };
      var invalidPronunciation = {
        invalid_pronunciation: "発音形式が正しくありません。各アクセント句に ' または正しい [ ] を指定し、句の区切りには空白を使ってください。",
        unsupported_pronunciation: "選択した発音は編集できません。最新のBatchを取得してください。",
        invalid_english_pronunciation: "ARPAbetの音素・強勢数字（0/1/2）を確認してください。",
        grouping_unavailable: "英語の単語区切りを確認できません。Mac側で発音を再準備してください。",
        stale_pronunciation: "編集対象の発音が更新されています。編集画面を開き直してください。",
        invalid_section: "選択したセクションは操作できません。現在の内容を確認してください。",
        invalid_section_text: "文章を確認してください。空欄・改行は使用できません。",
        stale_section: "セクションの文章が更新されています。編集画面を開き直してください。",
        invalid_filename: "ファイル名は .voiceger.json で終わる単一の名前を指定してください。",
        invalid_recipe: "Batchレシピが不正か、必要なVoicegerスタイルがありません。",
        missing_preparation: "すべてのCaptionの発音準備が必要です。除外したCaptionも確認してください。",
        invalid_dictionary: "辞書の入力内容を確認してください。発音・品詞・優先度・重複に注意してください。"
      };
      var error = new Error(
        response.status === 401 ? "認証できません。トークンを確認してください。" :
        response.status === 503 ? (conflictCode === "dictionary_io" ? "Mac側の辞書を保存できませんでした。" :
          conflictCode === "recipe_io" ?
          "Mac側のOutputフォルダまたはファイルを操作できません。" :
          "Mac側の接続設定を確認してください。") :
        response.status === 409 ?
          (conflictMessages[conflictCode] || conflictMessages.conflict) :
        response.status === 404 ? "セッションが見つかりません。再接続してください。" :
        response.status === 422 ?
          (invalidPronunciation[conflictCode] || "入力内容を確認してください。") :
        "操作を完了できませんでした。"
      );
      if (conflictCode === "missing_preparation" && problemIndex !== null) {
        error.message = "Caption " + problemIndex + " の発音を準備してください（除外中も対象）。";
      }
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
    $("open-batch-menu").hidden = deleteMode || reorderMode;
    if (deleteMode || reorderMode) closeBatchMenu();
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
    setFixed("generate-batch", count === 0);

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
      var accepted = (item.accepted_take_numbers || []).length;
      var state = item.generation_outcome;
      var status = state === "failed" ? "生成失敗" :
        state === "cancelled" ? "生成中断" :
        accepted ? "採用済み " + accepted :
        state === "completed" ? "確認待ち" : "";
      if (status) {
        var statusText = document.createElement("span");
        statusText.className = "caption-meta";
        statusText.textContent = status;
        content.append(statusText);
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
  function renderPronunciationSections(item) {
    var host = $("pronunciation-sections");
    host.replaceChildren();
    var sections = item.pronunciation_sections || [];
    sections.forEach(function (section) {
      var panel = document.createElement("section");
      panel.className = "pronunciation-section";

      var heading = document.createElement("div");
      heading.className = "section-top";
      var sourceButton = document.createElement("button");
      sourceButton.type = "button";
      sourceButton.className = "pronunciation-source-button";
      var tag = document.createElement("strong");
      tag.textContent = section.language === "ja" ? "JA" : "EN";
      sourceButton.setAttribute("aria-label", tag.textContent +
        "「" + (section.text || "") + "」の読み上げ文を編集");
      sourceButton.appendChild(tag);
      var source = document.createElement("span");
      source.className = "section-source-text";
      source.textContent = section.text || "";
      sourceButton.appendChild(source);
      var chevron = document.createElement("span");
      chevron.className = "section-header-chevron";
      chevron.textContent = "›";
      chevron.setAttribute("aria-hidden", "true");
      sourceButton.appendChild(chevron);
      sourceButton.addEventListener("click", function () {
        if (busy || !guardDraft()) return;
        enterSection(item, section, false, false);
      });
      heading.appendChild(sourceButton);
      panel.appendChild(heading);

      function edit(target, label, notation) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "pronunciation-entry";
        button.setAttribute("aria-label", label + " の発音を編集");
        var visible = document.createElement("span");
        visible.className = "pronunciation-entry-value";
        visible.textContent = notation;
        button.appendChild(visible);
        button.addEventListener("click", function () {
          if (busy || !guardDraft()) return;
          pronunciationTarget = target;
          enterPronunciation(item, false);
        });
        panel.appendChild(button);
      }
      if (section.language === "ja" && typeof section.notation === "string") {
        edit({ language: "ja", segmentIndex: section.index, groupIndex: null },
          "日本語セクション", section.notation);
      } else if (section.language === "en" && section.groups) {
        section.groups.forEach(function (group) {
          var notation = group.label + "　" + (group.display || "（音素なし）");
          if (group.editable === false) {
            var staticRow = document.createElement("div");
            staticRow.className = "pronunciation-entry pronunciation-entry-static";
            staticRow.textContent = notation;
            panel.appendChild(staticRow);
          } else {
            edit({ language: "en", segmentIndex: section.index, groupIndex: group.index },
              group.label, notation);
          }
        });
      } else {
        var error = document.createElement("p");
        error.className = "help-text";
        error.textContent = "このセクションの発音を表示できません。Mac側で発音を再準備してください。";
        panel.appendChild(error);
      }
      host.appendChild(panel);
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
    var pure = !!item.pronunciation;
    $("pronunciation-value").hidden = true;
    $("open-pronunciation").hidden = true;
    $("pronunciation-sections").hidden = !item.is_prepared;
    $("add-section").hidden = !item.is_prepared;
    $("reprepare-audio").hidden = !item.is_prepared;
    if (item.is_prepared) renderPronunciationSections(item);
    setFixed("previous-item", index === 0);
    // The right footer slot doubles as add-at-end, not a second button.
    $("next-item").textContent = index === batch.items.length - 1 ?
      "＋ Caption追加" : "次のCaption →";
    setFixed("next-item", false);
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
    batchOperation = null;
    recipeMode = "";
    closeBatchMenu();
    autoPrepareFailures.clear();
    captionEditMode = false;
    takeCountEditMode = false;
    takeMenuOpen = false;
    addFromItemId = "";
    sectionTarget = null;
    sectionOpening = null;
    sectionItemId = "";
    sectionHistoryActive = false;
    sectionExitPending = null;
    sectionStale = false;
    pronunciationOpening = null;
    pronunciationTarget = null;
    pronunciationItemId = "";
    pronunciationStale = false;
    pronunciationComposing = false;
    pronunciationHistoryActive = false;
    pronunciationHistoryExitInFlight = false;
    pronunciationExitPending = null;
    dictionaryHistoryDepth = 0;
    dictionaryHistoryDestination = null;
    dictionaryHistoryNotice = "";
    settingsReturnView = "list";
    settingsHistoryActive = false;
    settingsHistoryDestination = null;
    dictEntry = null;
    dictEntryOriginal = null;
    dictPronOpening = null;
    dictData = null;
    dictQuickPronSurface = null;
    $("dictionary-quick-form").hidden = true;
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
    setFixed("reprepare-audio", !prepared);
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
    var sectionPanel = $("section-operation-panel");
    if (sectionPanel) {
      sectionPanel.hidden = currentView !== "section";
      $("section-operation-progress").textContent = $("operation-progress").textContent;
      $("cancel-section-audio").hidden = !op.cancellable || op.status !== "running";
      $("cancel-section-audio").disabled = op.status !== "running";
    }
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
        (suffix.includes("?") ? "&" : "?") +
        "expected_revision=" + batch.revision, payload);
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
        if (currentView === "section") {
          sectionStale = true;
          setFixed("apply-section", true);
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
      $("section-operation-panel").hidden = true;
      setBusy(false);
      if (batch && currentView === "item") renderItem(true);
      updatePlaybackUI();
    }
  }


  function renderBatchProgress(op) {
    batchOperation = op;
    var running = op && (op.status === "running" || op.status === "cancelling");
    $("batch-progress-panel").hidden = !running;
    if (!running) return;
    var detail = op.detail || {};
    $("batch-progress-total").textContent = op.completed + " / " + op.total + " Take";
    $("batch-progress-bar").max = Math.max(1, op.total);
    $("batch-progress-bar").value = Math.min(op.completed, op.total);
    $("batch-progress-item").textContent =
      "Caption " + (detail.caption_number || 1) + " / " +
      (detail.caption_total || 1) + " · Take " +
      (detail.take_number || 0) + " / " + (detail.take_total || 0) +
      (op.status === "cancelling" ? " · キャンセル中" : "");
    $("cancel-batch").disabled = op.status !== "running";
  }

  async function followBatchOperation(op) {
    if (batchPolling || !op || op.kind !== "batch-generate") return;
    batchPolling = true;
    setBusy(true);
    try {
      while (op.status === "running" || op.status === "cancelling") {
        renderBatchProgress(op);
        await new Promise(function (resolve) { setTimeout(resolve, 650); });
        try {
          op = await request("GET", "/api/web/sessions/" +
            encodeURIComponent(sessionId) + "/operations/" + encodeURIComponent(op.id));
          await refresh();
          feedback("");
        } catch (error) {
          if (error.code === 401 || error.code === 404) throw error;
          feedback("通信が途切れています。進捗を再取得します。");
        }
      }
      var refreshed = true;
      try {
        await refresh();
      } catch (error) {
        if (error.code === 401 || error.code === 404) throw error;
        refreshed = false;
      }
      if (!refreshed) {
        feedback("生成は終了しましたが、一覧を更新できません。再接続してください。");
      } else if (op.status === "succeeded") {
        feedback("一括生成が完了しました。");
      } else {
        feedback(op.status === "cancelled" ?
          "一括生成をキャンセルしました。生成済みTakeは保持されています。" :
          (op.error || "一括生成に失敗しました。"));
      }
    } catch (error) {
      if (error.code === 404 || error.code === 401) resetLocal(error.code === 404);
      feedback(error.message);
    } finally {
      batchPolling = false;
      batchOperation = null;
      $("batch-progress-panel").hidden = true;
      setBusy(false);
      if (batch) renderList();
    }
  }

  function resumeBatchOperation() {
    if (batch && batch.active_operation && !batchPolling) {
      followBatchOperation(batch.active_operation);
    }
  }

  function closeBatchMenu() {
    batchMenuOpen = false;
    $("batch-menu").hidden = true;
    $("open-batch-menu").setAttribute("aria-expanded", "false");
  }

  function recipePath() { return batchPath() + "/recipes"; }
  function recipeRevisionPath(suffix) {
    return recipePath() + suffix + "?expected_revision=" + encodeURIComponent(batch.revision);
  }
  async function cancelRecipeReview() {
    if (!batch || !sessionId) return;
    await request("POST", recipeRevisionPath("/cancel"));
  }
  async function openRecipe(mode) {
    if (busy || !batch || reorderMode || deleteMode || !showView("recipe")) return;
    closeBatchMenu();
    recipeMode = mode;
    $("recipe-title").textContent = mode === "read" ? "Macから読み込む" : "Batchを保存";
    $("recipe-read-panel").hidden = mode !== "read";
    $("recipe-save-form").hidden = mode !== "save";
    if (mode !== "read") {
      $("recipe-filename").focus({ preventScroll: true });
      return;
    }
    $("recipe-files").replaceChildren();
    $("recipe-empty").hidden = true;
    setBusy(true);
    try {
      var listed = await request("GET", recipePath());
      var files = listed.files || [];
      $("recipe-empty").hidden = files.length !== 0;
      files.forEach(function (name) {
        var li = document.createElement("li");
        var button = document.createElement("button");
        button.type = "button";
        button.textContent = name;
        button.addEventListener("click", function () { readRecipe(name); });
        li.appendChild(button);
        $("recipe-files").appendChild(li);
      });
    } catch (error) {
      feedback(error.message);
    } finally { setBusy(false); }
  }

  async function readRecipe(filename) {
    if (busy || !batch || recipeMode !== "read") return;
    setBusy(true);
    try {
      var reviewed = await request("POST", recipeRevisionPath("/read/review"),
        { filename: filename });
      if (reviewed.replace_required && !window.confirm(
        "現在のBatchとメモリ上の生成済みTake・採用状態を置き換えますか？\\n" +
        "レシピにはTake音声や採用状態は含まれず、復元されません。\\n" +
        "Mac上に保存済みの音声ファイルは削除されません。"
      )) {
        await cancelRecipeReview();
        feedback("読み込みをキャンセルしました。Batchは変更されていません。");
        return;
      }
      var loaded = await request("POST", recipeRevisionPath("/read/commit"),
        { token: reviewed.token, confirmed_replace: reviewed.replace_required });
      clearPlayer();
      selectedId = "";
      autoPrepareFailures.clear();
      captionEditMode = false;
      takeCountEditMode = false;
      takeMenuOpen = false;
      batch = loaded;
      renderList();
      showView("list", true);
      feedback(filename + " を読み込みました。Takeは復元されません。");
    } catch (error) {
      if (error.conflictCode === "revision_conflict") {
        try { await refresh(); } catch (_ignored) {}
      }
      feedback(error.message);
    } finally { setBusy(false); }
  }

  async function saveRecipe(event) {
    event.preventDefault();
    if (busy || !batch || recipeMode !== "save") return;
    var filename = $("recipe-filename").value.trim();
    setBusy(true);
    try {
      var reviewed = await request("POST", recipeRevisionPath("/save/review"),
        { filename: filename });
      if (reviewed.exists && !window.confirm(
        filename + " はMacのOutputフォルダに存在します。上書きしますか？"
      )) {
        await cancelRecipeReview();
        feedback("保存をキャンセルしました。ファイルは変更されていません。");
        return;
      }
      await request("POST", recipeRevisionPath("/save/commit"),
        { token: reviewed.token, confirmed_overwrite: reviewed.exists });
      showView("list", true);
      feedback(filename + " をMacのOutputフォルダに保存しました。");
    } catch (error) {
      if (error.conflictCode === "revision_conflict") {
        try { await refresh(); } catch (_ignored) {}
      }
      feedback(error.message);
    } finally { setBusy(false); }
  }

  async function startBatchGeneration() {
    if (busy || !batch || reorderMode || deleteMode) return;
    setBusy(true);
    try {
      var result = await request("POST", batchPath() + "/generate?expected_revision=" +
        encodeURIComponent(batch.revision));
      if (result.status === "no-op") {
        feedback(result.reason === "empty_selection" ?
          "生成対象のCaptionをチェックしてください。" :
          "対象のTakeはすべて採用済みです。");
        return;
      }
      await followBatchOperation(result);
    } catch (error) {
      if (error.conflictCode === "revision_conflict") {
        try { await refresh(); } catch (_ignored) {}
      }
      if (error.code === 404 || error.code === 401) resetLocal(error.code === 404);
      feedback(error.message);
    } finally {
      if (!batchPolling) setBusy(false);
    }
  }

  function rememberPronunciationSelection() {
    var input = $("pronunciation-text");
    pronunciationSelection = { start: input.selectionStart, end: input.selectionEnd };
  }
  function replaceAtCaret(input, selection, mark, backspace) {
    var a = Math.min(selection.start, input.value.length);
    var b = Math.min(selection.end, input.value.length);
    if (backspace && a === b && a > 0) {
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
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }
  function editPronunciationAtCaret(mark, backspace) {
    if (busy || pronunciationComposing || currentView !== "pronunciation" ||
        pronunciationStale) return;
    var input = $("pronunciation-text");
    replaceAtCaret(input, pronunciationSelection, mark, backspace);
    rememberPronunciationSelection();
  }
  function enterPronunciation(item, fromHistory) {
    pronunciationReturnView = currentView;
    // A confirmed discarded Caption draft must not reappear on return.
    captionEditMode = false;
    takeCountEditMode = false;
    $("edit-caption").value = item.caption;
    var target = typeof pronunciationTarget !== "undefined" && pronunciationTarget ?
      pronunciationTarget : { language: "ja", segmentIndex: null, groupIndex: null };
    var opening = item.pronunciation, context = item.caption;
    if (item.pronunciation_sections && item.pronunciation_sections.length) {
      var section = item.pronunciation_sections.find(function (entry) {
        return entry.language === target.language && entry.index === target.segmentIndex;
      });
      if (!section) return false;
      if (target.language === "ja") {
        opening = section.notation;
        context = section.text;
      } else {
        var group = (section.groups || []).find(function (entry) {
          return entry.index === target.groupIndex;
        });
        if (!group) return false;
        opening = group.notation;
        context = group.label;
      }
    }
    if (typeof opening !== "string") return false;
    if (!showView("pronunciation", true)) return false;
    pronunciationTarget = target;
    pronunciationOpening = opening;
    pronunciationItemId = item.id;
    pronunciationStale = false;
    $("pronunciation-title").textContent = target.language === "en" ? "英語発音編集" : "発音編集";
    $("pronunciation-field-label").textContent = target.language === "en" ? "ARPAbet" : "発音";
    $("pronunciation-assists").hidden = target.language === "en";
    $("pronunciation-text").value = opening;
    $("pronunciation-caption").textContent = context;
    setFixed("apply-pronunciation", false);
    $("pronunciation-text").focus({ preventScroll: true });
    $("pronunciation-text").setSelectionRange(opening.length, opening.length);
    rememberPronunciationSelection();
    pronunciationHistoryExitInFlight = false;
    pronunciationExitPending = null;
    if (fromHistory) {
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
    if (item && typeof item.pronunciation === "string") {
      pronunciationTarget = { language: "ja", segmentIndex: null, groupIndex: null };
      enterPronunciation(item, false);
    }
  }
  function pronunciationEndpoint(preview) {
    var target = typeof pronunciationTarget !== "undefined" ? pronunciationTarget : null;
    var suffix = "/pronunciation";
    var payload = { notation: $("pronunciation-text").value };
    if (target && target.language === "en") {
      suffix += "/english/" + encodeURIComponent(target.segmentIndex) +
        "/" + encodeURIComponent(target.groupIndex);
      payload.opening = pronunciationOpening;
    }
    if (preview) suffix += "/preview";
    if (target && target.language === "ja" && target.segmentIndex !== null &&
        target.segmentIndex !== undefined) {
      suffix += "?segment_index=" + encodeURIComponent(target.segmentIndex);
    }
    return { suffix: suffix, payload: payload };
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
      var endpoint = pronunciationEndpoint(false);
      var response = await request("PATCH", itemAudioPath(selectedId) +
        endpoint.suffix + (endpoint.suffix.includes("?") ? "&" : "?") +
        "expected_revision=" + batch.revision, endpoint.payload);
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
  function selectedSectionLanguage() {
    var current = document.querySelector('input[name="section-language"]:checked');
    return current ? current.value : "ja";
  }
  function setSectionLanguage(language) {
    document.querySelectorAll('input[name="section-language"]').forEach(function (choice) {
      choice.checked = choice.value === language;
    });
  }
  function enterSection(item, section, add, fromHistory) {
    if (busy || !item || !item.is_prepared) return false;
    var target;
    if (add) {
      target = { mode: "add", language: "ja", index: null, opening: "" };
    } else {
      var found = (item.pronunciation_sections || []).find(function (entry) {
        return entry.index === section.index && entry.language === section.language &&
          entry.text === section.text;
      });
      if (!found) return false;
      target = { mode: "edit", language: found.language,
        index: found.index, opening: found.text };
    }
    if (!showView("section", true)) return false;
    // A previously confirmed Caption draft discard must not block Preview
    // or reappear when returning to Batch Item.
    captionEditMode = false;
    takeCountEditMode = false;
    $("edit-caption").value = item.caption;
    sectionTarget = target;
    sectionOpening = add ? "" : target.opening;
    sectionItemId = item.id;
    sectionStale = false;
    $("section-title").textContent = add ? "セクションを追加" : "読み上げ文";
    $("section-language-field").hidden = !add;
    setSectionLanguage(target.language);
    $("section-text").value = sectionOpening;
    $("preview-section").hidden = add;
    $("delete-section").hidden = add || target.index === null ||
      (item.pronunciation_sections || []).length <= 1;
    $("reset-section").hidden = true;
    $("apply-section").textContent = add ? "追加" : "反映";
    setFixed("apply-section", false);
    $("section-text").focus({ preventScroll: true });
    if (!fromHistory) {
      try {
        window.history.pushState(sectionHistoryState(), "");
        sectionHistoryActive = true;
      } catch (_ignored) { sectionHistoryActive = false; }
    } else {
      sectionHistoryActive = true;
    }
    return true;
  }
  async function deleteSectionFromEditor() {
    if (busy || sectionStale || !batch || !sectionTarget ||
        sectionTarget.mode !== "edit" || sectionItemId !== selectedId) return;
    var item = batch.items.find(function (row) { return row.id === sectionItemId; });
    var target = sectionTarget;
    var sections = item && item.pronunciation_sections || [];
    if (sections.length <= 1 || target.index === null ||
        !sections.some(function (section) {
          return section.index === target.index &&
            section.language === target.language && section.text === target.opening;
        })) return;
    if (!window.confirm("このセクションを削除しますか？\n\n" + target.opening +
        "\n\nTake候補と採用状態はクリアされます。Captionと保存済み音声は残ります。")) return;
    setBusy(true);
    try {
      var response = await request(
        "POST", itemAudioPath(item.id) + "/sections/delete?expected_revision=" + batch.revision,
        { language: target.language, index: target.index, opening: target.opening });
      clearPlayer();
      batch = response.batch;
      renderList();
      var message = "セクションを削除しました。";
      if (sectionHistoryActive) sectionExitPending = { destination: "item", message: message };
      showView("item", true);
      if (!sectionHistoryActive) feedback(message);
    } catch (error) {
      if (error.conflictCode === "revision_conflict") {
        sectionStale = true;
        setFixed("apply-section", true);
        setFixed("delete-section", true);
        try { await refresh(); } catch (_ignored) { /* Preserve original error. */ }
      }
      if (error.code === 401 || error.code === 404) resetLocal(error.code === 404);
      feedback(error.message);
    } finally {
      setBusy(false);
    }
  }
  $("add-section").addEventListener("click", function () {
    if (busy || !batch || !selectedId || !guardDraft()) return;
    var item = batch.items.find(function (row) { return row.id === selectedId; });
    enterSection(item, null, true, false);
  });
  document.querySelectorAll('input[name="section-language"]').forEach(function (choice) {
    choice.addEventListener("change", function () {
      if (sectionTarget && sectionTarget.mode === "add")
        sectionTarget.language = selectedSectionLanguage();
    });
  });
  $("section-back").addEventListener("click", function () { showView("item"); });
  $("delete-section").addEventListener("click", deleteSectionFromEditor);
  function updateSectionReset() {
    $("reset-section").hidden = !sectionTarget || sectionTarget.mode !== "edit" ||
      $("section-text").value === sectionOpening;
  }
  $("reset-section").addEventListener("click", function () {
    if (busy || sectionStale) return;
    $("section-text").value = sectionOpening || "";
    updateSectionReset();
    $("section-text").focus({ preventScroll: true });
    if (playback && playback.kind === "preview") clearPlayer();
  });
  $("section-text").addEventListener("input", function () {
    updateSectionReset();
    if (playback && playback.kind === "preview") clearPlayer();
  });
  $("preview-section").addEventListener("click", function () {
    if (busy || sectionStale || !sectionTarget ||
        sectionTarget.mode !== "edit" || sectionItemId !== selectedId) return;
    if (togglePlayback("preview", selectedId)) return;
    startAudio(selectedId, "/sections/text/preview", {
      language: sectionTarget.language, index: sectionTarget.index,
      opening: sectionTarget.opening, text: $("section-text").value
    });
  });
  $("cancel-section-audio").addEventListener("click", cancelActiveAudio);
  $("section-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    if (busy || sectionStale || !batch || !sectionTarget ||
        sectionItemId !== selectedId) return;
    var newText = $("section-text").value, target = sectionTarget;
    if (!newText.trim() || newText.includes("\n") || newText.includes("\r")) {
      feedback("読み上げ文は1行で入力してください。"); return;
    }
    var item = batch.items.find(function (row) { return row.id === selectedId; });
    if (!item) return;
    if (item.candidate_count > 0 && (target.mode === "add" ||
        newText !== target.opening) && !window.confirm(
      "変更するとTake候補と採用状態がクリアされます。保存済み音声は残ります。続けますか？"
    )) return;
    setBusy(true);
    try {
      var route = target.mode === "add" ? "/sections" : "/sections/text";
      var payload = target.mode === "add" ?
        { language: selectedSectionLanguage(), text: newText } :
        { language: target.language, index: target.index,
          opening: target.opening, text: newText };
      var response = await request(target.mode === "add" ? "POST" : "PATCH",
        itemAudioPath(selectedId) + route + "?expected_revision=" + batch.revision, payload);
      clearPlayer();
      batch = response.batch;
      renderList();
      var message = response.changed ? "読み上げるセクションを更新しました。" :
        "セクションは変更されていません。Take候補は保持されました。";
      if (sectionHistoryActive) sectionExitPending = { message: message };
      showView("item", true);
      if (!sectionHistoryActive) feedback(message);
    } catch (error) {
      if (error.conflictCode === "revision_conflict") {
        sectionStale = true;
        setFixed("apply-section", true);
        try { await refresh(); } catch (_ignored) {}
      }
      if (error.code === 401 || error.code === 404) resetLocal(error.code === 404);
      feedback(error.message);
    } finally { setBusy(false); }
  });
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
    var endpoint = pronunciationEndpoint(true);
    startAudio(selectedId, endpoint.suffix, endpoint.payload);
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
      "現在のCaptionから発音を再解析しますか？\n\n手動で調整した発音と、既存のTake候補・採用状態がクリアされます。保存済み音声は残ります。"
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
  $("cancel-batch").addEventListener("click", async function () {
    if (!batchOperation || batchOperation.status !== "running") return;
    try {
      var updated = await request("POST", "/api/web/sessions/" +
        encodeURIComponent(sessionId) + "/operations/" +
        encodeURIComponent(batchOperation.id) + "/cancel");
      renderBatchProgress(updated);
    } catch (error) { feedback(error.message); }
  });
  $("generate-batch").addEventListener("click", startBatchGeneration);
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
    resumeBatchOperation();
  });
  $("open-batch-menu").addEventListener("click", function () {
    if (busy || reorderMode || deleteMode) return;
    batchMenuOpen = !batchMenuOpen;
    $("batch-menu").hidden = !batchMenuOpen;
    this.setAttribute("aria-expanded", String(batchMenuOpen));
  });
  $("recipe-open-read").addEventListener("click", function () { openRecipe("read"); });
  $("recipe-open-save").addEventListener("click", function () { openRecipe("save"); });
  $("recipe-save-form").addEventListener("submit", saveRecipe);
  $("recipe-back").addEventListener("click", function () { showView("list"); });
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
  function openCaptionAdd(fromItem) {
    if (busy || !batch || !showView("add")) return;
    addFromItemId = fromItem ? selectedId : "";
    $("new-captions").focus({ preventScroll: true });
  }
  function backFromCaptionAdd() {
    var original = addFromItemId && batch &&
      batch.items.some(function (item) { return item.id === addFromItemId; });
    if (!showView(original ? "item" : "list")) return;
    if (addFromItemId) $("new-captions").value = "";
    addFromItemId = "";
  }
  $("open-add").addEventListener("click", function () { openCaptionAdd(false); });
  $("add-back").addEventListener("click", backFromCaptionAdd);
  $("item-back").addEventListener("click", function () { showView("list"); });
  $("session-back").addEventListener("click", function () {
    if (busy) return;
    if (settingsHistoryActive) window.history.back();
    else showView(settingsReturnView, true);
  });
  $("header-batch").addEventListener("click", function () { navigateGlobal("list"); });
  $("header-session").addEventListener("click", function () { navigateGlobal("session"); });
  $("header-dictionary").addEventListener("click", function () { navigateGlobal("dictionary"); });
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
    if (busy || !batch) return;
    // Detect the server-added IDs, not the number of local newline characters.
    var oldIds = new Set(batch.items.map(function (item) { return item.id; }));
    var originId = addFromItemId;
    var ok = await mutate("POST", "/items", { text: $("new-captions").value }, "Captionを追加しました。");
    if (ok) {
      $("new-captions").value = "";
      addFromItemId = "";
      var added = batch.items.filter(function (item) { return !oldIds.has(item.id); });
      if (originId && added.length === 1) {
        // Reuse the normal Batch Item open and automatic pronunciation prepare.
        openItem(added[0].id);
      } else {
        showView("list", true);
      }
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
  $("next-item").addEventListener("click", function () {
    if (!batch || !selectedId || busy) return;
    var index = batch.items.findIndex(function (item) { return item.id === selectedId; });
    if (index < 0) return;
    if (index === batch.items.length - 1) openCaptionAdd(true);
    else adjacent(1);
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


  var dictionarySortModes = {
    ja: [["surface_asc", "Surface ↑"], ["surface_desc", "Surface ↓"],
         ["word_type", "品詞"], ["priority_asc", "Priority ↑"],
         ["priority_desc", "Priority ↓"], ["added_asc", "Added ↑"],
         ["added_desc", "Added ↓"]],
    en: [["surface_asc", "Surface ↑"], ["surface_desc", "Surface ↓"],
         ["added_asc", "Added ↑"], ["added_desc", "Added ↓"]]
  };

  function dictionaryPath() {
    return "/api/web/sessions/" + encodeURIComponent(sessionId) + "/dictionary";
  }
  function openDictionaryManagement() {
    if (busy || currentView !== "dictionary" || dictionaryHistoryDestination) return;
    if (!showView("dictionary-management", true)) return;
    dictionaryExportNotice("", false);
    dictionaryPushHistory("dictionary-management");
  }
  function dictionaryExportNotice(text, isError) {
    var notice = $("dictionary-export-message");
    notice.textContent = text;
    notice.hidden = !text;
    notice.dataset.error = isError ? "true" : "false";
    if (text) {
      notice.scrollIntoView({ behavior: "auto", block: "center" });
      if (isError) notice.focus({ preventScroll: true });
    }
  }
  async function exportDictionary(format) {
    if (busy || currentView !== "dictionary-management" || !sessionId) return;
    setBusy(true);
    var tokenForCancel = "";
    try {
      var latest = await request("GET", dictionaryPath() + "/" + encodeURIComponent(dictLanguage) +
        "?sort=" + encodeURIComponent(dictSort) + "&query=" +
        encodeURIComponent(dictQuery) + "&word_type=" + encodeURIComponent(dictType));
      dictData = latest;
      var revision = latest.revision;
      var review = await request("POST", dictionaryPath() + "/export/review", {
        format: format, expected_revision: revision
      });
      tokenForCancel = review.token;
      var confirmLoss = false;
      if (format === "voicevox" && review.lossy_pitch_count > 0) {
        confirmLoss = window.confirm(
          review.lossy_pitch_count + "件の追加アクセント情報はVOICEVOX JSONに保存されません。\n" +
          "完全な保存にはZIPバックアップを使用してください。\nこのまま書き出しますか？"
        );
        if (!confirmLoss) {
          await request("POST", dictionaryPath() + "/export/cancel",
            { token: review.token });
          tokenForCancel = "";
          dictionaryExportNotice("エクスポートを中止しました。ファイルは作成していません。", false);
          return;
        }
      }
      var saved = await request("POST", dictionaryPath() + "/export/commit", {
        token: review.token, expected_revision: revision,
        confirmed_pitch_loss: confirmLoss
      });
      tokenForCancel = "";
      dictionaryExportNotice(
        saved.filename + " をMacのOutputフォルダに保存しました。", false);
    } catch (error) {
      // Cancel any outstanding review. Never retry a failed commit blindly.
      if (tokenForCancel) {
        try { await request("POST", dictionaryPath() + "/export/cancel",
          { token: tokenForCancel }); } catch (_ignored) {}
      }
      dictionaryExportNotice(error.conflictCode === "export_io" ?
        "MacのOutputフォルダへ書き込めませんでした。保存先と空き容量を確認してください。" :
        error.message, true);
    } finally { setBusy(false); }
  }
  function importPath() {
    return dictionaryPath() + "/import";
  }
  function dictionaryImportNotice(id, message, isError) {
    var notice = $(id);
    notice.textContent = message;
    notice.hidden = !message;
    notice.dataset.error = isError ? "true" : "false";
    if (isError) {
      notice.scrollIntoView({behavior: "auto", block: "center"});
      notice.focus({preventScroll: true});
    }
  }
  async function loadDictionaryImportFiles() {
    if (!sessionId) return;
    var chosen = $("dictionary-import-file").value;
    var response = await request("GET", importPath() + "/files");
    var files = response.files || [];
    var input = $("dictionary-import-file");
    input.replaceChildren();
    if (!files.length) {
      var empty = document.createElement("option");
      empty.value = "";
      empty.textContent = "ファイルがありません";
      input.append(empty);
      $("dictionary-import-open").disabled = true;
    } else {
      files.forEach(function (filename) {
        var option = document.createElement("option");
        option.value = filename;
        option.textContent = filename;
        input.append(option);
      });
      if (files.includes(chosen)) input.value = chosen;
      $("dictionary-import-open").disabled = busy;
    }
  }
  async function openDictionaryImportReview() {
    if (busy || currentView !== "dictionary-management") return;
    var filename = $("dictionary-import-file").value;
    if (!filename) {
      dictionaryImportNotice("dictionary-import-message",
        "MacのOutputフォルダに対象ファイルがありません。", true);
      return;
    }
    setBusy(true);
    try {
      var current = await request("GET", dictionaryPath() + "/ja?sort=surface_asc");
      var data = await request("POST", importPath() + "/review", {
        filename: filename, expected_revision: current.revision
      });
      dictionaryImportReview = data;
      renderDictionaryImportReview();
      showView("dictionary-import-review", true);
      dictionaryPushHistory("dictionary-import-review");
    } catch (error) {
      dictionaryImportNotice("dictionary-import-message", error.message, true);
    } finally { setBusy(false); }
  }
  function renderDictionaryImportReview() {
    var data = dictionaryImportReview;
    if (!data) return;
    $("dictionary-import-source").textContent = data.filename;
    $("dictionary-import-summary").textContent = "新規 " + data.new + "件 · 競合 " +
      data.conflicts + "件 · 一致 " + data.exact + "件（変更なし）";
    $("dictionary-import-selection").textContent = "選択 " + data.selected + "件";
    $("dictionary-import-commit").disabled = busy || data.selected === 0;
    $("dictionary-import-clear").disabled = busy || data.selected === 0;
    var list = $("dictionary-import-entries");
    list.replaceChildren();
    data.items.forEach(function (item) {
      var li = document.createElement("li");
      var row = document.createElement("label");
      row.className = "dictionary-import-row";
      var checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = item.selected;
      checkbox.disabled = busy;
      checkbox.setAttribute("aria-label", item.surface + "を取り込む");
      checkbox.addEventListener("change", function () {
        void updateDictionaryImportSelection(item.language, item.identity, checkbox.checked);
      });
      var words = document.createElement("span");
      words.className = "dictionary-import-word";
      var name = document.createElement("strong");
      name.textContent = item.surface;
      var annotation = document.createElement("small");
      annotation.textContent = (item.language === "ja" ? "日本語" : "English") +
        " · " + (item.relation === "conflict" ? "競合" : "新規") +
        " · " + item.pronunciation;
      words.append(name, annotation);
      row.append(checkbox, words);
      li.append(row);
      var details = document.createElement("details");
      var summary = document.createElement("summary");
      summary.textContent = "発音・品詞を比較";
      details.append(summary);
      var incoming = document.createElement("p");
      incoming.textContent = "取り込み: " + item.pronunciation;
      var existing = document.createElement("p");
      existing.textContent = item.existing_pronunciation ?
        "登録済み: " + item.existing_pronunciation : "登録済み: なし";
      details.append(incoming, existing);
      if (item.language === "ja") {
        var typeLabel = document.createElement("label");
        typeLabel.textContent = "取り込み後の品詞";
        var typeSelect = document.createElement("select");
        [["PROPER_NOUN","固有名詞"],["COMMON_NOUN","普通名詞"],
         ["VERB","動詞"],["ADJECTIVE","形容詞"],["SUFFIX","接尾辞"]]
          .forEach(function (optionData) {
            var option = document.createElement("option");
            option.value = optionData[0];
            option.textContent = optionData[1];
            typeSelect.append(option);
          });
        typeSelect.value = item.word_type;
        typeSelect.addEventListener("change", function () {
          void updateDictionaryImportWordType(item.identity, typeSelect.value);
        });
        typeLabel.append(typeSelect);
        details.append(typeLabel);
        if (item.existing_word_type) {
          var currentType = document.createElement("p");
          currentType.textContent = "登録済みの品詞: " +
            dictionaryTypeLabel(item.existing_word_type);
          details.append(currentType);
        }
      }
      li.append(details);
      list.append(li);
    });
  }
  function dictionaryPronunciationDirty() {
    return currentView === "dictionary-pron" && dictPronOpening !== null &&
      $("dictionary-pron-text").value !== dictPronOpening;
  }
  function guardDictionaryPronunciationDraft() {
    return !dictionaryPronunciationDirty() ||
      window.confirm("未反映の辞書発音変更を破棄しますか？");
  }
  function dictionaryEntryDirty() {
    if (!dictEntry || !dictEntryOriginal) return false;
    return JSON.stringify(dictionaryFormValue()) !== JSON.stringify(dictEntryOriginal);
  }
  function dictionaryFormValue() {
    return { surface: $("dictionary-surface").value,
      notation: dictEntry ? dictEntry.notation : "",
      word_type: $("dictionary-word-type").value,
      priority: Number($("dictionary-priority").value) };
  }
  function dictionaryTypeLabel(value) {
    return { PROPER_NOUN: "固有名詞", COMMON_NOUN: "普通名詞",
      VERB: "動詞", ADJECTIVE: "形容詞", SUFFIX: "接尾辞" }[value] || value;
  }
  async function loadDictionary() {
    if (!sessionId || !token) return;
    var requestNo = ++dictListRequest;
    var url = dictionaryPath() + "/" + encodeURIComponent(dictLanguage) +
      "?sort=" + encodeURIComponent(dictSort) + "&query=" + encodeURIComponent(dictQuery) +
      "&word_type=" + encodeURIComponent(dictType);
    var data = await request("GET", url);
    if (requestNo !== dictListRequest) return;
    dictData = data;
    renderDictionary();
  }
  function renderDictionary() {
    $("dictionary-ja").setAttribute("aria-pressed", String(dictLanguage === "ja"));
    $("dictionary-en").setAttribute("aria-pressed", String(dictLanguage === "en"));
    $("dictionary-filter-type-label").hidden = dictLanguage !== "ja";
    $("dictionary-sort").replaceChildren();
    dictionarySortModes[dictLanguage].forEach(function (option) {
      var node = document.createElement("option");
      node.value = option[0];
      node.textContent = option[1];
      $("dictionary-sort").append(node);
    });
    $("dictionary-sort").value = dictSort;
    $("dictionary-query").value = dictQuery;
    $("dictionary-filter-type").value = dictType;
    $("dictionary-words").replaceChildren();
    if (!dictData) return;
    $("dictionary-count").textContent = dictData.shown + "/" + dictData.total + "件";
    if (!dictData.entries.length) {
      var empty = document.createElement("li");
      empty.className = "help-text";
      empty.textContent = "該当する単語はありません。";
      $("dictionary-words").append(empty);
    }
    dictData.entries.forEach(function (row) {
      var li = document.createElement("li");
      var button = document.createElement("button");
      button.type = "button";
      button.className = "dictionary-word";
      var name = document.createElement("strong");
      name.textContent = row.surface;
      var pronunciation = document.createElement("span");
      pronunciation.textContent = row.notation;
      button.append(name, pronunciation);
      if (dictLanguage === "ja") {
        var meta = document.createElement("small");
        meta.textContent = dictionaryTypeLabel(row.word_type) + " · 優先度 " + row.priority;
        button.append(meta);
      }
      button.addEventListener("click", function () { openDictionaryEntry(row); });
      li.append(button);
      $("dictionary-words").append(li);
    });
  }
  function dictionaryPushHistory(view) {
    if (dictionaryHistoryDestination) return;
    try {
      var depth = dictionaryHistoryDepth + 1;
      window.history.pushState({ voicegerDictionary: true,
        sessionId: sessionId, view: view, depth: depth }, "");
      dictionaryHistoryDepth = depth;
    } catch (_ignored) { /* Browser may restrict history. */ }
  }
  function navigateGlobal(destination) {
    if (busy || !sessionId || dictionaryHistoryDestination) return;
    if (destination === currentView) return;
    if (currentView === "session" && settingsHistoryActive) {
      if (destination === "dictionary") dictReturnView = settingsReturnView;
      settingsHistoryDestination = destination;
      window.history.back();
      return;
    }
    if (currentView.indexOf("dictionary") === 0) {
      if (!guardDraft()) return;
      // Unwind only the nested dictionary history created by this session.
      var steps = destination === "dictionary" ?
        Math.max(0, dictionaryHistoryDepth - 1) : dictionaryHistoryDepth;
      if (steps > 0) {
        requestDictionaryHistoryExit(destination, -steps);
        return;
      }
      dictPronOpening = null;
      dictEntry = null;
      dictEntryOriginal = null;
      showView(destination, true);
      return;
    }
    if (destination === "dictionary") {
      dictReturnView = currentView === "pronunciation" || currentView === "section" ?
        "item" : currentView === "recipe" ? "list" : currentView;
      dictEntry = null;
      dictEntryOriginal = null;
    }
    showView(destination);
  }
  function dictionaryBack() {
    if (dictionaryHistoryDestination || busy || !(currentView === "dictionary-pron" ?
        guardDictionaryPronunciationDraft() : guardDraft())) return;
    if (dictionaryHistoryDepth > 0) {
      // The popstate handler owns state cleanup and the resulting screen.
      // Resolve the target on popstate, not from currentView alone.
      requestDictionaryHistoryExit("dictionary-back", -1);
      return;
    }
    var destination = currentView === "dictionary-pron" ? "dictionary-entry" :
      currentView === "dictionary-import-review" ? "dictionary-management" :
      (currentView === "dictionary-entry" || currentView === "dictionary-management") ?
      "dictionary" : dictReturnView;
    dictPronOpening = null;
    if (destination !== "dictionary-entry") {
      dictEntry = null;
      dictEntryOriginal = null;
    }
    showView(destination, true);
  }
  // The destination doubles as the in-flight guard until the first popstate.
  // Repeated Android taps must never schedule another browser history exit.
  function requestDictionaryHistoryExit(destination, delta) {
    if (dictionaryHistoryDestination) return false;
    dictionaryHistoryDestination = destination;
    try {
      if (delta === -1) window.history.back();
      else window.history.go(delta);
    } catch (_error) {
      dictionaryHistoryDestination = null;
      feedback("履歴移動に失敗しました。もう一度操作してください。");
      return false;
    }
    return true;
  }
  function revealDictionaryRegistrationError(id) {
    var notice = $(id);
    notice.scrollIntoView({ behavior: "auto", block: "center" });
    notice.focus({ preventScroll: true });
  }
  function hideDictionarySaveError() {
    $("dictionary-save-error").hidden = true;
    $("dictionary-save-error").textContent = "";
  }
  function showDictionarySaveError(message) {
    hideDictionaryDuplicate();
    $("dictionary-save-error").textContent = message;
    $("dictionary-save-error").hidden = false;
    feedback("");
    revealDictionaryRegistrationError("dictionary-save-error");
  }
  function hideDictionaryDuplicate() {
    hideDictionarySaveError();
    dictDuplicate = null;
    $("dictionary-duplicate").hidden = true;
    $("dictionary-duplicate-title").textContent = "";
    $("dictionary-duplicate-description").textContent = "";
  }
  function dictionaryDuplicateFor(data, matches) {
    if (!matches || !Array.isArray(matches.entries)) return null;
    return matches.entries.find(function (row) {
      return dictLanguage === "en" || row.word_type === data.word_type;
    }) || null;
  }
  function showDictionaryDuplicate(row) {
    hideDictionarySaveError();
    dictDuplicate = { surface: row.surface, language: dictLanguage };
    $("dictionary-duplicate-title").textContent =
      "「" + row.surface + "」は登録済みです";
    $("dictionary-duplicate-description").textContent = dictLanguage === "en" ?
      "英語辞書では大文字・小文字を区別しません。新規追加はできません。登録済みの単語を編集してください。" :
      "日本語辞書では表記と品詞の組み合わせが同じ単語を重複登録できません（" +
      dictionaryTypeLabel(row.word_type) + "）。登録済みの単語を編集してください。";
    $("dictionary-duplicate").hidden = false;
    feedback("");
    revealDictionaryRegistrationError("dictionary-duplicate");
  }
  function viewDictionaryDuplicate() {
    if (dictionaryHistoryDestination || busy || !dictDuplicate || !guardDraft()) return;
    dictQuery = dictDuplicate.surface;
    dictSort = "surface_asc";
    dictType = "ALL";
    hideDictionaryDuplicate();
    if (dictionaryHistoryDepth > 0) {
      requestDictionaryHistoryExit("dictionary", -1);
    } else {
      dictEntry = null;
      dictEntryOriginal = null;
      showView("dictionary", true);
    }
  }
  function renderDictionaryEntryLanguage() {
    // Language is selectable only while adding a new word, never on edit.
    var isNew = Boolean(dictEntry && !dictEntry.id);
    $("dictionary-entry-tabs").hidden = !isNew;
    $("dictionary-entry-ja").setAttribute("aria-pressed", String(dictLanguage === "ja"));
    $("dictionary-entry-en").setAttribute("aria-pressed", String(dictLanguage === "en"));
    $("dictionary-ja-fields").hidden = dictLanguage !== "ja";
  }
  async function switchDictionaryEntryLanguage(language) {
    if (busy || currentView !== "dictionary-entry" || !dictEntry || dictEntry.id ||
        (language !== "ja" && language !== "en") || language === dictLanguage) return;
    if (dictionaryEntryDirty() &&
        !window.confirm("入力中の単語を破棄して言語を切り替えますか？")) return;
    setBusy(true);
    try {
      // Fetch the target dictionary/revision *before* replacing the draft.
      // A failed request must preserve the source language and all inputs.
      var url = dictionaryPath() + "/" + encodeURIComponent(language) +
        "?sort=surface_asc&query=&word_type=ALL";
      var target = await request("GET", url);
      ++dictListRequest; // Discard an outstanding old-language list response.
      dictLanguage = language;
      dictSort = "surface_asc"; dictQuery = ""; dictType = "ALL";
      dictData = target;
      dictEntry = { id: null, language: language, surface: "", notation: "",
        word_type: "PROPER_NOUN", priority: 5 };
      $("dictionary-surface").value = "";
      $("dictionary-word-type").value = "PROPER_NOUN";
      $("dictionary-priority").value = "5";
      $("dictionary-pron-value").textContent = "未入力";
      dictEntryOriginal = dictionaryFormValue();
      hideDictionaryDuplicate();
      renderDictionary();
      renderDictionaryEntryLanguage();
      feedback("");
    } catch (error) { feedback(error.message); }
    finally { setBusy(false); }
  }
  function openDictionaryEntry(row) {
    if (!dictData || busy || dictionaryHistoryDestination) return;
    var entry = row || { id: null, surface: "", notation: "",
      word_type: "PROPER_NOUN", priority: 5 };
    dictEntry = { id: entry.id, language: dictLanguage,
      surface: entry.surface, notation: entry.notation,
      word_type: entry.word_type || "PROPER_NOUN",
      priority: entry.priority === undefined ? 5 : entry.priority };
    $("dictionary-surface").value = dictEntry.surface;
    $("dictionary-word-type").value = dictEntry.word_type;
    $("dictionary-priority").value = String(dictEntry.priority);
    renderDictionaryEntryLanguage();
    $("dictionary-delete").hidden = !entry.id;
    $("dictionary-entry-title").textContent = entry.id ? "単語を編集" : "単語を追加";
    dictEntryOriginal = dictionaryFormValue();
    hideDictionaryDuplicate();
    $("dictionary-pron-value").textContent = dictEntry.notation || "未入力";
    showView("dictionary-entry", true);
    dictionaryPushHistory("dictionary-entry");
  }
  function enterDictionaryPronunciation() {
    if (!dictEntry || busy || dictionaryHistoryDestination) return;
    dictPronOpening = dictEntry.notation;
    $("dictionary-pron-context").textContent = $("dictionary-surface").value;
    $("dictionary-pron-title").textContent = dictLanguage === "en" ? "英語発音編集" : "発音編集";
    $("dictionary-pron-text").value = dictPronOpening;
    clearDictionaryPronunciationError();
    showView("dictionary-pron", true);
    dictionaryPushHistory("dictionary-pron");
    var input = $("dictionary-pron-text");
    input.focus({ preventScroll: true });
    input.setSelectionRange(input.value.length, input.value.length);
    dictSelection = { start: input.selectionStart, end: input.selectionEnd };
  }
  function leaveDictionaryPronunciation() {
    if (dictionaryHistoryDestination || !dictEntry || busy ||
        !guardDictionaryPronunciationDraft()) return;
    if (dictionaryHistoryDepth > 0) {
      requestDictionaryHistoryExit("dictionary-entry", -1);
    } else {
      dictPronOpening = null;
      showView("dictionary-entry", true);
    }
  }
  function clearDictionaryPronunciationError() {
    $("dictionary-pron-error").hidden = true;
    $("dictionary-pron-error").textContent = "";
    $("dictionary-pron-text").removeAttribute("aria-invalid");
  }
  function showDictionaryPronunciationError(error, notation, operation) {
    var explanation = error.message;
    if (error.conflictCode === "invalid_dictionary") {
      if (dictLanguage === "ja") {
        explanation = /\s/.test(notation) ?
          "日本語辞書の発音は空白で区切れません。空白を削除して、1つのアクセント句にしてください。アクセントは ' または [ ] で指定します。" :
          "日本語の発音形式を確認してください。1つのアクセント句として、アクセントは ' または [ ] で指定してください。";
      } else {
        explanation = "ARPAbetの音素と強勢数字（0/1/2）を確認してください。";
      }
    }
    $("dictionary-pron-error").textContent = operation + "できません。 " + explanation;
    $("dictionary-pron-error").hidden = false;
    $("dictionary-pron-text").setAttribute("aria-invalid", "true");
    feedback("");
    $("dictionary-pron-error").scrollIntoView({ behavior: "auto", block: "center" });
    $("dictionary-pron-error").focus({ preventScroll: true });
  }
  async function applyDictionaryPronunciation(event) {
    event.preventDefault();
    if (!dictEntry || busy || dictionaryHistoryDestination) return;
    var notation = $("dictionary-pron-text").value;
    var surface = $("dictionary-surface").value;
    clearDictionaryPronunciationError();
    setBusy(true);
    try {
      // The core validator also powers Save: never silently Apply bad drafts.
      await request("POST", dictionaryPath() + "/pronunciation/validate", {
        language: dictLanguage, surface: surface, notation: notation
      });
      dictEntry.notation = notation;
      $("dictionary-pron-value").textContent = notation || "未入力";
      if (dictionaryHistoryDepth > 0) {
        requestDictionaryHistoryExit("dictionary-entry", -1);
      } else {
        dictPronOpening = null;
        showView("dictionary-entry", true);
      }
    } catch (error) { showDictionaryPronunciationError(error, notation, "反映"); }
    finally { setBusy(false); }
  }
  function rememberDictionarySelection() {
    var input = $("dictionary-pron-text");
    dictSelection = { start: input.selectionStart, end: input.selectionEnd };
  }
  async function waitDictionaryOperation(op) {
    while (op.status === "running" || op.status === "cancelling") {
      await new Promise(function (resolve) { setTimeout(resolve, 500); });
      op = await request("GET", "/api/web/sessions/" + encodeURIComponent(sessionId) +
        "/operations/" + encodeURIComponent(op.id));
    }
    if (op.status !== "succeeded")
      throw new Error(op.status === "cancelled" ? "キャンセルしました。" :
        (op.error || "辞書の音声処理が完了しませんでした。"));
    return op.result || {};
  }
  async function dictionaryGenerate() {
    if (!dictEntry || busy) return;
    var surface = $("dictionary-surface").value;
    setBusy(true);
    try {
      var op = await request("POST", dictionaryPath() + "/pronunciation/generate",
        { language: dictLanguage, surface: surface });
      var result = await waitDictionaryOperation(op);
      if (!dictEntry) return;
      dictEntry.notation = result.notation;
      $("dictionary-pron-value").textContent = result.notation || "未入力";
      feedback("発音を生成しました。保存前にPreviewで確認してください。");
    } catch (error) { feedback(error.message); }
    finally { setBusy(false); }
  }
  async function dictionaryPreview() {
    if (!dictEntry || busy) return;
    var notation = $("dictionary-pron-text").value;
    clearDictionaryPronunciationError();
    clearPlayer();
    setBusy(true);
    try {
      var op = await request("POST", dictionaryPath() + "/pronunciation/preview", {
        language: dictLanguage, surface: $("dictionary-surface").value,
        notation: notation
      });
      var result = await waitDictionaryOperation(op);
      var response = await fetch(dictionaryPath() + "/audio/preview/" +
        encodeURIComponent(result.preview_id), {
        headers: { Authorization: "Bearer " + token }, cache: "no-store",
        credentials: "same-origin"
      });
      if (!response.ok) throw new Error("Preview音声を取得できませんでした。");
      var bytes = await response.blob();
      if (!bytes.size || bytes.type.indexOf("audio/") !== 0)
        throw new Error("Preview音声が無効です。");
      playingUrl = URL.createObjectURL(bytes);
      var player = $("phone-player");
      player.src = playingUrl;
      player.hidden = false;
      try { await player.play(); }
      catch (_ignored) { feedback("プレイヤーの再生ボタンを押してください。"); }
    } catch (error) { showDictionaryPronunciationError(error, notation, "Preview"); }
    finally { setBusy(false); }
  }
  function dictionaryFinish(message) {
    if (dictionaryHistoryDestination) return;
    if (dictionaryHistoryDepth > 1) {
      dictionaryHistoryNotice = message;
      if (!requestDictionaryHistoryExit("dictionary", 1 - dictionaryHistoryDepth))
        dictionaryHistoryNotice = "";
    } else {
      dictEntry = null;
      dictEntryOriginal = null;
      showView("dictionary", true);
      feedback(message);
    }
  }
  async function dictionarySave(event) {
    event.preventDefault();
    if (busy || dictionaryHistoryDestination || !dictEntry || !dictData) return;
    var data = dictionaryFormValue();
    hideDictionaryDuplicate();
    if (!data.notation.trim()) { showDictionarySaveError("発音を入力してください。"); return; }
    if (dictLanguage === "ja" &&
      (!Number.isInteger(data.priority) || data.priority < 0 || data.priority > 10)) {
      showDictionarySaveError("優先度は0〜10で指定してください。"); return;
    }
    setBusy(true);
    try {
      // Explain duplicate failures beside Save before sending a failing write.
      // The Core-backed endpoint owns casefold and Japanese identity rules.
      if (!dictEntry.id) {
        var matches = await dictionaryQuickMatches(dictLanguage, data.surface);
        var duplicate = dictionaryDuplicateFor(data, matches);
        if (duplicate) {
          showDictionaryDuplicate(duplicate);
          return;
        }
        hideDictionaryDuplicate();
      }
      var payload = { ...data, language: dictLanguage, expected_revision: dictData.revision };
      var address = dictionaryPath() + "/words" +
        (dictEntry.id ? "/" + encodeURIComponent(dictEntry.id) : "");
      var result = await request(dictEntry.id ? "PUT" : "POST", address, payload);
      dictionaryFinish(result.changed ? "辞書に保存しました。" : "変更はありません。");
    } catch (error) {
      if (!dictEntry.id && error.conflictCode === "invalid_dictionary") {
        // Another client may have added the same word after our initial check.
        try {
          var latestMatches = await dictionaryQuickMatches(dictLanguage, data.surface);
          var lateDuplicate = dictionaryDuplicateFor(data, latestMatches);
          if (lateDuplicate) {
            showDictionaryDuplicate(lateDuplicate);
            return;
          }
        } catch (_ignored) { /* Keep the original validated error. */ }
      }
      showDictionarySaveError(error.conflictCode === "revision_conflict" ?
        "辞書が更新されています。入力内容を保持しています。戻って一覧を再取得してください。" :
        error.message);
    } finally { setBusy(false); }
  }
  async function dictionaryDelete() {
    if (!dictEntry || !dictEntry.id || busy || dictionaryHistoryDestination ||
        !window.confirm("この単語を辞書から削除しますか？")) return;
    setBusy(true);
    try {
      await request("DELETE", dictionaryPath() + "/words/" +
        encodeURIComponent(dictEntry.id) + "?language=" +
        encodeURIComponent(dictLanguage) + "&expected_revision=" +
        encodeURIComponent(dictData.revision));
      dictionaryFinish("単語を削除しました。");
    } catch (error) { feedback(error.message); }
    finally { setBusy(false); }
  }

  // Quick Save never Applies the source pronunciation or modifies Batch Takes.
  // A changed Surface must not retain the sentence's pronunciation.
  function dictionaryQuickMatches(language, surface) {
    return request("GET", dictionaryPath() + "/" + encodeURIComponent(language) +
      "/matches?surface=" + encodeURIComponent(surface));
  }
  function dictionaryQuickPriority() {
    if (dictQuickPriorityEdited) return;
    var selectedType = $("dictionary-quick-type").value;
    var match = dictQuickMatches.find(function (row) {
      return row.word_type === selectedType;
    });
    $("dictionary-quick-priority").value = String(match ? match.priority : 5);
  }
  function clearDictionaryQuickError() {
    $("dictionary-quick-error").hidden = true;
    $("dictionary-quick-error").textContent = "";
    $("dictionary-quick-notation").removeAttribute("aria-invalid");
  }
  function showDictionaryQuickError(message) {
    $("dictionary-quick-error").textContent = message;
    $("dictionary-quick-error").hidden = false;
    $("dictionary-quick-notation").setAttribute("aria-invalid", "true");
    feedback("");
    $("dictionary-quick-error").scrollIntoView({ behavior: "auto", block: "center" });
    $("dictionary-quick-error").focus({ preventScroll: true });
  }
  function dictionaryQuickSurfaceChanged() {
    if ($("dictionary-quick-form").hidden) return;
    var surface = $("dictionary-quick-surface").value;
    if (dictQuickPronSurface === surface) return;
    // Never attempt automatic substring-to-phoneme mapping.
    dictQuickPronSurface = null;
    $("dictionary-quick-notation").value = "";
    $("dictionary-quick-hint").textContent =
      "Surfaceを変更しました。この単語の発音を生成するか入力してください。";
    clearDictionaryQuickError();
    clearPlayer();
  }
  function dictionaryQuickNotationChanged() {
    if ($("dictionary-quick-form").hidden) return;
    // Explicit manual edits after a Surface change belong to this Surface.
    dictQuickPronSurface = $("dictionary-quick-surface").value;
    clearDictionaryQuickError();
    clearPlayer();
  }
  function dictionaryQuickDraft() {
    var surface = $("dictionary-quick-surface").value;
    var notation = $("dictionary-quick-notation").value;
    if (!surface.trim()) {
      showDictionaryQuickError("Surfaceに登録する単語を入力してください。");
      return null;
    }
    if (dictQuickPronSurface !== surface || !notation.trim()) {
      showDictionaryQuickError("この単語の発音を生成するか入力してから保存してください。");
      return null;
    }
    return { surface: surface, notation: notation,
      language: $("dictionary-quick-form").dataset.language };
  }
  async function openDictionaryQuick() {
    if (busy || currentView !== "pronunciation") return;
    var language = pronunciationTarget && pronunciationTarget.language || "ja";
    var seed = $("pronunciation-caption").textContent;
    dictQuickMatches = [];
    dictQuickPriorityEdited = false;
    setBusy(true);
    try {
      var snapshot = await dictionaryQuickMatches(language, seed);
      dictQuickMatches = snapshot.entries;
      $("dictionary-quick-form").dataset.language = language;
      $("dictionary-quick-form").dataset.revision = snapshot.revision;
      $("dictionary-quick-surface").value = seed;
      $("dictionary-quick-notation").value = $("pronunciation-text").value;
      dictQuickPronSurface = seed;
      $("dictionary-quick-hint").textContent =
        "現在の発音を使用します。単語だけ登録する場合はSurfaceを変更してください。";
      clearDictionaryQuickError();
      document.querySelectorAll(".dictionary-quick-ja").forEach(function (node) {
        node.hidden = language !== "ja";
      });
      $("dictionary-quick-type").value = "PROPER_NOUN";
      dictionaryQuickPriority();
      $("dictionary-quick-form").hidden = false;
      feedback("");
    } catch (error) { feedback(error.message); }
    finally { setBusy(false); }
  }
  async function generateDictionaryQuick() {
    if (busy || currentView !== "pronunciation" || $("dictionary-quick-form").hidden) return;
    var surface = $("dictionary-quick-surface").value;
    var language = $("dictionary-quick-form").dataset.language;
    if (!surface.trim()) {
      showDictionaryQuickError("Surfaceに登録する単語を入力してください。");
      return;
    }
    clearDictionaryQuickError();
    setBusy(true);
    try {
      var op = await request("POST", dictionaryPath() + "/pronunciation/generate",
        { language: language, surface: surface });
      var result = await waitDictionaryOperation(op);
      if (!result.notation) throw new Error("発音を生成できませんでした。");
      $("dictionary-quick-notation").value = result.notation;
      dictQuickPronSurface = surface;
      $("dictionary-quick-hint").textContent =
        "生成した発音を確認してください。必要なら編集できます。";
      feedback("");
    } catch (error) { showDictionaryQuickError(error.message); }
    finally { setBusy(false); }
  }
  async function previewDictionaryQuick() {
    if (busy || currentView !== "pronunciation" || $("dictionary-quick-form").hidden) return;
    clearDictionaryQuickError();
    var draft = dictionaryQuickDraft();
    if (!draft) return;
    clearPlayer();
    setBusy(true);
    try {
      var op = await request("POST", dictionaryPath() + "/pronunciation/preview", draft);
      var result = await waitDictionaryOperation(op);
      var response = await fetch(dictionaryPath() + "/audio/preview/" +
        encodeURIComponent(result.preview_id), {
        headers: { Authorization: "Bearer " + token }, cache: "no-store",
        credentials: "same-origin"
      });
      if (!response.ok) throw new Error("Preview音声を取得できませんでした。");
      var bytes = await response.blob();
      if (!bytes.size || bytes.type.indexOf("audio/") !== 0)
        throw new Error("Preview音声が無効です。");
      playingUrl = URL.createObjectURL(bytes);
      var player = $("phone-player");
      player.src = playingUrl;
      player.hidden = false;
      try { await player.play(); }
      catch (_ignored) { feedback("プレイヤーの再生ボタンを押してください。"); }
    } catch (error) { showDictionaryQuickError(error.message); }
    finally { setBusy(false); }
  }
  async function saveDictionaryQuick(event) {
    event.preventDefault();
    if (busy || currentView !== "pronunciation" ||
        $("dictionary-quick-form").hidden) return;
    clearDictionaryQuickError();
    var draft = dictionaryQuickDraft();
    if (!draft) return;
    var language = draft.language;
    var surface = draft.surface;
    var wordType = $("dictionary-quick-type").value;
    setBusy(true);
    try {
      // Resolve again after Surface edits: existing word and revision checks
      // apply identically to generated and manually edited pronunciations.
      var snapshot = await dictionaryQuickMatches(language, surface);
      if (snapshot.revision !== $("dictionary-quick-form").dataset.revision)
        throw new Error("辞書が更新されています。登録画面を開き直してください。");
      var candidates = snapshot.entries.filter(function (word) {
        return language === "en" || word.word_type === wordType;
      });
      if (candidates.length > 1) {
        showDictionaryQuickError("同じ表記の登録が複数あります。辞書一覧で対象を確認してください。");
        return;
      }
      if (language === "ja" && !dictQuickPriorityEdited) {
        $("dictionary-quick-priority").value =
          String(candidates.length ? candidates[0].priority : 5);
      }
      if (candidates.length && !window.confirm(
        "既存の辞書単語をこの発音で更新しますか？")) return;
      var payload = {
        expected_revision: snapshot.revision,
        language: language, surface: surface, notation: draft.notation,
        word_type: wordType, priority: Number($("dictionary-quick-priority").value)
      };
      var address = dictionaryPath() + "/words" +
        (candidates.length ? "/" + encodeURIComponent(candidates[0].id) : "");
      await request(candidates.length ? "PUT" : "POST", address, payload);
      $("dictionary-quick-form").hidden = true;
      dictQuickPronSurface = null;
      feedback("辞書に保存しました。Batch Itemの発音とTakeは変更していません。");
    } catch (error) { showDictionaryQuickError(error.message); }
    finally { setBusy(false); }
  }

  $("dictionary-back").addEventListener("click", dictionaryBack);
  $("dictionary-manage").addEventListener("click", openDictionaryManagement);
  $("dictionary-management-back").addEventListener("click", dictionaryBack);
  $("dictionary-ja").addEventListener("click", function () {
    if (dictLanguage === "ja" || busy) return;
    dictLanguage = "ja"; dictSort = "surface_asc"; dictQuery = ""; dictType = "ALL";
    loadDictionary().catch(function (error) { feedback(error.message); });
  });
  $("dictionary-en").addEventListener("click", function () {
    if (dictLanguage === "en" || busy) return;
    dictLanguage = "en"; dictSort = "surface_asc"; dictQuery = ""; dictType = "ALL";
    loadDictionary().catch(function (error) { feedback(error.message); });
  });
  $("dictionary-sort").addEventListener("change", function () {
    dictSort = this.value;
    loadDictionary().catch(function (error) { feedback(error.message); });
  });
  $("dictionary-query").addEventListener("input", function () {
    dictQuery = this.value;
    loadDictionary().catch(function (error) { feedback(error.message); });
  });
  $("dictionary-filter-type").addEventListener("change", function () {
    dictType = this.value;
    loadDictionary().catch(function (error) { feedback(error.message); });
  });
  $("dictionary-add").addEventListener("click", function () { openDictionaryEntry(null); });
  $("dictionary-entry-ja").addEventListener("click", function () {
    void switchDictionaryEntryLanguage("ja");
  });
  $("dictionary-entry-en").addEventListener("click", function () {
    void switchDictionaryEntryLanguage("en");
  });
  $("dictionary-entry-back").addEventListener("click", dictionaryBack);
  $("dictionary-pron-open").addEventListener("click", enterDictionaryPronunciation);
  $("dictionary-entry-form").addEventListener("submit", dictionarySave);
  $("dictionary-surface").addEventListener("input", hideDictionaryDuplicate);
  $("dictionary-word-type").addEventListener("change", hideDictionaryDuplicate);
  $("dictionary-duplicate-view").addEventListener("click", viewDictionaryDuplicate);
  $("dictionary-delete").addEventListener("click", dictionaryDelete);
  $("dictionary-generate").addEventListener("click", dictionaryGenerate);
  $("dictionary-pron-back").addEventListener("click", leaveDictionaryPronunciation);
  $("dictionary-pron-cancel").addEventListener("click", leaveDictionaryPronunciation);
  $("dictionary-pron-reset").addEventListener("click", function () {
    if (busy || dictPronOpening === null) return;
    $("dictionary-pron-text").value = dictPronOpening;
    clearDictionaryPronunciationError();
    $("dictionary-pron-text").focus({ preventScroll: true });
    $("dictionary-pron-text").setSelectionRange(dictPronOpening.length, dictPronOpening.length);
    rememberDictionarySelection();
  });
  $("dictionary-pron-form").addEventListener("submit", applyDictionaryPronunciation);
  $("dictionary-preview").addEventListener("click", dictionaryPreview);
  $("dictionary-pron-text").addEventListener("input", clearDictionaryPronunciationError);
  $("dictionary-pron-text").addEventListener("compositionstart", function () { dictComposing = true; });
  $("dictionary-pron-text").addEventListener("compositionend", function () {
    dictComposing = false; rememberDictionarySelection();
  });
  ["select", "keyup", "mouseup", "touchend", "input"].forEach(function (type) {
    $("dictionary-pron-text").addEventListener(type, rememberDictionarySelection);
  });
  $("dictionary-pron-assists").querySelectorAll(
    "[data-dictionary-insert], [data-dictionary-backspace]").forEach(function (button) {
    button.addEventListener("mousedown", function (event) { event.preventDefault(); });
    var composingAtPointerDown = false;
    button.addEventListener("pointerdown", function () {
      composingAtPointerDown = dictComposing;
      if (!dictComposing) rememberDictionarySelection();
    });
    button.addEventListener("pointercancel", function () { composingAtPointerDown = false; });
    button.addEventListener("click", function () {
      var suppress = composingAtPointerDown;
      composingAtPointerDown = false;
      if (busy || suppress || dictComposing || currentView !== "dictionary-pron") return;
      replaceAtCaret($("dictionary-pron-text"), dictSelection,
        button.dataset.dictionaryInsert || "",
        button.hasAttribute("data-dictionary-backspace"));
      rememberDictionarySelection();
    });
  });
  $("open-dictionary-quick").addEventListener("click", openDictionaryQuick);
  $("dictionary-quick-surface").addEventListener("input", dictionaryQuickSurfaceChanged);
  $("dictionary-quick-notation").addEventListener("input", dictionaryQuickNotationChanged);
  $("dictionary-quick-generate").addEventListener("click", generateDictionaryQuick);
  $("dictionary-quick-preview").addEventListener("click", previewDictionaryQuick);
  $("dictionary-quick-type").addEventListener("change", dictionaryQuickPriority);
  $("dictionary-quick-priority").addEventListener("input", function () {
    dictQuickPriorityEdited = true;
  });
  $("dictionary-quick-cancel").addEventListener("click", function () {
    if (busy) return;
    $("dictionary-quick-form").hidden = true;
    dictQuickPronSurface = null;
    clearDictionaryQuickError();
    clearPlayer();
  });
  $("dictionary-quick-form").addEventListener("submit", saveDictionaryQuick);
  $("dictionary-export-native").addEventListener("click", function () {
    void exportDictionary("native");
  });
  $("dictionary-export-voicevox").addEventListener("click", function () {
    void exportDictionary("voicevox");
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
