# MultiMemD (MMD)

Local-first personal memory for Hermes agents, designed for multi-user bots.

MMD stores each user's long-term memory as small Markdown files, updates them
with structured LLM extraction, and supports cross-channel identity pairing
without requiring a vector database, external memory API, or cloud service.

## What It Is

MMD is a Hermes `MemoryProvider` plugin. It gives Telegram, Discord, and other
gateway users isolated persistent memory while keeping storage inspectable and
portable.

Use it when you want:

- per-user memory isolation for multi-user bot deployments
- local Markdown storage instead of mem0, Qdrant, Chroma, or embeddings
- low operational overhead with no separate infrastructure
- optional pairing between multiple channel accounts owned by the same person

## How It Works

For each session, MMD:

1. Resolves the channel user to a canonical memory ID.
2. Loads that user's active memory before replies.
3. Buffers conversation turns in memory.
4. Flushes the buffer at session end, before compression, or after 30 minutes idle.
5. Asks the configured Hermes LLM to classify memory changes as
   `ADD`, `UPDATE`, `DELETE`, or `NOOP`.
6. Applies the changes to the user's Markdown memory file.
7. Compacts files over 200 lines and archives removed content to deep memory.

## Architecture

```
MemoryStore           — filesystem I/O for active and archived memory
MemoryClassifier      — LLM-based ADD / UPDATE / DELETE / NOOP extraction
MemoryCompactor       — LLM-based reduction when memory exceeds 200 lines
IdleFlushScheduler    — background idle flush after 30 minutes
PairingManager        — cross-channel identity pairing with short-lived codes
MMDProvider           — Hermes MemoryProvider orchestration
```

## Storage

`$MMD_DATA_DIR` defaults to `~/.hermes/mmd`.

```
$MMD_DATA_DIR/
├── identity.json
├── identity.lock
├── _pairing/
│   └── {CODE}.json
└── users/
    ├── {canonical_uuid}.md
    └── {canonical_uuid}_log.md
```

Active memory is loaded automatically. Log files contain archived deep memory
from compaction and are only loaded on demand through the `load_deep_memory`
tool.

## Install

```bash
ln -s "$(pwd)/plugin" ~/.hermes/plugins/mmd
```

Enable the provider in Hermes config:

```yaml
memory:
  provider: mmd
```

Then restart Hermes:

```bash
hermes gateway restart
```

## Commands

- `/mmd` flushes the current buffer, shows what changed, and displays active memory.
- `/pair` creates a short-lived pairing code for the current account.
- `/pair <CODE>` confirms a code from another account and merges memory files.

## Privacy Notes

MMD memory is isolated by canonical user ID. In multi-user gateways, disable
Hermes' global built-in memory files to avoid leaking owner-specific context:

```yaml
memory:
  memory_enabled: false
  user_profile_enabled: false
  provider: mmd
```

MMD also injects a prompt-level privacy instruction, but disabling shared global
files is the structural fix.

## Run Tests

```bash
python3 -m pytest tests/ -v
```

Tests cover file storage, LLM classification fallbacks, compaction, idle flush,
provider lifecycle, `/mmd`, cross-channel pairing, and `/pair`.

## Docs

- [Project Plan](docs/plan.md)
- [MMD Spec](docs/adr/0009-mmd-spec.md)
- [Roadmap](docs/roadmap.md)
