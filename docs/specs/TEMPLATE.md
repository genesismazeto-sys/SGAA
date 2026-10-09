# SPEC MP-<n> — <title>

Status: DRAFT | FROZEN <date> | CLOSED <date> | ABANDONED <date>
Charter: <three-line quote of the IAsup charter>
Risk tier: R1 | R2 | R3 (the highest of the charter floor and every slice tier)

<!-- Rules (docs/OPERATING_MODEL.md §5): reference global invariants, never copy
them; no shell transcripts; no evidence dumps, only pointers; target ≤~300
lines; Open decisions must be empty before FROZEN. Delete this comment. -->

## 1. Outcome

What the operator or user can do after this phase (≤5 bullets).

## 2. Current facts

Verified facts with `file:line` or symbol references. Unknowns, and how each is
resolved.

## 3. Target design

Owners (module → single responsibility, per `docs/ENGINEERING_STANDARDS.md`
§2); public contracts (routes, functions, CLIs, state machines); data flow;
transaction boundaries and lock order; error model. A diagram only when it
shows the mechanism.

## 4. Decisions

- D1 — decision · alternatives rejected · why.

Open decisions (product or architecture): none.

## 5. Phase invariants

Invariants specific to this phase. Global invariants: `ENGINEERING_STANDARDS.md`
and its guards (§11).

## 6. Scope

- Allowed subsystems / paths:
- Protected (must not change):
- Planned local refactors (`ENGINEERING_STANDARDS.md` §8):
- Out of scope / deferred to:

## 7. Data & schema

Schema version change (yes/no); SQLite / PostgreSQL parity; Path-B and Layer-2
policy impact; real-data custody; dry-run, idempotency, resume and
verification for any data migration.

## 8. Security & RBAC

New or changed routes → RBAC requirement and CSRF; fail-closed paths; secrets;
personal-data handling.

## 9. Compatibility / rollout

Legacy paths kept or removed; ordering; rollback.

## 10. External boundaries / environment permissions

Providers and environments touched; allowed DEV actions; PROD user gates (exact
list, or "none"); run-owned resources and cleanup; credentials the user must
provide.

## 11. Evidence plan

TEP vocabulary, per slice: T1–T4 selection; lanes (E-PG1 / E-PG2 / E-UI /
E-LIVE); expected full-suite trigger (TEP §5.1 letter, or "none expected");
negative and mutation controls; review tier and the boundary where it
applies. Where this section is silent, the TEP decides; it may demand more than
the TEP, never less.

## 12. Slices

| # | Goal | Paths | Exit evidence | Status |
|---|---|---|---|---|
| 1 | | | | |

## 13. Acceptance criteria

- AC1 — testable criterion → evidence.
- ACn — `docs/ENGINEERING_STANDARDS.md` self-audit (§13) passes.

## 14. Phase-specific hard stops

Additions only; `docs/OPERATING_MODEL.md` §7 always applies.

## 15. Deferred / known non-blockers

## 16. Amendments

- A1 <date> — what changed · why · impact · material? (escalated?)

## 17. Closure

Filled in the last slice: acceptance results, slice commits, residuals carried
to `PROJECT_STATE.md`, follow-ups.
