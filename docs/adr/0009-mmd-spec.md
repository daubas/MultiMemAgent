---
status: accepted
---

# MMD v1 Spec — Per-User Memory

## What MMD Does (v1)

1. Before each reply: load `{user_id}.md` into Hermes context
2. After the session: one Gemini Flash call classifies what changed → update `{user_id}.md`

That's it.

## Storage Layout

```
$MMD_DATA_DIR/
└── users/
    ├── telegram_123456.md
    └── discord_alice.md
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

Target size: ≤ 200 lines. When exceeded, LLM compresses by removing least-referenced entries; a summary of what was removed is appended to `{user_id}_log.md`.

## Lifecycle Hooks

### `initialize()`
Ensure `users/` directory exists.

### `prefetch(user_id)`
Read `{user_id}.md` and inject into Hermes system prompt.

### `sync_turn(user_id, turn)`
Append raw turn to in-memory buffer. Zero LLM cost.

### `_extract_and_persist(user_id)`
Triggered by whichever comes first:
- **(A)** Buffer reaches 50% of session context limit (default: 2000 tokens)
- **(B)** Session ends

Makes **one Gemini Flash call** to classify the buffer:

```json
{
  "private": [{"op": "ADD|UPDATE|DELETE|NOOP", "content": "..."}]
}
```

Applies the ops to `{user_id}.md`. Writes are atomic (tmp file + rename).

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
