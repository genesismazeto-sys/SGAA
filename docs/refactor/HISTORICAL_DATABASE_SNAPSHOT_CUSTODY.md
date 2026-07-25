# HISTORICAL-DATABASE-SNAPSHOT-CUSTODY

## Current status

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R1:
CLOSED / ACCEPTED

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R2:
CLOSED / ACCEPTED

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R3:
CLOSED / ACCEPTED

R30:
DESTINATION_OPTIONS_READY_AWAITING_HUMAN_SELECTION /
SUPERSEDED BY HUMAN SELECTION

Human decision dates: 25/07/2026 (custody policy, canonical destination,
provisioning and copy contract).

Active classification:
PROVISIONING_AND_COPY_CONTRACT_APPROVED /
DESTINATION NOT YET PROVISIONED /
PHYSICAL EXECUTION NOT AUTHORIZED AT THIS TIME

R3 read-only phase-time classification, now superseded by human approval:
COPY_EXECUTION_CONTRACT_READY_AWAITING_HUMAN_AUTHORIZATION

Historical / superseded classification:
CUSTODY_POLICY_UNRESOLVED
CANONICAL_DESTINATION_UNRESOLVED
CONTRACT_NOT_DRAFTED

Custody policy:
APPROVED

Human-selected canonical destination:

D:\programas\SGAA_Historical_Custody

Destination:
SELECTED

Destination status:
SELECTED

Provisioning status:
SELECTED / PARENT PATH NOT YET PROVISIONED

Physical action:
NOT AUTHORIZED

Copy:
NOT AUTHORIZED

Move:
NOT AUTHORIZED

Delete:
NOT AUTHORIZED

Compress:
NOT AUTHORIZED

SQLite open:
NOT AUTHORIZED

Phase 2–6:
UNAUTHORIZED

Custody model:
SHARED

Project owner:
APPROVES

Technical operator:
EXECUTES ONLY EXPLICITLY AUTHORIZED ACTIONS

Retention:
INDEFINITE

Destination class:
EXTERNAL CANONICAL CUSTODY LOCATION —
DEDICATED DIRECTORY OUTSIDE REPOSITORY AND ONEDRIVE

Physical volume:
SAME VOLUME AS SOURCE WORKSPACE — D:

Specific destination:
SELECTED — D:\programas\SGAA_Historical_Custody
Historical / superseded wording: "NOT YET SELECTED".

Acceptance gate after future copy:
RESTORE LEVEL 2 — SCHEMA AND METADATA

Gate before any future source removal:
RESTORE LEVEL 3 — OPERATIONAL RESTORATION
Level 2 never authorizes source removal.

Preservation requirement:
Each set must preserve jointly: .db; .db-wal; .db-shm when present.

Association by basename:
INFERRED

Operational SQLite association:
NOT PROVEN
No sidecar may be omitted because it is empty, repeated, or apparently inactive.

First future physical action:
COPY ONLY

Move:
NOT AUTHORIZED

Delete:
NOT AUTHORIZED

Compress:
NOT AUTHORIZED YET

Source after copy:
MUST REMAIN INTACT
Future source removal requires validated copy, Level 3 restoration, separate human decision, and new explicit physical authorization.

## Gate A — read-only destination verification (R2 / R31)

Verification was strictly read-only. No directory was created, no write test was
performed, no temporary file was created, no ACL was altered.

| Check | Result |
|-------|--------|
| `D:\programas` | DOES NOT EXIST |
| `D:\programas\SGAA_Historical_Custody` | DOES NOT EXIST |
| Absolute resolution | `D:\programas\SGAA_Historical_Custody` (literal; `programas`, not `Programação`) |
| Volume | `D:` — NTFS, Fixed |
| Physical disk | Disk 1 — SAMSUNG MZALQ512HBLU-00BL2, NVMe |
| Free space | 497,651,699,712 bytes (~463.5 GiB) |
| Required space | 4,808,704 bytes across 17 artifacts (~4.59 MiB) |
| Inside any SGAA Git worktree | NO — the only SGAA worktree is `D:\OneDrive\Programação\SGAA_clean_baseline` |
| Inside OneDrive | NO — OneDrive tree is `D:\OneDrive\...`; destination is a sibling top-level path |
| Inside `SGAA_database_backups` | NO — that directory is `D:\OneDrive\Programação\SGAA_database_backups` |
| Inside pytest roots | NO — `pytest.ini` declares `testpaths = tests`, rooted in the repository |
| Files with the same 17 names present | NONE — path absent |
| Conflicts | ZERO |
| Apparent read ACL (`D:\`) | Readable; Authenticated Users: Modify, Synchronize; SYSTEM/Administrators: FullControl |
| Longest projected path | `D:\programas\SGAA_Historical_Custody\database.pre-D6.4.0-target-readiness-2-20260531-101530.db-shm` — 98 characters, below the 260-character limit |
| Reparse point / redirection on `D:\` | NONE observed |

Provisioning status:
SELECTED / PARENT PATH NOT YET PROVISIONED

Neither `D:\programas` nor the custodial directory exists. This is not a blocker
for the R2 documentary closeout, and it does not authorize automatic creation of
either path.

## Storage-domain risk

Storage-domain risk:

The selected destination is outside the repository and outside the observed
OneDrive tree, but it remains on the same physical D: storage domain as the
source workspace.

This provides logical separation, not independent-disk redundancy.

The destination must not be represented as redundant, immutable, off-site,
independent of the source disk, protected by versioning, or protected against
deletion. A second independent copy may be discussed in the future; it is not
part of R2.

## Controlled-copy contract — Gates 0–6

No gate below was executed. All remain future work requiring separate explicit
human authorization.

**Gate 0 — authorization.** Destination ratified; separate human authorization to
copy; executor identified; copy-only; no move, delete or compress.

**Gate 1 — preflight.** Source 17/17; canonical hashes and sizes; destination
accessible; sufficient space; zero conflicts; source and Git stable.

**Gate 2 — copy.** Exactly 17 artifacts; names preserved; basename families
preserved; no overwrite; source intact.

**Gate 3 — integrity.** 17/17 at destination; identical sizes; identical SHA-256;
dated manifest; hard stop on any divergence.

**Gate 4 — Level 2 restoration.** On a disposable copy derived from the
destination: SQLite validity; schema; essential tables; indexes; version and
metadata; no production and no external services.

**Gate 5 — preservation.** Source intact; destination intact; nothing discarded.

**Gate 6 — eventual removal.** Only after Level 3, an accepted report, a new human
decision, and an explicit physical order.

## Approved provisioning and copy contract (R3)

R3 was read-only. It created nothing, copied nothing, applied no ACL and opened no
SQLite database. The contract below was **approved by human decision on 25/07/2026**
and remains **unexecuted**. Approval of the contract is not authorization to execute
it: physical execution was explicitly withheld in the same decision.

**Approved destination layout.**

```
D:\programas\SGAA_Historical_Custody\
  artifacts\   the 17 artifacts, exact names preserved
  manifests\   custody-manifest-<UTC timestamp>.json
  evidence\    copy and verification reports
```

Rationale accepted: disjoint namespaces between artifacts, manifests and evidence;
no collision with the 17 canonical names; unambiguous separation between custodial
artifact and custodial evidence. Longest projected path 108 characters against the
260-character limit (`LongPathsEnabled = 0`).

**Approved authorized executor.** `KR-IDEAPAD\klebe`
(SID `S-1-5-21-1500819853-3011909004-3032907821-1001`).

**Approved ACL.** Inheritance disabled on the custodial directory; `Authenticated
Users` and `BUILTIN\Users` removed; `SYSTEM` and `Administrators` with FullControl;
the executor with Modify during provisioning and copy; after verification, the
executor drops to ReadAndExecute on `artifacts\` and retains Modify on `manifests\`
and `evidence\`.

Recorded limitation, not superseded by approval: an ACL is not immutability. Any
member of `Administrators` can take ownership, and the executor retains delete
capability over `artifacts\` until the post-verification downgrade is applied. The
destination remains non-redundant, non-immutable, non-off-site, unversioned, and on
the same physical D: storage domain as the source workspace.

**Reason the ACL is mandatory and not cosmetic.** `D:\` carries ACEs flagged
`ContainerInherit, ObjectInherit` granting `Authenticated Users` effective modify
rights. A custodial directory created with default inheritance would be writable and
deletable by any authenticated user of the machine.

**Approved copy contract.** Copy-only; explicit list of the 17 paths; open glob
prohibited; overwrite prohibited; exact names preserved; `.db`, `.db-wal` and
`.db-shm` preserved jointly; stop at the first error; no artifact opened as SQLite;
source never modified. Required mechanism: semantics equivalent to
`File.Copy(source, destination, overwrite: false)`, which fails if the destination
already exists.

**Approved manifest.** JSON, schema fields: `manifest_version`, `created_at_utc`,
`project`, `source_workspace`, `destination_root`, `authorized_by`, `executed_by`,
`policy_commit`, `copy_contract_version`, `artifact_count`, `total_bytes`,
`artifacts[]`; each artifact carrying `filename`, `family_basename`,
`component_type`, `source_path`, `destination_path`, `size_bytes`,
`sha256_source_before`, `sha256_destination_after`, `copy_status`. The manifest must
not contain credentials, tokens, SQLite content, business data, PII or table dumps.
It records file identity, never file content.

**Approved partial-failure policy.**

```
Origin is never modified.

Partial destination residue is preserved for inspection until an explicit
cleanup decision is issued.
```

Automatic cleanup and silent retry are **not authorized**. Distinct failure classes
to be reported separately: file not copied; destination partially populated;
destination hash divergence; source divergence; preexisting conflict.

**Approved Level 2 restoration environment (provisional).** No container runtime is
available on this machine — `CONTAINER_RUNTIME_NOT_AVAILABLE` was observed read-only
(`docker` absent from PATH, no Docker install path, service not installed). While
that remains true, the approved provisional alternative is a controlled external
directory `D:\tmp\sgaa_restore_<UTC>`, disposable, created and destroyed within its
own round, binding only a copy derived from `artifacts\`. The source workspace must
never be mounted as the restoration database; `artifacts\` must never be opened
directly; logs are written to `evidence\`, never to `artifacts\`. The ISOLATED
CONTAINER preference recorded in R2 returns as preferred if a runtime is installed.

**Scope of the future authorized round.** Exactly: provision the two directories;
apply the approved ACL; copy the 17 artifacts; create the manifest; verify count,
sizes and SHA-256. Nothing else.

**Withheld in the same decision:** physical execution. Also prohibited: move, delete,
compress, SQLite open, restoration execution, source removal, and Phase 2–6.

## Disposable restoration environment

Preferred disposable restoration environment:
ISOLATED CONTAINER

Mount rule:
BIND ONLY A DERIVED DISPOSABLE COPY

Source workspace:
MUST NOT BE MOUNTED AS RESTORATION DATABASE

Custodial artifact:
MUST NOT BE OPENED DIRECTLY

This is a recorded preference, not an execution. No container was created, no
Docker runtime was verified, no volume was mounted, no image was built, and no
database was opened. Operational feasibility of the container remains a separate
future assessment.

## Governance rules

1. Esta é uma trilha administrativa/de governança autônoma. Não integra Phase 1, Phase 2 ou qualquer fase arquitetural de implementação.
2. Governa exclusivamente a custódia dos 17 snapshots históricos ignorados.
3. Nenhuma ação física está autorizada sem ordem humana explícita.
4. O track permanece aberto apenas porque os seguintes itens estão pendentes: specific physical destination; controlled-copy contract; disposable restoration environment; separate human authorization to execute the copy.
5. Qualquer ação física exige autorização humana explícita do responsável pelo projeto. IA futura não pode inferir autorização do fechamento da Phase 1, checkbox histórica, existência deste documento, ausência de consumidores runtime ou estado ignored.
6. Hashes são identidade read-only, não manifesto nem validação de restauração.
7. Os 17 artefatos históricos NÃO são backups gerenciados por `app/db_maintenance.py` nem `app/services/backup_service.py`. Nenhuma validação, restauração ou arquivamento foi realizada ou autorizada.

## Inventário read-only revalidado antes desta delegação

- database.pre-D6-shadow-collect-20260530-192502.db | 495616 bytes | 0fb13fb142b8e56bbb564ee1cfdf8f8dc15428671a4b76ab07e635b061d1725e
- database.pre-D6-shadow-collect-20260530-192502.db-shm | 32768 bytes | fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb
- database.pre-D6-shadow-collect-20260530-192502.db-wal | 0 bytes | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- database.pre-D6.4.0-activate-20260531-080306.db | 503808 bytes | 1fd6b33f2a4d93471e029619b11e9c7d51e4d8f552315ea5532d792c553609d8
- database.pre-D6.4.0-activate-20260531-080306.db-shm | 32768 bytes | fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb
- database.pre-D6.4.0-activate-20260531-080306.db-wal | 0 bytes | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- database.pre-D6.4.0-target-readiness-2-20260531-101530.db | 507904 bytes | 6da98eda32c71aaeac4b8b3d022cb69c5b6493ee0fe150d48317de263f332575
- database.pre-D6.4.0-target-readiness-2-20260531-101530.db-shm | 32768 bytes | fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb
- database.pre-D6.4.0-target-readiness-2-20260531-101530.db-wal | 0 bytes | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- database.pre-D6.4.0-write-runtime-20260530-210917.db | 495616 bytes | f13d78ee3b17a3088de33fe06076c7b6debf6fca9497817a31ac9181dad8e105
- database.pre-D6.4.0-write-runtime-20260530-210917.db-shm | 32768 bytes | fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb
- database.pre-D6.4.0-write-runtime-20260530-210917.db-wal | 0 bytes | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- database.pre-D7.2B2-runtime-check-20260608-133854.db | 528384 bytes | 128bb82421527afece427391e17f470bfc089f98f903c1166541d2a3109ac526
- database.pre-D7.6B-schema-migration-20260613-180525.db | 528384 bytes | 7ffb0c1ccc1bc3d60a86492bcda15f800af00dc84b6d9693ff5f4762680d55bf
- database.pre-D7.6B2-R1-default-fix-20260613-183117.db | 544768 bytes | 1ff670da11b1d5879bdadb1cc7f1de64691222561ce0cc15eb6e2ee3c103fc94
- database.pre-D7.6B2-R2-hardening-20260613-184709.db | 544768 bytes | 92627ded44c9094e74f01da5718c995cd3fdd5ac467ef79298541a75b777cd8c
- database.pre-debug-cleanup-20260604-124610.db | 528384 bytes | c90fc7b799b8317193e7fccfc655cdf11891ffa20ed8f07d7afd6f08648f7323

Exact next action:

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R4 — controlled provisioning, ACL
application, copy of the 17 artifacts, manifest creation and integrity
verification.

R4 is NOT STARTED. The contract it must follow is APPROVED, but physical execution
was explicitly withheld. R4 requires a separate explicit human order releasing
physical execution. The approval recorded here does not constitute that order and
must never be read as one.

R4 scope, when released: create `D:\programas` and
`D:\programas\SGAA_Historical_Custody\{artifacts,manifests,evidence}`; apply the
approved ACL; copy exactly 17 artifacts with overwrite disabled; create the custody
manifest; verify count, sizes and SHA-256. Move, delete, compress, SQLite open,
restoration execution and source removal remain prohibited in R4. Phase 2 remains
without authorized next action.

Preserved historical / superseded wording: statements that R2 or R3 were
"NOT STARTED", that the specific destination was "UNRESOLVED" or "NOT YET SELECTED",
that the provisioning and copy contract was undrafted or pending, the R30 state
`DESTINATION_OPTIONS_READY_AWAITING_HUMAN_SELECTION`, and the R3 phase-time state
`COPY_EXECUTION_CONTRACT_READY_AWAITING_HUMAN_AUTHORIZATION` are superseded by this
closeout and preserved only as historical record.
