# MMD Future Work

This file tracks work that is not part of the current stable core.

## Current Core

The core product is already implemented:

- per-user Markdown memory
- structured LLM memory updates
- compaction into active and archived memory
- idle and pre-compression flushing
- UUID-based cross-channel pairing
- `/mmd` and `/pair` slash commands

Future work should preserve the local-first, low-infrastructure boundary unless
there is a clear reason to split into an optional extension.

## Next Validation

- Run MMD inside a real Hermes gateway and confirm the lifecycle methods are
  called as expected.
- Verify Telegram and Discord user IDs resolve consistently through
  `PairingManager`.
- Confirm `plugin/plugin.yaml` hook declarations match the actual Hermes plugin
  loader requirements.
- Exercise memory compaction and `load_deep_memory` with real LLM responses.

## Documentation Cleanup

- Add a short manual test script for local Hermes integration.
- Keep archived design documents under `archive/` once current docs supersede
  them.

## Optional Feature: Wiki Candidate Buffering

Surface conversation content that should become shared project knowledge rather
than private user memory.

Possible flow:

- classifier emits a separate `wiki` key alongside `private`
- candidates append to `_wiki_queue/<YYYYMMDD>.jsonl`
- a scheduled job batches candidates into a wiki agent or llm-wiki workflow
- processed queue files are renamed to `.done`

Candidate schema:

```json
{
  "v": 1,
  "ts": "2026-05-20T15:30:00Z",
  "user_id": "telegram_123456",
  "content": "...",
  "reason": "substantial synthesis or repeated signal",
  "hint_page": "optional/page-slug"
}
```

This should remain optional because shared wiki memory has different privacy
and review requirements than per-user memory.

## Upgrade Path

MMD is intentionally optimized for small, readable memory files. If a deployment
needs large-scale semantic search, switch to a retrieval-backed memory system
instead of adding vector infrastructure to the core plugin.
