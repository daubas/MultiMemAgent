---
status: accepted
---

# Multi-User Content Isolation and llm-wiki as the Write Path

## Context

The earlier framing of "multi-user conflict" was incorrect. Conflicts do not arise in this system because:

**Obsidian is read-only in this architecture.** It is used to inspect private memory files (`{user_id}.md`) and wiki pages, but it cannot write shared wiki content directly. All writes go through `llm-wiki`. If a human wants to edit wiki content, they do so via Obsidian as a draft surface and then explicitly trigger `llm-wiki` to formalize the change — the edit does not bypass the write path.


1. Each user's memory content is isolated by `{user_id}.md` — one user's writes never touch another's file.
2. All shared wiki writes go through the `llm-wiki` skill. The LLM mediates every write, so raw Git text conflicts are not the resolution surface.

## Decision

### No Cross-User Conflicts by Design

User isolation is structural. `{user_id}.md` files are keyed by identity; parallel writes from different users operate on different files and cannot collide.

There is no locking, queuing, or merge strategy needed for cross-user scenarios because the problem does not exist at the file level.

### llm-wiki is the Sole Write Path for Shared Content

All shared wiki content flows through the `llm-wiki` skill, which has built-in content routing logic:

| Condition | Destination |
|---|---|
| 2+ sources, or central to one source, AND result is substantial synthesis / deep analysis | Write to wiki |
| Trivial lookup, or ephemeral response derivable from existing pages | Stay in session memory |

The decision criterion is **re-derivation cost**: if it would be painful to reconstruct later, archive it. This judgment is LLM-driven and automatic — no explicit user command is needed.

This means:
- The LLM reads the current wiki state before proposing any change.
- The LLM synthesizes new content with existing content, absorbing what would otherwise be overlapping edits.
- By the time the 3am cron commits and opens a PR, the content is already LLM-resolved; there is no raw Git conflict to arbitrate.

All agents write to the **same local wiki working tree** (single `wiki.path`). There are no separate per-agent branches during the day. The system runs as a **single Hermes process** — conversations are handled sequentially, so llm-wiki writes to the same page are never truly concurrent. No per-page locking or queue is required. The 3am cron opens one PR per changed page from that single working tree. Git worktree isolation is not used for daily writes; it remains available for rollback and investigation purposes only.

### Practical Rule

- Cross-user conflict → does not exist; isolation is structural.
- Same-page concurrent edits → llm-wiki reads current state and synthesizes; no raw conflict.
- Git merge conflict → not expected; if it occurs, it is a signal that a write bypassed llm-wiki and should be investigated.
