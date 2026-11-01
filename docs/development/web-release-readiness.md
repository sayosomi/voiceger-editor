# Issue #335 — Web final acceptance and release-readiness record

**Status: NOT READY TO RELEASE** (2026-11-02 JST; initial inventory only).
This is a development checklist and an **unapproved draft** of release notes, not publication instructions. The user-facing v0.1.1 guides and published release are unchanged.

## Grounded baseline

- Repository: `sayosomi/voiceger-editor`
- Current base `main`: `a5b38a5be945f281a0464fcbca906e53d99b9764`.
- Published latest release (GitHub): `v0.1.1` (2026-10-28 UTC); its release text describes the TUI and compatibility API. Do not silently rewrite those published statements.
- Source package version: `voiceger_editor/_version.py` = `0.1.1`; `pyproject.toml` reads this dynamically. **No next release version has been selected.**
- Difference from `v0.1.1` to base main: GitHub compare reports **24 commits ahead / 0 behind**. The substantive additions include the Web frontend, session/batch/pronunciation/Take/dictionary/settings/output routes and frontend assets; additional TUI/dictionary and shared core changes also exist.
- Baseline GitHub Actions `CI` run [41319648352](https://github.com/sayosomi/voiceger-editor/actions/runs/41319648352) SUCCESS at this exact main. The CI workflow includes Python 3.9 unit tests, Windows startup boundary, and Linux wheel/sdist clean-install smoke; the package smoke checks presence of the three Web static assets. This is **not** real Mac Voiceger synthesis or Android/Tailscale acceptance.

## Checklist (check only on direct evidence at intended release HEAD)

- [x] Baseline latest published release/tag verified: `v0.1.1`.
- [x] Current source version and optional dependencies inspected: `[tui]`, `[api]`, `[web]`, `[lab]`; Python `==3.9.*` in `pyproject.toml`.
- [x] Baseline CI packages Web HTML/CSS/JS in the wheel and smoke-installs `[api,tui,lab,web]`; Windows startup CI is a **limited** startup check only.
- [x] Initial internal [TUI↔Web matrix](tui-web-parity-matrix.md) inventoried with explicit unverified gates.
- [ ] Independent accuracy/semantic review of the matrix, resolve all known gaps.
- [ ] Explicit Human approval of **exact JA and EN user-facing text**, before any user-doc write.
- [ ] Update README / indices / setup / navigation / compatibility user docs and verify link/translation consistency.
- [ ] Verify documented Mac-local Web startup command and token/auth steps against actual packaged entrypoint (no accidental `0.0.0.0` bind).
- [ ] Run final exact-head aggregate `CI` after all proposed changes, verify Python 3.9 packaging and optional dependency requirements.
- [ ] Verify opt-in real Voiceger synthesis/integration in isolated scratch environment; do not modify Voiceger source or live user config.
- [ ] Confirm real Mac Tailscale Serve + ACL and isolated Android UX/audio + Mac accepted-file E2E. Existing CI does not verify physical Serve/ACL.
- [ ] Independent blocking review PASS for exact final pushed PR HEAD.
- [ ] Human approves intended version, final release notes and **separate** publication/tag/PyPI steps.
- [ ] Review user-guide claims against exact intended release commit; any unresolved restrictions remain explicit.
- [ ] After all gates, return to parent Issue #297; **do not publish or tag automatically**.

## Provisional change summary compared with v0.1.1

Draft content below is **NOT APPROVED**, **NOT COMPLETE**, and must not be presented as a released feature set until tested against the exact release commit.

### Draft Japanese release-notes topics

- Macでローカル起動するWeb画面を追加。既存のTUI、VOICEVOX形式のHTTP APIとは別の画面・API。
- Batch ListとBatch Itemの編集、生成、Takeの再生・採用、発音の直接編集、日本語・英語辞書をWebから操作可能。
- 発音のPreview/反映、採用済み音声の保持、未採用Takeの再生成、Batchレシピの保存・読込に対応。
- 音声合成設定・保存先・ファイル名・出力形式をWebから調整可能。設定保存とリセットは個別仕様に従う。
- WebはBearer token、Origin検証、セッションと生成候補の一時保存を採用。再起動・セッション終了からのTake復旧は保証しない。
- AndroidでのアクセスはMacローカルサーバーへのTailscale Serveを使う限定構成。一般公開やFunnelは対象外。
- 今後の承認事項: 実機動作・文面・バージョン・リリース手続き。TUI/HTTP APIの変更点は実際の差分を再点検する。

### Draft English release-notes topics

- Add a Mac-local browser frontend alongside, not in place of, the existing TUI and partial VOICEVOX-style HTTP API.
- Web workflows cover Batch management, direct JA/EN pronunciation, Takes and acceptance, user dictionaries, shared synthesis and output settings.
- Preserve saved audio when temporary session candidates are invalidated; distinguish noncommitting previews from generated and accepted Takes.
- Web authentication uses a local bearer token and browser request guards. Session IDs and temporary Takes are not restart-safe recovery checkpoints.
- Android access uses a Mac-hosted localhost service through tailnet-only Tailscale Serve; this is not public hosting.
- Final scope/support statements remain conditional on the exact-head automated, manual-device, documentation and release approvals.

## Release commands and safety

Publication commands are **not authorized** in this Issue. At the release-approval gate, present the *then-current* project release workflow, exact intended tag/version, verified CI/run, full source and distribution checksums, and human-visible sequence for explicit review. Never assume the next version number or tag from the provisional notes.

## Environment caveats to retain

- Voiceger runtime, models, and reference audio are **separately installed**; the repository does not own or redistribute them.
- The accepted-audio Voiceger usage terms and credits are separate from the Voiceger Editor MIT source-code license.
- CI checks Windows packaging/startup, **not** physical Windows synthesis, interactive Web/TUI usage or LAB hardware/configuration coverage.
- MP3 needs FFmpeg; LAB requires optional dependencies/external alignment tools according to current core docs. Do not claim a missing optional executable was exercised by hosted CI.
- The Web Python package `[web]` does not itself configure Tailscale, tailnet ACLs, a permanent authenticated session, or an internet-facing service.
- Retain `scratch/issue335-e2e` as the only disposable Human E2E root and never reuse the user's regular Output/config for tests.
