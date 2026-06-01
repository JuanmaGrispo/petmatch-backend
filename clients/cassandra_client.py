import os
import ssl
from cassandra.cluster import Cluster
from cassandra.auth import PlainTextAuthProvider
from dotenv import load_dotenv

load_dotenv()

ASTRA_HOST = os.environ["ASTRA_HOST"]
ASTRA_PORT = 29042
TOKEN     = os.environ["ASTRA_TOKEN"]
KEYSPACE  = os.environ["ASTRA_KEYSPACE"]

_session = None

def get_session():
    global _session
    if _session is None:
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        auth_provider = PlainTextAuthProvider("token", TOKEN)
        cluster = Cluster(
            contact_points=[ASTRA_HOST],
            port=ASTRA_PORT,
            auth_provider=auth_provider,
            ssl_context=ssl_ctx,
        )
        _session = cluster.connect(KEYSPACE)
    return _session


# ─── DDL ────────────────────────────────────────────────────────────────────

def create_tables():
    # Q1 — eventos de un usuario, por fecha DESC
    get_session().execute("""
        CREATE TABLE IF NOT EXISTS eventos_por_usuario (
            user_id    UUID,
            date       TIMESTAMP,
            event_type TEXT,
            pet_id     UUID,
            shelter_id UUID,
            details    TEXT,
            PRIMARY KEY (user_id, date)
        ) WITH CLUSTERING ORDER BY (date DESC)
    """)

    # Q2 — eventos de un perro, por fecha DESC
    get_session().execute("""
        CREATE TABLE IF NOT EXISTS eventos_por_perro (
            pet_id     UUID,
            date       TIMESTAMP,
            event_type TEXT,
            event_id   UUID,
            user_id    UUID,
            shelter_id UUID,
            details    TEXT,
            PRIMARY KEY (pet_id, date)
        ) WITH CLUSTERING ORDER BY (date DESC)
    """)

    # Q3 — solicitudes de un refugio, por fecha DESC
    get_session().execute("""
        CREATE TABLE IF NOT EXISTS eventos_por_refugio (
            shelter_id UUID,
            date       TIMESTAMP,
            event_type TEXT,
            event_id   UUID,
            pet_id     UUID,
            user_id    UUID,
            details    TEXT,
            PRIMARY KEY (shelter_id, date)
        ) WITH CLUSTERING ORDER BY (date DESC)
    """)

    # Q4 — eventos de un usuario sobre un perro específico, por fecha DESC
    # Composite partition key: (user_id, pet_id)
    get_session().execute("""
        CREATE TABLE IF NOT EXISTS eventos_por_usuario_y_perro (
            user_id    UUID,
            pet_id     UUID,
            date       TIMESTAMP,
            event_type TEXT,
            event_id   UUID,
            shelter_id UUID,
            details    TEXT,
            PRIMARY KEY ((user_id, pet_id), date)
        ) WITH CLUSTERING ORDER BY (date DESC)
    """)

    # Q5 — eventos de un tipo específico, por fecha DESC
    get_session().execute("""
        CREATE TABLE IF NOT EXISTS eventos_por_tipo (
            event_type TEXT,
            date       TIMESTAMP,
            event_id   UUID,
            pet_id     UUID,
            user_id    UUID,
            shelter_id UUID,
            details    TEXT,
            PRIMARY KEY (event_type, date)
        ) WITH CLUSTERING ORDER BY (date DESC)
    """)

    # Q6 — perros favoritos de un usuario, por fecha DESC
    get_session().execute("""
        CREATE TABLE IF NOT EXISTS favoritos_por_usuario (
            user_id    UUID,
            date       TIMESTAMP,
            pet_id     UUID,
            shelter_id UUID,
            details    TEXT,
            PRIMARY KEY (user_id, date)
        ) WITH CLUSTERING ORDER BY (date DESC)
    """)

    # Q7 — solicitudes de adopción de un usuario, por fecha DESC
    get_session().execute("""
        CREATE TABLE IF NOT EXISTS solicitudes_por_usuario (
            user_id    UUID,
            date       TIMESTAMP,
            event_id   UUID,
            pet_id     UUID,
            shelter_id UUID,
            status     TEXT,
            details    TEXT,
            PRIMARY KEY (user_id, date)
        ) WITH CLUSTERING ORDER BY (date DESC)
    """)

    # Q8 — eventos de un refugio en un rango de fechas (misma PK que Q3, tabla separada por semántica)
    get_session().execute("""
        CREATE TABLE IF NOT EXISTS eventos_por_refugio_y_fecha (
            shelter_id UUID,
            date       TIMESTAMP,
            event_type TEXT,
            event_id   UUID,
            pet_id     UUID,
            user_id    UUID,
            details    TEXT,
            PRIMARY KEY (shelter_id, date)
        ) WITH CLUSTERING ORDER BY (date DESC)
    """)


# ─── DML — writes denormalizados ────────────────────────────────────────────

def insert_evento(event_id, user_id, pet_id, shelter_id, event_type, date, details):
    """Escribe en todas las tablas de eventos simultáneamente (denormalización Cassandra)."""
    get_session().execute("""
        INSERT INTO eventos_por_usuario (user_id, date, event_type, pet_id, shelter_id, details)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (user_id, date, event_type, pet_id, shelter_id, details))

    get_session().execute("""
        INSERT INTO eventos_por_perro (pet_id, date, event_type, event_id, user_id, shelter_id, details)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (pet_id, date, event_type, event_id, user_id, shelter_id, details))

    get_session().execute("""
        INSERT INTO eventos_por_refugio (shelter_id, date, event_type, event_id, pet_id, user_id, details)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (shelter_id, date, event_type, event_id, pet_id, user_id, details))

    get_session().execute("""
        INSERT INTO eventos_por_usuario_y_perro (user_id, pet_id, date, event_type, event_id, shelter_id, details)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (user_id, pet_id, date, event_type, event_id, shelter_id, details))

    get_session().execute("""
        INSERT INTO eventos_por_tipo (event_type, date, event_id, pet_id, user_id, shelter_id, details)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (event_type, date, event_id, pet_id, user_id, shelter_id, details))

    get_session().execute("""
        INSERT INTO eventos_por_refugio_y_fecha (shelter_id, date, event_type, event_id, pet_id, user_id, details)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (shelter_id, date, event_type, event_id, pet_id, user_id, details))


def insert_favorito(user_id, pet_id, shelter_id, date, details):
    get_session().execute("""
        INSERT INTO favoritos_por_usuario (user_id, date, pet_id, shelter_id, details)
        VALUES (%s, %s, %s, %s, %s)
    """, (user_id, date, pet_id, shelter_id, details))


def insert_solicitud(user_id, event_id, pet_id, shelter_id, date, status, details):
    get_session().execute("""
        INSERT INTO solicitudes_por_usuario (user_id, date, event_id, pet_id, shelter_id, status, details)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (user_id, date, event_id, pet_id, shelter_id, status, details))


# ─── Helpers ────────────────────────────────────────────────────────────────

def _to_dict(row):
    d = {}
    for field in row._fields:
        val = getattr(row, field)
        if val is None:
            d[field] = None
        elif hasattr(val, 'hex'):       # UUID
            d[field] = str(val)
        elif hasattr(val, 'isoformat'): # datetime
            d[field] = val.isoformat()
        else:
            d[field] = val
    return d


# ─── Queries Q1–Q8 ──────────────────────────────────────────────────────────

def q1_eventos_por_usuario(user_id):
    rows = get_session().execute("""
        SELECT user_id, date, event_type, pet_id, shelter_id, details
        FROM eventos_por_usuario
        WHERE user_id = %s
    """, (user_id,))
    return [_to_dict(r) for r in rows]


def q2_eventos_por_perro(pet_id):
    rows = get_session().execute("""
        SELECT pet_id, date, event_type, event_id, user_id, shelter_id, details
        FROM eventos_por_perro
        WHERE pet_id = %s
    """, (pet_id,))
    return [_to_dict(r) for r in rows]


def q3_eventos_por_refugio(shelter_id):
    rows = get_session().execute("""
        SELECT shelter_id, date, event_type, event_id, pet_id, user_id, details
        FROM eventos_por_refugio
        WHERE shelter_id = %s
    """, (shelter_id,))
    return [_to_dict(r) for r in rows]


def q4_eventos_por_usuario_y_perro(user_id, pet_id):
    rows = get_session().execute("""
        SELECT user_id, pet_id, date, event_type, event_id, shelter_id, details
        FROM eventos_por_usuario_y_perro
        WHERE user_id = %s AND pet_id = %s
    """, (user_id, pet_id))
    return [_to_dict(r) for r in rows]


def q5_eventos_por_tipo(event_type):
    rows = get_session().execute("""
        SELECT event_type, date, event_id, pet_id, user_id, shelter_id, details
        FROM eventos_por_tipo
        WHERE event_type = %s
    """, (event_type,))
    return [_to_dict(r) for r in rows]


def q6_favoritos_por_usuario(user_id):
    rows = get_session().execute("""
        SELECT user_id, date, pet_id, shelter_id, details
        FROM favoritos_por_usuario
        WHERE user_id = %s
    """, (user_id,))
    return [_to_dict(r) for r in rows]


def q7_solicitudes_por_usuario(user_id):
    rows = get_session().execute("""
        SELECT user_id, date, event_id, pet_id, shelter_id, status, details
        FROM solicitudes_por_usuario
        WHERE user_id = %s
    """, (user_id,))
    return [_to_dict(r) for r in rows]


def q8_eventos_por_refugio_y_fecha(shelter_id, date_from, date_to):
    rows = get_session().execute("""
        SELECT shelter_id, date, event_type, event_id, pet_id, user_id, details
        FROM eventos_por_refugio_y_fecha
        WHERE shelter_id = %s AND date >= %s AND date <= %s
    """, (shelter_id, date_from, date_to))
    return [_to_dict(r) for r in rows]
