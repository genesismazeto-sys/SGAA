# SGAA — Operating Model

**Version:** 2.0 — 2026-10-09 (adopted by MP-0).
**Authority:** process owner for all work after MP-0. Supersedes
`docs/refactor/EXECUTION_PROTOCOL.md` as process authority; that file remains
the historical record of the UT-1…UT-17 structural refactor. This document
holds no project state.

| Concern | Owner (referenced, never restated here) |
|---|---|
| Present state, active phase, roadmap | `PROJECT_STATE.md` |
| Execution contract of a phase | its frozen SPEC in `docs/specs/` |
| Code health and structure | `docs/ENGINEERING_STANDARDS.md` |
| Test selection, reruns, evidence | `docs/TEST_EXECUTION_POLICY.md` (TEP) |

## 1. Principles

1. A frozen SPEC grants execution authority. The supervisor judges outcomes,
   not steps.
2. Decisions escalate; activities do not. Only a question whose answer changes
   product behaviour, a binding invariant, irreversible state or security
   posture leaves the phase.
3. Evidence is proportional to risk (TEP) and bound to bytes by Git.
4. Engineering quality is an acceptance criterion, not a reviewer preference.
5. Git and tests are the record; documents hold decisions and present state.
6. Independent review is spent where it buys independence: at declared risk
   boundaries.
7. Reversible actions are the executor's call; irreversible or outward-facing
   actions are gated.

## 2. Roles

**User** — authority of record. Approves macro-phases, decides product intent,
authorizes every gated action (§7, §9), provisions and revokes credentials,
selects models, decides exceptions. May interrupt at any time.

**IAsup** (supervisor, outside the repository) — sequences and charters
macro-phases; states product intent; answers escalations; for R3 phases
acknowledges the frozen SPEC and selects the cross-family reviewer; adjudicates
MATERIAL findings the executor disputes; accepts phases. IAsup does not
prescribe files or internal design, approve tests, fixes, reruns, staging,
commits or pushes, or review individual steps.

**Executor** — Claude, as architect, SPEC author and executor. Inside an
authorized phase it owns reconciliation, inventory, architecture, the SPEC,
decomposition, implementation, proportional local refactoring, tests and
evidence under the TEP, diagnosis and correction, the real-PostgreSQL /
browser / provider evidence the SPEC requires, self-review, review requests per
tier, finding handling, governance updates, staging, commits, fast-forward
publication, post-publication verification and the phase report.

## 3. Macro-phase lifecycle

```
CHARTER → 1 RECONCILE → 2 SPEC → 3 FREEZE → 4 SLICES 1..N → 5 CLOSE → 6 REPORT
```

1. **Reconcile** — Git (branch, HEAD, remote, divergence, clean tree),
   `PROJECT_STATE.md`, and the code the phase touches. Repository state beats
   memory and handoff notes.
2. **SPEC** — write `docs/specs/MP-<n>-<slug>.md` from `docs/specs/TEMPLATE.md`.
   Open product or architecture decisions go to IAsup as one batch.
3. **Freeze** — one docs-only commit (`docs(spec): freeze MP-<n> …`),
   fast-forward pushed so IAsup can read it. R1/R2: execution continues
   immediately. R3: substantive implementation waits for IAsup's
   acknowledgement.
4. **Slices** — the slice is the landing unit: build → TEP evidence →
   self-audit → review if the tier requires it → commit → push → verify. Each
   slice is green under the TEP on its own and carries its production code,
   tests and the documents it changes.
5. **Close** — verify every acceptance criterion and run any milestone evidence
   the SPEC or TEP requires. The last slice fills the SPEC closure and rewrites
   `PROJECT_STATE.md`.
6. **Report** — one page to IAsup (§10).

The SPEC slice table plus Git are the resume point across sessions. Chat memory
has no authority.

## 4. Charter (IAsup → executor, English, ≤15 lines)

```
PHASE CHARTER — MP-<n> <title>
Intent:       <operator/user outcome, 2–5 lines>
Includes:     <roadmap items>        Excludes: <items>
Decided:      <product decisions already taken>
Environments: DEV: <allowed actions> | PROD: none | <exact actions, each a user gate>
Publication:  FF push to the development branch (default) | hold
Risk floor:   R1 | R2 | R3           R3 cross-family reviewer: <model/provider>
```

## 5. SPEC lifecycle

- `DRAFT → FROZEN → CLOSED`, or `ABANDONED` with a three-line reason.
- A SPEC freezes only when its open-decisions list is empty.
- The phase tier is the highest of the charter floor and every slice tier.
- **Amendments.** When implementation disproves an assumption, the executor
  records an amendment in the SPEC and continues. An amendment is *material* —
  and becomes an escalation — when IAsup or the user could plausibly decide
  differently: it changes the outcome, crosses into another major subsystem,
  adds an undeclared schema or data migration, or changes security posture or
  a binding invariant.
- Writing rules: global invariants are referenced, never copied; no
  shell-command transcripts; no evidence dumps (pointers only); normal target
  ≤~300 lines; acceptance always includes `ENGINEERING_STANDARDS.md`
  compliance.
- A closed SPEC is immutable and stays at its path; `docs/specs/README.md`
  indexes every SPEC.

## 6. Autonomy rule

> Once a SPEC is FROZEN under an authorized charter, the executor is authorized,
> without further supervisor permission, to perform every action reasonably
> necessary to satisfy that SPEC — design refinement, implementation,
> proportional local refactoring, tests, diagnosis and correction of defects,
> evidence under the TEP, review requests, governance updates, explicit-path
> staging, commits, fast-forward publication to the development branch and
> post-publication verification — bounded by the SPEC's scope and
> external-boundary sections, `ENGINEERING_STANDARDS.md`, the TEP and the
> hard-stop table. Silence authorizes nothing outside those bounds.

**Authorized without asking:** implementation details, decomposition, naming,
private helpers; fixing candidate-caused defects; fixing a test written in the
same phase when the test is demonstrably defective and the SPEC contract is
unchanged (recorded as an amendment); updating pre-existing guards that the
SPEC's declared contract change makes false, with negative controls; reruns,
full suites and delta qualification as the TEP prescribes; choosing and
cleaning up run-owned resources (disposable local databases; DEV provider
resources declared in the SPEC, uniquely named per run); local refactoring
under `ENGINEERING_STANDARDS.md` §8; non-material review findings;
documentation reconciliation for the changed subsystem; staging, commits,
ordinary fast-forward push, post-push verification.

**Not authorized:** any PROD access or action not listed as a gate;
destructive or irreversible operations on real data; any action on protected
branches, tags, releases, pull requests or deployments; history rewriting;
schema or data migrations the SPEC does not declare; work in another major
subsystem; weakening guards beyond the declared contract change; editing this
document, `ENGINEERING_STANDARDS.md` or the TEP beyond recording facts; a new
runtime dependency with security, licensing or hosting impact that the SPEC
does not declare; creating or revoking credentials; starting the next phase.

**Findings.** MATERIAL: fixed before landing. NON_MATERIAL / FUTURE_HARDENING:
fixed now when cheap and in scope, otherwise recorded in the SPEC's deferred
list with a one-line reason. OUT_OF_SCOPE / PRE_EXISTING_TEST_DEBT: recorded,
not fixed. IAsup adjudicates only MATERIAL findings the executor disputes.

## 7. Hard stops

A **HARD STOP** halts the affected work, preserves state and escalates. A
**BLOCKER** lets the executor finish everything else and report at close.

| # | Hard stop | Not a hard stop |
|---|---|---|
| H1 | Product intent is ambiguous and the alternatives change user-visible behaviour | internal design choices |
| H2 | The design contradicts a binding contract (`ENGINEERING_STANDARDS.md`, a guard test, a closed SPEC) that this SPEC does not change | choosing among compliant designs |
| H3 | PROD access or action not listed as a gate; destructive or irreversible action on production or real data | declared DEV actions; cleanup of run-owned resources |
| H4 | Observed risk of persistent data loss or corruption (custody guard trips, real data mutated, provider objects missing) | churn in disposable test databases |
| H5 | Credential or security compromise (secret printed, committed or logged; live exposure found) | — |
| H6 | Schema or data migration not declared in the frozen SPEC | a declared schema change |
| H7 | Required work in another major subsystem | one-hop local refactor |
| H8 | Two binding invariants cannot both hold | — |
| H9 | A pre-existing guard must be weakened or retired beyond the SPEC's declared contract change | updating guards the declared change falsifies; fixing same-phase tests |
| H10 | Git requires merge, rebase, force or history rewrite, or the remote moved unexpectedly | ordinary fast-forward push |
| H11 | Evidence shows the phase's core design is wrong | local corrections recorded as amendments |
| BLOCKER | Required evidence unobtainable (no real PostgreSQL or DEV provider; the same environmental failure twice) or a user-only input is missing | — |

**Never, under any authorization:** put student or other personal data into a
model prompt, review packet, commit, fixture or report (schema and code are
fine; rows, documents and logs are not); print secrets; force-push or rewrite
published history; delete provider resources this run did not create.

```
ESCALATION — MP-<n> — <H#>
Facts (file:line) · State preserved (committed / uncommitted)
Options (≤3, with consequences) · Recommendation · What continues meanwhile
```

## 8. Review tiers

| Tier | Applies to | Review |
|---|---|---|
| **R1** | refactors and features behind existing authorization; no schema, provider or concurrency change | structured self-review: the full diff re-read against the SPEC and the `ENGINEERING_STANDARDS.md` checklist, refuting claims A–E |
| **R2** | schema change, new route or RBAC mapping, provider integration on DEV, locking or concurrency | R1 + one independent review in a fresh context (no executor conclusions) before the risky slice lands; targeted recheck after fixes |
| **R3** | authorization semantics, migration of real data, production actions, destructive operations, security posture | R2 + a blind review from a different model family (run by the user from a packet the executor prepares) + SPEC acknowledgement + user gates |

R1 and R2 phases have no supervisor checkpoint. R3 adds exactly the three
items above; it never becomes per-step approval.

Reviewers try to refute: **A** runtime behaviour outside the SPEC is unchanged;
**B** route, RBAC and CSRF semantics are as declared; **C** nothing outside
the declared scope changed; **D** owners stay cohesive (no duplication,
reverse dependency or new dumping ground); **E** the tests would fail on the
defect. Verdict PASS / FAIL with file:line; MATERIAL separated from
NON_MATERIAL.

A fresh session of the executor's model is context-independent but
same-family: it satisfies R2, never the R3 cross-family review. Reviewer
model and provider identity are reported truthfully; no silent fallback.

## 9. Landing and publication

The development and protected branches are named in `PROJECT_STATE.md`. The
development branch has a single writer during an active phase.

Per slice, with no supervisor message in between:

1. `git fetch`; on the development branch; not behind its upstream.
2. Stage explicit paths only; the staged set lies within the SPEC scope plus
   governance files; every new untracked file is staged or deleted;
   `git diff --cached --check` clean.
3. Commit: conventional subject; what/why body; trailers
   `Spec: docs/specs/MP-<n>-<slug>.md` and `Slice: <k>/<N>`.
4. `git push origin <development branch>` — never `--force` or
   `--force-with-lease`.
5. Verify local HEAD == origin == `git ls-remote`, divergence 0/0, clean tree.
   The result goes into the report and is never committed.

A rejected push, a moved remote or any divergence is H10.

**Always separately user-authorized:** protected branches, tags, releases, pull
requests, deployments, other remotes, any PROD environment, and any push a
charter marked `hold`.

The SPEC freeze is the only governance-only commit. No publication-record
commits: a document never states its own landing SHA; Git is the record.

## 10. Phase report (executor → IAsup, ≤1 page)

```
PHASE REPORT — MP-<n> — CLOSED | CLOSED_WITH_EXCEPTIONS | BLOCKED
Outcome · commits (subject + short SHA; local == origin == ls-remote verified)
Acceptance: AC1..ACn → met / not met + evidence pointer
Amendments: A1..An (material: none | escalated)
Reviews: tier, reviewer identity, MATERIAL found / fixed
Evidence: TEP tiers and lanes; full suite result or "not triggered: <reason>"
Engineering self-audit: all yes | exceptions with reasons
Deferred · residual risk · recommended next phase
```

IAsup accepts a clean report by default and decides only when the report
carries a blocker or an exception.

## 11. Documentation discipline

| Fact | Lives in | Never in |
|---|---|---|
| present state, active phase, readiness, blockers, environment facts | `PROJECT_STATE.md` (rewritten, ≤~60 lines) | history |
| phase design, decisions, amendments, closure | the phase SPEC | `PROJECT_STATE.md` |
| process / code-health / test rules | this file / `ENGINEERING_STANDARDS.md` / TEP | SPECs (reference only) |
| invariants | guard tests (documents name the test, not the number) | prose |
| SHAs, diffs, counts, durations, manifests | Git; test reports outside the repository | documents |
| history | Git, closed SPECs, `docs/history/`, frozen historical records | `PROJECT_STATE.md` |

One fact, one home. A hash appears only where the hash itself is the contract.
State is written in the present tense. Each phase adds roughly its SPEC plus a
few lines elsewhere; a document growing faster than that signals a misplaced
fact.

## 12. Language

Repository governance, SPECs, review packets, reports and commit messages:
English. IAsup ↔ user: Portuguese. Product user-facing text: Portuguese,
through `utils.messages`. Code comments match the language of their module;
new modules use English.
