---
status: accepted
---

# PR Trigger and Review Flow

## Context

ADR-0008 established that all shared wiki changes flow through PRs. ADR-0011 established that `llm-wiki` is the sole write path for shared content and handles all content synthesis before any Git operation occurs.

Hermes has a native GitHub skill covering the full PR lifecycle (create branch, commit, open PR, monitor CI). `llm-wiki` (`research/llm-wiki`) is a **built-in bundled skill** in Hermes, implementing Andrej Karpathy's LLM Wiki pattern. It builds persistent, interconnected Markdown knowledge bases with source ingestion, knowledge querying, and consistency linting. No custom skill code is required.

## Decision

### Trigger: Daily 3am Batch

Shared wiki changes are not pushed per conversation turn. They are batched and pushed to GitHub at **03:00 daily** via `hermes cron create "0 3 * * *"`.

**Candidate persistence is handled by llm-wiki itself.** As a persistent Markdown knowledge base, llm-wiki writes content changes directly to the wiki path (local repo clone) during each conversation. There is no separate staging layer — the files on disk are the persistent state. A gateway restart between conversations does not lose any candidate because the changes are already written to the filesystem.

The 3am cron job only needs to:
1. Run `git diff` to identify what llm-wiki changed during the day.
2. Use the GitHub skill to commit those changes and open a PR.

This means:
- No PR spam from individual conversations.
- llm-wiki absorbs all content conflicts at the LLM layer before writing to disk.
- The batch is naturally idempotent: if the cron fails, re-running it picks up whatever is in the working tree.

### Tooling

**`llm-wiki` skill** handles all content decisions: trigger classification, page routing, cross-referencing, and consistency linting. It is invoked via `/llm-wiki` or triggered automatically when Hermes detects a knowledge-work workflow (≥5 tool calls) or when the conversation references wiki/knowledge topics.

Configuration:
```yaml
# config.yaml
skills.config.wiki.path: <local clone of this GitHub repo>
```

The wiki path must point to the **local clone of this repository** so the 3am cron job commits directly from the llm-wiki working directory.

**GitHub skill** handles all Git and PR operations via natural language commands (e.g. `/github-pr-workflow`), not a structured parameter API.

**Full-file replacement only.** The GitHub skill does not support patch or diff-based writes. The write flow is:
1. `llm-wiki` reads the current wiki page in full.
2. LLM synthesizes the complete updated version.
3. GitHub skill commits the full file to the branch.

Branch naming convention: `wiki/<page-slug>/<YYYYMMDD>`

### Infrastructure Requirement

`hermes cron` requires **`hermes gateway` to be running continuously**. The 3am batch job will not fire if the gateway process is down. This is a hard deployment prerequisite — the gateway must be managed as a persistent service (e.g. systemd, launchd, or equivalent).

### Review Policy

| Scenario | Action |
|---|---|
| Standard wiki update | Human review required before merge |
| PR rejected with comments | Hermes reads comments, revises content, queues for next 3am batch |
| PR closed without merge | Content discarded; NOOP recorded |
| CI failure | Hermes alerts the originating user session; PR held until resolved |

### PR Rejection Handling

Rejection flows back into the next batch cycle:
1. Human reviewer leaves comments on PR.
2. At next 3am run, Hermes reads open PR comments via GitHub skill.
3. Hermes revises the candidate and includes it in the new batch commit.
4. If a PR has been revised and rejected more than **3 times**, it is closed and the candidate is discarded.

## Consequences

- The 3am batch window eliminates race conditions at the Git layer.
- Human review remains the change-control boundary.
- Rejection handling is async and non-blocking — no user session is held waiting for review.
- `llm-wiki` is a Hermes built-in bundled skill; no custom implementation is required beyond setting `skills.config.wiki.path`.
