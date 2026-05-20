---
status: accepted
---

# PR Trigger and Review Flow

## Context

ADR-0008 established that all shared wiki changes flow through PRs. ADR-0011 established that `llm-wiki` is the sole write path for shared content and handles all content synthesis before any Git operation occurs.

Hermes has a native GitHub skill covering the full PR lifecycle (create branch, commit, open PR, monitor CI). `llm-wiki` (`research/llm-wiki`) is a **built-in bundled skill** in Hermes, implementing Andrej Karpathy's LLM Wiki pattern. It ships with Hermes and is auto-deployed to `~/.hermes/skills/` on install.

**Verification:** `hermes skills list | grep llm-wiki` confirms the skill is present before first use.

**llm-wiki is not git-aware.** It manages a local Markdown directory only. All git operations (commit, push, branch, PR) are handled exclusively by the GitHub skill.

## Decision

### Trigger: Daily 3am Batch

Shared wiki changes are not pushed per conversation turn. They are batched and pushed to GitHub at **03:00 daily** via `hermes cron create "0 3 * * *"`.

**Candidate persistence is handled by MultiMemD (MMD).** During each conversation, MMD buffers wiki candidates in `_wiki_queue/<YYYYMMDD>.jsonl` — no llm-wiki call is made until the 3am batch. A gateway restart between conversations does not lose any candidate because the queue files are already on disk.

The 3am cron job:
1. Reads all entries in `_wiki_queue/<today>.jsonl`.
2. Feeds each candidate to llm-wiki for synthesis and deduplication.
3. llm-wiki writes the synthesized result to the local wiki working tree.
4. Runs `git diff` to identify what changed.
5. Uses the GitHub skill to commit those changes and open a PR.

This means:
- No PR spam from individual conversations.
- llm-wiki absorbs all content conflicts at the LLM layer before writing to disk.
- The batch is naturally idempotent: if the cron fails, re-running it picks up whatever is in the working tree.

### Tooling

**`llm-wiki` skill** handles all content decisions: trigger classification, page routing, cross-referencing, and consistency linting. In this system, **llm-wiki is called only by the 3am cron** — Hermes' default auto-trigger behaviour (on ≥5 tool calls or wiki topic detection) is disabled.

**Setup (one-time):**
1. Clone the wiki GitHub repo locally.
2. `hermes config set skills.config.wiki.path <path to clone>`
3. `hermes config set skills.config.llm-wiki.auto_trigger false`
4. Ensure git credentials (PAT or SSH key) are configured for that repo — llm-wiki is not involved in authentication.

llm-wiki initialises the directory with `SCHEMA.md`, `index.md`, `log.md` on first use if they do not exist.

**3am cron diff base:** `git diff origin/main` — captures all changes llm-wiki wrote during the batch run.

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
