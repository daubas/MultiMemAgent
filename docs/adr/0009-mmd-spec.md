---
status: accepted
---

# MMD v1 Spec — Per-User Memory

## Design Basis

MMD is a simplified version of mem0's memory model:
- **Same**: per-user isolation, ADD/UPDATE/DELETE/NOOP classification, read-first → classify → write ordering
- **Removed**: vector store, embedding model, graph memory, SQLite message buffer
- **Changed**: one LLM call per session (not per turn) to reduce cost; 200-line file cap (because the whole file is loaded into context)

## Plugin Type

MMD is a **Hermes Memory Provider plugin**, implementing the `MemoryProvider` abstract base class. Hermes handles lifecycle integration automatically.

## Plugin Structure

```
~/.hermes/plugins/mmd/
├── plugin.yaml       ← manifest
├── __init__.py       ← register(ctx)
└── tools.py          ← handler implementations
```

## LLM Access

MMD uses the user's configured Hermes model directly:

```python
result = await ctx.llm.acomplete_structured(
    messages=[...],
    schema=CLASSIFICATION_SCHEMA
)
```

No separate API key or provider needed.

## Storage Layout

```
$MMD_DATA_DIR/
└── users/
    ├── telegram_123456.md       ← active memory, ≤ 200 lines
    └── telegram_123456_log.md   ← deep memory, on-demand only
```

`$MMD_DATA_DIR` is configured via `plugin.yaml` and passed to `initialize()` as a kwarg.

## Memory File Format

```markdown
# Memory: telegram_123456
_last_updated: 2026-05-20_

## Facts
- 住台北，時區 Asia/Taipei

## Preferences
- 回覆要直接，用繁體中文

## Active Projects
- MultiMemAgent

## Corrections
- [2026-05-20] 修正：...
```

## Log File

`{user_id}_log.md` holds content removed during compaction. Not loaded by default — deep memory, retrieved on demand via the `load_deep_memory` tool. Each compaction appends a timestamped summary block.

## MemoryProvider Methods

### `initialize(session_id, **kwargs)`
Ensure `users/` directory exists. Read `user_id` from `kwargs` — always passed explicitly by the host bot. Never inferred from `session_id` (same pattern as mem0).

```python
# Bot side
await memory_provider.initialize(session_id, user_id=f"telegram_{message.from_user.id}")
```

### `get_tool_schemas()` / `handle_tool_call()`
Expose a `load_deep_memory` tool so the LLM can fetch `{user_id}_log.md` on demand.

### Prefetch (before each turn)
Read `{user_id}.md` and inject into system prompt. Hermes calls this automatically.

### Sync turn (after each response)
Append the turn to the in-memory buffer. Zero LLM cost. Hermes calls this automatically.

Buffer is in-memory only. If the process crashes before session end, that session's classification is skipped — acceptable for v1.

### `_extract_and_persist(user_id)`
**Sequence (read → classify → write, same as mem0):**
1. Take the full in-memory buffer
2. One `ctx.llm.acomplete_structured()` call to classify:

```json
{
  "private": [{"op": "ADD|UPDATE|DELETE|NOOP", "content": "..."}]
}
```

3. Apply ops to `{user_id}.md`. Write is atomic (tmp file + rename).
4. Check line count. If `{user_id}.md` exceeds ~200 lines → call `compact()`.
5. Clear the buffer.

If the LLM response is invalid, log a warning and skip — do not crash.

Triggered by **session end only** (`on_session_end()`).

### `compact(user_id)`
Called by `_extract_and_persist()` after writing, when the file exceeds ~200 lines.

1. One `ctx.llm.acomplete_structured()` call: rewrite file to ≤ 200 lines by removing least-referenced entries.
2. Append removed entries as a timestamped summary to `{user_id}_log.md`.
3. Write both files atomically (tmp file + rename).

Buffer is already cleared at this point — no re-entrant call needed.

### `on_session_end()`
Call `_extract_and_persist()` if buffer is non-empty. Session boundary is provided by Hermes' gateway adapter (e.g. Telegram adapter).

### `shutdown()`
Wait for any pending writes to finish.
