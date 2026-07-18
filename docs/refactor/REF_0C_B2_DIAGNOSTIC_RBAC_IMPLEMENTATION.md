# REF-0C-B2 — Diagnostic RBAC Implementation

## Scope and decision

This bounded implementation applies only the approved diagnostic requirements:

- R22 GET `admin_diagnostico_atividades_versionadas` → `atividades`/`view`.
- R23 GET `admin_diagnostico_atividades_versionadas_view` → `atividades`/`view`.
- R24 GET `admin_diagnostico_versioned_shadow_reads` → `banco_dados`/`view`.

The normative decision was accepted at `a9d375d` (`Document diagnostic RBAC and
R20 policy options`). Starting branch/HEAD: `refactor/architecture-safety-net` at
`a9d375d`. R22/R23 allow `admin_total`, `administrativo`, and `consultivo`; R24
allows only `admin_total`. Aluno and anonymous retain the outer `@admin_required`
login contract.

## Files and preserved boundaries

Changed production file: `app/auth.py`. The implementation adds exactly three
explicit GET mappings; POST on those endpoints and unrelated endpoints continue to
return `None`. No `main.py`, UI, schema, database, dependency, resource vocabulary,
profile override, wildcard, route-prefix fallback, or global fail-closed gate was
added. R20 local `readonly` is unchanged; its accepted central `matrizes`/`edit`
gate remains authoritative.

`tests/_artifacts/rbac_unmapped_routes_baseline.json` remains the characterization
mechanism and now has `unmapped_routes: []`. Dynamic reconstruction from
`main.app.url_map` also returned exactly an empty set.

## Tests and behavioral evidence

New `tests/test_ref_0c_b2_diagnostic_rbac.py` has 18 tests covering requirement
mapping, GET-only/no-fallback behavior, R22/R23 consistency, all approved actors,
outer aluno/anonymous denials, R24 browser redirect and AJAX JSON-403 contract,
domain-state equality after denied access, controlled temporary-log immutability,
R24 sensitive-output confinement, and existing limit clamping.

The B1 file keeps every original 21 mapping assertion. Only its three obsolete
assertions that R22–R24 remain unmapped were removed; B2 owns their replacement
coverage. The existing shadow-read diagnostic helper was generically primed through
the successful admin dashboard path: the first mapped RBAC request performs
fixture-local idempotent access-context maintenance, so priming preserves its
read-only database-hash assertion without changing any endpoint expectation or
negative-authentication fixture.

- New B2 suite: `18 passed`, exit `0`.
- Existing shadow-read suite after the generic helper adjustment: `9 passed`, exit
  `0`.
- Focused combined command: `python -m pytest tests/test_ref_0c_b2_diagnostic_rbac.py tests/test_ref_0c_b1_rbac_high_confidence_mappings.py tests/test_rbac_requirement_coverage.py tests/test_activity_versioning_phase_d1_diagnostic.py tests/test_activity_versioning_shadow_read_diagnostic.py`; it collected `70` tests and exited `0`.
- `git diff --check`: clean.

Every test database, log, upload, document, and backup path is fixture-controlled
under pytest temporary directories. No repository `database.db` or production log
was read or written.

## Final validation and status

Full hermetic validation ran in fresh detached worktree
`C:\Users\klebe\AppData\Local\Temp\sgaa-ref-0c-b2-full-validation`, created at
the implementation commit without copying `database.db`, `.env`, uploads,
documents, backups, or production logs. The command was
`D:\OneDrive\Programação\SGAA_clean_baseline\.venv\Scripts\python.exe -m pytest -q --tb=no --disable-warnings -rN`.
Collection reported `577/594 tests collected (17 deselected)`; the hermetic suite
completed successfully with `577 passed`, `17` D73H deselected, zero failures,
errors, skips, xfails, or xpasses (exit `0`). The selected-test delta from the
previous `562 passed` baseline is `+15`: 18 new B2 tests minus the 3 obsolete B1
unmapped assertions.

The disposable worktree was inspected for test-generated CSRF artifacts and restored
to its committed state. Its Git worktree registration was removed. The empty
temporary directory remained at `C:\Users\klebe\AppData\Local\Temp\sgaa-ref-0c-b2-full-validation`
because the environment denied its final recursive deletion; it contains no Git
worktree registration or production data and may be removed by the local user.
REF-0C-B2 is implemented and locally validated, **pending ChatGPT supervisor review**.
REF-0C-C and R20 cleanup remain unresolved and unauthorized.
