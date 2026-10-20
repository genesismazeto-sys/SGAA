# Request processing corrections

Scope: the owner's four corrections on `refactor/design-system-foundation`.
Publication is authorized; deployment, production schema changes and recovery of
real notifications are excluded from this work.

## Causes and owners

- `templates/admin_requisicoes.html`: view/process controls were natively locked
  but painted with muted read-only colours. They now opt into the shared readable
  detail treatment in `static/css/components/form.css` and `select.css`. Native
  locks remain, and create/edit do not opt in.
- Attachment labels repeated persisted labels. Presentation now numbers documents
  by their existing order; file names, URLs and storage metadata are preserved.
- `app/request_email_notifications.py` excluded returns. The canonical processing
  handler now snapshots an explicit `Devolvida`, and `request_email_render.py`
  identifies it as returned for correction with the recorded justification.
  Models without the request-detail placeholder receive the return details once
  at the end of the message; stored model text is not changed.
  There is no automatic send. Reopen/close supersede pending generations;
  `student_request_edit.py` already supersedes them on resubmission;
  `requisitions.py` now does so atomically on automatic expiry.
- The preset editor and processing selector had independent sources and a sticky
  once-only cache. They now share confirmed snapshots, coalesce reads and reject
  stale reads across a write. Failures remain retryable. The editor freezes during
  saving, reports success only after persistence, and closing discards drafts.
  Save/Close are template buttons using shared DS classes. The existing preset
  CSS lives once in `static/css/components/request-presets.css`, with a stacked
  layout on phones.

## Necessary schema amendment: prod-1/v18

The persisted decision-status CHECK also excluded `Devolvida`. Merely removing
the application exclusion fails with an integrity error, so a schema change is
necessary to store an honest snapshot. Only this CHECK expands; no columns or
tables are added and no notifications are backfilled.

`prod1_return_notifications_ddl.py` owns the SQLite statements, and
`prod1_return_notifications_v18.py` provides a transactional v17 → v18 rebuild.
It validates the frozen predecessor, preserves every existing row and sequence
counter, checks integrity, and rolls back the entire step on failure. Older
migration definitions and digests remain frozen. Head-version guards and
predecessor fixtures advance accordingly.

`pg_schema.py` provisions v18 and upgrades frozen v16/v17 transactionally; a v16
upgrade also includes the existing v17 activity correction. The metadata lock
serializes concurrent upgrades. PostgreSQL uses ALTER CONSTRAINT replacement;
the existing notification data, indexes, identity sequences and delivery history
are preserved. Startup continues to validate PostgreSQL without running DDL.

Path-B and Layer-2 use their existing schema authorities and automatically carry
the new version/contract and unchanged table inventory. A later, separately
authorized production rollout must take its governed pre-upgrade backup, apply
`python -m app.pg_schema upgrade`, validate, deploy compatible code and update
schema-pinned operational tooling. This work executes none of those production
steps. Restoring an older schema must use its matching code and governed backup;
there is no production downgrade that discards return events.

## Controlled legacy recovery

`app/request_email_recovery.py` is an operator-only command, never called by a
listing or startup. Use only against the explicitly authorized database:

```
python -m app.request_email_recovery --request-id ID --decided-at "YYYY-MM-DD HH:MM:SS"
```

The default is read-only and returns a fixed eligibility code. After separately
reviewing and authorizing that exact decision, `--apply` creates one pending
generation. It never sends a message or resets the correction deadline.

Eligibility requires the exact current return timestamp, a recorded administrator,
student and justification, an open correction window, and no prior event history.
Requests with any history are conservatively refused for individual review.
Application rechecks under a request lock inside `write_transaction`, so a
concurrent expiry, resubmission or recovery cannot create an obsolete/duplicate
generation. Repeated application is a no-op. No production recovery was run.

## Verification

Targeted tests cover real Chromium decision/preview/send flows for all four
outcomes with synthetic students and a fake mail transport, duplicate-send
prevention, readable native locks, zero/one/multiple document labels, immediate
preset use, save failures, stale-read races, draft discard, and desktop/phone
geometry. SQLite migration tests cover history/counter preservation, rollback and
predecessor refusal. Real local PostgreSQL 17 tests cover v16/v17 upgrades,
concurrent upgrades, return snapshots, recovery, expiry and resubmission.

The full suite is intentionally excluded. Tests use disposable databases and
external screenshot directories; no real student records or documents are used.
