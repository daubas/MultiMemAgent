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

MMD is a **Hermes Memory Provider plugin**, implementing the `MemoryProvider` abstract base class from `agent/memory_provider.py`.

All `MemoryProvider` methods are **synchronous**. LLM calls use `ctx.llm.complete_structured()` (not async).

## Plugin Structure

```
~/.hermes/plugins/memory/mmd/
├── plugin.yaml       ← manifest
├── __init__.py       ← register(ctx)
└── tools.py          ← load_deep_memory handler
```

Registration in `__init__.py`:

```python
def register(ctx) -> None:
    ctx.register_memory_provider(MMDProvider())
```

## LLM Access

```python
result = ctx.llm.complete_structured(
    messages=[...],
    schema=CLASSIFICATION_SCHEMA
)
```

Uses the user's configured Hermes model. No separate API key needed.

## Storage Layout

```
$MMD_DATA_DIR/
└── users/
    ├── telegram_123456.md       ← active memory, ≤ 200 lines
    └── telegram_123456_log.md   ← deep memory, on-demand only
```

`$MMD_DATA_DIR` is defined in `plugin.yaml` and passed to `initialize()` as a kwarg.

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

### `name -> str` (property)
Return `"mmd"`.

### `is_available() -> bool`
Return `True` if `$MMD_DATA_DIR` is configured and accessible.

### `initialize(session_id: str, **kwargs) -> None`
Ensure `users/` directory exists. Read `user_id` from `kwargs` — always passed explicitly by the host bot, never inferred from `session_id` (same pattern as mem0).

```python
# Bot side
memory_provider.initialize(session_id, user_id=f"telegram_{message.from_user.id}")
```

### `prefetch(query: str, *, session_id: str = "") -> str`
Read `{user_id}.md` and return its contents as a string. Hermes injects this into the system prompt automatically.

For v1, return the full file contents — no query-based filtering needed at ≤ 200 lines.

### `sync_turn(user_content: str, assistant_content: str, *, session_id: str = "") -> None`
Append the turn to the in-memory buffer. Zero LLM cost.

Buffer is in-memory only. If the process crashes before session end, that session's classification is skipped — acceptable for v1.

### `get_tool_schemas() -> List[Dict[str, Any]]`
Return the schema for the `load_deep_memory` tool.

### `handle_tool_call(tool_name: str, args: Dict, **kwargs) -> str`
Handle `load_deep_memory`: read and return `{user_id}_log.md` contents.

### `on_session_end(messages: List[Dict]) -> None`
Trigger `_extract_and_persist()` if buffer is non-empty. `messages` is the full conversation — available if needed for context, but MMD uses its own buffer.

### `shutdown() -> None`
Wait for any pending writes to finish.

---

## Internal Methods

### `_extract_and_persist(user_id)`
**Sequence (read → classify → write):**
1. Take the full in-memory buffer.
2. One `ctx.llm.complete_structured()` call:

```json
{
  "private": [{"op": "ADD|UPDATE|DELETE|NOOP", "content": "..."}]
}
```

3. Apply ops to `{user_id}.md`. Write is atomic (tmp file + rename).
4. Check line count — if `{user_id}.md` exceeds ~200 lines → call `compact()`.
5. Clear the buffer.

If the LLM response is invalid, log a warning and skip — do not crash.

### `compact(user_id)`
Called by `_extract_and_persist()` after writing, when the file exceeds ~200 lines.

1. One `ctx.llm.complete_structured()` call: rewrite file to ≤ 200 lines, removing least-referenced entries.
2. Append removed entries as a timestamped summary to `{user_id}_log.md`.
3. Write both files atomically (tmp file + rename).

Buffer is already cleared at this point — no re-entrant call.
