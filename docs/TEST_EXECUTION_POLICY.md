# SGAA-EJ — Test Execution Policy (TEP)

**Version:** 1.1 — 2026-10-09 (MP-0: role wording for the spec-driven operating
model and the E-LIVE lane; tiers, triggers, invalidators and failure classes
unchanged). v1.0 — 2026-10-06 (Phase G1, docs only; entry HEAD
`22f0274718d1c9741b8988a34ccc425ccfbb9ffc`).
**Authority:** canonical cross-cutting owner of test selection, rerun and
evidence-reuse policy for all work after UT-17 (see §14). It supersedes the
generic per-unit full-suite rule of `docs/refactor/EXECUTION_PROTOCOL.md` §7
step 7 for new work. The executor applies this policy autonomously under
`docs/OPERATING_MODEL.md`; its decisions are recorded, never submitted for
authorization. Where a frozen phase SPEC is silent, this policy decides; a SPEC
may demand stronger evidence or declare milestone triggers for its scope, but
it cannot weaken a MUST of this policy.

Keywords MUST, MUST NOT, SHOULD and MAY are normative.

---

## 1. Principle

**Run the smallest test set that materially reduces the uncertainty introduced
by the delta.** Test volume is not confidence. Evidence must match the risk
class.

Two questions decide every run:

1. **What plausible defect can this run detect that the evidence already
   collected cannot?**
2. **If it fails, what decision changes?**

A run with no concrete answer to (1), or whose failure would change no
implementation, review, landing or escalation decision under (2), MUST NOT take
place.

## 2. Test budget

Before any run expected to exceed 5 minutes, and before every full suite, the
executor MUST write this decision record into the phase evidence. It is a
record of the executor's decision, not a request for authorization:

```
TEST BUDGET
delta:    <files/surface; production bytes identical yes/no>
risk:     <specific plausible defect class>
run:      <exact tier/lane/command; estimated runtime>
new info: <what this run can detect that existing evidence cannot>
if fails: <decision that changes>
```

If `new info` has no concrete answer, the run MUST NOT take place. Shorter
runs need no written budget, but the two questions of §1 still apply.

## 3. Scope tiers

Tiers are a ladder of scope. Select from the bottom; escalate only per §3.7.

### 3.1 T0 — Static / custody

Purpose: prove what changed. Always required, as applicable to the unit:
branch / HEAD / status; exact dirty manifest; `git diff --check`; custody and
hash requirements relevant to the unit (for example `database.db`).

- Production-byte identity MUST be shown when delta qualification (§6) relies
  on unchanged production.
- Collection reconciliation (`collected = prior + added − retired`) is required
  only when tests are added, removed or renamed; when `pytest.ini`, plugins or
  collection configuration change; when parametrization materially changes the
  expected count; or when collection drift is suspected. Global collection is
  NOT required on every change.

### 3.2 T1 — Direct contract / reproduction

Required for every behavioural change. Purpose: prove the exact changed contract
or defect — a RED→GREEN reproduction, one route, one resolver, one transaction
invariant, a negative or mutation control. A purely additive feature without a
prior bug uses direct contract tests; an artificial RED failure MUST NOT be
invented.

### 3.3 T2 — Owner contract

Run the changed owner's complete contract when that owner has further behaviours
the delta can plausibly affect (examples: the transaction-owner suite for a
transaction-primitive change; the FC13 suite when `tests/fc13_semantic_scanner.py`
changes). "Whole module" is NOT mandatory merely because a file changed.

### 3.4 T3 — Impact set

Purpose: cover actual dependents. Select mechanically where practical:
importers of changed modules/symbols; callers of changed helpers; literal path or
contract references (`grep` over `tests/` and `tools/`); existing dependency and
ownership inventories. Vague "domain" MUST NOT be the primary selection concept.

Escalate when the impact set cannot reasonably be bounded, the changed primitive
has broad fan-out, or the impact set is a substantial fraction of the repository.
This is a judgment criterion recorded in the budget, not a fixed percentage.

### 3.5 T4 — Global governance / architecture guards

Purpose: catch whole-tree ratchets, ownership pins and architecture invariants
(FC13 is the reference case). **No canonical marker or lane exists yet** (§11).
Until it does, the executor MUST select the relevant existing global guards for
the changed architecture or surface from the candidate families in §11 —
starting from the permanent guards in `docs/ENGINEERING_STANDARDS.md` §11 — and
name them in the run record. Once a measured, acceptably cheap G-lane exists,
governance MAY make it a routine gate for every production change.

### 3.6 T5 — Full suite

Purpose: orthogonal repository-wide integration sweep and detection of unknown
unknowns. T5 is an exception governed by §5, not a unit-close ritual.

### 3.7 Escalation

Escalate one step only when a lower tier fails unexpectedly, the blast radius
cannot be bounded, the changed primitive is widely shared on an executed path,
dependency analysis shows broader exposure, or a §5 trigger applies. After a
broad run exposes failures, fix and verify at T1–T4 and delta-qualify (§6); do
not climb back to T5 by default.

## 4. Orthogonal evidence lanes

Scope tiers do not substitute for environment or risk-class evidence. No amount
of T5 replaces a required lane.

| Lane | Evidence | Required for |
|---|---|---|
| **E-PG1** | Real PostgreSQL, single connection | Dialect, DDL/types, `RETURNING`, constraints, runtime compatibility |
| **E-PG2** | Real PostgreSQL, multiple connections | Blocking, serialization, deadlocks, lock ordering, snapshot visibility |
| **E-UI** | Browser / visual | As governed by `docs/design-system/README.md` §5 (`--visual`, opt-in) |
| **E-LIVE** | Real external provider, DEV environment only | Provider contracts a fake cannot prove (transport, auth headers, limits, CORS, signed URLs), when the SPEC declares a provider-integration surface |

PostgreSQL evidence hierarchy, weakest to strongest for PG semantics: static
SQL / lock-order inspection → PG-shaped doubles (`tests/pg_shaped_support.py`:
statement order and lock-conflict matrix; it raises instead of waiting, so it
proves no blocking behaviour) → SQLite regression (default-engine behaviour only)
→ E-PG1 → E-PG2. The full application suite on SQLite proves default-engine
integration only.

Rules:

- **A GREEN SQLITE FULL SUITE MUST NOT BE CITED AS EVIDENCE OF POSTGRESQL
  LOCKING, SNAPSHOT, DEADLOCK OR MULTI-CONNECTION CORRECTNESS.**
- A run MAY claim real-PG evidence only when `SGAA_PG_TEST_URL` was set and the
  real-PG tests were collected and executed, not skipped.
- When required real-PG evidence is unavailable, the unit MUST record
  `REAL-PG EVIDENCE: ABSENT` as explicit technical debt and, where the evidence
  gates PostgreSQL cutover, as a cutover blocker.
- For a lock or isolation change, a small E-PG2 test is the decisive evidence;
  T5 on SQLite MUST NOT be scheduled in its place.
- E-LIVE runs only against a DEV environment the SPEC declares, with
  run-owned, uniquely named resources that are cleaned up afterwards, and a
  leak audit (no secret or personal data in output). Any PROD use is a user
  gate (`docs/OPERATING_MODEL.md` §7). A green fake-provider suite MUST NOT be
  cited as E-LIVE evidence.

## 5. Full-suite triggers

### 5.1 T5 MUST run when at least one applies

- **A.** Existing behaviour of a genuinely wide/shared primitive changes on a
  path the repository exercises broadly — for example the connection/transaction
  owner on the normal SQLite runtime path, app bootstrap or hooks, shared
  auth/authz gates, the global message authority, or a shared test/bootstrap
  primitive with broad existing semantics.
- **B.** Schema, migration, `init_db` or seed semantics change with broad
  application impact.
- **C.** The production delta spans multiple unrelated domains such that T3
  cannot meaningfully bound the blast radius.
- **D.** Dependency, interpreter, environment or test-collection infrastructure
  changes.
- **E.** `tests/conftest.py`, autouse/session bootstrap or equivalent global
  test machinery changes materially.
- **F.** T2/T3/T4 finds an unexpected failure and one re-scope still cannot
  bound the blast radius.
- **G.** An explicit integration, release or deployment milestone (§12)
  requires an orthogonal repository-wide sweep.

Touching a file that hosts a wide primitive is NOT by itself a trigger: the
changed semantics and their execution path decide. Example: a PostgreSQL-only
additive branch in `app/db.py` that SQLite never executes does not justify a
SQLite full suite; it requires T1–T4 and the applicable E-PG lane.

### 5.2 T5 MUST NOT be justified solely by

"closing the unit"; "more confidence"; "canonical record"; "fresh final full"; a
narrow bug fix; a docs-only change; a narrow governance-only or test-only delta;
or a prior full suite followed by a delta that touches no invalidator (§7).

## 6. Delta qualification

A prior complete broad or full run MAY qualify a later tree when all hold:

1. The prior run was complete, and its custody and result are known.
2. T0 enumerates the delta exactly.
3. No relevant evidence invalidator (§7) was touched.
4. Every previously failing node attributable to the candidate is now green.
5. Changed tests are rerun at an appropriate file or owner scope.
6. Changed assertions or allowlists that could weaken a guard have negative
   controls proving the guard still discriminates.
7. Changed production is either byte-identical to the broad-run candidate, or
   narrow, bounded and covered by the T1/T2/T3/T4 evidence appropriate to that
   delta.
8. Collection is reconciled only when the delta can affect collection (§3.1).

The record MUST read:

```
DELTA-QUALIFIED
against:      <prior run id / tree>
delta:        <files / surface>
reran:        <focused evidence>
invalidators: none
```

Another full suite MUST NOT be run merely to create a new "canonical record".

## 7. Evidence invalidators

Prior broad evidence is invalidated, for the affected risk classes, when the
delta changes:

- existing semantics of the global test harness or fixtures;
- pytest collection, configuration or plugins;
- the interpreter, dependencies or runtime environment;
- schema, bootstrap or seed semantics relevant to the prior run;
- existing behaviour of a truly wide primitive (§5.1 A);
- existing semantics of a shared helper with broad fan-out (§10);
- environment routing such as `DATABASE_URL` / `SGAA_PG_TEST_URL`;
- an artifact or baseline file (for example under `tests/_artifacts/`) — this
  invalidates the tests that consume it, and its consumers MUST be rerun; it
  invalidates the whole suite only when the artifact is itself global.

Evidence does NOT expire after an arbitrary number of days. Time-dependent
evidence expires only when the assumption it depends on crosses a relevant
boundary, such as a semester or calendar transition (REF-0TF-A class).

## 8. Failure classification and rerun

A rerun is NEVER automatic. Every failure MUST first be classified.
Classification and the resulting action are the executor's decisions under this
policy; they are recorded in the phase evidence and need no supervisor
authorization. `docs/refactor/REF_0TF_FAILURE_CLASSIFICATION.md` is historical
input to this taxonomy.

| Class | Meaning | Action |
|---|---|---|
| **A** | Candidate-related | Fix the candidate; rerun the failing contract plus the appropriate T2/T3/T4. Rerun T5 only if the fix itself hits a §5 trigger or §7 invalidator. |
| **B** | Deterministic governance / expectation mismatch | The executor adjudicates the expected or governance change when the frozen SPEC's declared contract explains it (otherwise hard stop H9, `docs/OPERATING_MODEL.md` §7); add negative controls when a guard is weakened; rerun the affected governance/owner lane. No T5 absent an invalidator. |
| **C** | Registered known flake | Valid only if a §8.1 registry entry matches mechanism, affected nodes, failure fingerprint, owner and expiry/review condition. "Probably flaky" is class E. |
| **D** | Environmental | Repair the environment; rerun only the portion whose evidence the environment failure invalidated, without further authorization. If collection or session initialization aborted, the run is not valid evidence. The same environmental cause failing twice is a BLOCKER (`docs/OPERATING_MODEL.md` §7), not a reason for a third run. |
| **E** | Unclear | Investigate and reproduce narrowly before changing anything. A full suite MUST NOT be rerun in the hope it turns green. |

A full suite MUST NOT be repeated merely to re-record a green result. A failure
MUST NOT be hidden by filtering, improvised `xfail` or selective rerun.

### 8.1 Known-flake registry

Empty. An entry is added only when a real flake has a reproduced, documented
mechanism.

| Mechanism | Affected nodes | Failure fingerprint | Owner | Expiry / review condition |
|---|---|---|---|---|
| — | — | — | — | — |

## 9. Test-only and governance-only deltas

"Tests don't need testing" is not a rule. Handle by kind:

| Delta | Required |
|---|---|
| Weakening / removing an assertion, widening an allowlist | Explicit adjudication by the executor against the SPEC's declared contract change (otherwise hard stop H9); negative control; affected owner/governance tests. Permanent guards: `docs/ENGINEERING_STANDARDS.md` §11. |
| Strengthening | The new/changed test plus the relevant owner and global-guard scope. |
| Expected-output rebaseline | Cause tied to the delta; consumers of that baseline rerun. |
| Narrow allowlist entry | Focused owner/governance test; negative controls proving neighbours remain rejected. |
| Negative-control-only | Direct file/owner test is ordinarily sufficient. |
| Shared fixture / `conftest.py` / harness | Potentially broad: apply §5 and §10. |
| Docs only | T0 only, unless a tool or test explicitly consumes the document. As of 2026-10-06, re-verified 2026-10-09 (MP-0), no test reads the governance documents (references are docstring mentions only). |

## 10. Shared test infrastructure

- Changing the **existing** semantics of a high-fan-out helper requires its
  importers / impact set, and T5 if the effective blast radius cannot be bounded
  or the session/global database or bootstrap changes.
- Adding a new, unused or purely additive helper function does not by itself
  trigger T5; its callers are the impact set.
- `tests/conftest.py` (environment routing, autouse per-test fixture,
  session database bootstrap, custody guard), global autouse fixtures and
  collection configuration (`pytest.ini`) remain strong T5 triggers when their
  behaviour changes.

Examples of high-fan-out helpers (direct importing test files, measured by grep
at `22f0274`; illustrative, not fixed thresholds): `versioned_test_support` 132,
`session_support` 75, `canonical_request_test_support` 46,
`canonical_matrix_test_support` 37, `canonical_baseline_support` 25,
`root_admin_test_config` 15. Low fan-out examples: `pg_shaped_support` 2,
`fc13_semantic_scanner` 2.

## 11. Global governance lane (G-lane) — planned follow-up

Not implemented. A separate, explicitly authorized unit will add it. Until then,
T4 operates as in §3.5.

Candidate guard families (non-exhaustive): FC13 obsolete-authority scanner;
route inventory snapshot; RBAC requirement coverage; route-complete actor matrix;
CSRF inventory; DB connection ownership; mail service boundary; canonical
baseline / governance probes and the request-hook write-isolation (C4) guard;
residual ownership and `app → main` edge scans; message catalogue and backend
message-scanner inventory; schema authority and static schema parity; selected
Design System contracts when UI is touched. Several of these live as individual
tests inside domain-named files, so the lane needs per-test selection.

Requirements for the future lane:

- measured runtime, with a target of roughly under 5 minutes, subject to
  measurement;
- a meta-guard that fails when a whole-tree production scanner sits outside the
  lane;
- an optional split into `governance` and `governance_slow` if measurement
  requires it.

## 12. Milestone full suites and reporting

Full suites are milestone- or risk-triggered, not periodic. Examples: before a
release or deployment; at a `clean-baseline` integration milestone; at a
milestone declared in the frozen phase SPEC; whenever a §5.1 trigger applies. A fixed cadence MAY be introduced later, only after timing and
failure-attribution data exist.

The next legitimately triggered full suite SHOULD record slow tests and skip
reasons, for example `python -m pytest -q --durations=50 -rs`. Full-suite
reports SHOULD state skips by reason so a skipped real-PG lane is never read as
green PG evidence.

## 13. Retrospective examples

Illustrations of the rules, not permanent special cases.

- **U5-A** (`460f9f0`, PostgreSQL schema authority): the first full suite was
  justified by the broad schema/runtime boundary (`init_db`, `db_maintenance`,
  `app/db.py`; §5.1 A/B). Real-PG evidence remained a separate lane and was
  unavailable on the executing machine.
- **U5-B** (`f273091`, runtime SQL dialect): the first full suite was justified
  by a wide, multi-domain runtime-dialect change (§5.1 A/C). Its two failures
  were stale governance tests pinning retired SQLite literals (class B). After a
  bounded governance-only correction with production byte-identical, the second
  full suite was correctly skipped (§6).
- **U5-C** (`22f0274`, activity-version serialization): under this policy the
  per-unit full suite would NOT have been required. The `app/db.py` delta was a
  docstring plus a PostgreSQL-only connection setting that SQLite never executes;
  the behavioural change was bounded to the activity-version owners (T1–T3). Its
  useful discovery was FC13, which belongs in the future G-lane (T4). The
  materially missing evidence was E-PG2 (multi-connection create×create and
  create×delete on one base), not another SQLite sweep. Not rerunning the full
  suite after the bounded FC13 delta was correct.

## 14. Relationship to other governance

- `docs/OPERATING_MODEL.md` — the process in which the executor applies this
  policy; the hard stops and BLOCKER referenced here are defined there (§7).
- Frozen phase SPECs (`docs/specs/`) — may demand stronger evidence or declare
  milestone triggers for their own scope; where a SPEC is silent this policy
  decides; a SPEC cannot weaken a MUST here.
- `docs/ENGINEERING_STANDARDS.md` — owns the permanent guards (§11) from which
  T4 selects, and the structural rules that carry forward from
  `EXECUTION_PROTOCOL.md`.
- `docs/refactor/EXECUTION_PROTOCOL.md` — historical. Its §7 step 7 per-unit
  full suite, the ~330 s runtime estimate, and the repeated "canonical / fresh
  final full" runs recorded in §11 and in historical blocks are historical
  requirements and records of the structural refactor (UT-1…UT-17). They do
  not govern new work.
- `docs/refactor/PYTEST_CUSTODY_EXTERNAL_WRITER_CONTRACT.md` — remains the entry
  contract for any full-suite run (supported runtime state and custody guard).
- `docs/design-system/README.md` — remains the owner of E-UI gates.
- Historical evidence everywhere is preserved as recorded; this policy does not
  reclassify or rewrite it.
