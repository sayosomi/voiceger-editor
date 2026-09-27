# AGENTS.md

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
