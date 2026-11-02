# Issue #335 — Web final acceptance and release-readiness record

**Status: NOT READY TO RELEASE** (2026-11-02 JST; initial inventory only).
This is an internal acceptance checklist, **not user-facing release notes** or publication instructions. No proposed Japanese/English release-note prose is recorded here before Human text approval. The published v0.1.1 guides and release remain unchanged.

## Grounded baseline

- Repository: `sayosomi/voiceger-editor`
- Refreshed GitHub remote `main` (2026-11-02 JST): `1ab38a439ff29b270537078efa867e8b486bfdde`. Existing Draft PR #336 has its own branch ancestry and must incorporate current main before final exact-head acceptance.
- Published latest release (GitHub): `v0.1.1` (2026-10-28 UTC); its release text describes the TUI and compatibility API. Do not silently rewrite those published statements.
- Source package version: `voiceger_editor/_version.py` = `0.1.1`; `pyproject.toml` reads this dynamically. **No next release version has been selected.**
- Compared with published `v0.1.1`, current main includes the Web frontend, batch/pronunciation/Take/dictionary/settings/output workflows, TUI/shared-core changes, and merged #322 JA-pronunciation-to-ARPAbet conversion for both TUI and Web. Recompute exact tag-to-release-HEAD comparison when the release target is chosen.
- Previous main checkpoint `a5b38a5...` passed [CI 41319648352](https://github.com/sayosomi/voiceger-editor/actions/runs/41319648352). Merged #322 PR #337 implementation HEAD `5c990c850fdb7891db96238db345614b28264c2b` passed [CI 41331395649](https://github.com/sayosomi/voiceger-editor/actions/runs/41331395649). **These are not CI at the current main `1ab38a4...` or at the final release commit.** CI includes Python 3.9 unit tests, Windows startup boundary, and Linux wheel/sdist clean-install smoke, but does not certify Mac Tailscale configuration or physical Windows synthesis.

## Checklist (check only on direct evidence at intended release HEAD)

- [x] Baseline latest published release/tag verified: `v0.1.1`.
- [x] Current source version and optional dependencies inspected: `[tui]`, `[api]`, `[web]`, `[lab]`; Python `==3.9.*` in `pyproject.toml`.
- [x] Reviewed prior CI packages Web HTML/CSS/JS in the wheel and smoke-installs `[api,tui,lab,web]`; Windows startup CI is a **limited** startup check only. Recheck at final release HEAD.
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

## Release-note coverage checklist (internal, not prose)

Before writing any Japanese or English release-note text, verify against the intended release HEAD:

- [ ] Web frontend, Mac-local startup and its separation from the TUI / compatibility API.
- [ ] Batch / pronunciation / Take / dictionary / settings / output workflows and any important limits.
- [ ] JA pronunciation → grouped ARPAbet in-place conversion (#322), supported inputs, lossy approximation and guarded rejection cases.
- [ ] Preview, transient Takes, persistent accepted files and restart/reconnect boundaries.
- [ ] Tailnet-only Android access, authentication model and non-public-hosting boundary.
- [ ] TUI/API changes and compatibility limits from the exact latest published tag.
- [ ] Human-approved exact JA/EN wording, version number and publication procedure.

This checklist intentionally contains no proposed user-facing release-note paragraphs.

## Release commands and safety

Publication commands are **not authorized** in this Issue. At the release-approval gate, present the *then-current* project release workflow, exact intended tag/version, verified CI/run, full source and distribution checksums, and human-visible sequence for explicit review. Never assume the next version number or tag from the provisional notes.

## Environment caveats to retain

- Voiceger runtime, models, and reference audio are **separately installed**; the repository does not own or redistribute them.
- The accepted-audio Voiceger usage terms and credits are separate from the Voiceger Editor MIT source-code license.
- CI checks Windows packaging/startup, **not** physical Windows synthesis, interactive Web/TUI usage or LAB hardware/configuration coverage.
- MP3 needs FFmpeg; LAB requires optional dependencies/external alignment tools according to current core docs. Do not claim a missing optional executable was exercised by hosted CI.
- The Web Python package `[web]` does not itself configure Tailscale, tailnet ACLs, a permanent authenticated session, or an internet-facing service.
- Retain `scratch/issue335-e2e` as the only disposable Human E2E root and never reuse the user's regular Output/config for tests.
