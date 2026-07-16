# REF-0TF-A - Progress Calendar Contract Hardening

## Scope

- Test-only hardening on `refactor/architecture-safety-net`, starting at `722b7a7`.
- No production code, template, static asset, schema, database, environment, dependency, RBAC, or route-modularization change was made.

## Cause

`app.views.aluno._build_aluno_progresso_payload` intentionally derives the current semester from `datetime.date.today()` and includes requests in that semester. The prior test fixed its expected calendar at `2026/1`, while its `2026-09-10` fixture becomes part of current semester `2026/2` on 2026-07-01. This was a decaying test assertion, not an evidenced application defect.

## Test contract

`tests/test_aluno_progresso.py` controls only the `datetime` binding imported by `app.views.aluno`; standard-library time and the application source remain untouched.

- Reference date `2026-06-30`: the `2026/2` event is a later semester and must be absent.
- Reference date `2026-07-01`: the same semester is current and must be present, with its hours aggregated.

The assertions use explicit fixture dates and expected semesters; they do not calculate expectations through the application helper under test.

## Validation

- Focused boundary nodes, three consecutive runs: `2 passed` each time.
- Entire `tests/test_aluno_progresso.py`: `4 passed`.
- Disposable detached worktree: `C:\Users\klebe\AppData\Local\Temp\sgaa-ref-0tf-a-validation` at the temporary validation commit. Collection: `538 tests collected`.
- Full suite in that worktree: `521 passed, 17 failed` in `234.13s`. Every failure is one of the pre-classified D73H nodes and stops at the absent worktree-local `database.db`; no other failure occurred.

## Decision

**GO for REF-0TF-B only.** D73H historical verification isolation remains the next authorized remediation. RBAC correction, route modularization, and production refactoring remain prohibited.
