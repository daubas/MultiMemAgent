# MultiMemD (MMD) — Project Plan

## Background

Hermes agent + its native `llm-wiki` skill already provide a working single-user LLM Wiki workflow. The problem is Hermes has no built-in mechanism for isolating memory per user.

## Solution: MMD Plugin

MultiMemD (MMD) is a lightweight middleware plugin that sits between the channel bot (Telegram, Discord) and Hermes. It adds multi-user support without modifying Hermes itself.

```
User A (Telegram) ─┐
User B (Discord)  ─┤── MMD ── Hermes
User C (Telegram) ─┘
```

## Scope

### v1 — Current Focus

**Per-user private memory.**

Each user has their own `{user_id}.md`. Before each reply, MMD loads it into Hermes context. After the session, MMD updates it.

That's it.

### Roadmap

- **Wiki candidate buffering** — surface worthy content from conversations into the shared llm-wiki
- **Cross-channel identity pairing** — merge a user's Telegram and Discord accounts into one memory (`src/pairing.py` is already written)

## What We're Building

| File | Status |
|---|---|
| `src/pairing.py` | Done (roadmap feature, usable when needed) |
| `src/mmd.py` | To build — v1 focus |

## Goal

Get `src/mmd.py` working with a Telegram bot. Validate that per-user memory isolation works end-to-end with Hermes.
