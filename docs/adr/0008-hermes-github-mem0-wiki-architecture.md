---
status: accepted
---

# GitHub-backed LLM Wiki with Hermes as Runtime and MultiMemD (MMD)

We want a multi-user LLM Wiki workflow that keeps the wiki itself version-controlled in GitHub, uses Hermes as the agent runtime, and uses MultiMemD (MMD) — a self-built Markdown memory plugin — for per-user memory isolation.

The deletion test for a separate knowledge service is favorable here: if the canonical wiki already lives in Markdown files under Git, then version history, diff review, branch-based conflict resolution, PR approval, and rollback already exist. A dedicated knowledge service would mostly duplicate the repository's strengths unless we need real-time shared mutation or task-claim coordination. For our use case, we do not.

## Decision

- **GitHub repository is the source of truth for wiki content.**
  - Markdown pages live in the repo.
  - Changes flow through branches and pull requests.
  - Review happens in PRs, not in a separate knowledge backend.
  - Obsidian can open the same folder for read-only inspection. It is not a write endpoint.

- **Hermes is the primary agent runtime.**
  - Hermes handles the long-lived agent process, profiles, skills, and MCP/tool access.
  - The `llm-wiki` skill is the agent-facing path for creating and maintaining the wiki.
  - Hermes is the editor / curator, not the canonical storage layer.

- **Mem0 is an architectural reference only. It is not used as a runtime dependency.**
  - The actual private memory store is MultiMemD (MMD) — see ADR-0009.
  - Mem0's entity-scoping model (user_id / agent_id / run_id) and ADD/UPDATE/DELETE/NOOP operation classification are used as design references.
  - Do not introduce Mem0 as a library or service dependency.

## Considered Options

- **Lithos as the main layer.** Rejected for this project direction.
  - Lithos is strong when the system itself needs a shared memory service with coordination primitives.
  - Our current need is a Git-backed wiki with reviewable edits, so Git already solves the main storage and conflict problems.

- **Honcho as the main layer.** Rejected for the same reason.
  - Honcho is a memory/runtime product, not a Git-native wiki workflow.
  - It can be useful for memory, but it does not replace PR review and repository history.

- **GitHub repo only, no agent runtime.** Rejected.
  - We still want Hermes to curate content, manage profiles, and operate the wiki through MCP/tools.

- **GitHub repo + Hermes + MultiMemD (MMD).** Accepted.
  - This keeps the wiki canonical and reviewable while giving agents a runtime and isolated memory.
  - Mem0 is referenced for its design patterns but not used as a runtime component.

## Consequences

- **Content governance improves.**
  - All wiki changes are diffable, reviewable, and revertible.
  - PRs become the natural change-control boundary.

- **Agent behavior becomes easier to reason about.**
  - Hermes owns generation, editing, and maintenance workflows.
  - MultiMemD (MMD) keeps user-specific memory out of the shared wiki corpus.

- **The wiki stays human-readable.**
  - Markdown remains the primary format.
  - Obsidian is a read-only inspection tool; all edits go through llm-wiki.

- **We avoid a second authoritative knowledge store.**
  - No separate knowledge database is needed for the wiki itself.
  - Any future memory service must justify itself as memory, not as content governance.

## Workflow Sketch

1. A user or agent provides input.
2. Hermes reads existing wiki pages and personal memory as needed.
3. Hermes decides whether the result belongs in the shared wiki or only in private memory.
4. Shared wiki content is written as Markdown changes in the GitHub repo.
5. The change is reviewed through PRs.
6. After merge, the repo is the source of truth.
7. MultiMemD (MMD) stores only the user-scoped memory that should not become shared wiki content.

## Practical Rule

If the information should be:

- **shared and reviewable** -> commit it to the GitHub wiki
- **personalized or user-scoped** -> keep it in MultiMemD (MMD)
- **agent behavior / editing workflow** -> let Hermes handle it

## References

- Hermes skills catalog: https://hermesagent.org.cn/en/docs/reference/skills-catalog
- Hermes configuration: https://hermesagent.org.cn/docs/user-guide/configuration
- Hermes work-with-skills guide: https://hermesagent.org.cn/en/docs/guides/work-with-skills
- Mem0 README: https://github.com/mem0ai/mem0
- Mem0 entity-scoped memory: https://docs.mem0.ai/platform/features/entity-scoped-memory
- Mem0 organizations and projects: https://docs.mem0.ai/api-reference/organizations-projects