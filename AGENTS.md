# AGENTS.md

## Development routing

Route all development work through this repository's `README.md` and the fixed [voiceger-editor project context](https://github.com/sayosomi/dev-context/blob/main/projects/voiceger-accent-adapter/README.md).

Load the shared documents routed from that entrypoint when their topics apply. In particular:

- use `shared/DEVELOPMENT.md` for the common development workflow and loading rules;
- use `shared/GIT-WORKFLOW.md` for remote state, checkout, branch, commit, push, and review work;
- use the project `CODING-AGENT.md` plus shared implementation-agent owners when generating implementation or blocking-fix prompts.

Authority:

- The latest remote `sayosomi/voiceger-editor` repository is authoritative for implemented repository facts.
- GitHub Issues in this repository are the primary Work and current implementation-contract authority.
- Reusable workflow mechanics belong in dev-context; repository-local environment, test, scratch-artifact, and hygiene rules remain owned here.
- Do not import nuinuiCAD-specific Linear workflow, declared lanes, Astra policy, Manual E2E policy, or other nuinuiCAD product rules.

## Development environment

- Voiceger is maintained separately from this repository.
- The default local Voiceger path is `~/voiceger_v2`.
- Use Voiceger's Python environment when running this project:
  `~/voiceger_v2/.venv/bin/python`.
- Do not modify files under `~/voiceger_v2` as part of work on this repository unless the task explicitly requires an upstream Voiceger change.

## Tests

Run unit tests with:

```bash
~/voiceger_v2/.venv/bin/python -m unittest discover -s tests -v
```

Run real Voiceger integration tests with:

```bash
VOICEGER_RUN_INTEGRATION=1 \
VOICEGER_ROOT=~/voiceger_v2 \
~/voiceger_v2/.venv/bin/python -m unittest \
  tests.integration.test_voiceger_runtime -v
```

## TUI architecture

- `voiceger_editor/tui.py` is the TUI composition root, not the default location for new feature logic.
- Put new TUI behavior in the subsystem that owns the responsibility. Give substantial new TUI state or policy that does not fit an existing subsystem a focused owner rather than enlarging `TuiApp`.
- Extracted `tui_*` modules must not import `tui.py` or `TuiApp`.
- Logic reusable by the API, Web UI, or other frontends belongs in shared application/core modules, not TUI-specific modules.
- Normally test subsystem behavior in its corresponding focused test module; use `tests/test_tui.py` for composition and genuinely cross-subsystem behavior.
- Keep TUI architecture regression tests green, including the 900-line ceiling for `tui.py`.
- See [`docs/tui-architecture.md`](docs/tui-architecture.md) for the subsystem ownership map and placement guidance.

## Manual testing and generated files

- Do not create temporary JSON, WAV, logs, or other test artifacts in the repository root.
- Put all disposable manual-test artifacts under `scratch/`.
- `scratch/` is gitignored and may be deleted at any time.
- Prefer streaming synthesized audio directly to a player when the output does not need to be kept.
- If an artifact needs to be preserved as part of the project, place it in an appropriate tracked directory instead of `scratch/`.

Examples:

```bash
curl ... > scratch/query.json
curl ... --output scratch/test.wav
```

For playback-only tests, prefer:

```bash
curl ... | ffplay -nodisp -autoexit -loglevel error -
```

## Repository hygiene

- Do not commit generated Python metadata or caches.
- Do not commit files from `scratch/`.
- Before finishing a task, run `git status --short`.
- Remove unintended generated files before finishing.
