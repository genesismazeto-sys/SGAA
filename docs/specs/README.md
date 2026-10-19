# Phase SPECs

A SPEC is the execution contract of one macro-phase (`docs/OPERATING_MODEL.md`
§3–§6). Write it from [`TEMPLATE.md`](TEMPLATE.md) as
`docs/specs/MP-<n>-<slug>.md`. A closed SPEC is immutable and stays at its
path. The roadmap and the active phase live in `PROJECT_STATE.md`; this file
indexes SPECs only.

| ID | Title | Tier | Status | SPEC |
|---|---|---|---|---|
| MP-0 | Spec-driven governance transition | R1 | CLOSED | none — executed under the pre-MP-0 protocol by supervisor instruction; the record is its Git commit |
| MP-1 | Storage convergence | R2 | CLOSED | [`MP-1-storage-convergence.md`](MP-1-storage-convergence.md) |
| MP-2 | Hosting readiness | R2 | CLOSED | [`MP-2-hosting-readiness.md`](MP-2-hosting-readiness.md) |
| MP-3 | Production integration and cutover | R3 | FROZEN, acknowledged with binding amendments 2026-10-10; amended through A19; C13 (PONR) recorded 2026-10-12; production reopened via GF1 (user reconciliation 2026-10-13) | [`MP-3-production-integration.md`](MP-3-production-integration.md) |
| MP-3 A20 | Automated hosted backup execution | R3 | PROD deployed 2026-10-15; first triggered due backup complete on both drives; scheduled due-wake evidence pending before close | [`MP-3-A20-hosted-backup-automation.md`](MP-3-A20-hosted-backup-automation.md) |
| MP-3 A22 | Correcting the activity of an editable request (schema v17) | R3 | FROZEN 2026-10-19; slice 1 implemented; PROD upgrade and deploy (G1) pending | [`MP-3-A22-request-reclassification.md`](MP-3-A22-request-reclassification.md) |
