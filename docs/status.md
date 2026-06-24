# MultiMemD (MMD) — Current Status

## Current Definition

MMD is a local-first personal memory provider for Hermes, designed for
multi-user bot deployments.

It keeps each user's long-term memory in small Markdown files, updates those
files through structured LLM extraction, and avoids any dependency on a vector
database, embedding model, or external memory service.

## Positioning

> Local-first per-user memory for Hermes bots.

MMD is inspired by mem0's useful core loop: read existing memory, classify
changes, then write updated memory. It intentionally removes the infrastructure
that is unnecessary for small per-user memories.

| Capability | MMD |
|---|---|
| Per-user isolation | Yes |
| ADD / UPDATE / DELETE / NOOP extraction | Yes |
| Session-end and idle flushing | Yes |
| Cross-channel identity pairing | Yes |
| Active memory stored as Markdown | Yes |
| Vector database / embeddings | No |
| External memory API | No |
| Graph memory | No |

## Product Boundary

MMD assumes a user's active memory can stay around 200 lines. At that size, the
whole file can be loaded into context and query-time vector search is not
needed.

When active memory grows too large, MMD compacts it back under the limit and
archives removed content to `{canonical_uuid}_log.md`. Archived content remains
available through the `load_deep_memory` tool.

If a deployment needs thousands of searchable facts per user, MMD is no longer
the right storage model; use a dedicated memory system with retrieval.

## Implemented Scope

- Hermes `MemoryProvider` implementation in `src/mmd.py`
- per-user Markdown storage under `$MMD_DATA_DIR/users/`
- structured LLM classification into `ADD`, `UPDATE`, `DELETE`, `NOOP`
- compaction and archived deep memory logs
- idle flush scheduler for sessions that never explicitly end
- thread-safe buffer swap during flush, with retry when classification fails
- pre-compression flush hook
- `/mmd` command for manual flush and inspection
- `load_deep_memory` tool schema and handler
- UUID-based cross-channel identity pairing in `src/pairing.py`
- `/pair` command for initiating and confirming account pairing
- confirmer-based pairing failure limits
- path validation for memory file user IDs
- pytest coverage for provider, storage, compaction, idle flush, and pairing

## Near-Term Work

1. Validate plugin behavior inside a real Hermes gateway with Telegram user IDs.
2. Confirm whether `plugin/plugin.yaml` should declare additional hooks used by
   the current provider lifecycle.
3. Decide whether wiki candidate buffering belongs in this repo or a separate
   plugin.
4. Confirm what command context Hermes passes to slash command handlers, then
   restrict `/mmd` and `/pair` to direct messages when possible.

## Success Criteria

MMD is successful when a multi-user Hermes bot can run with only local file
storage, preserve each user's memory independently, pair accounts on request,
and avoid exposing memory between users.
