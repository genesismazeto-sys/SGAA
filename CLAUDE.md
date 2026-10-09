# CLAUDE.md — session pointers

This file only points to the owners; it holds no rules of its own.

Read, in order, at the start of every session:

1. `PROJECT_STATE.md` — present state, active phase, roadmap.
2. `docs/OPERATING_MODEL.md` — roles, lifecycle, autonomy rule (§6), hard stops
   (§7), review tiers (§8), landing (§9), report format (§10).
3. `docs/ENGINEERING_STANDARDS.md` — binding code-health rules and the
   self-audit checklist (§13).
4. `docs/TEST_EXECUTION_POLICY.md` — test selection, reruns, evidence lanes.
5. The active SPEC in `docs/specs/`, if any.

Then reconcile Git (branch, HEAD, upstream divergence, clean tree) before
acting. Repository state beats memory, including assistant memory notes.

Reminders (owner: `docs/OPERATING_MODEL.md` §7 and §9):

- No student or personal data in prompts, review packets, commits, fixtures or
  reports.
- No PROD action, protected-branch action, deployment, force push or history
  rewrite outside the gates the model names.
- Inside an authorized phase, routine work — reruns under the TEP, staging,
  commits, fast-forward push — needs no permission; only hard stops escalate.

Workspace notes:

- Windows with `core.autocrlf=true`: prove file identity with
  `git hash-object`, not with raw-byte hashes of the working tree.
- Real-PostgreSQL lanes need `SGAA_PG_TEST_URL`; full-suite practicalities are
  in `PROJECT_STATE.md` (environment facts).
- Scratch harnesses and bulky evidence stay outside the repository.
