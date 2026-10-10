# coding: utf-8
"""Business-table fingerprint of a PostgreSQL SGAA database -- operator tool, read-only.

WHY THIS EXISTS
    The point of no return of the cutover is the first successful business write
    by a non-operator principal after users are admitted
    (``docs/specs/MP-3-production-integration.md`` section 3.4).  Nothing in the
    database says who wrote a row, but a business write changes a business
    table.  This tool reads one REPEATABLE READ READ ONLY snapshot and reports,
    per business table, its row count, the normalized content digest the
    Layer-2 backup uses, and a digest per row and column.  Comparing two
    snapshots names the tables, and the columns, that changed; the OPERATOR
    adjudicates (the detector over-reports on purpose: a missed write loses
    data, a false alarm only commits to forward-fix) and records the point of
    no return in the ledger.

WHICH TABLES AND COLUMNS
    The tables Path-B migrates exactly (business identity, catalog, requests,
    documents, configuration), except:

    * ``storage_objects`` -- the Drive mirror changes its mirror columns with no
      business write (an upload also adds a ``requisicao_arquivos`` /
      ``admin_arquivos`` row, which is seen);
    * ``requisicao_alerta_receipts`` -- a receipt is written when an
      administrator merely VIEWS the dashboard (the alert shows again without it).

    and the column ``usuarios.senha``: a login re-hashes a legacy password hash
    in place.  The re-hash also bumps ``usuario_credenciais.auth_version`` and
    ``atualizado_em``, which are INCLUDED: a first sign-in of an account that
    still has a legacy hash, and a real password change, both show as a candidate
    in USUARIO_CREDENCIAIS (columns ``auth_version``, ``atualizado_em``) and are
    indistinguishable by digest.  Throttle windows, import previews, upload
    intents, worker status, cloud accounts, backup settings and schema metadata
    are machine state and are never included.

    Known derived writes stay INCLUDED in the fingerprint.  Two of them -- and only
    these, a fixed list reviewed with the SPEC (``DERIVED_WRITE_CLASSES``) -- may be
    classified as derived by ``classify``, row by row, against the LIVE row:

    * ``REQUISICOES_AUTO_REJECTION``: an overdue returned request that an
      administrator's dashboard view turned into a rejection.  Exactly the columns
      ``status`` and ``observacao``; the reference status was ``Devolvida``, the
      current one is ``Indeferida``, and the current note is the reference note
      with the automatic marker appended (the workstation derives the same
      transition from dates and configuration, so rolling back loses nothing);
    * ``REQUISICOES_STUDENT_SEEN``: exactly ``aluno_update_seen_at``, from empty
      to a time (the student's "seen" mark).

    Anything else -- another table or column, an added or removed row, a value the
    verification does not reproduce, the credential-version bump of a password
    re-hash (indistinguishable from a real password change) -- is not derived.

OUTPUT
    Table and column names, counts and digests only; never a row value.  The
    snapshot file holds a short digest per cell: a low-entropy column (a status,
    an e-mail, a registration number) is guessable by dictionary, so the file is
    personal data and stays in the encrypted custody directory.

Commands: ``snapshot --out FILE`` (source: ``DATABASE_URL``) and
``compare --reference FILE --current FILE``.  ``classify`` is the ledger's (the rollback
from the opening takes the current fingerprint itself, live, and never trusts a file).  Exit codes: 0 done / identical,
1 changed or refused, 2 usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import pg_migrate_from_sqlite as pathb  # noqa: E402
from app import pg_schema  # noqa: E402

FORMAT = 2
# Business tables whose rows change without a business write.
EXCLUDED_BUSINESS_TABLES = frozenset({"storage_objects", "requisicao_alerta_receipts"})
# Columns rewritten by the system with no change of meaning.
EXCLUDED_COLUMNS = {"usuarios": frozenset({"senha"})}
#: The ONLY writes a rollback from the opening may treat as derived (reviewed with the SPEC, A15).
DERIVED_WRITE_CLASSES = {
    "REQUISICOES_AUTO_REJECTION": ("requisicoes", frozenset({"status", "observacao"})),
    "REQUISICOES_STUDENT_SEEN": ("requisicoes", frozenset({"aluno_update_seen_at"})),
}
_AUTO_REJECTION_MARKER = re.compile(
    r"\[Indeferida automaticamente: prazo de adequa\u00e7\u00e3o de [0-9]{1,4} dias expirado\.\]\Z"
)


class Refused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def business_tables() -> list[str]:
    return sorted(
        table
        for table, policy in pathb.SOURCE_TABLE_POLICIES.items()
        if policy.policy == pathb.MIGRATE_EXACT
        and table in pg_schema.PG_SCHEMA_TABLES
        and table not in EXCLUDED_BUSINESS_TABLES
    )


def _digest_of(tables: dict) -> str:
    payload = json.dumps(tables, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _short(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:10]


def _table_entry(table: str, rows) -> dict:
    columns = pathb._columns(table)
    ignored = EXCLUDED_COLUMNS.get(table, frozenset())
    keep = [index for index, name in enumerate(columns) if name not in ignored]
    normalized = pathb.normalize_rows(table, rows)
    comparable = {
        key: tuple(value if index in keep else None for index, value in enumerate(values))
        for key, values in normalized.items()
    }
    return {
        "rows": len(normalized),
        "sha256": pathb.table_digest(table, comparable),
        "columns": [columns[index] for index in keep],
        "row_hashes": {
            "|".join(str(part) for part in key): [_short(values[index]) for index in keep]
            for key, values in normalized.items()
        },
    }


def _read(conn) -> tuple[dict, dict]:
    """Fingerprint entries and the raw rows they were made from, inside the caller's snapshot."""
    raw = {table: pathb.read_target_rows(conn, table) for table in business_tables()}
    return {table: _table_entry(table, rows) for table, rows in raw.items()}, raw


def snapshot(conn) -> dict:
    """The fingerprint of the connected database, from one read-only snapshot."""
    conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
    try:
        tables, _raw = _read(conn)
    finally:
        try:
            conn.execute("ROLLBACK")
        except Exception:  # pragma: no cover - a broken connection ends the transaction anyway
            pass
    return {"format": FORMAT, "tables": tables, "fingerprint_sha256": _digest_of(tables)}


def _column_hash(table: str, row: tuple, column: str, value) -> str:
    """The short hash a row would carry for ``column`` holding ``value`` (the fingerprint's normalization)."""
    columns = pathb._columns(table)
    candidate = list(row)
    candidate[columns.index(column)] = value
    normalized = next(iter(pathb.normalize_rows(table, [tuple(candidate)]).values()))
    return _short(normalized[columns.index(column)])


def _verify_auto_rejection(row: tuple, before: dict, columns: list) -> bool:
    table = "requisicoes"
    current = dict(zip(columns, row))
    if current["status"] != "Indeferida" or before["status"] != _column_hash(table, row, "status", "Devolvida"):
        return False
    note = current["observacao"]
    if not isinstance(note, str) or not _AUTO_REJECTION_MARKER.search(note):
        return False
    marker = _AUTO_REJECTION_MARKER.search(note).group(0)
    if note == marker:  # the reference note was empty
        return before["observacao"] in {_column_hash(table, row, "observacao", None),
                                        _column_hash(table, row, "observacao", "")}
    prefix = note[: -len(marker)]
    if not prefix.endswith("\n"):
        return False
    return before["observacao"] == _column_hash(table, row, "observacao", prefix[:-1])


def _verify_student_seen(row: tuple, before: dict, columns: list) -> bool:
    current = dict(zip(columns, row))
    return current["aluno_update_seen_at"] is not None and \
        before["aluno_update_seen_at"] == _column_hash("requisicoes", row, "aluno_update_seen_at", None)


_VERIFIERS = {
    "REQUISICOES_AUTO_REJECTION": _verify_auto_rejection,
    "REQUISICOES_STUDENT_SEEN": _verify_student_seen,
}


def _classes_for(changed: frozenset) -> list[str] | None:
    """The derived classes whose column sets, together, are EXACTLY ``changed`` (None when none do)."""
    from itertools import combinations

    names = sorted(DERIVED_WRITE_CLASSES)
    for size in range(1, len(names) + 1):
        for combo in combinations(names, size):
            union = frozenset().union(*(DERIVED_WRITE_CLASSES[name][1] for name in combo))
            if union == changed and len({DERIVED_WRITE_CLASSES[name][0] for name in combo}) == 1:
                return list(combo)
    return None


def _classify(reference_tables: dict, current_tables: dict, raw: dict) -> dict:
    """Identical, every change verified as a fixed derived class, or the first reason it is not."""
    derived: set[str] = set()
    changed_tables = sorted(name for name in set(reference_tables) | set(current_tables)
                            if reference_tables.get(name) != current_tables.get(name))
    if not changed_tables:
        return {"identical": True, "derived_classes": [], "refusal": None, "changed_tables": []}

    def refused(code):
        return {"identical": False, "derived_classes": [], "refusal": code,
                "changed_tables": [name.upper() for name in changed_tables]}

    allowed_tables = {table for table, _columns in DERIVED_WRITE_CLASSES.values()}
    for table in changed_tables:
        before, after = reference_tables.get(table), current_tables.get(table)
        if table not in allowed_tables or not before or not after:
            return refused("NOT_A_DERIVED_TABLE")
        if before["columns"] != after["columns"]:
            return refused("SHAPE_CHANGED")
        old, new = before["row_hashes"], after["row_hashes"]
        if set(old) != set(new):
            return refused("ROWS_ADDED_OR_REMOVED")
        columns = pathb._columns(table)
        live = {}
        for record in raw[table]:
            values = tuple(record)
            normalized_key = next(iter(pathb.normalize_rows(table, [values])))
            live["|".join(str(part) for part in normalized_key)] = values
        for key in sorted(old):
            if old[key] == new[key]:
                continue
            changed = frozenset(name for name, left, right in zip(after["columns"], old[key], new[key]) if left != right)
            classes = _classes_for(changed)
            if classes is None:
                return refused("COLUMNS_NOT_DERIVED")
            row = live.get(key)
            if row is None:
                return refused("ROW_NOT_READ")
            before_hashes = dict(zip(before["columns"], old[key]))
            for name in classes:
                if not _VERIFIERS[name](row, before_hashes, columns):
                    return refused("DERIVED_VALUE_NOT_REPRODUCED")
            derived.update(classes)
    return {"identical": False, "derived_classes": sorted(derived), "refusal": None,
            "changed_tables": [name.upper() for name in changed_tables]}


def classify(conn, reference: dict) -> dict:
    """Take the CURRENT fingerprint live and classify every difference from ``reference``.

    One REPEATABLE READ READ ONLY transaction: the current fingerprint and the rows the derived
    classes are verified against are the same snapshot.  Returns ``current`` (a fingerprint),
    ``identical``, ``derived_classes`` and ``refusal`` (None, or why the difference is not derived).
    """
    reference = validate(reference)
    conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
    try:
        tables, raw = _read(conn)
    finally:
        try:
            conn.execute("ROLLBACK")
        except Exception:  # pragma: no cover
            pass
    verdict = _classify(reference["tables"], tables, raw)
    verdict["current"] = {"format": FORMAT, "tables": tables, "fingerprint_sha256": _digest_of(tables)}
    return verdict


def database_identity_sha256(conn) -> str:
    """Which database this is, as a digest: the server's system identifier when readable, else its address.

    Read on an autocommit connection (``tools.pg_backup.connect``).  The reference and every later
    observation must come from the same database, not from a copy of it.
    """
    from tools import pg_backup

    identity = pg_backup.database_identity(conn)
    basis = [identity.database, identity.user, identity.system_identifier or f"{identity.host}:{identity.port}"]
    return hashlib.sha256(json.dumps(basis).encode("utf-8")).hexdigest()


def validate(fingerprint) -> dict:
    ok = (
        isinstance(fingerprint, dict) and fingerprint.get("format") == FORMAT
        and isinstance(fingerprint.get("tables"), dict)
        and fingerprint.get("fingerprint_sha256") == _digest_of(fingerprint["tables"])
    )
    if not ok:
        raise Refused("FINGERPRINT_INVALID")
    return fingerprint


def compare(reference: dict, current: dict) -> dict:
    """Tables (and columns) whose rows differ; a table missing on one side counts as changed.

    ``detail`` is per table: counts of rows before and after, rows added, removed and changed, and
    the names of the columns in which a common row changed -- schema identifiers, never a value.
    """
    reference, current = validate(reference)["tables"], validate(current)["tables"]
    detail: dict[str, dict] = {}
    for name in sorted(set(reference) | set(current)):
        before, after = reference.get(name), current.get(name)
        if before == after:
            continue
        entry = {
            "rows_before": before["rows"] if before else None,
            "rows_after": after["rows"] if after else None,
            "added": 0, "removed": 0, "changed": 0, "changed_columns": [],
        }
        if before and after:
            old, new = before["row_hashes"], after["row_hashes"]
            entry["added"] = len(set(new) - set(old))
            entry["removed"] = len(set(old) - set(new))
            changed_columns: set[str] = set()
            for key in set(old) & set(new):
                if old[key] != new[key]:
                    entry["changed"] += 1
                    changed_columns.update(
                        column for column, left, right in zip(after["columns"], old[key], new[key]) if left != right
                    )
            entry["changed_columns"] = sorted(changed_columns)
        detail[name.upper()] = entry
    return {"identical": not detail, "changed_tables": sorted(detail), "detail": detail}


def _load(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Refused("FINGERPRINT_UNREADABLE") from None


def main(argv=None, *, out=None, err=None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    parser = argparse.ArgumentParser(prog="pg_fingerprint", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    snap = commands.add_parser("snapshot", allow_abbrev=False)
    snap.add_argument("--out", required=True, help="a new JSON file outside the repository")
    cmp_ = commands.add_parser("compare", allow_abbrev=False)
    cmp_.add_argument("--reference", required=True)
    cmp_.add_argument("--current", required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    try:
        if args.command == "snapshot":
            from tools import pg_backup

            target = Path(args.out)
            resolved = target.resolve()
            if resolved == REPO_ROOT.resolve() or REPO_ROOT.resolve() in resolved.parents:
                raise Refused("OUTPUT_INSIDE_REPOSITORY")
            if target.exists():
                raise Refused("OUTPUT_EXISTS")
            try:
                url = pg_backup.require_url(None, "DATABASE_URL")
            except pg_backup.BackupToolError as exc:
                raise Refused(exc.code) from None
            conn = pg_backup.connect(url)
            try:
                result = snapshot(conn)
            except pg_schema.PostgresSchemaError:
                raise Refused("SCHEMA_NOT_CURRENT") from None
            finally:
                conn.close()
            result["taken_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            target.write_text(json.dumps(result, sort_keys=True), encoding="ascii", newline="\n")
            json.dump({"tables": len(result["tables"]), "fingerprint_sha256": result["fingerprint_sha256"]}, out)
            out.write("\n")
            return 0
        verdict = compare(_load(args.reference), _load(args.current))
        json.dump(verdict, out, sort_keys=True)
        out.write("\n")
        return 0 if verdict["identical"] else 1
    except Refused as refusal:
        err.write(f"pg-fingerprint: refused: {refusal.code}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
