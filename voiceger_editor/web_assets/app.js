"use strict";

// This foundation is read-only: no session, synthesis or filesystem actions.
(function () {
  var statusNode = document.getElementById("connection-status");
  var versionNode = document.getElementById("server-version");
  var indicator = document.querySelector(".connection-indicator");
  if (!statusNode || !versionNode || !indicator) return;

  fetch("/api/web/health", { method: "GET", cache: "no-store", credentials: "same-origin" })
    .then(function (response) {
      if (!response.ok) throw new Error("Health check failed");
      return response.json();
    })
    .then(function (data) {
      if (!data || data.status !== "ok" || typeof data.version !== "string") {
        throw new Error("Invalid health response");
      }
      statusNode.textContent = "Webサーバーに接続済み";
      versionNode.textContent = "Voiceger Editor " + data.version;
      indicator.classList.add("is-online");
    })
    .catch(function () {
      statusNode.textContent = "接続状態を確認できません";
      versionNode.textContent = "ページを再読み込みして確認してください";
      indicator.classList.remove("is-online");
    });
})();
