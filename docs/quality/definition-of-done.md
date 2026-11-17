# Definition of done

A task is done only when **all** of these are true. Writing the code is not done.

1. **Acceptance criteria met, with evidence.** Each criterion in `status.md` maps to a test name, command output or screenshot in the PR description.
2. **Tests prove the behaviour.** New behaviour has tests that fail without the change. Bug fixes start with a failing test.
3. **Checks pass.** `/verify` passes locally and CI passes on the pull request.
4. **Independent review done.** `/review` ran; every BLOCKING finding is fixed; deferred findings are in `tech-debt.md` with a reason.
5. **Security and privacy considered.** The PR description states the impact, even if "none". `security/security-and-privacy.md` is updated when controls or the POPIA register change.
6. **Docs updated.** Every document that `docs/README.md` lists for this kind of change.
7. **No hidden work.** No TODO without a `tech-debt.md` entry. No disabled tests without a reason in `tech-debt.md`.
8. **Honest status.** `status.md` is updated; limitations and anything not verified are stated plainly.

A **phase** is done when every task is done, the phase's "Proven by" criteria in `roadmap.md` are met, the gate report is written, and **the owner has approved it**.
