---
status: accepted
---

# MMD v1 Spec — Per-User Memory

## What MMD Does (v1)

1. Before each reply: load `{user_id}.md` into Hermes context
2. After the session: one LLM call classifies what changed → update `{user_id}.md`
3. When memory file exceeds ~200 lines: compact it, archive removed content to `{user_id}_log.md`

## Storage Layout

```
$MMD_DATA_DIR/
└── users/
    ├── telegram_123456.md       ← active memory, always ≤ 200 lines
    └── telegram_123456_log.md   ← deep memory, archived content
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

## Log File

`{user_id}_log.md` holds content removed during compaction. It is **not** loaded into Hermes context by default — it is deep memory, retrieved on demand when the user asks about older context or when a query clearly requires historical information.

Format: rolling appends of summarised removed entries, with a timestamp per compaction run.

## Lifecycle Hooks

### `initialize()`
Ensure `users/` directory exists.

### `prefetch(user_id)`
Read `{user_id}.md` and inject into Hermes system prompt.

### `sync_turn(user_id, turn)`
Append raw turn to in-memory buffer. Zero LLM cost.

### `_extract_and_persist(user_id)`
Makes **one LLM call** to classify the buffer:

```json
{
  "private": [{"op": "ADD|UPDATE|DELETE|NOOP", "content": "..."}]
}
```

Applies ops to `{user_id}.md`. Writes are atomic (tmp file + rename).

If the LLM response is not valid JSON, log a warning and skip — do not crash.

Triggered by:
- **(A) `on_session_end()`** — always fires at session end
- **(B) `compact()`** — fires after compaction to flush the current buffer into the freshly compacted file

### `compact(user_id)`
Triggered when `{user_id}.md` exceeds ~200 lines.

1. LLM identifies and removes least-referenced entries, rewriting the file to ≤ 200 lines.
2. Removed entries are summarised and appended to `{user_id}_log.md` with a timestamp.
3. After compaction, `_extract_and_persist()` is called to merge any buffered turns into the compacted file.

Writes are atomic (tmp file + rename).

### `on_session_end(user_id)`
Trigger `_extract_and_persist()` if buffer is non-empty.

### `shutdown()`
Wait for any pending writes to finish.

## User ID Convention

Format: `{channel}_{platform_id}` (e.g. `telegram_123456`, `discord_alice`).

Passed directly by the bot — no alias resolution in v1.

```python
reply = await agent.chat(message, user_id=f"telegram_{user_id}")
```
