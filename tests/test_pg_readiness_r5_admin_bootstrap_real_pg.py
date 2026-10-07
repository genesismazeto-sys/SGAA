# coding: utf-8
"""R5 real-PostgreSQL qualification of the supported admin bootstrap.

Runs only when ``SGAA_PG_TEST_URL`` supplies a local PostgreSQL role with
CREATE DATABASE; otherwise the whole module skips (REAL-PG EVIDENCE: ABSENT).
The URL is server access only: nothing is ever written into the database it
names.  One template database is provisioned through
``app.pg_schema.provision_pg_schema``; every node clones its own disposable
database from it, points ``app.db.DATABASE_URL`` at the clone, and the run
drops everything it created with the accepted guard model (protected names,
run prefix, created-by-this-run, owned by the connected role, plain DROP first
and FORCE only on ObjectInUse).

* PGR5-1 fresh provisioned database -> the CLI creates the first full admin;
* PGR5-2 Path-B shape (pending ``admin_total`` + login-capable Coordenador,
  overrides, an outstanding link, an uploaded file) -> the CLI activates the
  SAME ``usuarios.id``, no duplicate, relationships intact;
* PGR5-3 an already login-capable full admin -> refused, nothing changes;
* PGR5-4 a non-full-admin holder of the e-mail -> refused, no escalation;
  plus the fail-closed cases (ambiguous, unclassifiable, revoked, a pending
  full admin under another address);
* PGR5-5 the resulting credential authenticates through the production
  ``POST /login`` and reaches ``/admin/acesso`` (resource ``acesso``, which
  only a full administrator holds -- the Coordenador is refused there);
* PGR5-6 atomicity: a test-only trigger fails the credential write after the
  first ``usuarios`` write; the owner rolls everything back.

No production owner is monkeypatched: the CLI runs its real connection path,
and the only test seam is the hidden-prompt callable ``main`` accepts.  Every
assertion reads the database through an independent autocommit observer.
"""
from __future__ import annotations

import os
import secrets
from urllib.parse import urlsplit, urlunsplit

import pytest

PG_URL = os.environ.get("SGAA_PG_TEST_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT",
)

psycopg = pytest.importorskip("psycopg")

from app import admin_bootstrap  # noqa: E402
from app import db as app_db  # noqa: E402
from app import pg_schema  # noqa: E402
from app.security.passwords import check_password, hash_password  # noqa: E402

#: Every database this run creates carries this prefix (random per run).
RUN_PREFIX = f"sgaa_r5bs_test_{secrets.token_hex(4)}_"
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1", "sgaa_qual"})
CONNECT_TIMEOUT_SECONDS = 10

ADMIN_EMAIL = "r5.admin@example.test"
COORD_EMAIL = "r5.coordenador@example.test"
COORD_PASSWORD = "r5-coordenador-Synthetic"
FAILPOINT_MARKER = "r5 test failpoint"


def _database_url(database):
    parts = urlsplit(PG_URL)
    return urlunsplit(
        (parts.scheme, parts.netloc, "/" + database, f"connect_timeout={CONNECT_TIMEOUT_SECONDS}", "")
    )


def _raw_connect(url, *, autocommit=False):
    return psycopg.connect(
        url, prepare_threshold=None, autocommit=autocommit, connect_timeout=CONNECT_TIMEOUT_SECONDS
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

    def create(self, label, *, template=None):
        database = f"{RUN_PREFIX}{label}_{secrets.token_hex(4)}"
        clause = f' TEMPLATE "{template}"' if template else ""
        self.admin().execute(f'CREATE DATABASE "{database}"{clause}')
        self._owned.add(database)
        return database, _database_url(database)

    def drop(self, database):
        if database in PROTECTED_DATABASES or not database.startswith(RUN_PREFIX):
            raise AssertionError(f"refusing to drop {database!r}: not run-owned")
        if database not in self._owned:
            raise AssertionError(f"refusing to drop {database!r}: not created by this run")
        row = self.admin().execute(
            "SELECT pg_get_userbyid(datdba) = current_user FROM pg_database WHERE datname = %s",
            (database,),
        ).fetchone()
        if row is not None and not row[0]:
            raise AssertionError(f"refusing to drop {database!r}: not owned by this role")
        try:
            self.admin().execute(f'DROP DATABASE IF EXISTS "{database}"')
        except psycopg.errors.ObjectInUse:
            self.admin().execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        self._owned.discard(database)

    def leftovers(self):
        rows = self.admin().execute(
            "SELECT datname FROM pg_database WHERE starts_with(datname, %s)", (RUN_PREFIX,)
        ).fetchall()
        return sorted(row[0] for row in rows)

    def close(self):
        failures = []
        # Clones before their template.
        for database in sorted(self._owned, key=lambda name: "_template_" in name):
            try:
                self.drop(database)
            except Exception as exc:  # pragma: no cover - teardown reporting
                failures.append((database, repr(exc)))
        leftovers = self.leftovers() if not failures else []
        if self._admin is not None and not self._admin.closed:
            self._admin.close()
        assert not failures, f"could not drop run-owned databases: {failures!r}"
        assert not leftovers, f"run-owned databases left behind: {leftovers!r}"


@pytest.fixture(scope="module")
def registry():
    registry = _RunDatabaseRegistry()
    try:
        try:
            registry.admin()
        except psycopg.Error as exc:
            pytest.skip(f"SGAA_PG_TEST_URL is not a usable PostgreSQL connection: {exc}")
        template, url = registry.create("template")
        connection = _raw_connect(url)
        try:
            assert pg_schema.provision_pg_schema(connection)["status"] == "provisioned"
            connection.commit()
        finally:
            connection.close()
        registry.template = template
        yield registry
    finally:
        registry.close()


class _Db:
    pass


@pytest.fixture
def pgdb(registry, request, monkeypatch):
    """A freshly provisioned clone; the canonical backend authority points at it."""
    import main

    database, url = registry.create(request.node.name[:12].strip("_[").lower(), template=registry.template)
    monkeypatch.setattr(app_db, "DATABASE_URL", url)
    monkeypatch.setitem(main.app.config, "TESTING", True)
    assert app_db.database_backend() == "postgres"
    observer = _raw_connect(url, autocommit=True)
    d = _Db()
    d.database, d.url, d.observer, d.app = database, url, observer, main.app
    try:
        yield d
    finally:
        with main.app.app_context():
            app_db.close_db_connection(None)
        observer.close()
        registry.drop(database)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _Prompt:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, text):
        self.prompts.append(text)
        return self.answers.pop(0)


def _run_cli(capsys, argv, *answers):
    prompt = _Prompt(*answers)
    code = admin_bootstrap.main(argv, prompt=prompt)
    captured = capsys.readouterr()
    for answer in answers:
        assert answer not in captured.out and answer not in captured.err
    assert "pbkdf2" not in captured.out + captured.err
    assert PG_URL not in captured.out + captured.err
    return code, captured, prompt


def _production_connection():
    return app_db._connect_postgres()


def _owner(callable_, *args, **kwargs):
    conn = _production_connection()
    try:
        return callable_(conn, *args, **kwargs)
    finally:
        conn.close()


def _create(conn, nome, email, user_type, level, state, password=None):
    from app.user_accounts import create_usuario_with_access_level

    usuario_id = create_usuario_with_access_level(
        conn,
        nome,
        email,
        hash_password(password or secrets.token_hex(8)),
        user_type,
        level,
        credential_state=state,
    ).usuario_id
    conn.commit()
    return int(usuario_id)


def _state(observer, usuario_id):
    row = observer.execute(
        "SELECT u.id,u.email,u.tipo,u.nivel_acesso,u.senha,c.estado,c.auth_version,c.acesso_ativo "
        "FROM usuarios u LEFT JOIN usuario_credenciais c ON c.usuario_id=u.id WHERE u.id=%s",
        (usuario_id,),
    ).fetchone()
    keys = ("id", "email", "tipo", "nivel_acesso", "senha", "estado", "auth_version", "acesso_ativo")
    return dict(zip(keys, row)) if row else None


def _snapshot(observer):
    return observer.execute(
        "SELECT u.id,u.email,u.tipo,u.nivel_acesso,u.senha,c.estado,c.auth_version,c.acesso_ativo "
        "FROM usuarios u LEFT JOIN usuario_credenciais c ON c.usuario_id=u.id ORDER BY u.id"
    ).fetchall()


def _count(observer, table):
    return observer.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def _login(app, email, password):
    client = app.test_client()
    response = client.post("/login", data={"email": email, "senha": password})
    return client, response


def _assert_full_admin_login(app, email, password):
    """PGR5-5: production login, then a resource only a full admin holds."""
    client, response = _login(app, email, password)
    assert response.status_code == 302, response.status_code
    assert response.headers["Location"].endswith("/admin/dashboard") or "dashboard" in response.headers["Location"]
    with client.session_transaction() as session:
        assert session["access_level"] == "admin_total"
        assert session["user_type"] == "admin"
    page = client.get("/admin/acesso")
    assert page.status_code == 200, page.status_code
    assert b"access-users-data" in page.data
    return client


def _assert_login_refused(app, email, password):
    client, response = _login(app, email, password)
    assert response.status_code == 200, response.status_code
    with client.session_transaction() as session:
        assert "user_id" not in session


# ===========================================================================
# PGR5-1 + PGR5-5 -- fresh provisioned database
# ===========================================================================


def test_pgr5_1_fresh_database_bootstrap_creates_first_usable_full_admin(pgdb, capsys):
    obs = pgdb.observer
    assert _count(obs, "usuarios") == 0
    assert _count(obs, "usuario_credenciais") == 0
    password = "r5-fresh-Synthetic-" + secrets.token_hex(4)

    code, captured, prompt = _run_cli(
        capsys, ["--email", ADMIN_EMAIL, "--name", "R5 Administrador"], password, password
    )
    assert code == 0, captured.err
    assert len(prompt.prompts) == 2
    assert captured.err == ""
    assert captured.out.startswith("bootstrap-admin: full administrator created (usuario_id=")

    rows = _snapshot(obs)
    assert len(rows) == 1
    state = _state(obs, rows[0][0])
    assert state["email"] == ADMIN_EMAIL
    assert (state["tipo"], state["nivel_acesso"]) == ("admin", "admin_total")
    assert (state["estado"], state["auth_version"], state["acesso_ativo"]) == ("personal", 1, 1)
    assert state["senha"].startswith("pbkdf2:sha256:600000$")
    assert check_password(state["senha"], password)
    assert _count(obs, "usuarios_permissoes_acesso") == 0

    # PGR5-5 -- the credential authenticates through the real login route.
    _assert_login_refused(pgdb.app, ADMIN_EMAIL, password + "-wrong")
    _assert_full_admin_login(pgdb.app, ADMIN_EMAIL, password)

    # The command is not a second door: rerunning it is refused.
    code, captured, prompt = _run_cli(capsys, ["--email", ADMIN_EMAIL])
    assert code == 1 and prompt.prompts == []
    assert "a login-capable full administrator already exists" in captured.err
    assert _snapshot(obs) == rows


# ===========================================================================
# PGR5-2 + PGR5-5 -- Path-B migrated shape: activate the SAME pending admin
# ===========================================================================


def _seed_path_b(obs):
    from app.user_accounts import create_usuario_pending

    conn = _production_connection()
    try:
        filler = _create(conn, "R5 Aluno", "r5.aluno@example.test", "aluno", "usuario", "personal")
        admin_id = int(create_usuario_pending(conn, "R5 Admin Migrado", ADMIN_EMAIL, "admin").usuario_id)
        conn.commit()
        coord_id = _create(
            conn, "R5 Coordenador", COORD_EMAIL, "admin", "administrativo", "personal", COORD_PASSWORD
        )
    finally:
        conn.close()
    obs.execute(
        "INSERT INTO usuarios_permissoes_acesso(usuario_id,recurso,escopo) VALUES (%s,'acesso','full')",
        (admin_id,),
    )
    token_id = obs.execute(
        "INSERT INTO senha_tokens(usuario_id,purpose,token_hash,expires_at) "
        "VALUES (%s,'first_access',%s,'2999-01-01T00:00:00Z') RETURNING id",
        (admin_id, secrets.token_hex(32)),
    ).fetchone()[0]
    file_id = obs.execute(
        "INSERT INTO admin_arquivos(titulo,filename,uploader_user_id) VALUES ('R5 doc','r5.pdf',%s) RETURNING id",
        (admin_id,),
    ).fetchone()[0]
    return {"filler": filler, "admin": admin_id, "coord": coord_id, "token": token_id, "file": file_id}


def test_pgr5_2_path_b_pending_full_admin_is_activated_in_place(pgdb, capsys):
    obs = pgdb.observer
    ids = _seed_path_b(obs)
    before = _state(obs, ids["admin"])
    assert (before["nivel_acesso"], before["estado"], before["acesso_ativo"]) == ("admin_total", "pending", 1)
    users_before = _count(obs, "usuarios")
    coord_before = _state(obs, ids["coord"])
    password = "r5-pathb-Synthetic-" + secrets.token_hex(4)

    # Path-B login is impossible before activation, with any password.
    _assert_login_refused(pgdb.app, ADMIN_EMAIL, password)

    # The operator's casing does not matter; the stored address is kept.
    code, captured, _prompt = _run_cli(capsys, ["--email", ADMIN_EMAIL.upper()], password, password)
    assert code == 0, captured.err
    assert captured.out.strip() == (
        "bootstrap-admin: pending full administrator activated "
        f"(usuario_id={ids['admin']} email={ADMIN_EMAIL})"
    )

    after = _state(obs, ids["admin"])
    assert after["id"] == ids["admin"]
    assert _count(obs, "usuarios") == users_before
    assert obs.execute("SELECT count(*) FROM usuarios WHERE LOWER(email)=%s", (ADMIN_EMAIL,)).fetchone()[0] == 1
    assert (after["email"], after["tipo"], after["nivel_acesso"]) == (ADMIN_EMAIL, "admin", "admin_total")
    assert (after["estado"], after["acesso_ativo"]) == ("personal", 1)
    assert after["auth_version"] == before["auth_version"] + 1
    assert after["senha"] != before["senha"]
    assert check_password(after["senha"], password)
    # Unrelated relationships are untouched; the outstanding first-access link
    # is retired by the production password writer.
    assert obs.execute(
        "SELECT recurso,escopo FROM usuarios_permissoes_acesso WHERE usuario_id=%s", (ids["admin"],)
    ).fetchall() == [("acesso", "full")]
    assert obs.execute(
        "SELECT uploader_user_id FROM admin_arquivos WHERE id=%s", (ids["file"],)
    ).fetchone()[0] == ids["admin"]
    token = obs.execute(
        "SELECT consumed_at,invalidated_at FROM senha_tokens WHERE id=%s", (ids["token"],)
    ).fetchone()
    assert token[0] is None and token[1] is not None
    assert _state(obs, ids["coord"]) == coord_before

    # PGR5-5: the activated admin reaches the full-admin-only resource; the
    # login-capable Coordenador (administrativo) does not.
    _assert_full_admin_login(pgdb.app, ADMIN_EMAIL, password)
    coord_client, response = _login(pgdb.app, COORD_EMAIL, COORD_PASSWORD)
    assert response.status_code == 302
    assert coord_client.get("/admin/acesso").status_code != 200

    # Once usable, a second activation is refused.
    snapshot = _snapshot(obs)
    code, captured, prompt = _run_cli(capsys, ["--email", ADMIN_EMAIL])
    assert code == 1 and prompt.prompts == []
    assert _snapshot(obs) == snapshot


# ===========================================================================
# PGR5-3 -- an already login-capable full admin: refused, nothing changes
# ===========================================================================


@pytest.mark.parametrize("existing_state", ["personal", "default"])
@pytest.mark.parametrize("requested", ["same-email", "other-email"])
def test_pgr5_3_existing_usable_full_admin_refuses(pgdb, capsys, existing_state, requested):
    obs = pgdb.observer
    password = "r5-usable-Synthetic"
    conn = _production_connection()
    try:
        admin_id = _create(conn, "R5 Admin", ADMIN_EMAIL, "admin", "admin_total", existing_state, password)
    finally:
        conn.close()
    snapshot = _snapshot(obs)
    email = ADMIN_EMAIL if requested == "same-email" else "r5.second@example.test"

    code, captured, prompt = _run_cli(capsys, ["--email", email])
    assert code == 1 and prompt.prompts == []
    assert "bootstrap-admin: refused: a login-capable full administrator already exists" in captured.err
    # The owner refuses on its own too (the in-transaction decision, not just
    # the CLI pre-check).
    with pytest.raises(admin_bootstrap.AdminBootstrapRefused) as refused:
        _owner(admin_bootstrap.bootstrap_admin, email, hash_password("r5-other"))
    assert refused.value.reason == admin_bootstrap.REFUSED_USABLE_ADMIN_EXISTS

    assert _snapshot(obs) == snapshot
    assert _count(obs, "usuarios") == 1
    assert check_password(_state(obs, admin_id)["senha"], password)
    _assert_full_admin_login(pgdb.app, ADMIN_EMAIL, password)


# ===========================================================================
# PGR5-4 -- non-full-admin holder of the e-mail: refused, no escalation
# ===========================================================================


@pytest.mark.parametrize(
    "user_type,level,override",
    [
        ("admin", "administrativo", None),
        ("admin", "consultivo", None),
        ("aluno", "usuario", None),
        ("admin", "admin_total", ("acesso", "view")),
    ],
    ids=["coordenador", "consultor", "aluno", "admin_total-narrowed"],
)
def test_pgr5_4_non_full_admin_collision_is_refused(pgdb, capsys, user_type, level, override):
    obs = pgdb.observer
    conn = _production_connection()
    try:
        usuario_id = _create(conn, "R5 Colisao", ADMIN_EMAIL, user_type, level, "pending")
    finally:
        conn.close()
    if override:
        obs.execute(
            "INSERT INTO usuarios_permissoes_acesso(usuario_id,recurso,escopo) VALUES (%s,%s,%s)",
            (usuario_id, *override),
        )
    snapshot = _snapshot(obs)

    code, captured, prompt = _run_cli(capsys, ["--email", ADMIN_EMAIL])
    assert code == 1 and prompt.prompts == []
    assert "is not a full administrator" in captured.err
    with pytest.raises(admin_bootstrap.AdminBootstrapRefused) as refused:
        _owner(admin_bootstrap.bootstrap_admin, ADMIN_EMAIL, hash_password("r5-escalate"))
    assert refused.value.reason == admin_bootstrap.REFUSED_NOT_FULL_ADMIN
    assert _snapshot(obs) == snapshot
    assert _state(obs, usuario_id)["nivel_acesso"] == level


def _seed_ambiguous(obs, conn):
    _create(conn, "R5 A", ADMIN_EMAIL, "admin", "admin_total", "pending")
    _create(conn, "R5 B", ADMIN_EMAIL.upper(), "admin", "admin_total", "pending")


def _seed_unknown_level(obs, conn):
    usuario_id = _create(conn, "R5 A", ADMIN_EMAIL, "admin", "admin_total", "pending")
    obs.execute("UPDATE usuarios SET nivel_acesso='superpoderes' WHERE id=%s", (usuario_id,))


def _seed_missing_credential(obs, conn):
    usuario_id = _create(conn, "R5 A", ADMIN_EMAIL, "admin", "admin_total", "pending")
    obs.execute("DELETE FROM usuario_credenciais WHERE usuario_id=%s", (usuario_id,))


def _seed_revoked(obs, conn):
    usuario_id = _create(conn, "R5 A", ADMIN_EMAIL, "admin", "admin_total", "pending")
    obs.execute("UPDATE usuario_credenciais SET acesso_ativo=0 WHERE usuario_id=%s", (usuario_id,))


def _seed_pending_elsewhere(obs, conn):
    _create(conn, "R5 A", "r5.migrated@example.test", "admin", "admin_total", "pending")


@pytest.mark.parametrize(
    "seed,reason",
    [
        (_seed_ambiguous, admin_bootstrap.REFUSED_AMBIGUOUS_TARGET),
        (_seed_unknown_level, admin_bootstrap.REFUSED_UNCLASSIFIABLE),
        (_seed_missing_credential, admin_bootstrap.REFUSED_UNCLASSIFIABLE),
        (_seed_revoked, admin_bootstrap.REFUSED_TARGET_REVOKED),
        (_seed_pending_elsewhere, admin_bootstrap.REFUSED_UNACTIVATED_ADMIN_ELSEWHERE),
    ],
    ids=["ambiguous", "unknown-level", "missing-credential", "revoked", "pending-elsewhere"],
)
def test_pgr5_4b_unsafe_states_fail_closed(pgdb, seed, reason):
    obs = pgdb.observer
    conn = _production_connection()
    try:
        seed(obs, conn)
    finally:
        conn.close()
    snapshot = _snapshot(obs)
    with pytest.raises(admin_bootstrap.AdminBootstrapRefused) as refused:
        _owner(admin_bootstrap.bootstrap_admin, ADMIN_EMAIL, hash_password("r5-unsafe"))
    assert refused.value.reason == reason
    assert _snapshot(obs) == snapshot


# ===========================================================================
# PGR5-6 -- atomicity: a failure after the first write leaves nothing behind
# ===========================================================================


def _install_failpoint(obs):
    """Test-only fault injection in the disposable database, not in the owner."""
    obs.execute(
        "CREATE FUNCTION r5_failpoint() RETURNS trigger LANGUAGE plpgsql AS "
        f"$$BEGIN RAISE EXCEPTION '{FAILPOINT_MARKER}'; END$$"
    )
    obs.execute(
        "CREATE TRIGGER r5_failpoint BEFORE INSERT OR UPDATE ON usuario_credenciais "
        "FOR EACH ROW EXECUTE FUNCTION r5_failpoint()"
    )


@pytest.mark.parametrize("path", ["create", "activate"])
def test_pgr5_6_failure_after_first_write_rolls_back_everything(pgdb, path):
    obs = pgdb.observer
    ids = _seed_path_b(obs) if path == "activate" else None
    snapshot = _snapshot(obs)
    tokens = obs.execute("SELECT id,consumed_at,invalidated_at FROM senha_tokens ORDER BY id").fetchall()
    _install_failpoint(obs)

    conn = _production_connection()
    try:
        with pytest.raises(Exception, match=FAILPOINT_MARKER):
            admin_bootstrap.bootstrap_admin(conn, ADMIN_EMAIL, hash_password("r5-atomic"))
        assert app_db.connection_transaction_status(conn) == "IDLE"
    finally:
        conn.close()

    # The usuarios write (INSERT, or the password UPDATE) preceded the failing
    # credential write; none of it survives.
    assert _snapshot(obs) == snapshot
    assert obs.execute("SELECT id,consumed_at,invalidated_at FROM senha_tokens ORDER BY id").fetchall() == tokens
    if path == "create":
        assert _count(obs, "usuarios") == 0
    else:
        assert _state(obs, ids["admin"])["estado"] == "pending"
