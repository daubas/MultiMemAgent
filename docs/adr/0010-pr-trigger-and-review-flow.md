---
status: accepted
---

# PR Trigger and Review Flow

We need to define when and how Hermes creates GitHub PRs for shared wiki content, who reviews them, and what happens when a PR is rejected.

## Context

ADR-0008 established that all shared wiki changes must flow through PRs. Hermes has a built-in GitHub skill that covers the full PR lifecycle (create branch, commit, open PR, monitor CI status). The `llm-wiki` skill does not exist in the Hermes catalog and must be authored as a custom skill wrapping the GitHub skill.

## Decision

### Trigger Condition

Hermes opens a PR only when content is classified as **shared & reviewable** per the practical rule in ADR-0008. The trigger is explicit, not automatic per-turn:

- User or agent explicitly requests a wiki update, **or**
- Hermes accumulates enough shared-knowledge candidates across a session to justify a batch commit.

Single-turn memory updates that belong in `{user_id}.md` (private memory) do **not** trigger a PR.

### Tooling

All Git and GitHub operations are performed through **Hermes' native GitHub skill**. No custom Git tooling is built. The custom `llm-wiki` skill wraps this GitHub skill to add:

1. Wiki-specific branch naming: `wiki/<topic>/<date>`
2. Markdown diff construction from agent-proposed content
3. PR description template including source turn context

### Review Policy

| Scenario | Reviewer |
|---|---|
| Standard wiki update | Human review required before merge |
| Automated fix (typo, dead link) | Human review still required; no auto-merge |
| PR rejected with comments | Hermes re-reads comments, revises, and force-pushes the branch |
| PR closed without merge | Content is discarded; agent records a NOOP for that candidate |

Human review is the default. No auto-approve path is defined at this stage.

### CI Monitoring

Hermes monitors CI status after opening a PR. If CI fails, Hermes alerts the relevant user session and holds further PRs on the same page until the failure is resolved.

### Rejection Handling

1. Reviewer leaves comments on PR.
2. Hermes reads comments via GitHub skill.
3. Hermes revises the Markdown and updates the branch.
4. If revision is not possible (contradictory feedback, out-of-scope), Hermes closes the PR and logs the decision in `{user_id}_log.md`.

## Consequences

- PR spam is avoided because the trigger is explicit, not per-turn.
- Human review remains the change-control boundary as defined in ADR-0008.
- `llm-wiki` skill is a thin wrapper; most complexity lives in Hermes GitHub skill.
- Rejection handling creates a feedback loop that improves future proposals.
