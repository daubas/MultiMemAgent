# Project Plan

## Goal

Build an agent runtime that can help multiple users maintain an LLM Wiki with GitHub as the source of truth and Mem0 as the scoped memory sidecar.

## Current Direction

- GitHub repo stores the wiki content as Markdown.
- Hermes runs the agent workflow and wiki-maintenance skills.
- Mem0 handles user-scoped and agent-scoped memory isolation.
- PRs and reviews are the change-control boundary.
- Obsidian stays a first-class human viewer/editor.

## What We Are Not Building First

- A separate knowledge database for wiki content.
- A Lithos-style shared-memory coordination layer.
- A full custom UI before the repo workflow is stable.

## Next Steps

1. Keep the wiki content in Markdown.
2. Define the agent workflow for read / summarize / propose / edit.
3. Add the tool and skill wiring needed for Hermes.
4. Keep shared knowledge and private memory clearly separated.