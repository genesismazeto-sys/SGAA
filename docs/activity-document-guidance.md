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
