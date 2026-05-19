---
status: accepted
---

# Multi-Agent Conflict Resolution

We need a strategy for handling concurrent edits to the same wiki page across multiple agents or users, and for isolating per-user memory writes.

## Context

**Hermes** provides Git worktree isolation for parallel multi-agent operations on the same repository, but has no built-in distributed lock or conflict resolution primitives.

**Mem0** enforces isolation through entity scoping (`user_id`, `agent_id`, `run_id`) and uses `threading.Lock()` for thread-level safety. This covers in-process concurrency but not multi-process deployments.

The two conflict surfaces are separate:

| Surface | Risk |
|---|---|
| Shared wiki (Git) | Two agents propose conflicting edits to the same Markdown page |
| Private memory (`.md` files) | Two sessions for the same user write simultaneously |

## Decision

### Shared Wiki — Worktree Isolation + Human Merge

Each agent edit runs in a **dedicated Git worktree and branch** (Hermes native). This means:

- No agent edits the `main` branch directly.
- Conflicts surface at PR merge time, not during editing.
- When two PRs edit overlapping sections of the same page, the second PR to merge will have a Git conflict that **requires human resolution** before merge.

No automated wiki-content merge is performed. The human reviewer is the merge authority.

To reduce collision frequency:

- Branch naming includes page path: `wiki/<page-slug>/<date>-<agent-id>`
- Before opening a PR, Hermes checks if an open PR already targets the same page. If one exists, Hermes either rebases onto it or waits for it to merge.

### Private Memory — Mem0-Style Entity Scoping

Per-user Markdown memory files follow the same isolation model as Mem0:

- Every read and write is scoped to exactly one `user_id`.
- File path itself encodes scope: `users/{user_id}.md`
- `sync_turn()` (Gemini Flash, per ADR-0009) operates on one user file per invocation; parallel invocations for different users are safe by design.
- Concurrent writes for the **same user** from multiple sessions are serialized with a per-file write lock (equivalent to `threading.Lock()` in Mem0's SQLiteManager).

### Multi-Process Caveat

`threading.Lock()` does not protect across multiple OS processes. If the deployment runs more than one Hermes process:

- Use file-based locking (`fcntl.flock` or equivalent) on `{user_id}.md` for writes.
- This is a deployment concern, not a design concern; the single-process assumption holds until explicitly scaled out.

## Consequences

- Wiki conflict handling is simple: one branch per edit, human resolves conflicts at PR time.
- Memory conflict is avoided structurally through per-user file isolation.
- Collision frequency is reduced by the pre-open-PR check for same-page open PRs.
- Multi-process scaling requires adding file-level locking at the deployment layer.
