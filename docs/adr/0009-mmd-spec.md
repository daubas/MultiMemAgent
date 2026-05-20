---
status: accepted
---

# MultiMemD (MMD) — Plugin Spec

MultiMemD (MMD) is a self-built open-source middleware plugin between the channel bot and Hermes. It manages per-user private memory and buffers wiki candidates for the 3am llm-wiki batch.

## Storage Layout

```
$MMD_DATA_DIR/
├── users/
│   ├── telegram_123456.md
│   ├── telegram_123456_log.md
│   └── discord_alice.md
├── _wiki_queue/
│   ├── 20260520.jsonl
│   └── 20260520.jsonl.done
├── _pairing/
│   └── {code}.json
├── identity.json
└── identity.lock
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

Target size: ≤ 200 lines. When exceeded, LLM compresses by removing least-referenced entries; deleted content is summarised into `{user_id}_log.md`.

## Lifecycle Hooks

### `initialize()`
- Ensure `users/` and `_wiki_queue/` directories exist.
- Remove orphaned `.tmp` files left by crashed atomic writes.

### `prefetch(user_id)`
- Read `{user_id}.md`.
- Inject content into Hermes system prompt as the user's memory context.

### `sync_turn(user_id, turn)`
- Append raw turn to in-memory buffer. **Zero LLM cost.**

### `_extract_and_persist(user_id)` — triggered by whichever comes first:
- **(A) Context pressure**: accumulated buffer reaches 50% of session context limit (default: 2000 tokens).
- **(B) Session end**: `on_session_end()` fires this unconditionally.

Makes **one Gemini Flash call** to classify the entire buffer:

```json
{
  "private": [{"op": "ADD|UPDATE|DELETE|NOOP", "content": "..."}],
  "wiki":    [{"content": "...", "reason": "re-derivation cost"}]
}
```

- `private` results → apply ADD/UPDATE/DELETE/NOOP to `{user_id}.md`
- `wiki` results → append to `_wiki_queue/<YYYYMMDD>.jsonl`

Wiki criteria: 2+ sources, or substantial synthesis painful to re-derive.

Result: short sessions → 1 call at end. Long sessions → 1 call at pressure threshold + 1 at end.

### `on_session_end(user_id)`
- Trigger `_extract_and_persist()` if buffer is non-empty.

### `shutdown()`
- Wait for all background queue workers to finish before exit.

## `_wiki_queue` JSONL Schema

Each line is one JSON object:

```json
{
  "v": 1,
  "ts": "2026-05-20T15:30:00Z",
  "user_id": "telegram_123456",
  "content": "...",
  "reason": "2+ sources / substantial synthesis",
  "hint_page": "optional/page-slug"
}
```

| Field | Required | Description |
|---|---|---|
| `v` | yes | Schema version. Consumer skips and warns on `v != 1`. |
| `ts` | yes | ISO-8601 UTC write time. |
| `user_id` | yes | Source user, for audit only. |
| `content` | yes | Wiki candidate text. |
| `reason` | yes | Why it was classified as wiki-worthy. |
| `hint_page` | no | Suggested target page slug; llm-wiki may ignore. |

**3am consumer rules:**
- Read `<today>.jsonl` only.
- Skip entries where `v != 1`.
- Feed all entries to llm-wiki as a batch.
- Rename file to `<YYYYMMDD>.jsonl.done` after processing to prevent re-runs.

## Concurrency: Per-User Async Write Queue

All writes to `{user_id}.md` go through a per-user `asyncio.Queue`. This serialises `sync_turn`, `_extract_and_persist`, `on_session_end`, and `shutdown` for the same user within a single async event loop.

```python
queues: dict[str, asyncio.Queue] = {}
```

The system runs as a single process; conversations are sequential. The queue prevents interleaving of async tasks within one conversation, not cross-conversation concurrency.

## Identity and Pairing

User IDs follow the format `{channel}_{platform_id}` (e.g. `telegram_123456`, `discord_alice`).

**Before each reply cycle**, the bot resolves the incoming ID to its canonical form:

```python
canonical_id = pairing.resolve(f"telegram_{user_id}")
reply = await agent.chat(message, user_id=canonical_id)
```

`PairingManager.resolve()` is the sole alias-resolution interface. If unpaired, the raw ID is returned unchanged.

**Canonical name priority:** the initiator's existing canonical group wins; the confirmer's group is absorbed. If both are new, `initiator_id` becomes the canonical name.

**Pairing flow:**
1. User A sends `/pair` → system generates a 6-char code (10-min TTL, 3-attempt cap).
2. User B submits the code → `identity.json` is atomically updated (`fcntl.flock` + tmp rename).
3. Caller receives `(canonical_name, merged_ids, memory_files_to_merge)` and is responsible for LLM-merging the listed memory files into `{canonical_name}.md`.

See `src/pairing.py` for the implementation.

## Truncation Policy

When `{user_id}.md` exceeds ~200 lines:
1. LLM identifies and removes least-referenced entries.
2. Removed content is summarised and appended to `{user_id}_log.md`.
3. Main file is overwritten at ≤200 lines.

`{user_id}_log.md` is not loaded into Hermes context — it exists for human inspection only.
