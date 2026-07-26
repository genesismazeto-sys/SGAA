# HISTORICAL-DATABASE-SNAPSHOT-CUSTODY

## Current status

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R1:
CLOSED / ACCEPTED

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R2:
CLOSED / ACCEPTED

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R3:
CLOSED / ACCEPTED

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R4:
EXECUTED / PHYSICAL PROVISIONING COMPLETE /
COPY COMPLETE / INTEGRITY VERIFIED /
SOURCE PRESERVED

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R5:
CLOSED / ACCEPTED

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R6:
CLOSED / ACCEPTED WITH DECLARED POST-MUTATION NONCONFORMITY

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R7:
CLOSED / ACCEPTED

R7 READ-ONLY ASSESSMENT:
COMPLETE

LEVEL2 EXECUTION CONTRACT:
READY

PHYSICAL LEVEL2 RESTORATION:
NOT AUTHORIZED

R7 DOCUMENTARY CLOSEOUT:
COMMITTED AND PUBLISHED

R6 EXECUTION CLASSIFICATION:
POST-MUTATION HARD STOP

PHYSICAL DACL OUTCOME:
TARGET APPLIED / INDEPENDENTLY VERIFIED

R5 assessment classification (final, pre-decision):
PARENT_ACL_HARDENING_RECOMMENDED_AWAITING_HUMAN_DECISION

R5 read-only assessment result:
FILE_DELETE_CHILD_NOT_GRANTED_CONFIRMED

Human decision:
HARDENING POLICY APPROVED / STRICT HARDENING OPTION B SELECTED /
PHYSICAL APPLICATION NOT AUTHORIZED AT THIS TIME

R30:
DESTINATION_OPTIONS_READY_AWAITING_HUMAN_SELECTION /
SUPERSEDED BY HUMAN SELECTION

Human decision dates: 25/07/2026 (custody policy, canonical destination,
provisioning and copy contract).

Active classification:
CUSTODY_COPY_EXECUTED_AND_VERIFIED /
DESTINATION PROVISIONED /
PARENT ACL HARDENING APPLIED AND VERIFIED /
SOURCE PRESERVED /
SECURITY-COMPLETE CUSTODY: NOT CLAIMED

Superseded phase-time classification:
PROVISIONING_AND_COPY_CONTRACT_APPROVED /
DESTINATION NOT YET PROVISIONED /
PHYSICAL EXECUTION NOT AUTHORIZED AT THIS TIME /
R5 NOT STARTED / R5 AWAITING HUMAN DECISION

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
DESTINATION PROVISIONED / PARENT DEDICATED TO CUSTODY TRACK /
PARENT ACL HARDENING APPLIED AND VERIFIED

Physical action (general):
NOT AUTHORIZED WITHOUT SEPARATE EXPLICIT ORDER

Copy (additional):
NOT AUTHORIZED

Move:
NOT AUTHORIZED

Delete:
NOT AUTHORIZED

Compress:
NOT AUTHORIZED

SQLite open:
NOT AUTHORIZED

Parent ACL hardening (R6):
APPLIED / EXTERNALLY VERIFIED /
R6 POST-MUTATION HARD STOP

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
LEVEL 2 RESTORATION ONLY AFTER A LATER SEPARATE EXPLICIT HUMAN ORDER

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

That withholding was lifted by a later, separate human authorization; see R4 below.

## R4 — executed physical provisioning and copy

```
HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R4:
EXECUTED / PHYSICAL PROVISIONING COMPLETE /
COPY COMPLETE / INTEGRITY VERIFIED /
SOURCE PRESERVED

Canonical destination:
D:\programas\SGAA_Historical_Custody

Destination:
PROVISIONED

Artifacts:
17 / 4,808,704 bytes / VERIFIED

Custody manifest:
custody-manifest-20260725T233026Z.json

Evidence report:
r4-copy-and-verification-20260725T233315Z.md

SQLite:
NOT OPENED

Restoration Level 2:
NOT EXECUTED

Restoration Level 3:
NOT EXECUTED

Source removal:
NOT AUTHORIZED

Phase 2–6:
UNAUTHORIZED
```

**Pre-execution physical authorization.**

```
PRE-EXECUTION PHYSICAL AUTHORIZATION:
EVIDENCED

Authority:
PROJECT OWNER

Scope:
R4 ONLY
```

The authorization was issued as an explicit human instruction in the Claude Code
session, immediately before execution and before the point of no return. It enumerated
ten authorized actions, named the technical executor and SID, required stopping at the
first error or divergence, listed the standing prohibitions, and stated that it applied
only to R4 and did not constitute permanent authorization. Its medium is the session
record, not a repository file; this closeout is the durable repository record of it.

**Gate results.** Gate 1 preflight PASS; Gate P1 provisioning PASS; Gate P2 ACL PASS;
Gate 2 copy PASS; Gate 3 integrity PASS; Gate 5 preservation PASS.

**Destination layout as built.**

```
D:\programas\SGAA_Historical_Custody\
  artifacts\   17 files, 4,808,704 bytes, zero subdirectories
  manifests\   custody-manifest-20260725T233026Z.json, 16,872 bytes
  evidence\    r4-copy-and-verification-20260725T233315Z.md, 4,505 bytes
```

Manifest SHA-256:
`8552c289acfa0067a24848b960383446ffb1b5663a324515bac9309a65a9f0c3`

Evidence report SHA-256:
`82494024c71d374e54b5ed1d2470d86c00738d345ece8179d76967c80ac56d71`

Source aggregate SHA-256 before and after copy, unchanged:
`44ae5da3f368605ac2550cc65d70d2081d432977c48fad1f467884a65f2e3be3`

Per-file destination SHA-256 equals source equals canonical inventory for all 17
artifacts. No unexpected file at the destination. The manifest and the evidence report
live outside `artifacts\`. Source remains 17/17, ignored and untracked, physically
unchanged.

**Final ACL as built.**

| Path | Protected | ACEs |
|------|-----------|------|
| `D:\programas` | No (inherits `D:\`) | Administrators FC; SYSTEM FC; Authenticated Users Modify; Users ReadAndExecute |
| `…\SGAA_Historical_Custody` | Yes | SYSTEM FC; Administrators FC; executor Modify |
| `…\artifacts` | Yes | SYSTEM FC; Administrators FC; executor ReadAndExecute |
| `…\manifests` | No (inherits custody root) | SYSTEM FC; Administrators FC; executor Modify |
| `…\evidence` | No (inherits custody root) | SYSTEM FC; Administrators FC; executor Modify |

Custody root SDDL:
`O:S-1-5-21-…-1001G:S-1-5-21-…-1001D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1301bf;;;S-1-5-21-…-1001)`

`artifacts\` SDDL differs only in the executor mask, `0x1200a9` (ReadAndExecute).

`Authenticated Users` and `BUILTIN\Users` are absent from the custody root and from
`artifacts\`, as approved.

**Operational nonconformities.**

```
DECLARED / CONTAINED / NO ARTIFACT INTEGRITY IMPACT /
NOT AN AUTHORIZED PRECEDENT
```

1. `New-Item -LiteralPath` is incompatible with PowerShell 5.1; the failure occurred at
   parameter binding, before any directory was created. Absence of residue was verified.
   The mechanism was replaced by `[System.IO.Directory]::CreateDirectory`, which is
   literal by definition.
2. `Set-Acl` failed with `PrivilegeNotHeldException` (`SeSecurityPrivilege`) during the
   post-verification ACL downgrade, because the cmdlet attempted to write the SACL. No
   artifact was altered. The correction was localized: `DirectoryInfo.SetAccessControl`
   with `AccessControlSections::Access`, writing the DACL exclusively.
3. The first attempt to write the evidence report failed on shell quoting; no partial
   file was created, the evidence directory was verified empty, and a second explicit
   write completed.

These are recorded as operational failures. R4 must not be described as a flawless
execution.

**Residual security risk — corrected measurement.**

```
Residual security risk:
PARENT DIRECTORY ACL EXPOSURE OPEN

Security-complete custody:
NOT YET CLAIMED
```

The R4 execution report stated a `DELETE_CHILD` exposure on the parent. Direct
measurement in this closeout does not support that specific claim and corrects it. The
inherited `Authenticated Users` ACE on `D:\programas` carries mask `0x1301BF`, in which
`FILE_DELETE_CHILD` (`0x40`) is **not** set. `WRITE_DAC` (`0x40000`) and `WRITE_OWNER`
(`0x80000`) are also **not** set. Deleting or renaming the custody root therefore
requires either `DELETE` on that object — which no non-privileged principal holds, since
the custody root DACL is protected and omits them — or `FILE_DELETE_CHILD` on the
parent, which is not granted.

What remains genuinely open, and is the subject of R5:

- `Authenticated Users` hold `ADD_FILE` (`0x2`) and `ADD_SUBDIRECTORY` (`0x4`) on
  `D:\programas`, so any authenticated principal can create arbitrary content beside the
  custody root in the same parent namespace.
- `Authenticated Users` hold `DELETE` (`0x10000`) on `D:\programas` itself. The parent is
  non-empty and its children are not deletable by them, so removal is blocked in
  practice, but the right is present on the object.
- The custody root is owned by the executor. An owner implicitly holds `READ_CONTROL`
  and `WRITE_DAC`, so the executor can restore Modify on `artifacts\` at will, and
  `Administrators` can take ownership. This is inherent to the approved model, not a
  defect introduced by R4, and it is why an ACL is not immutability.

No parent hardening was performed. It was outside the approved contract and outside the
R4 authorization.

## R5 — read-only parent ACL assessment and hardening decision closeout

```
HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R5:
CLOSED / ACCEPTED

R5 read-only assessment result:
FILE_DELETE_CHILD_NOT_GRANTED_CONFIRMED

Final R5 assessment classification before human decision:
PARENT_ACL_HARDENING_RECOMMENDED_AWAITING_HUMAN_DECISION

Human decision:
HARDENING POLICY APPROVED / STRICT HARDENING OPTION B SELECTED

Parent ACL hardening:
PHYSICAL APPLICATION NOT AUTHORIZED AT THIS TIME
```

R5 was a strict read-only Windows ACL assessment followed by this documentary
human-decision closeout. No ACL or physical mutation occurred in R5 or this
closeout. No file was created, deleted, renamed, or written outside the seven
authorized repository documents.

### Verified findings

The following findings were verified read-only from the current physical state
of `D:\programas` and its parent `D:\`:

1. **Physical dedication of `D:\programas`:** The directory currently contains
   only the immediate child `SGAA_Historical_Custody`. It is physically dedicated
   to this custody track. No workspace directory, no other custodial directory,
   no unrelated content exists at `D:\programas`.

2. **Human declaration:** `D:\programas` is human-declared exclusively dedicated
   to the SGAA-EJ historical-custody track.

3. **Literal directory distinction:** `D:\programas` and `D:\Programação` are
   distinct literal directories on the same volume. No inspected path was a
   reparse point, junction, symlink, or mount point.

4. **Authenticated Users parent-object mask:** The inherited `Authenticated Users`
   ACE on `D:\programas` carries applicable-object mask `0x001301BF`. It lacks
   `FILE_DELETE_CHILD` (`0x00000040`), `WRITE_DAC` (`0x00040000`) and
   `WRITE_OWNER` (`0x00080000`).

5. **Included rights on `D:\programas`:** The same ACE includes `DELETE`
   (`0x00010000`), `FILE_ADD_FILE` (`0x00000002`) and `FILE_ADD_SUBDIRECTORY`
   (`0x00000004`).

6. **Immediate custody-root protection:** A common `Authenticated Users` plus
   `BUILTIN\Users` principal cannot directly delete or rename
   `D:\programas\SGAA_Historical_Custody` because they have neither `DELETE`
   on the protected custody root itself (the root DACL is protected and omits
   them) nor `FILE_DELETE_CHILD` on the parent.

7. **Namespace contamination risk:** The same principal can create sibling
   files and directories beside the custody root (`FILE_ADD_FILE`,
   `FILE_ADD_SUBDIRECTORY`). Furthermore, `DELETE` on `D:\programas` combined
   with `FILE_ADD_SUBDIRECTORY` on `D:\` statically permits rename of the parent
   and recreation of a replacement `D:\programas` namespace. No destructive test
   was performed; this is a static analysis finding.

8. **Token evaluation note:** The current non-elevated executor token has the
   `Administrators` SID as deny-only. Nominal group membership was not treated
   as an active allow SID. The executor/owner can alter the DACL at will through
   `WRITE_DAC` ownership; elevated administrators retain full authority.

9. **Independent confirmation:** `FILE_DELETE_CHILD_NOT_GRANTED_CONFIRMED`
   resulted independently from three representations: SDDL decoding, raw mask
   decoding, and `icacls` plus `Get-Acl`/.NET representation. All three agreed.

### Human-approved hardening policy for `D:\programas`

The human has approved the following strict ACL for `D:\programas`:

- Directory is exclusive to SGAA-EJ historical custody.
- Disable DACL inheritance.
- `SYSTEM` — FullControl `0x001F01FF` OI/CI.
- `BUILTIN\Administrators` — FullControl `0x001F01FF` OI/CI.
- `KR-IDEAPAD\klebe` (SID
  `S-1-5-21-1500819853-3011909004-3032907821-1001`) — ReadAndExecute
  `0x001200A9` OI/CI.
- Remove `Authenticated Users`.
- Remove `BUILTIN\Users`.
- Keep current owner `KR-IDEAPAD\klebe`.

### Approved target SDDL (policy only — NOT applied)

```
O:S-1-5-21-1500819853-3011909004-3032907821-1001G:S-1-5-21-1500819853-3011909004-3032907821-1001D:P(A;OICI;0x001F01FF;;;SY)(A;OICI;0x001F01FF;;;BA)(A;OICI;0x001200A9;;;S-1-5-21-1500819853-3011909004-3032907821-1001)
```

This SDDL is the approved target. It is recorded as policy only. It has **not**
been applied.

This paragraph is the preserved R5 phase-time state. It is superseded by the R6
post-mutation reconciliation below: the approved target DACL was applied once and
independently verified.

### Accepted residuals

The following residual risks are accepted as inherent to the approved model:

- The owner (currently `KR-IDEAPAD\klebe`) can still alter the DACL through
  implicit `WRITE_DAC`.
- Elevated administrators retain authority (can take ownership, override
  protection).
- An ACL is not immutability.
- Source and destination remain on the same physical `D:` volume; a single
  disk failure would affect both.
- No independent redundancy (off-site, second disk, or cloud copy) is created
  by this policy.

### Physical state (truthful current state)

- **Current `D:\programas` SDDL:** Remains the inherited R4-era SDDL (inherits
  from `D:\`). The strict target SDDL above is **NOT APPLIED**.
- **Custody-root ACL:** Remains unchanged from R4.
- **Source and destination:** 17/17 artifacts intact, 4,808,704 bytes each,
  all per-file SHA-256 hashes matched (unchanged from R4 verification).
- **Manifest:** 16,872 bytes, SHA-256
  `8552c289acfa0067a24848b960383446ffb1b5663a324515bac9309a65a9f0c3` — unchanged.
- **Evidence:** 4,505 bytes, SHA-256
  `82494024c71d374e54b5ed1d2470d86c00738d345ece8179d76967c80ac56d71` — unchanged.
- No SQLite was opened. No restoration, recopy, source removal, ACL change,
  owner change, file/directory creation/deletion/rename, test, application, or
  Phase 2-6 work occurred in R5 or this closeout.

### Documentary closeout details

- **Baseline/pre-closeout HEAD:**
  `4a08d7407c4a0f6cf424718dc48cb8502088f790`
- **Baseline subject:** `Record executed historical custody provisioning and copy`
- **Exact seven-document manifest:**
  - `AGENT_HANDOFF.md`
  - `PROJECT_STATE.md`
  - `docs/DOCUMENTATION_INDEX.md`
  - `docs/mapeamento/03_banco_de_dados.md`
  - `docs/mapeamento/05_avaliacao_refactor.md`
  - `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`
  - `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`
- **Authorized commit subject:**
  `Record approved R5 parent ACL hardening decision`
- **Identity resolution:** Identity resolved through Git history; do not invent
  future commit SHA or claim it already exists.
- **Tests:** NOT RUN / PROHIBITED.

### Supersession — R5 awaiting-decision wording

All pre-closeout statements that R5 was "NOT STARTED" or
"not authorized to modify D:\programas" (or similar awaiting-human-decision
wording) in any of the seven documents are superseded by this closeout. Where
such statements appear in historical phase-time blocks below this active
section, they are preserved only as historical record of the pre-decision
phase-time state and must not be mistaken for current state.

## R6 — post-mutation reconciliation and documentary closeout

```
HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R6:
CLOSED / ACCEPTED WITH DECLARED POST-MUTATION NONCONFORMITY

R6 EXECUTION CLASSIFICATION:
POST-MUTATION HARD STOP

PHYSICAL DACL OUTCOME:
TARGET APPLIED / INDEPENDENTLY VERIFIED

SetAccessControl calls:
1

Apply process:
EXIT 1

Post-application error:
PropertyNotFoundStrict — property 'Value' not found

Failure location:
POST-MUTATION VERIFICATION / SERIALIZATION PATH

Retry:
NOT PERFORMED / PROHIBITED

Rollback:
NOT PERFORMED / PROHIBITED
```

The error occurred after the one authorized DACL mutation. The script produced no
successful Apply JSON, so the execution classification remains POST-MUTATION HARD STOP.
Independent read-only verification proved that the approved target DACL is physically
present; this closeout does not describe R6 as an execution without failures and does not
authorize a second call.

**Observed parent state.** `D:\programas` has protected access rules, owner and group
`S-1-5-21-1500819853-3011909004-3032907821-1001`, exactly three explicit Allow ACEs,
zero inherited ACEs and zero Deny ACEs:

| Principal | Mask | Inheritance | Type |
|-----------|------|-------------|------|
| SYSTEM (`S-1-5-18`) | `0x001F01FF` | OI/CI | Allow |
| BUILTIN\Administrators (`S-1-5-32-544`) | `0x001F01FF` | OI/CI | Allow |
| executor (`S-1-5-21-1500819853-3011909004-3032907821-1001`) | `0x001200A9` | OI/CI | Allow |

`Authenticated Users`, `BUILTIN\Users`, `Everyone`, inherited ACEs and Deny ACEs are
absent. The executor ACE does not grant delete, create or write. Owner/group are
unchanged. The owner nevertheless retains inherent authority to change the DACL, and
elevated administrators retain FullControl.

Observed parent SDDL:

```
O:S-1-5-21-1500819853-3011909004-3032907821-1001G:S-1-5-21-1500819853-3011909004-3032907821-1001D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;S-1-5-21-1500819853-3011909004-3032907821-1001)
```

**Preserved external evidence.** Read-only reconciliation confirmed:

- `evidence\r6-parent-acl-hardening.ps1` — 5,830 bytes; SHA-256
  `92B81095C9BC4CE8254A0CC279CD9A524AAC54305529318879BE91E86D4FB7E2`.
- `evidence\r6-parent-acl-hardening-20260726T094257Z.md` — 12,529 bytes; SHA-256
  `E5A9F4EC7FD7CA20B6537187198AE2657DB17421EF405B1436C95C6F3F814E85`.
- `evidence\` contains exactly the R4 report, the preserved R6 script and the R6 report.
- Manifest R4 — 16,872 bytes; SHA-256
  `8552C289ACFA0067A24848B960383446FFB1B5663A324515BAC9309A65A9F0C3`.
- Report R4 — 4,505 bytes; SHA-256
  `82494024C71D374E54B5ED1D2470D86C00738D345ECE8179D76967C80AC56D71`.
- Source and destination: 17/17, 4,808,704 bytes each; source SHA-256 equals
  destination SHA-256 equals manifest for all 17.
- SDDL of the custody root, `artifacts\`, `manifests\` and `evidence\`: zero drift.

**Declared nonconformity.** `DECLARED / CONTAINED / NO DACL TARGET DEVIATION /
NO ARTIFACT INTEGRITY IMPACT / NO RETRY / NOT AN AUTHORIZED PRECEDENT`.

**Residual risks accepted.** The owner can still modify the DACL by inherent authority;
elevated administrators retain FullControl; ACL does not constitute immutability; source
and destination remain on physical volume D:; no independent redundancy exists; Levels 2
and 3 were not executed; source removal remains prohibited. SECURITY-COMPLETE CUSTODY is
not claimed.

**Documentary closeout.** Baseline/pre-closeout HEAD
`07fe0666eedbaa76395c278b4c0f798a0d3320ed`, subject
`Record approved R5 parent ACL hardening decision`. Authorized subject:
`Record verified R6 parent ACL hardening outcome`; identity resolved through Git history.
Exactly seven repository documents changed. Tests/application/pytest: NOT RUN /
PROHIBITED. No new physical mutation, ACL call, retry, rollback, SQLite open, restoration,
source change, external-file creation or evidence modification occurred in this closeout.

IAexec routing was consultative. FREE session `ses_06227b5d6ffe5s5DrFi4JTkxYE` used
`opencode/deepseek-v4-flash-free`, exit 0 and cost 0, but delivered no final text and was
rejected as unusable. Explicit normal complement session
`ses_06226b324ffeHTsk45kMGIfguu` used `opencode-go/deepseek-v4-flash`, exit 0,
`CONSULTATIVE_USABLE`; this was a task-level explicit fallback, not router-native fallback.
Final acceptance is the IAsup deterministic decision.

## R7 — read-only Level 2 restoration readiness assessment and restoration-execution contract

```
HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R7:
CLOSED / ACCEPTED

R7 READ-ONLY ASSESSMENT:
COMPLETE

LEVEL2 EXECUTION CONTRACT:
READY

PHYSICAL LEVEL2 RESTORATION:
NOT AUTHORIZED

R7 DOCUMENTARY CLOSEOUT:
COMMITTED AND PUBLISHED
```

The R7 assessment round was read-only and performed no repository mutation or physical
restoration. The seven-document closeout is committed and published under the authorized
subject `Record accepted R7 Level 2 restoration contract`; identity is resolved through
Git history. No physical order is issued by this closeout.

### Level 2 primary candidate

Primary future Level 2 candidate:

```
database.pre-D7.6B2-R2-hardening-20260613-184709.db
```

SHA-256: `92627ded44c9094e74f01da5718c995cd3fdd5ac467ef79298541a75b777cd8c`

Fallback Level 2 candidate:

```
database.pre-D7.6B-schema-migration-20260613-180525.db
```

SHA-256: `7ffb0c1ccc1bc3d60a86492bcda15f800af00dc84b6d9693ff5f4762680d55bf`

The fallback requires another specific human decision; it must never be automatic.

### Primary future environment

NATIVE WINDOWS. The R3-era container preference (ISOLATED CONTAINER) is
historical/provisional and is superseded by this R7 selection. No container
fallback is currently ready.

### Approved Level 2 restoration layout

```
D:\tmp\sgaa_restore_<UTC>\
  sealed\     custody copies only
  working\    derives only from sealed
  evidence\   reports and logs
```

The root `D:\tmp\sgaa_restore_<UTC>` remains unresolved until a later physical
authorization and must be one concrete literal timestamped path matching the
pattern `D:\tmp\sgaa_restore_<UTC>`, where `<UTC>` is replaced by an actual UTC
timestamp.

### Contract boundaries

- Custody copies: only to `sealed\`.
- `working\` derives only from `sealed\`; never from custody, source or any other
  origin.
- Only `working\` may be opened. Source, custody and `sealed\` must never be
  opened directly.
- Zero glob, overwrite, move, delete or automatic cleanup.
- Level 2 runs no `init_db`, no `ensure_*`, no migrations and no hardening.
- No Flask, `main.py`, application, network, production or external services.
- No business rows or personal data may be selected, emitted or exposed; schema
  inventory and aggregate table row counts are permitted.
- Level 2 never authorizes source removal.

### Future execution revalidation requirements

Before any physical Level 2 execution, the operator must revalidate:

- Exact Python executable path, version and SHA-256.
- Open `working\` initially with SQLite URI mode `mode=ro`.
- Set and prove `PRAGMA query_only=ON`.
- Stop immediately if open requires recovery or write.
- Record only `foreign_key_check` row count; never record rowids or content.

### Physical Level 2 status

PHYSICAL LEVEL 2: NOT AUTHORIZED.

This closeout creates no `D:\tmp` root, no `sealed\`, `working\` or `evidence\`
directories, no ACL, no copy, no database open, no validator, no
recovery/checkpoint/migration, no fallback, no Level 3, no source/custody change,
no Phase 2 and no restoration.

The fallback candidate is not authorized without a separate explicit human order.

### Custody track status

Custody track remains OPEN. SECURITY-COMPLETE CUSTODY NOT CLAIMED because
Level 2, Level 3 and independent redundancy remain absent.

### Accepted preservation rule

No automatic cleanup, no fallback automatic. `sealed/`, `working/` and
`evidence/` remain preserved until a later cleanup-specific order. Historical
R1-R7 decision records remain explicitly superseded where applicable and are
not deleted or compacted by this closeout. Operational router telemetry is kept
outside repository documentation.

### Preserved historical/superseded — pre-R7 wording

Statements that R7 was "NOT STARTED", "not authorized", "requires a separate
explicit order", that R7 had no objective defined, or wording that R7's contract
was undrafted or pending are superseded by this closeout. Such claims in
historical blocks below are preserved only as historical record.

## Historical / superseded — R3 provisional disposable restoration environment

Preferred disposable restoration environment:
ISOLATED CONTAINER

Mount rule:
BIND ONLY A DERIVED DISPOSABLE COPY

Source workspace:
MUST NOT BE MOUNTED AS RESTORATION DATABASE

Custodial artifact:
MUST NOT BE OPENED DIRECTLY

This is a recorded R3-era preference, not an execution. No container was created, no
Docker runtime was verified, no volume was mounted, no image was built, and no
database was opened. Operational feasibility of the container remains a separate
future assessment.

**Current R7 authority: NATIVE WINDOWS. This R3 provisional block is historical
/ superseded; no container fallback is currently ready.**

## Governance rules

1. Esta é uma trilha administrativa/de governança autônoma. Não integra Phase 1, Phase 2 ou qualquer fase arquitetural de implementação.
2. Governa exclusivamente a custódia dos 17 snapshots históricos ignorados.
3. Nenhuma ação física está autorizada sem ordem humana explícita.
4. O track permanece aberto porque Level 2 e Level 3 não foram executados, não há redundância independente e a origem permanece preservada.
5. Qualquer ação física exige autorização humana explícita do responsável pelo projeto. IA futura não pode inferir autorização do fechamento da Phase 1, checkbox histórica, existência deste documento, ausência de consumidores runtime ou estado ignored.
6. Hashes são identidade read-only, não manifesto nem validação de restauração.
7. Os 17 artefatos históricos NÃO são backups gerenciados por `app/db_maintenance.py` nem `app/services/backup_service.py`. Cópia e integridade custodial foram verificadas; restauração Level 2/3 e remoção da origem não foram executadas.

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

A new separate explicit human physical Level 2 order restricted to the primary
candidate (`database.pre-D7.6B2-R2-hardening-20260613-184709.db`) and containing
a concrete literal timestamped root matching `D:\tmp\sgaa_restore_<UTC>`.

No physical order is issued by this closeout.

Preserved historical / superseded wording: statements that R2, R3, R4, R5, R6 or
R7 were "NOT STARTED", that the specific destination was "UNRESOLVED" or "NOT YET
SELECTED", that the destination was "NOT YET PROVISIONED", that the provisioning and
copy contract was undrafted or pending, that physical execution was "NOT AUTHORIZED
AT THIS TIME", the R30 state `DESTINATION_OPTIONS_READY_AWAITING_HUMAN_SELECTION`,
the R3 phase-time state `COPY_EXECUTION_CONTRACT_READY_AWAITING_HUMAN_AUTHORIZATION`,
the R5 pre-decision states `PARENT_ACL_HARDENING_RECOMMENDED_AWAITING_HUMAN_DECISION`
and "NOT STARTED" / awaiting-human-decision, and any pre-R7 wording that R7 was
"NOT STARTED", "not authorized", or awaiting a separate explicit order are superseded
by this closeout and preserved only as historical record.
