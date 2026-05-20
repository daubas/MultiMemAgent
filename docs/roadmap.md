# MMD Roadmap

Features deferred from v1. Design notes are preserved here for when the time comes.

---

## Wiki Candidate Buffering

Surface worthy content from conversations into the shared llm-wiki.

**How it works:**
- Gemini Flash classification adds a `wiki` key to the output alongside `private`
- Wiki candidates are appended to `_wiki_queue/<YYYYMMDD>.jsonl`
- Hermes' 3am cron reads the queue, feeds candidates to `llm-wiki`, which synthesises and writes to the local wiki working tree
- GitHub skill commits and opens one PR per day (`wiki/batch/<YYYYMMDD>`)

**Queue entry schema:**
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

Consumer rules: read today's file only, skip `v != 1`, feed all entries to llm-wiki as a batch, rename to `.done` after processing.

---

## Cross-Channel Identity Pairing

Merge a user's Telegram and Discord accounts into one shared memory file.

**`src/pairing.py` is already written.** It handles:
- `PairingManager.create_request()` — generates a 6-char code (10-min TTL, 3-attempt cap)
- `PairingManager.confirm()` — atomic `identity.json` update, returns memory files to merge
- `PairingManager.resolve()` — `channel_id → canonical_name`

**When enabled**, the bot resolves identity before each reply:
```python
canonical_id = pairing.resolve(f"telegram_{user_id}")
reply = await agent.chat(message, user_id=canonical_id)
```

Canonical name priority: initiator's existing group wins; if both are new, `initiator_id` becomes canonical. User-supplied names not supported.

**Async write queue** (needed when pairing is active to serialise in-process async tasks per user):
```python
queues: dict[str, asyncio.Queue] = {}
```

---

## Memory Size: Upgrade Path

MMD assumes ≤ 200 lines per user. When that breaks down:

1. **Truncation** — LLM identifies least-referenced entries, compresses to ≤ 200 lines, appends summary to `{user_id}_log.md`
2. **Upgrade to mem0** — natural exit path if the use case outgrows MMD
