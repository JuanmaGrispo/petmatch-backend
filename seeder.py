"""
Seeder de Cassandra (Astra DB) para PetMatch.

Genera N eventos con distribución de tipos pre-definida y los inserta
DENORMALIZADOS en las 5 tablas del modelo Chebotko (modelo query-driven).

A diferencia de versiones anteriores, NO se usa BatchStatement multi-partición:
en Cassandra un batch que toca muchas particiones distintas degrada el
rendimiento (los batches son para atomicidad, no para escritura masiva).
Se usan inserts asíncronos individuales (execute_async), que rinden mejor
a volumen.

Modelo de 5 tablas:
    eventos_por_usuario           PK user_id        CK (date DESC, event_id)
    eventos_por_perro             PK pet_id         CK (date DESC, event_id)
    eventos_por_refugio_y_fecha   PK shelter_id     CK (date DESC, event_id)
    solicitudes_por_usuario       PK user_id        CK (date DESC, event_id)
    solicitudes_por_refugio       PK shelter_id     CK (status, date DESC, event_id)

Fan-out por tipo de evento:
    visita / favorito   → eventos_por_usuario, eventos_por_perro, eventos_por_refugio_y_fecha
    solicitud / decision→ las 3 anteriores + solicitudes_por_usuario + solicitudes_por_refugio

Uso:
    python seeder.py                    # 2000 eventos
    python seeder.py --n 500            # 500 eventos
    python seeder.py --truncate         # TRUNCATE antes de sembrar
    python seeder.py --seed 42          # semilla reproducible
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID, uuid4

from faker import Faker

try:
    from clients import cassandra_client
except Exception as e:
    print(f"[WARN] Cassandra no disponible en seeder: {e}")
    cassandra_client = None

import clients.mongo_client as mongo

# ─── Parámetros del dataset ─────────────────────────────────────────────────

N_USERS = 30
N_PETS = 50
N_SHELTERS = 10
DEFAULT_N_EVENTS = 2000

# Tipos de evento del dominio. 'decision' reemplaza al viejo 'rechazo':
# representa la RESOLUCIÓN de una solicitud (aprobada / rechazada), modelada
# como un evento append-only, no como una edición del estado anterior.
EVENT_TYPES = ["visita", "favorito", "solicitud", "decision"]
EVENT_TYPE_WEIGHTS = [0.50, 0.20, 0.20, 0.10]

# El status solo aplica a eventos de solicitud y decision.
SOLICITUD_STATUSES = ["pendiente", "aprobada", "rechazada"]
SOLICITUD_STATUS_WEIGHTS = [0.60, 0.25, 0.15]

# Pool de templates para `details` por tipo (Faker llena los huecos)
DETAILS_TEMPLATES: dict[str, list[str]] = {
    "visita": [
        "Visita al refugio para conocer al perro",
        "Segunda visita, jugó en el patio",
        "Visita acompañada por la familia",
        "Conoció a {name} en persona",
    ],
    "favorito": [
        "Marcado como favorito desde la app",
        "Lo agregó a su lista de seguidos",
        "Compartió la ficha en redes",
    ],
    "solicitud": [
        "Solicitud de adopción enviada",
        "Inició proceso de adopción",
        "Completó el formulario de adopción",
    ],
    "decision": [
        "El refugio aprobó la solicitud",
        "El refugio rechazó la solicitud (no apto)",
        "Resolución tras la entrevista",
    ],
}


# ─── Generación de IDs y dataset ────────────────────────────────────────────

def build_pool(faker: Faker) -> dict:
    """
    Genera el pool fijo de entidades. Los IDs son UUIDs inventados:
    Cassandra no tiene trazabilidad con los otros motores (decisión de diseño
    del TP). pet_to_shelter mantiene la coherencia de que un perro pertenece
    siempre al mismo refugio.
    """
    users = [uuid4() for _ in range(N_USERS)]
    pets = [uuid4() for _ in range(N_PETS)]
    shelters = [uuid4() for _ in range(N_SHELTERS)]
    pet_to_shelter = {p: random.choice(shelters) for p in pets}
    return {
        "users": users,
        "pets": pets,
        "shelters": shelters,
        "pet_to_shelter": pet_to_shelter,
    }


def random_date_last_year() -> datetime:
    now = datetime.now(timezone.utc)
    delta_seconds = random.randint(0, 365 * 24 * 3600)
    return now - timedelta(seconds=delta_seconds)


def render_details(faker: Faker, event_type: str) -> str:
    template = random.choice(DETAILS_TEMPLATES[event_type])
    return template.format(name=faker.first_name())


def _slug(texto: str) -> str:
    """Normaliza un texto para usarlo en un email: quita acentos, espacios
    y caracteres raros, y lo pasa a minúsculas. 'José Pérez' → 'jose.perez'."""
    import unicodedata
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return t.lower().replace(" ", "").replace("'", "")


# ─── Statements preparados (modelo de 5 tablas) ─────────────────────────────

def prepare_statements(session) -> dict:
    """
    Prepara los INSERT de las 5 tablas. event_id está presente en TODAS
    porque forma parte de la clustering key (garantiza unicidad: dos eventos
    en el mismo timestamp no se pisan).
    """
    return {
        "eventos_por_usuario": session.prepare("""
            INSERT INTO eventos_por_usuario
                (user_id, date, event_id, event_type, pet_id, shelter_id, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """),
        "eventos_por_perro": session.prepare("""
            INSERT INTO eventos_por_perro
                (pet_id, date, event_id, event_type, user_id, shelter_id, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """),
        "eventos_por_refugio_y_fecha": session.prepare("""
            INSERT INTO eventos_por_refugio_y_fecha
                (shelter_id, date, event_id, event_type, pet_id, user_id, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """),
        "solicitudes_por_usuario": session.prepare("""
            INSERT INTO solicitudes_por_usuario
                (user_id, date, event_id, pet_id, shelter_id, status, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """),
        "solicitudes_por_refugio": session.prepare("""
            INSERT INTO solicitudes_por_refugio
                (shelter_id, status, date, event_id, user_id, pet_id, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """),
    }


# ─── Inserción denormalizada (fan-out asíncrono) ────────────────────────────

def write_event(session, stmts: dict, *, event_id: UUID, user_id: UUID,
                pet_id: UUID, shelter_id: UUID, event_type: str,
                date: datetime, details: str, status: str | None) -> list[str]:
    """
    Escribe un evento en las tablas que correspondan según su tipo, usando
    execute_async (no batch). Devuelve la lista de tablas escritas.

    Fan-out:
      - todos los eventos          → eventos_por_usuario, eventos_por_perro,
                                      eventos_por_refugio_y_fecha
      - solicitud / decision       → además solicitudes_por_usuario,
                                      solicitudes_por_refugio
    """
    futures = []
    tablas: list[str] = []

    # — 3 tablas de evento (todas las filas) —
    futures.append(session.execute_async(
        stmts["eventos_por_usuario"],
        (user_id, date, event_id, event_type, pet_id, shelter_id, details)))
    tablas.append("eventos_por_usuario")

    futures.append(session.execute_async(
        stmts["eventos_por_perro"],
        (pet_id, date, event_id, event_type, user_id, shelter_id, details)))
    tablas.append("eventos_por_perro")

    futures.append(session.execute_async(
        stmts["eventos_por_refugio_y_fecha"],
        (shelter_id, date, event_id, event_type, pet_id, user_id, details)))
    tablas.append("eventos_por_refugio_y_fecha")

    # — 2 tablas de solicitud (solo solicitud / decision) —
    if event_type in ("solicitud", "decision"):
        futures.append(session.execute_async(
            stmts["solicitudes_por_usuario"],
            (user_id, date, event_id, pet_id, shelter_id, status, details)))
        tablas.append("solicitudes_por_usuario")

        futures.append(session.execute_async(
            stmts["solicitudes_por_refugio"],
            (shelter_id, status, date, event_id, user_id, pet_id, details)))
        tablas.append("solicitudes_por_refugio")

    # Esperamos a que terminen los inserts de este evento.
    for f in futures:
        f.result()

    return tablas


# ─── Orquestación ───────────────────────────────────────────────────────────

def run(
    n_events: int = DEFAULT_N_EVENTS,
    truncate: bool = False,
    seed: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    """
    Ejecuta el seeder y devuelve un resumen.

    Args:
        n_events: cantidad total de eventos a generar.
        truncate: si True, hace TRUNCATE de las 5 tablas antes.
        seed: semilla para `random` y `Faker` (reproducibilidad).
        progress: callback opcional `(done, total)` para reportar avance.
    """
    if seed is not None:
        random.seed(seed)
        Faker.seed(seed)

    faker = Faker("es_ES")
    session = cassandra_client.get_session()

    if truncate:
        cassandra_client.truncate_tables()

    pool = build_pool(faker)
    stmts = prepare_statements(session)

    counts: dict[str, int] = {t: 0 for t in EVENT_TYPES}
    status_counts: dict[str, int] = {s: 0 for s in SOLICITUD_STATUSES}

    for i in range(n_events):
        event_type = random.choices(EVENT_TYPES, weights=EVENT_TYPE_WEIGHTS, k=1)[0]
        user_id = random.choice(pool["users"])
        pet_id = random.choice(pool["pets"])
        shelter_id = pool["pet_to_shelter"][pet_id]
        date = random_date_last_year()
        details = render_details(faker, event_type)

        # status solo para solicitud y decision
        status = None
        if event_type in ("solicitud", "decision"):
            status = random.choices(SOLICITUD_STATUSES,
                                    weights=SOLICITUD_STATUS_WEIGHTS, k=1)[0]
            status_counts[status] += 1

        write_event(
            session, stmts,
            event_id=uuid4(),
            user_id=user_id,
            pet_id=pet_id,
            shelter_id=shelter_id,
            event_type=event_type,
            date=date,
            details=details,
            status=status,
        )

        counts[event_type] += 1

        if progress and (i + 1) % 100 == 0:
            progress(i + 1, n_events)

    if progress:
        progress(n_events, n_events)

    return {
        "n_events": n_events,
        "by_type": counts,
        "solicitud_by_status": status_counts,
        "users": len(pool["users"]),
        "pets": len(pool["pets"]),
        "shelters": len(pool["shelters"]),
        "truncated": truncate,
    }


# ════════════════════════════════════════════════════════════════════════════
# MONGO — Generadores de documentos  (SIN CAMBIOS)
# ════════════════════════════════════════════════════════════════════════════

# Valores posibles para cada campo (refleja los datos reales de los CSVs)
TIPOS_ANIMAL   = ["Perro", "Gato"]
TIPO_WEIGHTS   = [0.60, 0.40]          # 60% perros, 40% gatos — igual que el CSV original

ESTADOS_ANIMAL = ["Disponible", "Adoptado", "En tránsito", "Devuelto"]
ESTADO_WEIGHTS = [0.50, 0.25, 0.15, 0.10]

REFUGIOS       = ["Huellitas", "Patitas Felices"]

SEXOS_ANIMAL   = ["Macho", "Hembra"]

RAZAS = {
    "Perro": [
        "Mestizo", "Labrador", "Golden Retriever", "Beagle",
        "Bulldog", "Poodle", "Pastor Alemán", "Chihuahua",
    ],
    "Gato": [
        "Doméstico de pelo corto", "Siamés", "Persa", "Maine Coon",
        "Mestizo", "Bengalí", "Ragdoll",
    ],
}

COLORES = [
    "Negro", "Blanco", "Marrón", "Gris", "Naranja",
    "Blanco y Negro", "Marrón y Blanco", "Tricolor",
]

# Catálogo de vacunas por tipo de animal (para el sub-documento salud.vacunas)
VACUNAS = {
    "Perro": ["Antirrábica", "Quíntuple", "Séxtuple", "Tos de las perreras", "Giardia"],
    "Gato":  ["Antirrábica", "Triple Felina", "Leucemia Felina", "Rinotraqueítis"],
}

# Tags de comportamiento/características (para el array simple animal.tags)
TAGS = [
    "sociable", "energético", "tranquilo", "bueno_con_niños",
    "bueno_con_otros_animales", "juguetón", "guardián", "cariñoso",
    "independiente", "entrenado",
]

TIPOS_VIVIENDA   = ["Casa", "Departamento", "Casa con patio", "Casa de campo"]
EXPERIENCIAS     = ["Alta", "Media", "Baja"]
SEXOS_PERSONA    = ["M", "F"]
CIUDADES = [
    "Buenos Aires", "Córdoba", "Rosario", "Mendoza", "La Plata",
    "San Miguel de Tucumán", "Mar del Plata", "Salta", "Santa Fe", "Quilmes",
]
PROVINCIAS = {
    "Buenos Aires" : "Buenos Aires",
    "Córdoba"      : "Córdoba",
    "Rosario"      : "Santa Fe",
    "Mendoza"      : "Mendoza",
    "La Plata"     : "Buenos Aires",
    "San Miguel de Tucumán": "Tucumán",
    "Mar del Plata": "Buenos Aires",
    "Salta"        : "Salta",
    "Santa Fe"     : "Santa Fe",
    "Quilmes"      : "Buenos Aires",
}


def _generar_vacunas(faker, tipo: str, fecha_ingreso) -> list:
    """
    Genera entre 0 y 3 vacunas para un animal.
    - Algunos animales quedan SIN vacunas (array vacío) → demuestra el esquema flexible.
    - Cada vacuna es un OBJETO {nombre, fecha} → array de documentos embebidos.
    - La fecha de cada vacuna es POSTERIOR al ingreso del animal (coherencia temporal).
    """
    cantidad = random.choices([0, 1, 2, 3], weights=[0.15, 0.35, 0.35, 0.15], k=1)[0]
    if cantidad == 0:
        return []

    nombres = random.sample(VACUNAS[tipo], k=min(cantidad, len(VACUNAS[tipo])))

    vacunas = []
    for nombre in nombres:
        fecha_vac = faker.date_between(start_date=fecha_ingreso, end_date="today")
        vacunas.append({
            "nombre": nombre,
            "fecha": datetime.combine(fecha_vac, datetime.min.time()),
        })
    return vacunas


def _generar_animal(faker, indice: int) -> dict:
    """Genera un documento de animal con Faker."""
    tipo = random.choices(TIPOS_ANIMAL, weights=TIPO_WEIGHTS, k=1)[0]
    fecha_nac = faker.date_of_birth(minimum_age=0, maximum_age=10)
    fecha_ingreso = faker.date_between(start_date=fecha_nac, end_date="today")

    return {
        "animal_id"       : f"A{indice:06d}",
        "nombre"          : faker.first_name(),
        "tipo"            : tipo,
        "raza"            : random.choice(RAZAS[tipo]),
        "color"           : random.choice(COLORES),
        "sexo"            : random.choice(SEXOS_ANIMAL),
        "fecha_nacimiento": datetime.combine(fecha_nac, datetime.min.time()),
        "fecha_ingreso"   : datetime.combine(fecha_ingreso, datetime.min.time()),
        "estado"          : random.choices(ESTADOS_ANIMAL, weights=ESTADO_WEIGHTS, k=1)[0],
        "refugio"         : random.choice(REFUGIOS),
        "salud": {
            "castrado"     : random.choice([True, False]),
            "desparasitado": random.choice([True, False]),
            "vacunas"      : _generar_vacunas(faker, tipo, fecha_ingreso),
        },
        "tags": random.sample(TAGS, k=random.randint(1, 3)),
    }


def _generar_adoptante(faker, indice: int, animal_ids: list) -> dict:
    """Genera un documento de adoptante con Faker."""
    ciudad = random.choice(CIUDADES)
    animal_id = random.choice(animal_ids) if random.random() < 0.40 else None
    fecha_nac = faker.date_of_birth(minimum_age=18, maximum_age=70)

    nombre   = faker.first_name()
    apellido = faker.last_name()
    if random.random() < 0.12:
        email = None
    else:
        dominio = random.choice(["gmail.com", "hotmail.com", "outlook.com", "yahoo.com.ar"])
        base    = _slug(nombre) + "." + _slug(apellido)
        email   = f"{base}{random.randint(1, 99)}@{dominio}"

    doc = {
        "person_id"           : f"P{indice:05d}",
        "nombre"              : nombre,
        "apellido"            : apellido,
        "fecha_nacimiento"    : datetime.combine(fecha_nac, datetime.min.time()),
        "edad"                : (
            __import__("datetime").date.today() - fecha_nac
        ).days // 365,
        "sexo"                : random.choice(SEXOS_PERSONA),
        "telefono"            : faker.phone_number(),
        "perfil": {
            "ciudad"              : ciudad,
            "provincia"           : PROVINCIAS[ciudad],
            "tipo_vivienda"       : random.choice(TIPOS_VIVIENDA),
            "experiencia_mascotas": random.choice(EXPERIENCIAS),
        },
        "animal_id"           : animal_id,
    }
    if email is not None:
        doc["email"] = email
    return doc


def run_mongo(
    n_animales: int = 1000,
    n_adoptantes: int = 1000,
    truncate: bool = False,
    seed: int | None = None,
) -> dict:
    """Siembra las colecciones 'animales' y 'adoptantes' en MongoDB."""
    if seed is not None:
        random.seed(seed)
        Faker.seed(seed)

    faker = Faker("es_AR")
    db = mongo.get_db()

    if truncate:
        db["animales"].drop()
        db["adoptantes"].drop()

    mongo.ensure_indexes()

    animales_docs = [_generar_animal(faker, i + 1) for i in range(n_animales)]
    db["animales"].insert_many(animales_docs, ordered=False)

    animal_ids = [d["animal_id"] for d in animales_docs]

    adoptantes_docs = [
        _generar_adoptante(faker, i + 1, animal_ids)
        for i in range(n_adoptantes)
    ]
    db["adoptantes"].insert_many(adoptantes_docs, ordered=False)

    estados = {}
    for doc in animales_docs:
        estados[doc["estado"]] = estados.get(doc["estado"], 0) + 1

    con_animal = sum(1 for d in adoptantes_docs if d["animal_id"] is not None)

    return {
        "animales_insertados" : n_animales,
        "adoptantes_insertados": n_adoptantes,
        "animales_por_estado" : estados,
        "adoptantes_con_animal": con_animal,
        "truncated"           : truncate,
    }


# ─── CLI ────────────────────────────────────────────────────────────────────

def _cli():
    parser = argparse.ArgumentParser(description="Seeder de Cassandra para PetMatch")
    parser.add_argument("--n", type=int, default=DEFAULT_N_EVENTS,
                        help=f"Cantidad de eventos (default: {DEFAULT_N_EVENTS})")
    parser.add_argument("--truncate", action="store_true",
                        help="TRUNCATE las 5 tablas antes de sembrar")
    parser.add_argument("--seed", type=int, default=None,
                        help="Semilla para reproducibilidad")
    parser.add_argument("--mongo", action="store_true",
                    help="Sembrar MongoDB (animales + adoptantes)")
    parser.add_argument("--mongo-animales", type=int, default=1000)
    parser.add_argument("--mongo-adoptantes", type=int, default=1000)
    parser.add_argument("--solo-mongo", action="store_true",
                        help="Sembrar solo MongoDB, sin correr Cassandra")

    args = parser.parse_args()

    def _progress(done: int, total: int):
        pct = 100 * done / total
        print(f"  {done:>5}/{total} ({pct:5.1f}%)")

    if not args.solo_mongo:
        print(f"Sembrando {args.n} eventos…")
        if args.truncate:
            print("  → TRUNCATE de 5 tablas")
        summary = run(n_events=args.n, truncate=args.truncate,
                    seed=args.seed, progress=_progress)

        print("\nResumen:")
        print(f"  Total eventos:         {summary['n_events']}")
        print(f"  Por tipo:              {summary['by_type']}")
        print(f"  Solicitudes por status:{summary['solicitud_by_status']}")
        print(f"  Pool: {summary['users']} users · "
            f"{summary['pets']} pets · {summary['shelters']} shelters")

    if args.mongo or args.solo_mongo:
        print(f"Sembrando MongoDB — {args.mongo_animales} animales, "
              f"{args.mongo_adoptantes} adoptantes…")
        summary_mongo = run_mongo(
            n_animales=args.mongo_animales,
            n_adoptantes=args.mongo_adoptantes,
            truncate=args.truncate,
            seed=args.seed,
        )
        print("\nResumen MongoDB:")
        print(f"  Animales:   {summary_mongo['animales_insertados']}")
        print(f"  Adoptantes: {summary_mongo['adoptantes_insertados']}")
        print(f"  Por estado: {summary_mongo['animales_por_estado']}")
        print(f"  Con animal asignado: {summary_mongo['adoptantes_con_animal']}")


if __name__ == "__main__":
    _cli()
