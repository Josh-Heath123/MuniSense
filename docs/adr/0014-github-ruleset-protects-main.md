# ADR-0014: A GitHub ruleset protects `main`

- **Status:** Accepted. Supersedes ADR-0010's "Protecting `main`" point only; everything else in ADR-0010 stands.
- **Date:** 2026-11-20 (decided by the owner, W21, E53)
- **Deciders:** Josh Heath (owner)

## Context

ADR-0010 says: "GitHub branch protection on a private repository needs a paid plan, so it is not relied on. Instead, `guard_bash.py` will block Claude Code from pushing to `main` (task P0-9); changes reach `main` only through a pull request that the owner merges."

Since E52 the owner has GitHub Pro and a ruleset on `main` ("protect main", active, no bypass): a pull request is required (0 approvals), the "verify and audit" check is required, and force pushes and deletion are blocked. W21 asked how a paid plan squares with CLAUDE.md rule 6 (zero spending) and whether ADR-0010's point still holds.

## Decision

- **The E52 ruleset on `main` is the control.** Merges to `main` need a pull request and the green "verify and audit" check, and `main` cannot be force-pushed or deleted. GitHub enforces this, for everyone.
- **The local guards stay, as defence in depth:** `guard_bash.py`'s block on pushes to `main`, and the pre-push hook (P0-5, P0-9). They act before anything reaches GitHub, and they keep working if the ruleset ever stops being enforced.
- **Cost basis (rule 6).** The owner's GitHub Pro subscription existed before MuniSense and is paid independently of it, so it is not a project cost under CLAUDE.md rule 6. MuniSense takes on no subscription, and nothing in the project may come to depend on a plan the owner would otherwise drop.

## Consequences

- Good: protection of `main` no longer rests only on hooks that the agent's own environment runs; GitHub refuses an unreviewed or red merge, and a force push or deletion of `main`.
- Unchanged limit: CI runs the pull request's own code, so a pull request that changes CI or the guards could still weaken them. The owner's review and the data-only rule for publications (E51, W20) remain the controls.
- **If Pro lapses while the repository is private, protection falls back to the local guards.** The owner states that GitHub enforces rulesets on private repositories only on paid plans. On 2026-11-20 the pages read for this ADR did not state the plan rule for rulesets in their text: "Available rules for rulesets" (docs.github.com, managing-rulesets/available-rules-for-rulesets) lists the rules without plan terms; "About rulesets" names GitHub Team and GitHub Enterprise only for rulesets across an organization; "GitHub's plans" lists "Protected branches" under GitHub Pro's "Advanced tools and insights in private repositories". Re-check the plan rule against GitHub's documentation if the plan or the repository's visibility changes.
- ADR-0010's status line records the supersession; its text is unchanged.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Keep ADR-0010's point and treat the ruleset as unofficial | The ruleset is the strongest control there is; leaving it unrecorded hides what protects `main` |
| Rely on the ruleset alone and drop the local guards | The guards act before a push and survive a lapsed plan; removing them gains nothing |
| Make the repository public to get rulesets on GitHub Free | Changes product and privacy posture; not the question asked |
