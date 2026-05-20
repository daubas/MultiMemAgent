# MultiMemD (MMD) — Project Plan

## What Is MMD

MMD is mem0's core ideas, stripped down to zero infrastructure dependency:

| mem0 | MMD |
|---|---|
| Per-user isolation | ✅ |
| ADD / UPDATE / DELETE / NOOP extraction | ✅ |
| Async update after conversation | ✅ |
| Vector database (Qdrant / Chroma) | ❌ not needed |
| Embedding model | ❌ not needed |
| Cloud API dependency | ❌ not needed |
| Graph memory | ❌ not needed |

**Storage:** plain `.md` files. **Retrieval:** LLM reads the whole file — no search needed when memory is small.

## Positioning

> mem0 for Hermes, targeting lightweight bot scenarios, zero infrastructure dependency.

For Hermes users, the official mem0 plugin requires an API key, a vector database, and a monthly fee. MMD requires nothing — it works out of the box.

## The Honest Boundary

mem0 uses vector search because memory can grow too large for the LLM to read in full. MMD's design assumes:

```
Each user's .md stays around ~200 lines
→ fits in LLM context
→ no vector search needed
```

This assumption holds for typical Telegram / Discord bot usage. If a user's memory grows to thousands of lines, the options are:
1. Truncation (compress and summarise, keeping the file ≤ 200 lines)
2. Upgrade to the official mem0 plugin

MMD handles option 1. Option 2 is the natural exit path if the use case outgrows MMD.

## Scope

### v1 — Current Focus

**Per-user private memory.**

Each user has their own `{user_id}.md`. Before each reply, MMD loads it into Hermes context. After the session, MMD updates it using one Gemini Flash call to classify what changed.

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
