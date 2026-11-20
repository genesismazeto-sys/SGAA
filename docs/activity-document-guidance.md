# Documentação exigida: guidance and DOCX templates of an activity version

Scope: the owner's COMPROVANTES-01 request on `refactor/design-system-foundation`.
No push, no deployment and no schema change on DEV or PROD are part of it.

## The rule

The guidance is informative. Nothing compares a submitted proof with a required
document or a template, requires a template, blocks a submission or decides a
request because of them. The coordination analyses every request; the
comprovante upload is unchanged.

## Required documents (A)

The list lives in `atividade_versao.documentos_json`, already a semantic field
of the version, so it follows the canonical freeze policy
(`app.activity_catalog.can_activity_version_be_mutated_in_place`): the version
form edits it in place only on an unreferenced draft, a frozen version changes
only through Nova versão, and Matrices and requests keep the version they
reference. `app/activity_documentation.py` owns the rule: the list is stored as
`{"comprovantes_exigidos": [...]}`, in the administrator's order, each item a
proof name of at most 60 characters. What the column held before -- one
regulation sentence per version -- is not a proof name: it is never listed (to
the student or in the version form), an unchanged list keeps the stored text
byte for byte, and the first saved list keeps it under `"texto_anterior"`.

## Templates (B) and their storage: prod-1/v19

The canonical object store (`storage_objects`, Supabase staging and the drive
mirrors) pins request documents and ARQUIVOS: PDF / PNG / JPEG only and one
business row per object. A template is a DOCX shared by every version it is
carried into, so instead of widening those custody tables v19 follows the v13
precedent of application-owned content in the database
(`app/prod1_document_templates_ddl.py`):

- `modelo_documento_arquivos`: the verified bytes, content addressed by
  SHA-256, at most 4 MiB, DOCX type and ZIP signature checked; a trigger makes
  a row immutable, and `ON DELETE RESTRICT` keeps the bytes of every
  association -- ended ones included -- from being deleted.
- `atividade_versao_modelos`: title, download name and slot of a template in
  one version, `ativo` -> `substituido` | `retirado`; only an active row may
  change, and only into its end state. A replacement takes over its
  predecessor's slot, so the rows of a slot are that template's history.

`app/docx_validation.py` decides from the bytes whether a file is a plain Word
document: ZIP and OOXML structure, the plain document content type (not
`.docm` / `.dotx`), no VBA, ActiveX, embedded objects or executables, no
external relationship other than a hyperlink (no remote template), no DTD,
CRC-checked entries and bounded expansion.

`app/activity_document_templates.py` owns the lifecycle. Writes run in one
write transaction under the base lock, then the version row lock
(`app.db.lock_activity_version`), and re-check the freeze policy. A new version
(the version form or any semantic successor) starts with a copy of its source's
active templates. Downloads are application responses (`private, no-store`,
attachment): there is no URL to the object. Administrators need
`atividades:view`; a student reads an active template of a version that the
effective Matrix offers or that one of the student's own requests uses.

v19 is purely additive. The SQLite migration (`app/prod1_document_templates_v19.py`)
proves every existing row and counter unchanged; `python -m app.pg_schema upgrade`
moves an exact v16, v17 or v18 PostgreSQL schema to v19 in one transaction.
Path-B migrates both tables exactly with value-free integrity checks, and the
governed PostgreSQL backup carries them like every other table. The hosted
snapshot file carries the bytes and the history too, and its restore puts them
back exactly; only its readable registers leave out the template bytes, as they
do images.

## Capacity

A template is at most 4 MiB and a version has at most 10 active ones. Identical
bytes are stored once and a version made from another reuses its bytes, so the
database grows only with new uploads, and it keeps every replaced or withdrawn
file by design. A DOCX is already compressed: each stored byte costs about a byte
in the database, in every governed generation and in every hosted snapshot. The
Free plans bound this (500 MB database; 5 GB egress a month, which every daily
generation spends on a full read of the database), so the templates should stay
within tens of MB in total. Nothing enforces a total; the operator watches the
database size with the other Free limits (`docs/PRODUCTION_CUTOVER_RUNBOOK.md`).

Vercel Hobby limits a function's request and response body to 4.5 MB. An upload
at the 4 MiB limit with its form fits, and so does its download. A larger upload
is refused by the platform (HTTP 413) before the application can answer with its
own message.

If templates ever need larger files or a large total, the path is a private
bucket or prefix of their own: a DOCX-only table, the signed TUS upload of the
comprovantes and a short-lived signed download, added to the object backup set.
`storage_objects` and its PDF / PNG / JPEG CHECK stay as they are.

## Publication (GF1)

PROD is v19 since GF1-V19 (2026-11-19, `PROJECT_STATE.md`), which published it by the gate G1
sequence of `docs/specs/MP-3-A22-request-reclassification.md` §10, as run for v18 on
2026-10-20. A later release that leaves the schema at v19 has no upgrade step. The sequence was:

1. the GF1 grant naming the commit and the upgrade;
2. a pre-upgrade governed generation with objects, from the pinned v18 worktree
   (the rollback point);
3. from a worktree of the commit, against the verified PROD source:
   `python -m app.pg_schema upgrade` (`upgrade: upgraded (... version=19 ...)`;
   one transaction that refuses anything but an exact frozen v16 / v17 / v18
   contract and then writes nothing), `python -m app.pg_schema validate`
   (`version=19`) and `python -m app.hosting_cli check --database` (schema 19,
   API exposure clean: under the cleared default privileges the two new tables
   reach no API role);
4. in the same session, a governed generation with objects from the new
   worktree, with the daily governed-backup script and task repinned to it (the
   v18 tools refuse a v19 database);
5. the GF1 deploy, `authorize-code`, promote and smoke.

The order matters. The v19 code reads the template tables on the version form
and on Nova requisição, so it is never deployed before the upgrade. The v18 code
in production does not read them, so the time between steps 3 and 5 is safe,
and a code rollback needs no schema rollback. The operator's read-only identity
proof used for v18 expects the notification CHECK only when the version is 18
exactly. v19 leaves that CHECK unchanged, so for v19 the proof must expect it for
every version from 18. After the upgrade, the v19 restore reader refuses the
earlier hosted snapshots (`SOURCE_SCHEMA_UNSUPPORTED`); the post-upgrade
generations are the new restore points.

## Student form (C)

`aluno_nova_requisicao.html` shows, between the event fields and Comprovantes,
the guidance of the selected activity version, rebuilt from
`#atividade-orientacoes-json` on every change of Tipo, Grupo or Atividade and
hidden when that version has nothing to show. Editing or rectifying a request
shows the recorded version's guidance, even when the Matrix no longer offers
it; like the field guidance of the same form, the read-only view shows none.
