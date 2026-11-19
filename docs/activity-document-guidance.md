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
reference. `app/activity_documentation.py` owns the rule: new writes store a JSON
array in the administrator's order; older shapes are read through the tolerant
`parse_documentos_json`; an unchanged list keeps the stored text byte for byte.

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
governed PostgreSQL backup carries them like every other table; the hosted
snapshot's readable registers leave out the template bytes, as they do images.
