---
status: accepted
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

## Concurrency: Per-User Async Write Queue

All writes to `{user_id}.md` go through a single per-user async queue. A background worker per user processes items in order. No direct file writes outside the queue are permitted.

```python
queues: dict[str, asyncio.Queue] = {}

async def sync_turn(user_id, delta):
    await queues[user_id].put(("write", delta))

async def on_session_end(user_id):
    await queues[user_id].put(("flush", None))

async def shutdown(user_id):
    await queues[user_id].put(("stop", None))
```

This serializes sync_turn(), on_session_end(), compression, and shutdown() for the same user, eliminating all four identified race conditions (see discussion log).

## Identity Schema and Cross-Channel Pairing

User identity follows Mem0's entity scoping model: `user_id` is a plain string with no internal whitespace. The canonical format is `{channel}_{platform_id}` (e.g. `telegram_123456`, `discord_alice`).

### Default: Channel-Isolated

Each channel creates an independent memory file. A new user arriving from any channel gets their own `{channel}_{id}.md` immediately.

### Pairing: User-Confirmed Unification

When a user wants to merge their identities across channels, they initiate a **pair** flow:

1. User sends a pair request from Channel A → system generates a short-lived confirmation code.
2. User enters the code from Channel B → identities are linked.
3. Both channel IDs are recorded in `identity.json` under a canonical name.
4. The two memory files are merged by LLM into a single canonical `{canonical_name}.md`.
5. The channel-specific files become aliases that resolve to the canonical file.

```json
// identity.json
{
  "paul": ["telegram_123456", "discord_alice"]
}
```

After pairing, `set_user()` resolves any alias to the canonical name before any read or write.

The canonical name defaults to the channel ID of the initiating side, or a user-supplied name.

Pairing requires action from both sides to prevent impersonation.

## Bot-Side Invocation

The host application should bind the current user before each reply cycle.

```python
memory_provider.set_user("telegram", user_id)  # resolves alias if paired
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

## Decisions

1. **`sync_turn()` 使用 Gemini Flash** 做記憶萃取。理由：速度快、成本低，足以處理每輪對話後的增量更新。
2. **截斷策略：壓縮回 200 行以內。** 當主記憶檔超過 ~200 行時，由 LLM 識別並刪除最不相關、最少被引用的條目，將全文壓縮至 200 行以內後覆寫。不保留被刪除條目的原文。
3. **`{user_id}_log.md` 採滾動摘要（rolling summary）。** 每次壓縮主檔前，將被刪除或被合併的段落以摘要形式 append 進 log 檔，作為可查閱的歷史紀錄，但 log 檔本身不作為 LLM context 的常規輸入。

## Practical Rule

- Shared and reviewable information belongs in the Git-backed wiki.
- User-specific memory belongs in the Markdown memory provider.
- Hermes owns the decision of what gets written where.