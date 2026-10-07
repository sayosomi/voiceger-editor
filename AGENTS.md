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

## Module growth guard

- The unit suite includes a repository-wide Python module growth guard in `tests/test_module_growth.py`.
- The current review triggers are 1,500 physical source lines for production modules under `voiceger_editor/` and 3,500 lines for test modules under `tests/`.
- These thresholds are review/growth triggers only. Responsibility boundaries remain the architecture rule; do not split code mechanically just to satisfy a number.
- Oversized files that have been explicitly reviewed must be listed in `tests/module_growth_exceptions.json` with a reviewed maximum line count, a concise responsibility justification, and a follow-up Issue when the exception represents temporary debt.
- A registered exception must not grow beyond its reviewed baseline without an intentional registry change. Remove the exception once the file drops below its review trigger.
- When a module reaches a review trigger, first look for an existing focused owner or introduce a coherent new owner. Do not use formatting compression, code golf, or line-count tricks to evade the guard.

## TUI architecture

- `voiceger_editor/tui.py` is the TUI composition root, not the default location for new feature logic.
- Do not add new feature state, interaction policy, key interpretation, rendering logic, or operation logic to `TuiApp`.
- Existing composition wiring and top-level routing may change when needed, but when a task introduces a new responsibility, place it in the existing focused `tui_*` owner or create a new focused module.
- Do not use formatting compression, line-count tricks, or unrelated refactoring as a substitute for preserving responsibility boundaries.
- Extracted `tui_*` modules must not import `tui.py` or `TuiApp`.
- Logic reusable by the API, Web UI, or other frontends belongs in shared application/core modules, not TUI-specific modules.
- Normally test subsystem behavior in its corresponding focused test module; use `tests/test_tui.py` for composition and genuinely cross-subsystem behavior.
- Keep TUI architecture regression tests green.
- See [`docs/development/tui-architecture.md`](docs/development/tui-architecture.md) for the subsystem ownership map and placement guidance.

## TUI UI conventions

- Before settling the implementation contract for any Task that changes TUI-visible presentation, navigation, focus behavior, key interaction, editor or modal interaction, or Status behavior, read [`docs/development/tui-ui-guidelines.md`](docs/development/tui-ui-guidelines.md).
- Treat that document as the canonical owner of reusable cross-screen TUI interaction and presentation conventions.
- If a Task introduces a new reusable cross-screen convention or changes an existing one, update the guideline in the same change and cover the resulting behavior with focused tests where applicable.
- Keep feature-specific behavior, screen-specific menu order, and exact feature semantics out of the shared guideline; those belong in the feature owner, Issue contract, and focused tests.

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
