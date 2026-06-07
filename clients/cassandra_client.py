"""
Cliente Cassandra (Astra DB) para PetMatch — modelo query-driven de 5 tablas.

Modelo (Chebotko):
    eventos_por_usuario           PK user_id        CK (date DESC, event_id)
    eventos_por_perro             PK pet_id         CK (date DESC, event_id)
    eventos_por_refugio_y_fecha   PK shelter_id     CK (date DESC, event_id)
    solicitudes_por_usuario       PK user_id        CK (date DESC, event_id)
    solicitudes_por_refugio       PK shelter_id     CK (status, date DESC, event_id)

Columnas:
    event_id uuid, user_id uuid, pet_id uuid, shelter_id uuid,
    event_type text, date timestamp, details text
    (las tablas de solicitudes incluyen además: status text)

Las lecturas usan prepared statements cacheados. La serialización a dict
(uuid -> str, timestamp -> isoformat, claves en minúscula) se hace acá para
que las rutas solo tengan que jsonify-ar la lista.
"""

import os
import ssl
import tempfile
import zipfile
from pathlib import Path

from cassandra.cluster import Cluster
from cassandra.auth import PlainTextAuthProvider
from dotenv import load_dotenv

load_dotenv()


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BUNDLE = BASE_DIR / "secure-connect-petmatch.zip"

ASTRA_BUNDLE_PATH = os.environ.get("ASTRA_BUNDLE_PATH", str(DEFAULT_BUNDLE))
TOKEN             = os.environ["ASTRA_TOKEN"]
KEYSPACE          = os.environ["ASTRA_KEYSPACE"]

_session = None
_prepared: dict[str, object] = {}


def _build_ssl_context(bundle_path: Path) -> ssl.SSLContext:
    # Astra rechaza el handshake TLS 1.3 sobre LibreSSL (macOS), así que
    # forzamos TLS 1.2 leyendo los certs directamente del bundle.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(bundle_path) as zf:
            zf.extractall(tmp_path)

        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ssl_ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        ssl_ctx.load_verify_locations(cafile=str(tmp_path / "ca.crt"))
        ssl_ctx.verify_mode = ssl.CERT_REQUIRED
        # Astra usa SNI-based routing: el SNI es el host_id (UUID) del nodo,
        # que no coincide con el CN del certificado. La cadena se sigue
        # validando contra la CA del bundle, así que es seguro.
        ssl_ctx.check_hostname = False
        ssl_ctx.load_cert_chain(
            certfile=str(tmp_path / "cert"),
            keyfile=str(tmp_path / "key"),
        )
        return ssl_ctx


def get_session():
    global _session
    if _session is None:
        bundle_path = Path(ASTRA_BUNDLE_PATH)
        if not bundle_path.exists():
            raise FileNotFoundError(
                f"No se encontró el Secure Connect Bundle en {bundle_path}. "
                "Definí ASTRA_BUNDLE_PATH en .env o dejá el archivo "
                "secure-connect-petmatch.zip en la raíz del proyecto."
            )

        cloud_config = {
            "secure_connect_bundle": str(bundle_path),
            "ssl_context": _build_ssl_context(bundle_path),
        }
        auth_provider = PlainTextAuthProvider("token", TOKEN)
        cluster = Cluster(
            cloud=cloud_config,
            auth_provider=auth_provider,
        )
        _session = cluster.connect(KEYSPACE)
    return _session


def _prepare(cql: str):
    """Prepara (y cachea por texto de query) un statement."""
    stmt = _prepared.get(cql)
    if stmt is None:
        stmt = get_session().prepare(cql)
        _prepared[cql] = stmt
    return stmt


# ─── DDL — modelo de 5 tablas ───────────────────────────────────────────────

# event_id forma parte de la clustering key en las 5 tablas: garantiza unicidad
# (dos eventos en el mismo timestamp no se pisan) y un orden total estable.

CREATE_STATEMENTS = {
    "eventos_por_usuario": """
        CREATE TABLE IF NOT EXISTS eventos_por_usuario (
            user_id    UUID,
            date       TIMESTAMP,
            event_id   UUID,
            event_type TEXT,
            pet_id     UUID,
            shelter_id UUID,
            details    TEXT,
            PRIMARY KEY (user_id, date, event_id)
        ) WITH CLUSTERING ORDER BY (date DESC, event_id ASC)
    """,
    "eventos_por_perro": """
        CREATE TABLE IF NOT EXISTS eventos_por_perro (
            pet_id     UUID,
            date       TIMESTAMP,
            event_id   UUID,
            event_type TEXT,
            user_id    UUID,
            shelter_id UUID,
            details    TEXT,
            PRIMARY KEY (pet_id, date, event_id)
        ) WITH CLUSTERING ORDER BY (date DESC, event_id ASC)
    """,
    "eventos_por_refugio_y_fecha": """
        CREATE TABLE IF NOT EXISTS eventos_por_refugio_y_fecha (
            shelter_id UUID,
            date       TIMESTAMP,
            event_id   UUID,
            event_type TEXT,
            pet_id     UUID,
            user_id    UUID,
            details    TEXT,
            PRIMARY KEY (shelter_id, date, event_id)
        ) WITH CLUSTERING ORDER BY (date DESC, event_id ASC)
    """,
    "solicitudes_por_usuario": """
        CREATE TABLE IF NOT EXISTS solicitudes_por_usuario (
            user_id    UUID,
            date       TIMESTAMP,
            event_id   UUID,
            pet_id     UUID,
            shelter_id UUID,
            status     TEXT,
            details    TEXT,
            PRIMARY KEY (user_id, date, event_id)
        ) WITH CLUSTERING ORDER BY (date DESC, event_id ASC)
    """,
    "solicitudes_por_refugio": """
        CREATE TABLE IF NOT EXISTS solicitudes_por_refugio (
            shelter_id UUID,
            status     TEXT,
            date       TIMESTAMP,
            event_id   UUID,
            user_id    UUID,
            pet_id     UUID,
            details    TEXT,
            PRIMARY KEY (shelter_id, status, date, event_id)
        ) WITH CLUSTERING ORDER BY (status ASC, date DESC, event_id ASC)
    """,
}

# Tablas del modelo actual (las que se siembran y consultan).
MODEL_TABLES = list(CREATE_STATEMENTS.keys())

# Tablas de modelos anteriores que comparten nombre o quedaron huérfanas.
# Se dropean en el reset para que el seeder pueda recrear el esquema correcto
# (no se puede ALTER de una PRIMARY KEY: hay que DROP + CREATE).
LEGACY_TABLES = [
    "eventos_por_refugio",
    "eventos_por_usuario_y_perro",
    "eventos_por_tipo",
    "favoritos_por_usuario",
]


def create_tables():
    """Crea las 5 tablas del modelo (idempotente, CREATE IF NOT EXISTS)."""
    s = get_session()
    for cql in CREATE_STATEMENTS.values():
        s.execute(cql)


# ─── Mantenimiento ──────────────────────────────────────────────────────────

def truncate_tables():
    """
    Resetea el esquema de Cassandra: DROP de todas las tablas (modelo actual +
    legacy) y CREATE de las 5 del modelo vigente.

    Se llama desde el flujo de seed ("BORRAR Y SEMBRAR"), que es explícitamente
    destructivo. Hace DROP + CREATE en vez de TRUNCATE porque el seeder inserta
    `event_id` como parte de la clustering key: si en Astra todavía vive el
    esquema viejo (PRIMARY KEY (user_id, date), sin event_id), un TRUNCATE
    dejaría el esquema incompatible y el INSERT fallaría. El DROP + CREATE migra
    el esquema y deja las tablas vacías y listas para sembrar. Operación
    irreversible.
    """
    s = get_session()
    for table in MODEL_TABLES + LEGACY_TABLES:
        s.execute(f"DROP TABLE IF EXISTS {table}")
    # El cache de prepared statements apunta a tablas que acabamos de dropear.
    _prepared.clear()
    create_tables()


def get_sample_ids(limit_users: int = 30, limit_pets: int = 50, limit_shelters: int = 10):
    """
    Devuelve UUIDs reales sembrados, para poblar los dropdowns de la UI.
    Usa `SELECT DISTINCT <partition_key>` (Cassandra solo permite DISTINCT
    sobre la partition key completa).
    """
    s = get_session()

    users = [
        str(r.user_id)
        for r in s.execute(f"SELECT DISTINCT user_id FROM eventos_por_usuario LIMIT {limit_users}")
    ]
    pets = [
        str(r.pet_id)
        for r in s.execute(f"SELECT DISTINCT pet_id FROM eventos_por_perro LIMIT {limit_pets}")
    ]
    shelters = [
        str(r.shelter_id)
        for r in s.execute(
            f"SELECT DISTINCT shelter_id FROM eventos_por_refugio_y_fecha LIMIT {limit_shelters}")
    ]
    return {"users": users, "pets": pets, "shelters": shelters}


# ─── Serialización ──────────────────────────────────────────────────────────

def _to_dict(row) -> dict:
    """Convierte una fila de Cassandra a dict serializable a JSON: uuid -> str,
    timestamp -> isoformat, claves en minúscula (igual que las columnas)."""
    d = {}
    for field in row._fields:
        val = getattr(row, field)
        if val is None:
            d[field] = None
        elif hasattr(val, "hex"):        # UUID
            d[field] = str(val)
        elif hasattr(val, "isoformat"):  # datetime
            d[field] = val.isoformat()
        else:
            d[field] = val
    return d


# ─── Lecturas (una por pantalla del front) ──────────────────────────────────

def eventos_por_usuario(user_id):
    """Historial de un usuario, recientes primero (pantalla "Mi actividad")."""
    stmt = _prepare("""
        SELECT user_id, date, event_id, event_type, pet_id, shelter_id, details
        FROM eventos_por_usuario
        WHERE user_id = ?
    """)
    return [_to_dict(r) for r in get_session().execute(stmt, (user_id,))]


def eventos_por_perro(pet_id):
    """Interés recibido por un perro (pantalla "Ficha del animal")."""
    stmt = _prepare("""
        SELECT pet_id, date, event_id, event_type, user_id, shelter_id, details
        FROM eventos_por_perro
        WHERE pet_id = ?
    """)
    return [_to_dict(r) for r in get_session().execute(stmt, (pet_id,))]


def eventos_por_refugio_y_fecha(shelter_id, date_from=None, date_to=None):
    """
    Actividad de un refugio, opcionalmente acotada a un rango de fechas
    (pantalla "Panel por fecha"). `date` es clustering key, así que el rango es
    eficiente. Si `date_from`/`date_to` vienen en None, se omite ese borde.
    """
    cql = ("SELECT shelter_id, date, event_id, event_type, pet_id, user_id, details "
           "FROM eventos_por_refugio_y_fecha WHERE shelter_id = ?")
    params = [shelter_id]
    if date_from is not None:
        cql += " AND date >= ?"
        params.append(date_from)
    if date_to is not None:
        cql += " AND date <= ?"
        params.append(date_to)

    stmt = _prepare(cql)
    return [_to_dict(r) for r in get_session().execute(stmt, tuple(params))]


def solicitudes_por_usuario(user_id):
    """Solicitudes de adopción de un usuario (pantalla "Mis solicitudes")."""
    stmt = _prepare("""
        SELECT user_id, date, event_id, pet_id, shelter_id, status, details
        FROM solicitudes_por_usuario
        WHERE user_id = ?
    """)
    return [_to_dict(r) for r in get_session().execute(stmt, (user_id,))]


def solicitudes_por_refugio(shelter_id, status):
    """
    Cola de solicitudes de un refugio filtrada por estado (pantalla "Bandeja").
    `status` es la primera clustering key, así que el filtro es barato
    (sin ALLOW FILTERING).
    """
    stmt = _prepare("""
        SELECT shelter_id, status, date, event_id, user_id, pet_id, details
        FROM solicitudes_por_refugio
        WHERE shelter_id = ? AND status = ?
    """)
    return [_to_dict(r) for r in get_session().execute(stmt, (shelter_id, status))]
