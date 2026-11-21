# DIAG-500 — Versioned-activity diagnostic lookups

**Record type** — Post-implementation specification and decision record for
R3 admission. The owner approved the product decisions during implementation
and remediation. This file was prepared after the code was frozen. It does
not record a pre-implementation SPEC freeze or acknowledgement under the
[Operating Model](../OPERATING_MODEL.md). Integration remains on HOLD pending
acceptance of R3. The governance authority must also acknowledge this
retrospective record or record a formal exception to the original freeze gate.
Amendment A1 records the correction made after the R3 cross-family finding on
`b722d9a` and its risk classification.

## Candidate and scope

Review `b722d9a69248dfe9d0c85d5a24e0c97c5e0add87` on
`fix/diagnostic-lookup-500` against the accepted UI-B46 tip `35e95f2`.
The implementation history is `4112436` → `50c5784` → `b722d9a`.
The scope covers the existing JSON GET
`/admin/diagnostico/atividades-versionadas`, its HTML GET at `/view`, the
two activity-listing functions they call, the diagnostic template and focused
regression tests. UI-B46 is the accepted base. The documentation commit
records the decision separately from the code.

## Original failure and root cause

The listing resolver returned `status: "not_found"` with a null matrix and
without totals when a turma or matrix could not be resolved. Both turma
paths dereferenced the null matrix. The HTML matrix path tried to render
missing totals. Those failures produced HTTP 500, including for a turma
offered by the quick list with no linked matrix. The JSON matrix path
instead returned HTTP 200 with `ok: true` and an unresolved listing. A
value beyond SQLite's signed 64-bit integer range could fail at bind time.
The old Flask integer conversion also treated malformed input as absent,
and the subsequent truthiness check did the same for zero. The first fix
rejected stored negative IDs. The remediation restored signed lookups and
applied the range check before parameter precedence selects a lookup.

## Owner decisions and lookup contract

| Case | HTML and HTTP | JSON |
|---|---|---|
| No applicable identifier, including blank form fields | 200, neutral index | Existing `ok: true`, index `consulta`, instructions and available turmas |
| Selected identifier names an existing turma with a linked matrix or an existing matrix | 200, existing diagnostic listing | Existing successful `ok`, `status`, `consulta`, matrix, activities and totals. Turma lookups include the turma reference |
| Existing matrix with no selected activity versions | 200, existing per-axis empty state | `status: "resolved"`, empty `atividades`, zero totals |
| Existing turma without a linked matrix, by ID or code | 200, neutral `Turma <codigo>: sem matriz vinculada.` note, falling back to the name | `ok: true`, `status: "not_found"`, `reason: "turma has no matrix"`, the `turma` reference, `matriz: null`, `atividades: []`, and `consulta.matriz_id: null`. No totals |
| Invalid explicit numeric identifier, or a selected ID or code with no matching row | 404, entity-specific UI-B46 alert | 404 with `ok: false` and the entity-specific `message` |

The 404 and neutral 200 outcomes record owner-approved product behavior.
The no-matrix case previously failed with HTTP 500. Its new JSON body uses
the existing listing fields and includes the reason and turma reference.
An unknown selected matrix intentionally moves from the old unresolved
HTTP 200 to the existing error envelope. Successful and index payloads
retain their established fields.

For numeric parameters, surrounding whitespace is trimmed. Blank values
supply no ID. Each nonblank occurrence must be an ASCII decimal integer,
with an optional leading minus sign, within the signed 64-bit range and
nonzero. This includes values in lower-priority fields and repeated numeric
keys. A numeric value that fails these checks returns 404 rather than
falling through. Select the first nonblank occurrence of each numeric key.
`turma_codigo` follows the same policy: its first nonblank occurrence,
trimmed (Amendment A1; it previously took the first occurrence even when
blank). Lookup precedence is `turma_id`, then `turma_codigo`, then `matriz_id`.
Existence is checked for the selected lookup. A representable numeric value
in an unused field need not name a stored row. A selected lookup that misses
does not fall through to another field.

Stored negative turma and matrix IDs are valid, including a turma linked to
a negative matrix. The resolver checks the SQLite bind range before querying
and supports both engines' stored signed IDs. PostgreSQL uses signed 32-bit
columns, so an in-range 64-bit value outside those columns' range has no
matching row on PostgreSQL. Both numeric HTTP parameters reject explicit zero
even if an imported row holds it. The direct resolver can look up a row with
primary key zero. The existing truthiness check for a turma's matrix link
continues to treat a link value of zero as no matrix. The two ID fields of the
page's form are text fields with no lower bound (Amendment A1), so they admit
negative IDs and can carry a rejected value back. The server alone rejects
zero and malformed values.

## Access and presentation

Both routes require administrator authentication and the existing
`atividades:view` RBAC permission before diagnostic queries run. Route names,
URLs, methods and CSRF policy stay as defined in the accepted base. The routes
perform diagnostic reads. Lookup errors use `.diag-alert` and the UI-B46
tokens `--alert-red-border`, `--alert-red-bg` and `--alert-text`. The index and
the no-matrix message use `.diag-note`. The matrix and turma presentation,
badge components and ordinary empty states follow the accepted UI-B46
[Design System contract](../design-system/README.md).

## Evidence available at admission

- The tracked diagnostic and resolver tests cover signed IDs, invalid and
  missing numeric IDs, mixed and repeated numeric parameters, the two response
  formats, neutral cases and denial before lookup. The impact set includes
  the matrix-version contract, structured hours, FC13 resolver ownership,
  route and RBAC guards, and the Design System alert palette.
- The executor's local `DIAG500-R3-RECHECK2-PACKET` contains the candidate
  identity and evidence in `evidence/sqlite/`, `evidence/postgresql/` and
  `evidence/responses/`. Its SQLite run passed the focused route and resolver
  impact set. The disposable PostgreSQL 15 and 17 probes passed on both
  versions, including populated negative IDs and bounds in mixed queries.
  The prior code failed the targeted out-of-range tests, and the response
  comparison recorded changes at those cases only.
- R2 passed on the original candidate. Later reviews found the negative-ID
  and invalid-input defects (C1/C2, also called F2/F1), then the mixed-query
  range defect (F1-R). The executor's test reports and earlier findings are
  evidence for the read-only cross-family review of the frozen final candidate.

## Amendment A1 — one reading for the page, its JSON link and its form

**Finding (R3 cross-family review of `b722d9a`, MATERIAL, accepted by the
owner).** The routes read each ID by its first nonblank, validated value, but
the page re-read the raw parameters to fill its form fields and build its
"Abrir JSON diagnóstico" link. Its number fields also discarded any value that is
not a number. One query could therefore select different resources. The page
of `turma_id=&turma_id=-431&matriz_id=910` showed Turma -431 while its link and
unmodified form loaded Matriz 910. The rejected
`turma_id=-431&turma_id=bogus&matriz_id=910` became a successful Turma -431
lookup through both.

**Frozen contract (owner, 2026-11-21).**
1. The page, its generated JSON link and its unmodified form submission keep
   the same effective resource selection.
2. A rejected query cannot become a successful lookup through either action.
3. Repeated, empty, malformed and conflicting parameters follow one consistent,
   explicit policy.
4. Stored negative IDs keep working.
5. Invalid, missing and out-of-range IDs return controlled responses.
6. A Turma without a Matriz keeps its neutral behaviour.
7. Authorization is unchanged.
8. UI-B46 styling is untouched.

**Correction.** The view reads the query once, and both routes and the page use
that reading. The policy is the one above (Owner decisions and lookup
contract), with `turma_codigo` now aligned on the first nonblank occurrence.
The page's fields and link carry each parameter as it was read:
- a valid ID in canonical decimal;
- the first rejected occurrence of a rejected ID;
- the Turma code that was read;
- otherwise blank.

Read again, that echo selects the same resource or fails in the same way. CR,
LF and NUL, which a form field or the HTML parser drops or alters, appear as
U+FFFD. The ID fields are text fields so that a rejected value can make the
round trip. The template no longer reads the raw parameters.

**Risk classification.** Under the Operating Model's review tiers the
correction itself is R1. It changes how one admin-only view reads its query and
renders its own form and link. It changes no schema, route, RBAC mapping, CSRF,
provider or concurrency behaviour. DIAG-500 as a whole runs at R3.

**Binding exception (owner decision, 2026-11-21).** This correction gets no
new full R3 cycle. Instead it gets the R1 self-review plus one targeted
independent recheck, in a fresh context, of the demonstrated defect and its
immediate regression matrix. The recheck reviewer was the same model family as
the executor, so it is R2-grade and not cross-family; the owner's decision
accepts that. This amendment does not change the retrospective-freeze
acknowledgement or exception owed above.

**Evidence** (outside the repository, executor's `diag500_fix`, reviewer's
`diag500_recheck`, synthetic data only):
- **RED:** the two reported queries and 10 more diverge on the prior code.
- **GREEN:** the tracked one-reading test covers 21 queries, and the new tests
  fail on the prior code. Seven mutants that reintroduce a second reading are
  all killed.
- **PostgreSQL 17:** a 20-query page, link and form probe is consistent.
- **Real browser:** the page's own link and submit button were clicked for both
  reported queries, and a 35-query matrix used the browser's own form
  serialization, on the committed bytes.
- **Focused regression:** the view's contract, the files that reference these
  routes or template, and the relevant permanent guards. Failures were the
  known `test_b11` debt only; the Git-dependent guards were rerun in a Git
  checkout.
- **Targeted recheck: PASS.**
  - The prior code diverged on 50 of 127 queries, and 39 rejected queries
    became successes.
  - The correction was consistent on 123 of 127 queries, with no HTTP 500.
  - The four exceptions are the unreachable stored-code case below.
  - Refused actors reached no lookup.
  - The page's styles are unchanged.

## Exclusions and remaining limits

- `DIAG-500-A1-CODE-CONTROL-CHARACTERS` (backlog, NON_MATERIAL).
  - The Turma-code lookup uses the trimmed value as sent, while the fields and
    link show CR, LF and NUL as U+FFFD.
  - Page, link and form can therefore disagree only for a stored code that
    contains one of those characters or U+FFFD.
  - No write path produces such a code: course codes match `^[A-Z-]+$` and
    Turma codes are `<curso>-T<nn>`, with an optional `-<id>`.
  - Making the lookup use the shown value would also change the NUL behaviour
    excluded below.
- The ID fields are text fields. Phones show the full keyboard instead of a
  numeric pad, chosen so a minus sign can always be typed, and the browser no
  longer shows a spinner.

- `PG-NUL-TURMA-CODIGO-404` remains in the backlog. A selected `turma_codigo`
  containing a NUL byte can cause HTTP 500 on PostgreSQL because the driver
  rejects NUL in text parameters. SQLite returns 404 for the synthetic missing
  code. This behavior predates DIAG-500 and is outside the approved numeric-ID
  remediation.
- Schema, ID generation, data repair for imported zero IDs, access policy,
  unrelated message-catalogue work, unrelated Design System audits and
  baseline regeneration are outside the approved scope.
- R3 authorizes review of the frozen code. Publication, production access or
  writes, migration, deployment and integration remain outside this admission.
