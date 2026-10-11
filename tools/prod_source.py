# coding: utf-8
"""The one way an operator tool reaches the PROD database -- verified, unrouted (MP-3 SPEC A17).

WHY THIS EXISTS
    The cutover ledger and the governed backup decide whether a database IS production by reading
    its identity from the connection itself (``app.hosting.database_source``: database, role, cluster,
    authenticated tenant).  That reading is evidence only if the connection reached the provider.  A
    hosts-file entry, an inherited ``PGHOSTADDR``, a service file or a ``hostaddr`` parameter can send
    the same URL to any server, and any server answers whatever names it likes.  So every connection
    whose answer the cutover relies on -- the qualification, the backups, the reference, the opening,
    the write barrier, the rollback -- is opened here, and only here:

    * no libpq routing or TLS input from the environment (``ROUTING_ENVIRONMENT``): refused by name,
      never silently overridden;
    * the URL names exactly one Supabase session-pooler host and port, the tenant login
      ``postgres.<ref>`` and a database; no password, and no parameter but ``sslmode``;
    * the connection is ``sslmode=verify-full`` against the Supabase root CA committed beside this
      module and pinned by the SHA-256 of its DER bytes, whatever the URL said: the server must present
      a certificate for that host name issued under the provider's root, so a redirected connection
      fails before any query is sent; the connection must then report TLS in use with those settings;
    * the pooler authenticated the tenant login with its password, so the project is the tenant's.

    ``store_buckets`` is the second, independent channel the qualification compares against: the
    project's own storage API (public TLS, the secret key) lists the buckets the database must hold.

    Nothing here is a paid feature: the CA is the one every Supabase project publishes.

OUTPUT
    Fixed codes and digests; never a host, a URL or a credential.
"""

from __future__ import annotations

import hashlib
import os
import ssl
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import hosting  # noqa: E402

#: The Supabase root CA every project's database certificate chains to (public, published by the
#: provider for ``sslmode=verify-full``), pinned so a replaced file is refused.
PINNED_CA_FILE = Path(__file__).resolve().parent / "certs" / "supabase-root-2021-ca.crt"
PINNED_CA_SHA256 = "807025ad50d4ed219d2c9c7d299c004f824eb00cf7f65afef607d07b72e6cafa"
SESSION_POOLER_PORT = "5432"
CONNECT_TIMEOUT_SECONDS = 15
#: libpq inputs that route a connection, choose its server or weaken how it is verified; read from the
#: environment they would apply to every connection invisibly, so any of them set refuses.
ROUTING_ENVIRONMENT = (
    "PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGUSER", "PGSERVICE", "PGSERVICEFILE", "PGSYSCONFDIR",
    "PGOPTIONS", "PGTARGETSESSIONATTRS", "PGLOADBALANCEHOSTS", "PGSSLMODE", "PGREQUIRESSL", "PGSSLNEGOTIATION",
    "PGSSLROOTCERT", "PGSSLCRL", "PGSSLCRLDIR", "PGSSLSNI", "PGSSLCERT", "PGSSLKEY", "PGSSLMINPROTOCOLVERSION",
    "PGSSLMAXPROTOCOLVERSION", "PGGSSENCMODE", "PGREQUIREAUTH", "PGCHANNELBINDING", "PGREQUIREPEER",
)
#: What the URL may carry, as libpq parses it.
_ALLOWED_PARAMETERS = frozenset({"host", "port", "user", "dbname", "sslmode"})
_ACCEPTED_SSLMODES = frozenset({"require", "verify-full"})


class Refused(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class VerifiedSource:
    """What a verified connection proved: the canonical identity and the project, as digests."""

    identity: str
    project_sha256: str
    source: dict


def refuse_routing_environment(environ=None) -> None:
    env = os.environ if environ is None else environ
    present = sorted(name for name in ROUTING_ENVIRONMENT if str(env.get(name) or "").strip())
    if present:
        raise Refused("SOURCE_ENV_ROUTING", ",".join(present))


def pinned_ca() -> Path:
    """The committed CA file, refused unless it is exactly the pinned certificate."""
    try:
        text = PINNED_CA_FILE.read_text(encoding="ascii")
        if text.count("-----BEGIN CERTIFICATE-----") != 1:
            raise ValueError("one certificate")
        der = ssl.PEM_cert_to_DER_cert(text.strip())
    except (OSError, ValueError, UnicodeError):
        raise Refused("SOURCE_CA_UNREADABLE") from None
    if hashlib.sha256(der).hexdigest() != PINNED_CA_SHA256:
        raise Refused("SOURCE_CA_PIN_MISMATCH")
    return PINNED_CA_FILE


def verified_url(url) -> str:
    """The URL a verified connection uses: the operator's endpoint, ``verify-full`` against the pinned CA.

    Refuses anything that could reach another server than the one the URL shows: a password, a
    parameter other than ``sslmode``, a list of hosts, an address that is not a Supabase session
    pooler, a login that names no tenant.
    """
    from psycopg.conninfo import conninfo_to_dict

    url = str(url or "").strip()
    if not url:
        raise Refused("SOURCE_REQUIRED")
    if not url.startswith(("postgres://", "postgresql://")):
        raise Refused("SOURCE_NOT_POSTGRESQL")
    try:
        parts = urlsplit(url)
        password = parts.password
        params = conninfo_to_dict(url)
    except Exception:
        raise Refused("SOURCE_URL_INVALID") from None
    if password is not None or "password" in params:
        raise Refused("SOURCE_URL_CONTAINS_PASSWORD")
    unexpected = sorted(set(params) - _ALLOWED_PARAMETERS)
    if unexpected:
        raise Refused("SOURCE_URL_PARAMETER_REFUSED", ",".join(unexpected))
    if "sslmode" in params and params["sslmode"] not in _ACCEPTED_SSLMODES:
        raise Refused("SOURCE_URL_PARAMETER_REFUSED", "sslmode")
    host = str(params.get("host") or "").strip().lower()
    port = str(params.get("port") or "").strip()
    user = str(params.get("user") or "")
    database = str(params.get("dbname") or "")
    if not host or "," in host or "," in port:
        raise Refused("SOURCE_URL_AMBIGUOUS")
    if not host.endswith(hosting.SUPABASE_POOLER_SUFFIX) or port != SESSION_POOLER_PORT:
        raise Refused("SOURCE_NOT_THE_SESSION_POOLER")
    if hosting.supabase_project_ref(host, user) is None:
        raise Refused("SOURCE_NO_TENANT", "the login must be the tenant postgres.<ref>")
    if not database:
        raise Refused("SOURCE_URL_INVALID", "name the database")
    ca = quote(str(pinned_ca()), safe="")
    return (f"postgresql://{quote(user, safe='')}@{host}:{port}/{quote(database, safe='')}"
            f"?sslmode=verify-full&sslrootcert={ca}")


def connect(url):
    """A verified, autocommit connection to the database ``url`` names; refused otherwise."""
    import psycopg

    refuse_routing_environment()
    verified = verified_url(url)
    try:
        conn = psycopg.connect(verified, autocommit=True, prepare_threshold=None,
                               connect_timeout=CONNECT_TIMEOUT_SECONDS)
    except psycopg.Error as exc:
        # A certificate that does not verify is the redirect this module exists to stop.
        text = str(exc).lower()
        code = "SOURCE_TLS_NOT_VERIFIED" if ("certificate" in text or "ssl" in text) else "SOURCE_UNREACHABLE"
        raise Refused(code) from None
    try:
        settings = conn.info.get_parameters()
        if not conn.pgconn.ssl_in_use or settings.get("sslmode") != "verify-full" or \
                Path(settings.get("sslrootcert") or "") != pinned_ca():
            raise Refused("SOURCE_TLS_NOT_VERIFIED")
    except BaseException:
        conn.close()
        raise
    return conn


def observe(conn) -> VerifiedSource:
    """The identity a verified connection proves (``app.hosting``), or a refusal."""
    source = hosting.database_source(conn)
    project = hosting.source_project_sha256(source)
    identity = hosting.source_identity_sha256(source)
    if project is None:
        raise Refused("SOURCE_NO_TENANT")
    if identity is None:
        raise Refused("DATABASE_IDENTITY_UNPROVEN", "the database does not prove its cluster (system identifier)")
    return VerifiedSource(identity=identity, project_sha256=project, source=source)


# ---------------------------------------------------------------------------
# the second channel: the project's own storage API
# ---------------------------------------------------------------------------


def _second(moment) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def store_project_sha256(environ=None) -> str:
    """The project ``SUPABASE_URL`` names (``https://<ref>.supabase.co``), as a digest."""
    from app.storage.object_store import CanonicalStoreError
    from app.storage.supabase_store import configured_project_url

    try:
        url = configured_project_url(environ)
    except CanonicalStoreError:
        raise Refused("STORE_NOT_CONFIGURED") from None
    parts = urlsplit(url)
    ref = hosting.supabase_project_ref(parts.hostname) if parts.scheme == "https" else None
    if ref is None or parts.port is not None:
        raise Refused("STORE_NOT_A_PROJECT", "SUPABASE_URL must be https://<ref>.supabase.co")
    return hosting.project_sha256(ref)


def store_buckets(environ=None, *, session=None) -> frozenset:
    """``(id, created second)`` of every bucket the project's storage API lists (TLS verified)."""
    from datetime import datetime

    from app.storage.object_store import CanonicalStoreError
    from app.storage.supabase_store import SECRET_KEY_PREFIX, SupabaseStorageConfig

    store_project_sha256(environ)
    try:
        config = SupabaseStorageConfig.from_environment(environ)
    except CanonicalStoreError:
        raise Refused("STORE_NOT_CONFIGURED") from None
    headers = {"apikey": config.secret_key}
    if not config.secret_key.startswith(SECRET_KEY_PREFIX):
        headers["Authorization"] = f"Bearer {config.secret_key}"
    if session is None:
        import requests

        session = requests.Session()
    try:
        response = session.request("GET", f"{config.url}/storage/v1/bucket", headers=headers, timeout=(5.0, 30.0),
                                   allow_redirects=False)
        listed = response.json() if int(response.status_code) == 200 else None
        return frozenset((str(item["id"]), _second(datetime.fromisoformat(str(item["created_at"]).replace("Z", "+00:00"))))
                         for item in listed)
    except Exception:
        raise Refused("STORE_UNREADABLE") from None


def database_buckets(conn) -> frozenset:
    """``(id, created second)`` of every bucket in the database's ``storage.buckets``."""
    try:
        rows = conn.execute("SELECT id, created_at FROM storage.buckets").fetchall()
    except Exception:
        raise Refused("DATABASE_BUCKETS_UNREADABLE") from None
    return frozenset((str(row[0]), _second(row[1])) for row in rows)


__all__ = [
    "PINNED_CA_FILE",
    "PINNED_CA_SHA256",
    "ROUTING_ENVIRONMENT",
    "Refused",
    "VerifiedSource",
    "connect",
    "database_buckets",
    "observe",
    "pinned_ca",
    "refuse_routing_environment",
    "store_buckets",
    "store_project_sha256",
    "verified_url",
]
