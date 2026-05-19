---
status: accepted
---

# Multi-User Content Isolation and llm-wiki as the Write Path

## Context

The earlier framing of "multi-user conflict" was incorrect. Conflicts do not arise in this system because:

1. Each user's memory content is isolated by `{user_id}.md` — one user's writes never touch another's file.
2. All shared wiki writes go through the `llm-wiki` skill. The LLM mediates every write, so raw Git text conflicts are not the resolution surface.

## Decision

### No Cross-User Conflicts by Design

User isolation is structural. `{user_id}.md` files are keyed by identity; parallel writes from different users operate on different files and cannot collide.

There is no locking, queuing, or merge strategy needed for cross-user scenarios because the problem does not exist at the file level.

### llm-wiki is the Sole Write Path for Shared Content

All shared wiki content — regardless of which user or agent initiated the change — flows through the `llm-wiki` skill. This means:

- The LLM reads the current wiki state before proposing any change.
- The LLM synthesizes new content with existing content, absorbing what would otherwise be overlapping edits.
- By the time a PR is opened, the content is already LLM-resolved; there is no raw Git conflict to arbitrate.

Git worktree isolation (Hermes native) remains in use to keep agent edits on separate branches, but its purpose is **auditability and rollback**, not conflict prevention. Conflicts at the Git layer are not expected because llm-wiki controls the write path end-to-end.

### Practical Rule

- Cross-user conflict → does not exist; isolation is structural.
- Same-page concurrent edits → llm-wiki reads current state and synthesizes; no raw conflict.
- Git merge conflict → not expected; if it occurs, it is a signal that a write bypassed llm-wiki and should be investigated.
