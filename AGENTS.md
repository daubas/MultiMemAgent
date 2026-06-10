# Repository Guidelines

## Project Structure & Module Organization

This repository contains MultiMemD (MMD), a local-first personal memory provider
for Hermes agents in multi-user bot deployments. Core implementation lives in
`src/`: `mmd.py` handles Markdown memory storage, LLM extraction, compaction,
idle flushing, and provider orchestration; `pairing.py` handles cross-channel
identity pairing. Hermes plugin files live in `plugin/`, including
`plugin.yaml`. Tests are in `tests/` and mirror the source modules. Design notes
and roadmap material are in `docs/`, including ADRs under `docs/adr/`.

## Build, Test, and Development Commands

- `python3 -m pytest tests/ -v` runs the full test suite.
- `python3 -m pytest tests/test_mmd.py -v` runs only MMD provider tests.
- `python3 -m pytest tests/test_pairing.py -v` runs only pairing tests.
- `ln -s "$(pwd)/plugin" ~/.hermes/plugins/mmd` links the plugin into a local
  Hermes install for manual integration testing.

There is no separate build step or package metadata in this repo at present.

## Coding Style & Naming Conventions

Use Python 3 with 4-space indentation and type hints where they clarify public
interfaces. Keep classes focused on one responsibility, matching the current
`MemoryStore`, `MemoryClassifier`, `MemoryCompactor`, `IdleFlushScheduler`,
`MMDProvider`, and `PairingManager` structure. Use `snake_case` for functions,
methods, variables, and test names; use `PascalCase` for classes; keep constants
uppercase with a leading underscore for module-private values, e.g.
`_LINE_LIMIT`.

Prefer small, direct changes over broad refactors. Preserve UTF-8 handling for
Markdown memory files and JSON identity files.

## Testing Guidelines

Tests use `pytest` plus `unittest.mock`. Add or update tests whenever changing
memory operations, compaction behavior, pairing flows, slash commands, or file
storage semantics. Follow existing test class names such as `TestMemoryStore`
and descriptive method names like `test_resolve_new_user_creates_uuid`.

Use temporary directories for filesystem tests; do not write test data into the
real `$MMD_DATA_DIR` or `~/.hermes`.

## Commit & Pull Request Guidelines

Recent history uses short imperative commits, often with Conventional Commit
prefixes such as `feat:` and `docs:`. Keep commits focused, for example:
`feat: add pairing retry guard` or `docs: update MMD setup notes`.

Pull requests should include a concise summary, the reason for the change,
test commands run, and any Hermes/manual validation performed. Link related
issues or ADRs when behavior changes. Include screenshots or terminal excerpts
only when they clarify user-visible plugin behavior.

## Security & Configuration Tips

Memory files are per user and stored under `$MMD_DATA_DIR`, defaulting to
`~/.hermes/mmd`. Avoid logging private memory content. In multi-user Hermes
gateways, keep built-in global `USER.md` and `MEMORY.md` disabled as described
in `README.md`.
