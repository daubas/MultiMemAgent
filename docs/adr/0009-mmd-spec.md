---
status: accepted
---

# MMD v1 Spec — Per-User Memory

## Plugin Type

MMD is a **Hermes Memory Provider plugin**, implementing the `MemoryProvider` abstract base class. Hermes handles the lifecycle integration automatically; MMD only needs to implement the required methods.

## Plugin Structure

```
~/.hermes/plugins/mmd/
├── plugin.yaml       ← manifest
├── __init__.py       ← register(ctx)
└── tools.py          ← handler implementations
```

## LLM Access

MMD calls the user's configured Hermes model directly — no separate API key or provider needed:

```python
result = await ctx.llm.acomplete_structured(
    messages=[...],
    schema=CLASSIFICATION_SCHEMA   # ADD/UPDATE/DELETE/NOOP JSON schema
)
```

All calls are automatically audit-logged by Hermes with plugin ID and token usage.

## Storage Layout

```
$MMD_DATA_DIR/
└── users/
    ├── telegram_123456.md       ← active memory, always ≤ 200 lines
    └── telegram_123456_log.md   ← deep memory, on-demand only
```

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

Target size: ≤ 200 lines.

## Log File

`{user_id}_log.md` holds content removed during compaction. It is **not** loaded into Hermes context by default. It is deep memory — retrieved on demand when the user asks about older context or when a query clearly requires historical information.

Each compaction appends a timestamped summary block of what was removed.

## MemoryProvider Methods

### `initialize(session_id, **kwargs)`
Ensure `users/` directory exists. `user_id` is passed explicitly by the host bot via `kwargs` — it is never inferred from `session_id`. This follows mem0's pattern: identity is always the caller's responsibility.

```python
# Bot side — before each conversation
await memory_provider.initialize(session_id, user_id=f"telegram_{message.from_user.id}")
```

### `get_tool_schemas()` / `handle_tool_call()`
Expose a `load_deep_memory` tool so the LLM can fetch `{user_id}_log.md` on demand.

### Prefetch (before each turn)
Read `{user_id}.md` and inject into system prompt. Hermes calls this automatically.

### Sync turn (after each response)
Append the turn to the in-memory buffer. Zero LLM cost. Hermes calls this automatically.

### `_extract_and_persist(user_id)`
Makes **one `ctx.llm.acomplete_structured()` call** to classify the buffer:

```json
{
  "private": [{"op": "ADD|UPDATE|DELETE|NOOP", "content": "..."}]
}
```

Applies ops to `{user_id}.md`. Writes are atomic (tmp file + rename).

If the response is not valid JSON or is missing required fields, log a warning and skip — do not crash.

**Triggered by:**
- **(A) Session end** — `on_session_end()` fires this if buffer is non-empty
- **(B) After `compact()`** — flushes buffered turns into the freshly compacted file

### `compact(user_id)`
Triggered when `{user_id}.md` exceeds ~200 lines:

1. One `ctx.llm.acomplete_structured()` call identifies and removes least-referenced entries, rewriting the file to ≤ 200 lines.
2. Removed entries are summarised and appended to `{user_id}_log.md` with a timestamp.
3. `_extract_and_persist()` is called to merge any buffered turns into the compacted file.

Writes are atomic (tmp file + rename).

### `on_session_end()`
Trigger `_extract_and_persist()` if buffer is non-empty.

## User ID Convention

Format: `{channel}_{platform_id}` (e.g. `telegram_123456`, `discord_alice`).

In v1, passed directly from the bot with no alias resolution:

```python
reply = await agent.chat(message, user_id=f"telegram_{user_id}")
```
