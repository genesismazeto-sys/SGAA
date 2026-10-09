"""Legacy business-document convergence into canonical storage.

Legacy request documents and admin ARQUIVOS live on Google Drive
(``provider='google'``) or on the local disk (``provider='local_legacy'``).
Convergence copies their bytes into canonical Supabase Storage and LINKS the
legacy row to the new ``storage_objects`` row through ``storage_object_id``;
the row keeps its provider and locator as provenance and legacy residue.  A
row with a canonical reference is canonical custody, whatever its provider.

This module owns the ONE eligibility rule per table and provider -- the
census counts with it, the convergence acts on it -- and the provider ->
``storage_objects.origin`` rule the cross-check verifies.

THE ELIGIBILITY RULE
    A legacy row converges only from its steady state -- the state in which
    its bytes are known and nothing else is in flight:

    requisicao_arquivos  google        ``active`` with a Drive locator
                         local_legacy  ``legacy_active`` with a file name
    admin_arquivos       google        ``active`` with a Drive locator, no
                                       failure, residue or cleanup in flight
                         local_legacy  ``legacy_active`` with a file name, no
                                       replacement reservation or failure

    Every other legacy row is BLOCKED (pending, failed, in reconciliation, in
    deletion, trashed, mid-replacement): the census reports it by provider and
    status, and convergence never touches it.  Eligibility is a steady STATE;
    a locator outside the legal alphabet is classified when the row's bytes
    are read, so an eligible count is an upper bound.
"""

from __future__ import annotations

from app.prod1_document_custody_ddl import CANONICAL_PROVIDER
from app.prod1_storage_ddl import STORAGE_OBJECT_REFERENCE_TABLES, STORAGE_ORIGINS

STEADY_REQUEST_GOOGLE = (
    "provider = 'google' AND storage_status = 'active' AND storage_object_id IS NULL"
    " AND COALESCE(TRIM(remote_file_id), '') <> ''"
)
STEADY_REQUEST_LOCAL = (
    "provider = 'local_legacy' AND storage_status = 'legacy_active' AND storage_object_id IS NULL"
    " AND COALESCE(TRIM(filename), '') <> ''"
)
STEADY_ARQUIVO_GOOGLE = (
    "provider = 'google' AND storage_status = 'active' AND storage_object_id IS NULL"
    " AND failure_code IS NULL AND prior_provider IS NULL AND cleanup_started_at IS NULL"
    " AND COALESCE(TRIM(remote_file_id), '') <> ''"
)
STEADY_ARQUIVO_LOCAL = (
    "provider = 'local_legacy' AND storage_status = 'legacy_active' AND storage_object_id IS NULL"
    " AND operation_key IS NULL AND failure_code IS NULL AND COALESCE(TRIM(filename), '') <> ''"
)

TABLES = STORAGE_OBJECT_REFERENCE_TABLES
LEGACY_PROVIDERS = ("google", "local_legacy")
#: The ``storage_objects.origin`` the canonical object of each business
#: provider carries: a direct upload for a canonical row, a migration for a
#: converged legacy row.
ORIGIN_BY_PROVIDER = {
    CANONICAL_PROVIDER: "direct_upload",
    "google": "migrated_google",
    "local_legacy": "migrated_local_legacy",
}
assert set(ORIGIN_BY_PROVIDER.values()) == set(STORAGE_ORIGINS)

_ELIGIBLE = {
    ("requisicao_arquivos", "google"): STEADY_REQUEST_GOOGLE,
    ("requisicao_arquivos", "local_legacy"): STEADY_REQUEST_LOCAL,
    ("admin_arquivos", "google"): STEADY_ARQUIVO_GOOGLE,
    ("admin_arquivos", "local_legacy"): STEADY_ARQUIVO_LOCAL,
}

#: Legacy rows not converged yet -- eligible or blocked.
UNCONVERGED_LEGACY = "provider IN ('google', 'local_legacy') AND storage_object_id IS NULL"
#: Legacy rows already linked to a canonical object.
CONVERGED_LEGACY = "provider IN ('google', 'local_legacy') AND storage_object_id IS NOT NULL"


def eligible_predicate(table: str, provider: str) -> str:
    """The fixed SQL predicate of the rows of ``table`` / ``provider`` that may converge."""
    try:
        return _ELIGIBLE[(table, provider)]
    except KeyError:
        raise ValueError("unknown legacy table or provider") from None


def _table(table: str) -> str:
    if table not in TABLES:
        raise ValueError("unknown legacy table")
    return table


def legacy_census(conn, table: str) -> dict:
    """Value-free counts of one business table's custody classes."""
    table = _table(table)

    def count(predicate: str) -> int:
        return int(conn.execute(f"SELECT count(*) FROM {table} WHERE {predicate}").fetchone()[0])

    eligible = {provider: count(eligible_predicate(table, provider)) for provider in LEGACY_PROVIDERS}
    eligible_any = " OR ".join(f"({eligible_predicate(table, provider)})" for provider in LEGACY_PROVIDERS)
    blocked = {
        f"{row[0]}:{row[1]}": int(row[2])
        for row in conn.execute(
            f"SELECT provider, storage_status, count(*) FROM {table}"
            f" WHERE {UNCONVERGED_LEGACY} AND NOT ({eligible_any})"
            " GROUP BY provider, storage_status ORDER BY provider, storage_status"
        ).fetchall()
    }
    converged = {
        str(row[0]): int(row[1])
        for row in conn.execute(
            f"SELECT provider, count(*) FROM {table} WHERE {CONVERGED_LEGACY} GROUP BY provider ORDER BY provider"
        ).fetchall()
    }
    return {
        "canonical": count("provider = 'supabase'"),
        "converged": converged,
        "eligible": eligible,
        "blocked": blocked,
        "unconverged": count(UNCONVERGED_LEGACY),
    }


__all__ = [
    "CONVERGED_LEGACY",
    "LEGACY_PROVIDERS",
    "ORIGIN_BY_PROVIDER",
    "TABLES",
    "UNCONVERGED_LEGACY",
    "eligible_predicate",
    "legacy_census",
]
