# coding: utf-8
"""Broad real-PostgreSQL route smoke: representative Flask routes end to end.

Runs only when ``SGAA_PG_TEST_URL`` supplies a local PostgreSQL role with
CREATE DATABASE; otherwise the whole module skips (REAL-PG EVIDENCE: ABSENT).
The URL is server access only: nothing is ever written into the database it
names.  The module creates ONE disposable database under a random per-run
prefix, provisions it through ``app.pg_schema.provision_pg_schema``, points
``app.db.DATABASE_URL`` at it for the module, and drops it at teardown with the
accepted guard model (protected names, run prefix, created-by-this-run, owned
by the connected role, plain DROP first and FORCE only on ObjectInUse).

This is a smoke lane, not route coverage.  Each node crosses a distinct
integration boundary through the real ``main.app`` request path:

* R1 app startup + ``/health`` (which runs ``SELECT 1`` on ``g.db``);
* R2 the production ``POST /login`` (real hash, credential, auth_version);
* R3 ``/admin/acesso`` list, ``q`` search and ``s``/``dir`` ordering;
* R4 access save: M9 (E-PG1) already qualifies ``/admin/acesso/salvar`` on real
  PG, so only one authenticated CREATE happy path is repeated here;
* R5 ``/admin/atividades`` list, ``nome`` filter and ``s``/``dir`` ordering;
* R6 ``POST /admin/catalogo-versoes/<base>/nova-versao``;
* R7 ``POST /admin/catalogo-versoes/<base>/versoes/<v>/excluir``;
* R8 ``GET /admin/banco-dados`` and ``POST /admin/banco-dados/backup`` refusal.

No production owner is monkeypatched.  Two passive probes are installed:
``sqlite3.connect`` is a tripwire that records (and refuses) any SQLite
connection opened while a smoke request runs, and Flask's ``request_finished``
signal records which connection type and PostgreSQL database served ``g.db``.
Every mutation is confirmed by an independent autocommit psycopg observer
after the HTTP request completes; no commit is inferred from a 302 or a flash.

The fixture bootstrap rows (admin user, distinguishable users, activity bases
and versions) are qualification seed only.  They do NOT close R5: a freshly
provisioned database has zero application rows (asserted by the first node).
"""
from __future__ import annotations

import os
import secrets
import sqlite3
import traceback
from urllib.parse import urlsplit, urlunsplit

import pytest

PG_URL = os.environ.get("SGAA_PG_TEST_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT",
)

psycopg = pytest.importorskip("psycopg")

from app import db as app_db  # noqa: E402
from app import pg_schema  # noqa: E402

#: Every database this run creates carries this prefix (random per run).
RUN_PREFIX = f"sgaa_rsmk_test_{secrets.token_hex(4)}_"
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1", "sgaa_qual"})
CONNECT_TIMEOUT_SECONDS = 10

ADMIN_EMAIL = "rsmk.admin@example.test"
ADMIN_PASSWORD = "rsmk-senha-admin"
ACCESS_MARKER = "Rsmkq"
ACCESS_USERS = (
    # (nome, email): names sort Alfa < Bravo < Charlie, emails sort the other way.
    ("Rsmkq Charlie", "rsmk.a-charlie@example.test"),
    ("Rsmkq Alfa", "rsmk.c-alfa@example.test"),
    ("Rsmkq Bravo", "rsmk.b-bravo@example.test"),
)
OUTSIDER = ("Fora Do Filtro", "rsmk.fora@example.test")
ACTIVITY_MARKER = "RSMK Atividade"
ACTIVITY_NAMES = ("RSMK Atividade Charlie", "RSMK Atividade Alfa", "RSMK Atividade Bravo")
ACTIVITY_OUTSIDER = "RSMK Outra Coisa"
GRUPO = "1 - RSMK"

BACKUP_REFUSAL_MESSAGE = (
    "Backup e restauração do banco por arquivo SQLite não estão disponíveis: "
    "o banco de dados configurado é PostgreSQL."
)
DB_ADMIN_PG_NOTICE = "O banco de dados configurado é PostgreSQL"


def _database_url(database):
    parts = urlsplit(PG_URL)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            "/" + database,
            f"connect_timeout={CONNECT_TIMEOUT_SECONDS}",
            "",
        )
    )


def _raw_connect(url, *, autocommit=False):
    return psycopg.connect(
        url,
        prepare_threshold=None,
        autocommit=autocommit,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
    )


class _RunDatabaseRegistry:
    """Sole creator and destroyer of this run's disposable databases."""

    def __init__(self):
        self._admin = None
        self._owned = set()

    def admin(self):
        if self._admin is None or self._admin.closed:
            self._admin = _raw_connect(PG_URL, autocommit=True)
        return self._admin

    def create(self, label):
        database = f"{RUN_PREFIX}{label}_{secrets.token_hex(4)}"
        self.admin().execute(f'CREATE DATABASE "{database}"')
        self._owned.add(database)
        return database, _database_url(database)

    def drop(self, database):
        if database in PROTECTED_DATABASES or not database.startswith(RUN_PREFIX):
            raise AssertionError(f"refusing to drop {database!r}: not run-owned")
        if database not in self._owned:
            raise AssertionError(f"refusing to drop {database!r}: not created by this run")
        row = self.admin().execute(
            "SELECT pg_get_userbyid(datdba) = current_user FROM pg_database "
            "WHERE datname = %s",
            (database,),
        ).fetchone()
        if row is not None and not row[0]:
            raise AssertionError(f"refusing to drop {database!r}: not owned by this role")
        # Plain DROP first (autovacuum workers exit on their own); FORCE only
        # for a leftover run connection, which a non-superuser may terminate.
        try:
            self.admin().execute(f'DROP DATABASE IF EXISTS "{database}"')
        except psycopg.errors.ObjectInUse:
            self.admin().execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        self._owned.discard(database)

    def leftovers(self):
        rows = self.admin().execute(
            "SELECT datname FROM pg_database WHERE starts_with(datname, %s)",
            (RUN_PREFIX,),
        ).fetchall()
        return sorted(row[0] for row in rows)

    def close(self):
        failures = []
        for database in sorted(self._owned):
            try:
                self.drop(database)
            except Exception as exc:  # pragma: no cover - teardown reporting
                failures.append((database, repr(exc)))
        leftovers = self.leftovers() if not failures else []
        if self._admin is not None and not self._admin.closed:
            self._admin.close()
        assert not failures, f"could not drop run-owned databases: {failures!r}"
        assert not leftovers, f"run-owned databases left behind: {leftovers!r}"


def _public_table_counts(connection):
    tables = [
        row[0]
        for row in connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        ).fetchall()
    ]
    return {
        table: connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        for table in tables
    }


# ---------------------------------------------------------------------------
# environment: one disposable database, the fixture bootstrap, real login
# ---------------------------------------------------------------------------


class _Env:
    pass


def _seed_activity_base(observer, nome, limits):
    """Fixture-only raw seed: one base with a chained v1..vN version set."""
    base_id = observer.execute(
        "INSERT INTO atividade_base(nome_conceito, status) VALUES (%s, 'ativo') RETURNING id",
        (nome,),
    ).fetchone()[0]
    ids = []
    for number, limite_total in enumerate(limits, start=1):
        ids.append(
            observer.execute(
                "INSERT INTO atividade_versao(atividade_base_id, eixo, grupo, limite_total, "
                "numero_versao, status, versao_anterior_id) "
                "VALUES (%s, 'AAC', %s, %s, %s, 'ativa', %s) RETURNING id",
                (base_id, GRUPO, limite_total, number, ids[-1] if ids else None),
            ).fetchone()[0]
        )
    return int(base_id), [int(i) for i in ids]


@pytest.fixture(scope="module")
def env():
    import flask
    import main
    from app.security.passwords import hash_password
    from app.user_accounts import create_usuario_with_access_level

    registry = _RunDatabaseRegistry()
    patcher = pytest.MonkeyPatch()
    observer = None
    try:
        try:
            registry.admin()
        except psycopg.Error as exc:
            pytest.skip(f"SGAA_PG_TEST_URL is not a usable PostgreSQL connection: {exc}")
        database, url = registry.create("route")
        connection = _raw_connect(url)
        try:
            result = pg_schema.provision_pg_schema(connection)
            connection.commit()
        finally:
            connection.close()
        assert result["status"] == "provisioned"

        observer = _raw_connect(url, autocommit=True)
        e = _Env()
        e.database = database
        e.url = url
        e.observer = observer
        # R5 observation: what the provisioning owner leaves in the database.
        e.fresh_counts = _public_table_counts(observer)

        # Test configuration only: the canonical backend authority now resolves
        # to the disposable PostgreSQL database for every request of the module.
        patcher.setattr(app_db, "DATABASE_URL", url)
        patcher.setitem(main.app.config, "TESTING", True)
        assert app_db.database_backend() == "postgres"

        # Fixture bootstrap through the production account owner (real
        # PBKDF2 hash, credential row, auth_version).
        production = app_db._connect_postgres()
        try:
            e.user_ids = {}
            for nome, email, password in (
                ("RSMK Admin", ADMIN_EMAIL, ADMIN_PASSWORD),
                *((nome, email, None) for nome, email in ACCESS_USERS),
                (*OUTSIDER, None),
            ):
                cursor = create_usuario_with_access_level(
                    production,
                    nome,
                    email,
                    hash_password(password or secrets.token_hex(8)),
                    "admin",
                    "admin_total",
                    credential_state="personal",
                )
                e.user_ids[email] = int(cursor.usuario_id)
            production.commit()
        finally:
            production.close()

        # Fixture bootstrap with raw SQL: no runtime owner creates catalog rows
        # outside the activity form, which is not under test here.
        e.list_bases = {
            nome: _seed_activity_base(observer, nome, [40])
            for nome in (*ACTIVITY_NAMES, ACTIVITY_OUTSIDER)
        }
        e.mutation_base = _seed_activity_base(observer, "RSMK Mutacao", [40])
        e.delete_base = _seed_activity_base(observer, "RSMK Exclusao", [10, 20, 30])

        # Passive probes (no production owner replaced).
        e.sqlite_calls = []
        e.served = []
        real_sqlite_connect = sqlite3.connect

        def _sqlite_tripwire(*args, **kwargs):
            # MP-3 A19: the only SQLite files a PostgreSQL request opens are the "Gerar backup agora"
            # snapshot it creates in scratch (app.backup.pg_snapshot) and the snapshot it restores from
            # scratch (app.backup.pg_restore); never the application database.
            if args and os.path.basename(str(args[0])).startswith(("sgaa-pg-snapshot-", "sgaa-pg-restore")):
                return real_sqlite_connect(*args, **kwargs)
            if flask.has_request_context():
                e.sqlite_calls.append(
                    (flask.request.path, repr(args[:1]), "".join(traceback.format_stack(limit=8)))
                )
                raise AssertionError("SQLite connection opened during a real-PG smoke request")
            return real_sqlite_connect(*args, **kwargs)

        patcher.setattr(sqlite3, "connect", _sqlite_tripwire)

        def _record_served(sender, response, **_extra):
            db = flask.g.get("db")
            dbname = None
            if db is not None and hasattr(db, "raw_connection"):
                dbname = db.raw_connection.info.dbname
            e.served.append((flask.request.path, type(db).__name__, dbname))

        flask.request_finished.connect(_record_served, main.app)
        e.app = main.app
        try:
            yield e
        finally:
            flask.request_finished.disconnect(_record_served, main.app)
            with main.app.app_context():
                app_db.close_db_connection(None)
    finally:
        patcher.undo()
        if observer is not None and not observer.closed:
            observer.close()
        registry.close()


def _login(app, email, password):
    client = app.test_client()
    response = client.post("/login", data={"email": email, "senha": password})
    return client, response


def _pop_flashes(client):
    with client.session_transaction() as session:
        return list(session.pop("_flashes", []))


@pytest.fixture(scope="module")
def admin_client(env):
    """A client authenticated through the real production login route."""
    client, response = _login(env.app, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert response.status_code == 302, response.status_code
    _pop_flashes(client)
    return client


@pytest.fixture(autouse=True)
def _purity(request):
    """Every smoke request is served by g.db on the disposable PG database."""
    if "env" not in request.fixturenames:
        yield
        return
    e = request.getfixturevalue("env")
    start = len(e.served)
    yield
    assert e.sqlite_calls == [], e.sqlite_calls
    served = e.served[start:]
    for path, kind, dbname in served:
        if kind == "NoneType":
            continue  # a request that never opened g.db (e.g. a refusal)
        assert kind == "_PostgresConnectionAdapter", (path, kind)
        assert dbname == e.database, (path, dbname)


def _access_row_order(text, emails):
    """Row order of the access table (the page also embeds an id-ordered JSON
    payload before the table, so bare e-mails are not row markers)."""
    order = _position_order(text, [f'data-user-email="{email}"' for email in emails])
    return [marker.split('"')[1] for marker in order]


def _position_order(text, markers):
    positions = {marker: text.find(marker) for marker in markers}
    missing = [marker for marker, index in positions.items() if index < 0]
    assert not missing, f"markers missing from response: {missing}"
    return [marker for marker, _index in sorted(positions.items(), key=lambda item: item[1])]


# ===========================================================================
# R0 -- fresh provisioned database state (R5 observation)
# ===========================================================================


def test_r0_fresh_provisioned_database_has_no_application_rows(env):
    assert env.fresh_counts, "provisioning created no public tables"
    # Provisioning writes only its own schema metadata (the schema stamp and
    # the applied-migration ledger); every application table starts empty.
    schema_metadata = {"pg_schema_meta", "schema_migrations"}
    assert env.fresh_counts["pg_schema_meta"] == 1
    assert env.fresh_counts["schema_migrations"] >= 1
    non_empty = {
        table: count
        for table, count in env.fresh_counts.items()
        if count and table not in schema_metadata
    }
    # No admin, no access defaults, no settings rows, no grupos_def and no
    # catalog rows.
    assert non_empty == {}, non_empty
    for table in (
        "usuarios",
        "usuario_credenciais",
        "configuracoes_acesso",
        "configuracoes_app",
        "configuracoes_backup",
        "grupos_def",
        "atividade_base",
        "atividade_versao",
    ):
        assert table in env.fresh_counts, table


# ===========================================================================
# R1 -- app startup + health
# ===========================================================================


def test_r1_health_runs_select_on_postgresql(env):
    assert app_db.database_backend() == "postgres"
    client = env.app.test_client()
    start = len(env.served)
    response = client.get("/health")
    assert response.status_code == 200, response.data
    assert response.get_json() == {"status": "ok"}
    # /health executes SELECT 1 through get_db_connection(): it must have been
    # served by the PostgreSQL adapter on the disposable database.
    assert env.served[start:] == [("/health", "_PostgresConnectionAdapter", env.database)]


# ===========================================================================
# R2 -- real login
# ===========================================================================


def test_r2_login_success_establishes_session_and_unlocks_admin(env):
    client, response = _login(env.app, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert response.status_code == 302, response.status_code
    assert urlsplit(response.headers["Location"]).path == "/admin/dashboard"
    auth_version = env.observer.execute(
        "SELECT auth_version FROM usuario_credenciais WHERE usuario_id = %s",
        (env.user_ids[ADMIN_EMAIL],),
    ).fetchone()[0]
    with client.session_transaction() as session:
        assert session["user_id"] == env.user_ids[ADMIN_EMAIL]
        assert session["user_type"] == "admin"
        assert session["access_level"] == "admin_total"
        assert session["auth_version"] == int(auth_version)
    protected = client.get("/admin/acesso")
    assert protected.status_code == 200
    assert ADMIN_EMAIL in protected.get_data(as_text=True)


def test_r2_login_wrong_password_does_not_authenticate(env):
    client, response = _login(env.app, ADMIN_EMAIL, "senha-errada")
    assert response.status_code == 200
    assert "E-mail ou senha inválidos." in response.get_data(as_text=True)
    with client.session_transaction() as session:
        assert "user_id" not in session
    protected = client.get("/admin/acesso")
    assert protected.status_code == 302
    assert urlsplit(protected.headers["Location"]).path != "/admin/acesso"


# ===========================================================================
# R3 -- access admin list / search / order
# ===========================================================================


def test_r3_access_list_search_and_order(env, admin_client):
    plain = admin_client.get("/admin/acesso")
    assert plain.status_code == 200
    plain_text = plain.get_data(as_text=True)
    for _nome, email in (*ACCESS_USERS, OUTSIDER):
        assert email in plain_text

    emails = [email for _nome, email in ACCESS_USERS]
    by_name = admin_client.get(f"/admin/acesso?q={ACCESS_MARKER.lower()}&s=nome&dir=asc")
    assert by_name.status_code == 200
    text = by_name.get_data(as_text=True)
    assert OUTSIDER[1] not in text and ADMIN_EMAIL not in text
    # Alfa, Bravo, Charlie by human-text name order.
    assert _access_row_order(text, emails) == [
        "rsmk.c-alfa@example.test",
        "rsmk.b-bravo@example.test",
        "rsmk.a-charlie@example.test",
    ]

    by_email_desc = admin_client.get(f"/admin/acesso?q={ACCESS_MARKER}&s=email&dir=desc")
    assert by_email_desc.status_code == 200
    text = by_email_desc.get_data(as_text=True)
    assert OUTSIDER[1] not in text
    assert _access_row_order(text, emails) == [
        "rsmk.c-alfa@example.test",
        "rsmk.b-bravo@example.test",
        "rsmk.a-charlie@example.test",
    ]
    by_email_asc = admin_client.get(f"/admin/acesso?q={ACCESS_MARKER}&s=email&dir=asc")
    assert _access_row_order(by_email_asc.get_data(as_text=True), emails) == [
        "rsmk.a-charlie@example.test",
        "rsmk.b-bravo@example.test",
        "rsmk.c-alfa@example.test",
    ]


# ===========================================================================
# R4 -- access save: one CREATE happy path (M9 owns the uniqueness matrix)
# ===========================================================================


def test_r4_access_save_create_commits(env, admin_client):
    email = "rsmk.novo@example.test"
    before = env.observer.execute("SELECT count(*) FROM usuarios").fetchone()[0]
    response = admin_client.post(
        "/admin/acesso/salvar",
        data={"nome": "RSMK Novo", "email": email, "nivel_acesso": "admin_total", "senha": ""},
    )
    assert response.status_code == 302
    flashes = _pop_flashes(admin_client)
    assert ("success", "Acesso salvo com sucesso.") in flashes, flashes
    rows = env.observer.execute(
        "SELECT u.nome, u.nivel_acesso, c.usuario_id IS NOT NULL FROM usuarios u "
        "LEFT JOIN usuario_credenciais c ON c.usuario_id = u.id WHERE u.email = %s",
        (email,),
    ).fetchall()
    assert [tuple(row) for row in rows] == [("RSMK Novo", "admin_total", True)]
    assert env.observer.execute("SELECT count(*) FROM usuarios").fetchone()[0] == before + 1


# ===========================================================================
# R5 -- activities admin list / search / order
# ===========================================================================


def test_r5_activity_list_filter_and_order(env, admin_client):
    plain = admin_client.get("/admin/atividades")
    assert plain.status_code == 200
    plain_text = plain.get_data(as_text=True)
    for nome in (*ACTIVITY_NAMES, ACTIVITY_OUTSIDER, "RSMK Mutacao", "RSMK Exclusao"):
        assert nome in plain_text, nome

    asc = admin_client.get(f"/admin/atividades?nome={ACTIVITY_MARKER}&s=nome&dir=asc")
    assert asc.status_code == 200
    text = asc.get_data(as_text=True)
    assert ACTIVITY_OUTSIDER not in text and "RSMK Mutacao" not in text
    assert _position_order(text, ACTIVITY_NAMES) == [
        "RSMK Atividade Alfa",
        "RSMK Atividade Bravo",
        "RSMK Atividade Charlie",
    ]

    desc = admin_client.get(f"/admin/atividades?nome={ACTIVITY_MARKER.lower()}&s=nome&dir=desc")
    assert desc.status_code == 200
    text = desc.get_data(as_text=True)
    assert ACTIVITY_OUTSIDER not in text
    assert _position_order(text, ACTIVITY_NAMES) == [
        "RSMK Atividade Charlie",
        "RSMK Atividade Bravo",
        "RSMK Atividade Alfa",
    ]


# ===========================================================================
# R6 -- activity version creation through the route
# ===========================================================================


def _versions(env, base_id):
    return [
        tuple(row)
        for row in env.observer.execute(
            "SELECT id, numero_versao, versao_anterior_id, status, limite_total "
            "FROM atividade_versao WHERE atividade_base_id = %s ORDER BY numero_versao, id",
            (base_id,),
        ).fetchall()
    ]


def test_r6_new_version_route_commits_next_version(env, admin_client):
    base_id, (v1,) = env.mutation_base
    form_url = f"/admin/catalogo-versoes/{base_id}/nova-versao"
    form = admin_client.get(form_url)
    assert form.status_code == 200
    assert "Nova versão (será v2)" in form.get_data(as_text=True)

    response = admin_client.post(
        form_url,
        data={
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": GRUPO,
            "nome": "RSMK Mutacao",
            "descricao": "",
            "tipo_limitacao": "total",
            "limite_valor": "60",
            "ch_por_evento": "",
            "ch_por_evento_mode": "disabled",
            "observacoes": "",
            "versao_anterior_id": str(v1),
        },
    )
    flashes = _pop_flashes(admin_client)
    assert response.status_code == 302, (response.status_code, flashes)
    assert urlsplit(response.headers["Location"]).path == f"/admin/catalogo-versoes/{base_id}"
    assert ("success", "Versão criada com sucesso em rascunho.") in flashes, flashes

    versions = _versions(env, base_id)
    assert len(versions) == 2, versions
    assert versions[0] == (v1, 1, None, "ativa", 40)
    new_id, number, previous, status, limite = versions[1]
    assert (number, previous, status, float(limite)) == (2, v1, "rascunho", 60.0)
    eixo, grupo = env.observer.execute(
        "SELECT eixo, grupo FROM atividade_versao WHERE id = %s", (new_id,)
    ).fetchone()
    assert (eixo, grupo) == ("AAC", GRUPO)

    detail = admin_client.get(f"/admin/catalogo-versoes/{base_id}")
    assert detail.status_code == 200


# ===========================================================================
# R7 -- activity version deletion through the route
# ===========================================================================


def test_r7_delete_version_route_reanchors_and_renumbers(env, admin_client):
    base_id, (v1, v2, v3) = env.delete_base
    response = admin_client.post(f"/admin/catalogo-versoes/{base_id}/versoes/{v2}/excluir")
    flashes = _pop_flashes(admin_client)
    assert response.status_code == 302, (response.status_code, flashes)
    assert urlsplit(response.headers["Location"]).path == f"/admin/catalogo-versoes/{base_id}"
    assert ("success", "Versão excluída definitivamente com sucesso.") in flashes, flashes

    assert _versions(env, base_id) == [
        (v1, 1, None, "ativa", 10),
        (v3, 2, v1, "ativa", 30),
    ]
    assert env.observer.execute(
        "SELECT count(*) FROM atividade_versao WHERE id = %s", (v2,)
    ).fetchone()[0] == 0


# ===========================================================================
# R8 -- database maintenance under PostgreSQL
# ===========================================================================


def test_r8_database_admin_get_renders_postgresql_state(env, admin_client):
    response = admin_client.get("/admin/banco-dados")
    assert response.status_code == 200
    assert DB_ADMIN_PG_NOTICE in response.get_data(as_text=True)


def test_r8_backup_post_is_refused_without_mutation(env, admin_client):
    before = _public_table_counts(env.observer)
    local_dir = env.app.config["LOCAL_BACKUP_DIR"]
    cloud_dir = env.app.config["CLOUD_BACKUP_DIR"]
    files_before = (sorted(os.listdir(local_dir)), sorted(os.listdir(cloud_dir)))
    start = len(env.served)

    response = admin_client.post("/admin/banco-dados/backup")
    flashes = _pop_flashes(admin_client)
    assert response.status_code == 302, response.status_code
    assert urlsplit(response.headers["Location"]).path == "/admin/banco-dados"
    # MP-3 A19: the PostgreSQL manual backup runs; with no cloud account connected it has nowhere to
    # send the snapshot, says so, and writes nothing.
    assert ("warning", "Nenhuma conta em nuvem está conectada para receber o backup do banco.") in flashes, flashes
    assert not any(category == "success" for category, _message in flashes), flashes

    assert _public_table_counts(env.observer) == before
    assert (sorted(os.listdir(local_dir)), sorted(os.listdir(cloud_dir))) == files_before
    # The only connection the refused request may open is the session
    # auth_version check, and it must be the PostgreSQL adapter.
    assert [kind for _p, kind, _d in env.served[start:]] in (
        ["_PostgresConnectionAdapter"],
        ["NoneType"],
    )

    # The app stays usable afterward.
    assert admin_client.get("/admin/banco-dados").status_code == 200
    assert env.app.test_client().get("/health").get_json() == {"status": "ok"}


def _policy_rows(observer) -> dict:
    return dict(observer.execute(
        "SELECT chave, valor FROM configuracoes_backup WHERE chave IN"
        " ('pg_database_cadence_hours', 'pg_object_cadence_days', 'pg_retention_generations', 'pg_restore_test_days')"
    ).fetchall())


def test_r8_the_administrator_sets_the_postgresql_backup_policy(env, admin_client):
    """MP-3 A19: under PostgreSQL the retention route administers the backup policy the runs apply."""
    from app.backup import pg_posture

    policy = {"pg_database_cadence_hours": "12", "pg_object_cadence_days": "3",
              "pg_retention_generations": "5", "pg_restore_test_days": "14"}
    try:
        before = _public_table_counts(env.observer)
        response = admin_client.post("/admin/banco-dados/retencao", data=policy)
        flashes = _pop_flashes(admin_client)
        assert response.status_code == 302 and urlsplit(response.headers["Location"]).path == "/admin/banco-dados"
        assert any(c == "success" and "Política de retenção atualizada" in m for c, m in flashes), flashes
        assert _policy_rows(env.observer) == policy
        read = pg_posture.read_policy(env.observer)
        assert {k: str(read[k]) for k in policy} == policy and read["configured"] is True
        after = _public_table_counts(env.observer)
        assert {t: n for t, n in after.items() if t != "configuracoes_backup"} == \
            {t: n for t, n in before.items() if t != "configuracoes_backup"}

        page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
        assert "data-protection-policy-form" in page and 'id="pg-retention-form"' in page
        for key, value in policy.items():
            assert f'name="{key}" value="{value}"' in page
        assert "PostgreSQL · 5 gerações" in page and "Gerações registradas" in page
        assert "data-protection-operations" in page and "Nenhuma geração foi registrada ainda." in page

        # an out-of-bounds value is refused and changes nothing
        response = admin_client.post("/admin/banco-dados/retencao", data=dict(policy, pg_retention_generations="1"))
        flashes = _pop_flashes(admin_client)
        assert any(c == "error" and "Valor inválido para as gerações mantidas" in m for c, m in flashes), flashes
        assert _policy_rows(env.observer) == policy
    finally:
        env.observer.execute("DELETE FROM configuracoes_backup WHERE chave IN ('pg_database_cadence_hours', 'pg_object_cadence_days',"
                             " 'pg_retention_generations', 'pg_restore_test_days')")


def test_r8_an_open_cutover_caps_the_database_cadence_at_the_one_it_recorded(env, admin_client):
    import json

    from app import hosting

    identity = hosting.source_identity_sha256(hosting.database_source(env.observer))
    reference = {"type": "reference", "backup_cadence_hours": 6, "rpo_hours": 6, "seq": 45, "prev": "0" * 64,
                 "database_identity_sha256": identity}
    reference["hash"] = hosting.ledger_entry_hash(reference)
    try:
        for statement in hosting.OPENING_DDL:
            env.observer.execute(statement)
        env.observer.execute(hosting.OPENING_INSERT_SQL, (reference["hash"], "7" * 64, json.dumps(reference)))
        policy = {"pg_database_cadence_hours": "12", "pg_object_cadence_days": "7",
                  "pg_retention_generations": "2", "pg_restore_test_days": "30"}
        admin_client.post("/admin/banco-dados/retencao", data=policy)
        flashes = _pop_flashes(admin_client)
        assert any(c == "error" and "não pode passar de 6 h" in m for c, m in flashes), flashes
        assert _policy_rows(env.observer) == {}
        admin_client.post("/admin/banco-dados/retencao", data=dict(policy, pg_database_cadence_hours="6"))
        assert _policy_rows(env.observer)["pg_database_cadence_hours"] == "6"
        page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
        assert "teto registrado na abertura: 6 h" in page and 'max="6"' in page
    finally:
        env.observer.execute("DROP SCHEMA IF EXISTS sgaa_cutover CASCADE")
        env.observer.execute("DELETE FROM configuracoes_backup WHERE chave IN ('pg_database_cadence_hours', 'pg_object_cadence_days',"
                             " 'pg_retention_generations', 'pg_restore_test_days')")



def _backup_now_fakes(monkeypatch, view, cloud_drives, remote, uploads, deleted, *, folder_id="chosen-folder",
                      registers=None, registers_fail=False):
    import sqlite3
    from pathlib import Path

    registers = [] if registers is None else registers

    def upload(conn, provider, *, zip_path, file_name, folder_name, folder_id=None, drive_id=None, replace=True):
        import zipfile

        assert replace is False  # a snapshot never replaces an existing file (A19 R3 rereview R8)

        if file_name.endswith(".zip"):
            if registers_fail:
                raise RuntimeError("upload refused")
            with zipfile.ZipFile(zip_path) as archive:
                assert "alunos.csv" in archive.namelist() and "usuario_credenciais.csv" not in archive.namelist()
            registers.append((provider, file_name, folder_id))
            file_id = "new-csv" if len(registers) == 1 else f"new-csv-{len(registers)}"
            # each run a later stamp (several runs fall in the same second here)
            remote.append({"id": file_id, "name": f"sgaa-registros-202611{len(registers):02d}T000000Z.zip"})
            return {"file_id": file_id, "file_name": file_name, "folder_id": folder_id or "default-folder"}
        lite = sqlite3.connect(zip_path)
        try:
            assert lite.execute("PRAGMA user_version").fetchone()[0] == 16
        finally:
            lite.close()
        uploads.append((provider, Path(zip_path).name, folder_id))
        file_id = "new" if len(uploads) == 1 else f"new-{len(uploads)}"
        remote.append({"id": file_id, "name": f"sgaa-pg-snapshot-202611{len(uploads):02d}T000000Z.db"})
        return {"file_id": file_id, "file_name": file_name, "folder_id": folder_id or "default-folder"}

    def listed(token, folder, prefix):
        assert folder == folder_id  # the folder the snapshot was sent to, by its id
        return [f for f in remote if f["name"].startswith(prefix)]

    monkeypatch.setattr(view, "_get_active_cloud_account",
                        lambda conn, provider: {"account_email": "x@example.invalid"} if provider == "google" else None)
    monkeypatch.setattr(view, "_get_cloud_drive_folder_setting",
                        lambda conn, provider: {"folder_id": folder_id, "drive_id": ""})
    # A20: the send body lives in app.backup.hosted_backup -- its collaborator reads are patched there
    from app.backup import hosted_backup

    monkeypatch.setattr(hosted_backup, "active_cloud_account",
                        lambda conn, provider: {"account_email": "x@example.invalid"} if provider == "google" else None)
    monkeypatch.setattr(hosted_backup, "cloud_drive_folder_setting",
                        lambda conn, provider: {"folder_id": folder_id, "drive_id": ""})
    monkeypatch.setattr(view._cloud_connections, "upload_backup_zip", upload)
    monkeypatch.setattr(view._cloud_connections, "get_authenticated_access_token", lambda conn, provider: ("tok", "x"))
    monkeypatch.setattr(cloud_drives, "google_list_folder_files", listed)
    monkeypatch.setattr(cloud_drives, "google_delete_file", lambda token, file_id: deleted.append(file_id))


def test_r8_gerar_backup_agora_sends_a_verified_snapshot_to_the_chosen_folder(env, admin_client, monkeypatch):
    """MP-3 A19: the snapshot is proven, sent to the folder "Selecionar pasta" chose, pruned there, recorded."""
    from app import cloud_drives
    from app.backup import pg_posture
    from app.views.admin import banco_dados as view

    uploads, deleted = [], []
    remote = [{"id": f"old-{i}", "name": f"sgaa-pg-snapshot-2026100{i}T000000Z.db"} for i in range(1, 5)]
    remote += [{"id": "legacy", "name": "sgaa_backup_legacy.db"}, {"id": "copy", "name": "sgaa-pg-snapshot-copia.db"}]
    remote += [{"id": f"csv-{i}", "name": f"sgaa-registros-2026100{i}T000000Z.zip"} for i in range(1, 4)]
    registers = []
    _backup_now_fakes(monkeypatch, view, cloud_drives, remote, uploads, deleted, registers=registers)
    before = _public_table_counts(env.observer)
    try:
        response = admin_client.post("/admin/banco-dados/backup")
        flashes = _pop_flashes(admin_client)
        assert response.status_code == 302, response.status_code
        assert ("success", "Backup do banco gerado e enviado para Google Drive.") in flashes, flashes
        assert len(uploads) == 1 and uploads[0][1].startswith("sgaa-pg-snapshot-") and uploads[0][2] == "chosen-folder"
        assert len(registers) == 1 and registers[0][1].startswith("sgaa-registros-") and registers[0][2] == "chosen-folder"
        # same-named files this installation never recorded -- another installation's, a person's copy --
        # are never deleted (A19 R3 M4)
        assert deleted == []
        after = _public_table_counts(env.observer)
        assert {t: n for t, n in after.items() if t != "configuracoes_backup"} == \
            {t: n for t, n in before.items() if t != "configuracoes_backup"}
        posture = pg_posture.read(env.observer)
        assert posture["database_status"] == "CURRENT" and posture["recent"][0]["snapshot"] is True
        assert posture["recent"][0]["destinations"] == ["google"]
        page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
        assert "Backup agora" in page and "Gerar backup agora" in page
        # "Baixar snapshot": the original download button, sent to the drive's own download address
        manifest = posture["recent"][0]["manifest"]
        assert posture["recent"][0]["files"] == {"google": "new"}
        assert f'generation={manifest}' in page and 'data-lucide="download"' in page
        monkeypatch.setattr(cloud_drives, "google_download_link",
                            lambda token, file_id: f"https://drive.example.invalid/{file_id}")
        response = admin_client.get(f"/admin/banco-dados/download?generation={manifest}")
        assert response.status_code == 302 and response.headers["Location"] == "https://drive.example.invalid/new"
        assert posture["recent"][0]["exports"] == {"google": "new-csv"} and "kind=registros" in page
        assert 'data-lucide="file-spreadsheet"' in page
        response = admin_client.get(f"/admin/banco-dados/download?generation={manifest}&kind=registros")
        assert response.status_code == 302 and response.headers["Location"] == "https://drive.example.invalid/new-csv"
        response = admin_client.get("/admin/banco-dados/download?generation=" + "0" * 64)
        flashes = _pop_flashes(admin_client)
        assert response.status_code == 302 and ("error", "Snapshot solicitado não está disponível para download.") in flashes
        # retention keeps the policy's 2 of this installation's own files of each kind
        admin_client.post("/admin/banco-dados/backup")
        assert deleted == []
        admin_client.post("/admin/banco-dados/backup")
        _pop_flashes(admin_client)
        assert sorted(deleted) == ["new", "new-csv"]  # this installation's oldest; nobody else's
    finally:
        env.observer.execute("DROP SCHEMA IF EXISTS sgaa_ops CASCADE")


def test_r8_a_registers_copy_that_did_not_reach_a_drive_is_never_reported_as_success(env, admin_client, monkeypatch):
    """A19 R3 N2: the database copy arrived, the CSV did not: a warning that says so."""
    from app import cloud_drives
    from app.backup import pg_posture
    from app.views.admin import banco_dados as view

    uploads, deleted, remote = [], [], []
    _backup_now_fakes(monkeypatch, view, cloud_drives, remote, uploads, deleted, registers_fail=True)
    try:
        admin_client.post("/admin/banco-dados/backup")
        flashes = _pop_flashes(admin_client)
        assert ("warning", "Backup do banco gerado e enviado para Google Drive, mas os registros (CSV) não foram "
                           "enviados para Google Drive.") in flashes, flashes
        assert pg_posture.read(env.observer)["recent"][0]["exports"] == {}
    finally:
        env.observer.execute("DROP SCHEMA IF EXISTS sgaa_ops CASCADE")


def test_r8_recuperar_banco_restores_a_snapshot_after_sending_a_safety_copy(env, admin_client, monkeypatch, tmp_path):
    """MP-3 A19: "Recuperar banco de dados" -- from the drive and from an uploaded file; a bad file changes nothing."""
    import shutil

    from app import cloud_drives
    from app.backup import pg_posture
    from app.views.admin import banco_dados as view

    uploads, deleted, stash = [], [], {}
    remote = []
    _backup_now_fakes(monkeypatch, view, cloud_drives, remote, uploads, deleted)
    wrapped = view._cloud_connections.upload_backup_zip

    def keep(conn, provider, **kwargs):
        result = wrapped(conn, provider, **kwargs)
        if kwargs["file_name"].endswith(".db"):
            stash[len(stash)] = shutil.copy(kwargs["zip_path"], tmp_path / f"copy-{len(stash)}.db")
        return result

    monkeypatch.setattr(view._cloud_connections, "upload_backup_zip", keep)
    monkeypatch.setattr(cloud_drives, "google_download_to",
                        lambda token, file_id, path: shutil.copy(stash[0], path))
    try:
        admin_client.post("/admin/banco-dados/backup")
        assert ("success", "Backup do banco gerado e enviado para Google Drive.") in _pop_flashes(admin_client)
        manifest = pg_posture.read(env.observer)["recent"][0]["manifest"]
        page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
        assert 'id="restore-snapshot-form"' in page and 'id="restore-upload-form"' in page
        assert f'value="{manifest}"' in page and "Recuperar banco de dados" in page

        def bases():
            return {row[0] for row in env.observer.execute("SELECT nome_conceito FROM atividade_base").fetchall()}

        snapshot_bases = bases()
        later_id, _ = _seed_activity_base(env.observer, "RSMK Depois do backup", [40])
        assert "RSMK Depois do backup" in bases()

        remote += [{"id": f"older-{i}", "name": f"sgaa-pg-snapshot-2026100{i}T000000Z.db"} for i in range(1, 4)]
        deleted.clear()
        response = admin_client.post("/admin/banco-dados/restaurar", data={"generation": manifest})
        flashes = _pop_flashes(admin_client)
        assert response.status_code == 302, response.status_code
        assert deleted == []  # the safety copy prunes nothing: the generation being restored survives
        assert ("success", "Banco restaurado com sucesso. Uma cópia de segurança da base anterior foi enviada "
                           "para Google Drive.") in flashes, flashes
        assert len(uploads) == 2  # the safety copy went out before anything changed
        assert bases() == snapshot_bases
        # an id issued after the snapshot is never issued again
        reissued = _seed_activity_base(env.observer, "RSMK Depois da recuperacao", [40])[0]
        assert reissued > later_id
        # the session survived: the administrator is still signed in
        assert admin_client.get("/admin/banco-dados").status_code == 200

        # a file that is not an SGAA snapshot is refused and nothing changes
        import io

        before = bases()
        response = admin_client.post("/admin/banco-dados/restaurar/upload", content_type="multipart/form-data",
                                     data={"backup_file": (io.BytesIO(b"not a database"), "x.db")})
        flashes = _pop_flashes(admin_client)
        assert any(category == "error" and message.startswith("Não foi possível restaurar o arquivo enviado: ")
                   for category, message in flashes), flashes
        assert bases() == before and len(uploads) == 2

        # "Carregar arquivo": the downloaded snapshot file, uploaded back
        with open(stash[0], "rb") as handle:
            body = handle.read()
        response = admin_client.post("/admin/banco-dados/restaurar/upload", content_type="multipart/form-data",
                                     data={"backup_file": (io.BytesIO(body), "sgaa-pg-snapshot-x.db")})
        flashes = _pop_flashes(admin_client)
        assert ("success", "Banco restaurado com sucesso. Uma cópia de segurança da base anterior foi enviada "
                           "para Google Drive.") in flashes, flashes
        assert bases() == snapshot_bases and len(uploads) == 3

        # an unknown generation is refused
        response = admin_client.post("/admin/banco-dados/restaurar", data={"generation": "0" * 64})
        assert ("error", "Backup selecionado é inválido ou não está mais disponível.") in _pop_flashes(admin_client)

        # no connected drive: no safety copy possible, so nothing is restored
        _seed_activity_base(env.observer, "RSMK Sem nuvem", [40])
        before = bases()
        from app.backup import hosted_backup

        monkeypatch.setattr(view, "_get_active_cloud_account", lambda conn, provider: None)
        # A20: the safety copy is sent by the hosted backup owner; its account read is patched there too
        monkeypatch.setattr(hosted_backup, "active_cloud_account", lambda conn, provider: None)
        response = admin_client.post("/admin/banco-dados/restaurar/upload", content_type="multipart/form-data",
                                     data={"backup_file": (io.BytesIO(body), "sgaa-pg-snapshot-x.db")})
        flashes = _pop_flashes(admin_client)
        assert any(category == "error" and "nada foi alterado" in message for category, message in flashes), flashes
        assert bases() == before
    finally:
        env.observer.execute("DROP SCHEMA IF EXISTS sgaa_ops CASCADE")


def test_r8_gerar_backup_agora_never_prunes_by_a_policy_it_could_not_read(env, admin_client, monkeypatch):
    from app import cloud_drives
    from app.backup import pg_posture
    from app.views.admin import banco_dados as view

    uploads, deleted = [], []
    remote = [{"id": f"old-{i}", "name": f"sgaa-pg-snapshot-2026100{i}T000000Z.db"} for i in range(1, 5)]
    _backup_now_fakes(monkeypatch, view, cloud_drives, remote, uploads, deleted)

    def unreadable(raw, *, strict=False):
        if strict:
            raise RuntimeError("statement timeout")
        return pg_posture.policy_from_rows([])

    monkeypatch.setattr(pg_posture, "read_policy", unreadable)
    try:
        admin_client.post("/admin/banco-dados/backup")
        flashes = _pop_flashes(admin_client)
        assert ("success", "Backup do banco gerado e enviado para Google Drive.") in flashes, flashes
        assert len(uploads) == 1 and deleted == []  # sent, and nothing deleted
    finally:
        env.observer.execute("DROP SCHEMA IF EXISTS sgaa_ops CASCADE")
