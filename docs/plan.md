# MultiMemD (MMD) — Project Plan

## Background

Hermes agent + its native `llm-wiki` skill already provide a working single-user LLM Wiki workflow:

- Hermes manages conversations, skills, and tool access
- `llm-wiki` handles wiki content synthesis and local Markdown writes
- The GitHub skill handles commits and PRs
- A 3am cron batches daily changes into a PR for human review

This works well for one user. The problem is Hermes has no built-in mechanism for isolating memory per user or routing wiki candidates from multiple users through a shared write path.

## Solution: MMD Plugin

MultiMemD (MMD) is a lightweight middleware plugin that sits between the channel bot (Telegram, Discord) and Hermes. It adds multi-user support without modifying Hermes itself.

```
User A (Telegram) ─┐
User B (Discord)  ─┤── MMD ── Hermes ── llm-wiki ── GitHub wiki
User C (Telegram) ─┘
```

Once MMD is in place, the system naturally becomes a multi-user Hermes agent.

## What MMD Does

1. Resolves each incoming message to a canonical user identity via `pairing.resolve()`
2. Loads that user's private memory (`{user_id}.md`) into Hermes context before each reply
3. Buffers conversation turns with zero LLM cost per turn
4. At session end or context pressure threshold (50%): one Gemini Flash call classifies content into:
   - Private memory → ADD / UPDATE / DELETE / NOOP on `{user_id}.md`
   - Wiki candidates → appended to `_wiki_queue/<YYYYMMDD>.jsonl`
5. Hermes' 3am cron reads the queue, feeds candidates to `llm-wiki`, which synthesizes and writes to the local wiki working tree; GitHub skill commits and opens a PR

## What We're Building

| File | Status |
|---|---|
| `src/pairing.py` | Done — cross-channel identity pairing |
| `src/mmd.py` | To build — MMD core plugin |

## Goal

Validate that MMD works as a plugin. If it does, any Hermes agent becomes a multi-user agent by adding MMD as middleware.
