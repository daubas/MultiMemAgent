# Project Plan

## Goal

Build an agent runtime that can help multiple users maintain an LLM Wiki with GitHub as the source of truth and a Markdown Memory Provider as the per-user memory layer.

## Current Direction

- GitHub repo stores the wiki content as Markdown.
- Hermes runs the agent workflow and wiki-maintenance skills.
- Markdown Memory Provider (Mem0-inspired, no Mem0 runtime dependency) handles per-user memory isolation.
- PRs and reviews are the change-control boundary.
- Obsidian is read-only: for inspecting wiki pages and private memory files only. All writes go through llm-wiki.

## What We Are Not Building First

- A separate knowledge database for wiki content.
- A Lithos-style shared-memory coordination layer.
- A full custom UI before the repo workflow is stable.

## Next Steps

1. Keep the wiki content in Markdown.
2. Define the agent workflow for read / summarize / propose / edit.
3. Add the tool and skill wiring needed for Hermes.
4. Keep shared knowledge and private memory clearly separated.

## Decided

### Agent 工作流程
參照 Mem0 的記憶操作模型（ADD / UPDATE / DELETE / NOOP），以相同分類邏輯驅動 read / summarize / propose / edit 四階段：
- **Read**：載入用戶 Markdown 記憶檔與相關 Wiki 頁面
- **Summarize**：萃取本輪對話中值得持久化的資訊，分類為 ADD / UPDATE / DELETE / NOOP
- **Propose**：若屬共享知識，生成 Markdown diff 並開 PR；若屬用戶私人記憶，直接寫入 `{user_id}.md`
- **Edit**：PR 合併後 repo 即為新的真實來源；私人記憶則在 `sync_turn()` 後立即生效

### Hermes Tool / Skill Wiring
`llm-wiki` skill 與 MCP 連接方式**由 Hermes 原生設定處理**，不另立 ADR。
具體介面與參數依照 Hermes skills catalog 的標準格式配置，無需自定義中間層。