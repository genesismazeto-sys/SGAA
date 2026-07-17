# REF-0C-B1-P0 — admin access-context transaction hygiene

Status: implemented and locally validated; pending ChatGPT supervisor review.

## Root cause and ownership

`_get_current_admin_access_context()` obtains the request-scoped connection from
`get_db_connection()` and calls `_load_admin_access_context()`.  That loader
calls `ensure_usuario_access_schema()` before reading `usuarios` and
`usuarios_permissoes_acesso`.

The exact transaction-opening statements are the helper's idempotent DML:

- `INSERT OR IGNORE INTO configuracoes_acesso ...` (five times); and
- the three `UPDATE usuarios SET nivel_acesso = ...` normalization statements.

With Python's SQLite connection defaults, those statements begin a write
transaction even if they make no row change.  The shared Flask connection is
kept in `g.db` for the request and is only closed at app-context teardown.  A
read of the authorization context could therefore leave the request connection
in a write transaction.  The newly mapped `admin_matriz_nova_atividade` route
then reaches its lazy `ensure_atividades_schema_current()` rebuild: SQLite
cannot change `PRAGMA foreign_keys` inside that transaction, so the subsequent
`DROP TABLE atividades` can fail its foreign-key checks and the outstanding
writer can also cause a lock.

`ensure_usuario_access_schema()` is used outside the authorization gate by
bootstrap/init code and normal write flows (user creation, access management,
profile and CSRF test setup).  It cannot assume it owns the connection's outer
transaction.  Other Flask hooks may also already have used `g.db`; the global
authorization gate has no proof that it owns any transaction it observes.

## Correction

The helper now creates a named SQLite savepoint before the implementation and
releases it on success.  If the helper fails, it rolls back only to that
savepoint, releases it, and propagates the error.

- On a clean connection, `RELEASE SAVEPOINT` finishes the helper-owned unit,
  making required access-schema/bootstrap work durable and leaving
  `conn.in_transaction == False`.
- Inside a caller-owned transaction, releasing the nested savepoint does not
  commit or roll back the outer transaction.  The caller still owns its final
  commit or rollback.

The former blanket `conn.rollback()` in
`enforce_admin_access_control()` was removed.  It was rejected because it could
roll back work performed by an earlier hook or other request participant and it
would discard required helper changes on a first-use database.  The gate now
only evaluates authorization; transaction completion happens at the source,
where ownership is knowable.

## Focused proof

`tests/test_ref_0c_b1_p0_access_context_transactions.py` uses only temporary
databases and proves:

1. a clean access-schema/access-context call leaves no transaction open;
2. access-schema tables, default rows, and `usuarios.nivel_acesso` persist
   after reopening the database;
3. a caller transaction remains active, is neither committed nor rolled back,
   and remains invisible to an observer until its owner decides otherwise;
4. repeated context loads are idempotent and transaction-neutral;
5. the RBAC gate reaches a real lazy `atividades` schema rebuild with no open
   request transaction, no lock, and no foreign-key DDL failure; and
6. mapped-route allow/deny results remain unchanged.

Focused result: `5 passed`.

No schema design, migration, dependency, real database, UI, or authorization
policy change is included in this prerequisite correction.
