---
status: proposed
---

# Hermes Markdown Memory Provider for Multi-User Isolation

We want a low-cost, inspectable memory layer for Hermes that isolates memory per user, keeps the on-disk format human-readable, and avoids a vector database entirely.

This design intentionally treats memory as a small Markdown artifact rather than as a semantic retrieval system. The goal is not global recall across a large corpus; the goal is to keep a compact, user-scoped memory snapshot that Hermes can load quickly and update incrementally.

## Decision Table

| Item | Decision |
|---|---|
| Memory format | Pure Markdown (`.md`) |
| Vector database | Not used |
| Retrieval | LLM reads the whole memory file directly |
| Memory size | Roughly <= 200 lines is acceptable |
| Integration | Hermes Memory Provider plugin |

## File Layout

```text
$HERMES_HOME/multi-user-md/users/
├── telegram_123456.md
├── telegram_123456_log.md
├── telegram_789012.md
├── telegram_789012_log.md
└── discord_abc123.md
```

The primary file is `{user_id}.md`. A companion `{user_id}_log.md` file can hold rolling summaries or high-signal historical updates if we decide we need more than a single snapshot.

## Canonical Memory File Format

```markdown
# Memory: telegram_123456
_last_updated: 2026-05-19_

## Facts
- 住台北，時區 Asia/Taipei
- 職業：全端開發者

## Preferences
- 回覆要直接，用繁體中文
- 代碼偏好 TypeScript

## Active Projects
- MultiMemAgent

## Corrections
- [2026-05-19] 修正：...
```

## Plugin Lifecycle

The plugin should behave like a small stateful adapter around the markdown files.

1. `initialize()`
   - Ensure `users_dir` exists.
   - Create a user file lazily when the first message arrives.

2. `prefetch()`
   - Read `{user_id}.md`.
   - Inject a compact memory summary into the system prompt.

3. `sync_turn()`
   - Run asynchronously after the turn.
   - Extract memory changes and update the Markdown file.
   - Keep the write path non-blocking for the chat response.

4. `on_session_end()`
   - Flush any pending updates.
   - Persist the latest snapshot before the session closes.

5. `shutdown()`
   - Wait for background sync work to finish.
   - Avoid leaving partial writes behind.

## Memory Update Policy

The LLM should classify each candidate change into one of four operations:

- `ADD`: add a new fact or preference
- `UPDATE`: replace an older statement with a newer one
- `DELETE`: remove a contradictory or obsolete item
- `NOOP`: do nothing

This mirrors Mem0-style update behavior, but the stored representation remains a simple Markdown document.

## Bot-Side Invocation

The host application should bind the current user before each reply cycle.

```python
memory_provider.set_user("telegram", user_id)
reply = await agent.chat(message)
```

The important rule is that user-scoped memory is selected before the agent generates a response.

## Truncation Policy

We do not need a vector database, but we do need a strict size discipline.

Recommended rules:

- Keep the main memory file near or below ~200 lines.
- Prioritize `Preferences`, then `Facts`, then `Active Projects`, then `Corrections`.
- When the file grows too large, compress old content into a rolling summary or log file.
- Do not let the memory file become a raw transcript.

## Optional Log File

If we need historical traceability, use `{user_id}_log.md` for rolling summaries.

Do not store full raw conversations in the memory provider path unless we explicitly need them for debugging or compliance. The log should be high-signal, not exhaustive.

## Why This Works

- Markdown is inspectable and version-controllable.
- User isolation is explicit through file names and directory layout.
- Hermes can load the entire file cheaply because the memory snapshot stays small.
- We avoid running and maintaining a separate vector database.
- The model decides whether new information belongs in the shared wiki or in private memory.

## Open Questions

1. Which model should `sync_turn()` use for extraction? The current candidates are a cheap fast model such as Haiku or Gemini Flash.
2. What exact truncation / compression strategy should apply once the file exceeds the soft line limit?
3. Should we maintain `{user_id}_log.md` as an append-only rolling summary file, or keep only the current snapshot?

## Practical Rule

- Shared and reviewable information belongs in the Git-backed wiki.
- User-specific memory belongs in the Markdown memory provider.
- Hermes owns the decision of what gets written where.