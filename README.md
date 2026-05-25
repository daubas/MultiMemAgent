# MultiMemD (MMD)

Per-user Markdown memory plugin for Hermes agent. Zero infrastructure dependency.

## What It Does

Adds per-user persistent memory to Hermes. Each user gets their own `{user_id}.md` (≤ 200 lines). MMD:

- Loads memory before every reply (injected as context)
- Extracts and updates memory at session end using one LLM call
- Auto-flushes after 30 minutes of idle (no session end needed)
- Compacts the file when it exceeds 200 lines, archiving removed content to `{user_id}_log.md`

## Architecture

```
MemoryStore           — filesystem I/O
MemoryClassifier      — LLM-based ADD/UPDATE/DELETE/NOOP classification
MemoryCompactor       — LLM-based file compaction
IdleFlushScheduler    — background thread, fires after 30min idle
MMDProvider           — Hermes MemoryProvider orchestrator
```

## Storage

```
$MMD_DATA_DIR/users/
├── {user_id}.md        ← active memory, ≤ 200 lines
└── {user_id}_log.md    ← archived content removed during compaction
```

`$MMD_DATA_DIR` defaults to `~/.hermes/mmd`.

## Install

```bash
# Link the plugin into Hermes' plugin directory
ln -s "$(pwd)/plugin" ~/.hermes/plugins/mmd

# Enable the plugin in config.yaml
# memory:
#   provider: mmd

# Restart Hermes
hermes gateway restart
```

## Slash Command

`/mmd` — flush the current session buffer, show what changed, and display current memory.

## What Gets Remembered

The classifier is prompted to extract 7 categories:

1. Personal details (name, birthday, location, relationships)
2. Important dates & events (converted to absolute dates)
3. Preferences (likes/dislikes, habits, communication style)
4. Plans & intentions
5. Ongoing projects
6. Professional context
7. Health & lifestyle

Skipped: phatic filler, session-only instructions, vague characterisations.

## Multi-User Gateway

MMD is designed for multi-user scenarios (e.g. Telegram gateway with multiple users). Each user's memory is isolated by `user_id`.

However, Hermes' built-in `USER.md` and `MEMORY.md` are global single files shared across all sessions. In a multi-user setup, these files may expose the agent owner's personal information to other users.

**Recommended:** clear or disable the built-in files in `config.yaml`:

```yaml
memory:
  memory_enabled: false
  user_profile_enabled: false
  provider: mmd
```

MMD's `system_prompt_block` includes a prompt-level privacy instruction to reduce unintended disclosure, but disabling the built-in files is the only structural solution.

## Run Tests

```bash
python3 -m pytest tests/ -v
```

71 tests covering MemoryStore, MemoryClassifier, MemoryCompactor, IdleFlushScheduler, MMDProvider, and the `/mmd` command.

## Docs

- [Project Plan](docs/plan.md)
- [MMD Spec](docs/adr/0009-mmd-spec.md)
- [Roadmap](docs/roadmap.md)
