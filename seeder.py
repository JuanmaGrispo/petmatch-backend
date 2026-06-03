"""
Seeder de Cassandra (Astra DB) para PetMatch.

Genera N eventos con distribución de tipos pre-definida y los inserta
denormalizados en las 8 tablas del modelo Chebotko usando BatchStatement
UNLOGGED (recomendado para escrituras multi-partición).

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

from cassandra.query import BatchStatement, BatchType
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

EVENT_TYPES = ["visita", "favorito", "solicitud", "rechazo"]
EVENT_TYPE_WEIGHTS = [0.50, 0.20, 0.20, 0.10]

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
    "rechazo": [
        "El refugio rechazó la solicitud (no apto)",
        "Rechazo por inconsistencia en la verificación",
        "El postulante canceló el proceso",
    ],
}


# ─── Generación de IDs y dataset ────────────────────────────────────────────

def build_pool(faker: Faker) -> dict:
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


# ─── Statements preparados ──────────────────────────────────────────────────

def prepare_statements(session) -> dict:
    return {
        "eventos_por_usuario": session.prepare("""
            INSERT INTO eventos_por_usuario (user_id, date, event_type, pet_id, shelter_id, details)
            VALUES (?, ?, ?, ?, ?, ?)
        """),
        "eventos_por_perro": session.prepare("""
            INSERT INTO eventos_por_perro (pet_id, date, event_type, event_id, user_id, shelter_id, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """),
        "eventos_por_refugio": session.prepare("""
            INSERT INTO eventos_por_refugio (shelter_id, date, event_type, event_id, pet_id, user_id, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """),
        "eventos_por_usuario_y_perro": session.prepare("""
            INSERT INTO eventos_por_usuario_y_perro (user_id, pet_id, date, event_type, event_id, shelter_id, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """),
        "eventos_por_tipo": session.prepare("""
            INSERT INTO eventos_por_tipo (event_type, date, event_id, pet_id, user_id, shelter_id, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """),
        "eventos_por_refugio_y_fecha": session.prepare("""
            INSERT INTO eventos_por_refugio_y_fecha (shelter_id, date, event_type, event_id, pet_id, user_id, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """),
        "favoritos_por_usuario": session.prepare("""
            INSERT INTO favoritos_por_usuario (user_id, date, pet_id, shelter_id, details)
            VALUES (?, ?, ?, ?, ?)
        """),
        "solicitudes_por_usuario": session.prepare("""
            INSERT INTO solicitudes_por_usuario (user_id, date, event_id, pet_id, shelter_id, status, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """),
    }


# ─── Inserción denormalizada ────────────────────────────────────────────────

def build_event_batch(stmts: dict, *, event_id: UUID, user_id: UUID, pet_id: UUID,
                      shelter_id: UUID, event_type: str, date: datetime,
                      details: str, status: str | None) -> BatchStatement:
    """
    Construye un BatchStatement UNLOGGED con los inserts a las tablas
    correspondientes al evento. Todos los eventos van a las 6 tablas de
    eventos; favoritos y solicitudes además van a su tabla específica.
    """
    batch = BatchStatement(batch_type=BatchType.UNLOGGED)

    batch.add(stmts["eventos_por_usuario"],
              (user_id, date, event_type, pet_id, shelter_id, details))
    batch.add(stmts["eventos_por_perro"],
              (pet_id, date, event_type, event_id, user_id, shelter_id, details))
    batch.add(stmts["eventos_por_refugio"],
              (shelter_id, date, event_type, event_id, pet_id, user_id, details))
    batch.add(stmts["eventos_por_usuario_y_perro"],
              (user_id, pet_id, date, event_type, event_id, shelter_id, details))
    batch.add(stmts["eventos_por_tipo"],
              (event_type, date, event_id, pet_id, user_id, shelter_id, details))
    batch.add(stmts["eventos_por_refugio_y_fecha"],
              (shelter_id, date, event_type, event_id, pet_id, user_id, details))

    if event_type == "favorito":
        batch.add(stmts["favoritos_por_usuario"],
                  (user_id, date, pet_id, shelter_id, details))
    elif event_type == "solicitud":
        batch.add(stmts["solicitudes_por_usuario"],
                  (user_id, date, event_id, pet_id, shelter_id, status, details))

    return batch


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
        truncate: si True, hace TRUNCATE de las 8 tablas antes.
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

        status = None
        if event_type == "solicitud":
            status = random.choices(SOLICITUD_STATUSES,
                                    weights=SOLICITUD_STATUS_WEIGHTS, k=1)[0]
            status_counts[status] += 1

        batch = build_event_batch(
            stmts,
            event_id=uuid4(),
            user_id=user_id,
            pet_id=pet_id,
            shelter_id=shelter_id,
            event_type=event_type,
            date=date,
            details=details,
            status=status,
        )
        session.execute(batch)

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
 
 
# ════════════════════════════════════════════════════════════════════════════
# MONGO — Generadores de documentos
# ════════════════════════════════════════════════════════════════════════════
 
def _generar_animal(faker, indice: int) -> dict:
    """
    Genera un documento de animal con Faker.
    Los campos y valores replican exactamente el schema del CSV original,
    con las mismas transformaciones (tipo en español, estado en español, etc.)
    """
    tipo = random.choices(TIPOS_ANIMAL, weights=TIPO_WEIGHTS, k=1)[0]
 
    # Fecha de nacimiento: entre 1 y 10 años atrás
    fecha_nac = faker.date_of_birth(minimum_age=0, maximum_age=10)
 
    # Fecha de ingreso: posterior a la fecha de nacimiento
    fecha_ingreso = faker.date_between(start_date=fecha_nac, end_date="today")
 
    return {
        "animal_id"       : f"A{indice:06d}",          # ej: A000001
        "nombre"          : faker.first_name(),
        "tipo"            : tipo,
        "raza"            : random.choice(RAZAS[tipo]),
        "color"           : random.choice(COLORES),
        "fecha_nacimiento": fecha_nac.strftime("%Y-%m-%d"),
        "fecha_ingreso"   : fecha_ingreso.strftime("%Y-%m-%d"),
        "sexo"            : random.choice(SEXOS_ANIMAL),
        "estado"          : random.choices(ESTADOS_ANIMAL, weights=ESTADO_WEIGHTS, k=1)[0],
        "refugio"         : random.choice(REFUGIOS),
    }
 
 
def _generar_adoptante(faker, indice: int, animal_ids: list) -> dict:
    """
    Genera un documento de adoptante con Faker.
    El 40% de los adoptantes tiene un animal_id asignado
    (simula adopciones realizadas), el resto tiene None.
    """
    ciudad = random.choice(CIUDADES)
 
    # 40% de adoptantes tienen un animal asignado
    animal_id = random.choice(animal_ids) if random.random() < 0.40 else None
 
    fecha_nac = faker.date_of_birth(minimum_age=18, maximum_age=70)
 
    return {
        "person_id"           : f"P{indice:05d}",       # ej: P00001
        "nombre"              : faker.first_name(),
        "apellido"            : faker.last_name(),
        "fecha_nacimiento"    : fecha_nac.strftime("%Y-%m-%d"),
        "edad"                : (
            __import__("datetime").date.today() - fecha_nac
        ).days // 365,
        "sexo"                : random.choice(SEXOS_PERSONA),
        "ciudad"              : ciudad,
        "provincia"           : PROVINCIAS[ciudad],
        "telefono"            : faker.phone_number(),
        "email"               : faker.email(),
        "tipo_vivienda"       : random.choice(TIPOS_VIVIENDA),
        "experiencia_mascotas": random.choice(EXPERIENCIAS),
        "animal_id"           : animal_id,
    }
 
 
# ════════════════════════════════════════════════════════════════════════════
# MONGO — Función principal del seeder
# ════════════════════════════════════════════════════════════════════════════
 
def run_mongo(
    n_animales: int = 1000,
    n_adoptantes: int = 1000,
    truncate: bool = False,
    seed: int | None = None,
) -> dict:
    """
    Siembra las colecciones 'animales' y 'adoptantes' en MongoDB.
 
    Misma firma que run() de Cassandra para mantener consistencia.
 
    Args:
        n_animales  : cantidad de documentos a insertar en 'animales'.
        n_adoptantes: cantidad de documentos a insertar en 'adoptantes'.
        truncate    : si True, vacía las colecciones antes de sembrar.
        seed        : semilla para reproducibilidad (mismo que Cassandra).
 
    Returns:
        dict con resumen de la operación.
    """
    if seed is not None:
        random.seed(seed)
        Faker.seed(seed)
 
    # Faker en español argentino para nombres y datos locales
    faker = Faker("es_AR")
 
    db = mongo.get_db()
 
    # — Truncate opcional —
    if truncate:
        db["animales"].drop()
        db["adoptantes"].drop()
 
    # — Crear índices (idempotente) —
    mongo.ensure_indexes()
 
    # — Sembrar animales —
    animales_docs = [_generar_animal(faker, i + 1) for i in range(n_animales)]
    db["animales"].insert_many(animales_docs, ordered=False)
 
    # — Obtener los animal_ids generados para asignarlos a adoptantes —
    animal_ids = [d["animal_id"] for d in animales_docs]
 
    # — Sembrar adoptantes —
    adoptantes_docs = [
        _generar_adoptante(faker, i + 1, animal_ids)
        for i in range(n_adoptantes)
    ]
    db["adoptantes"].insert_many(adoptantes_docs, ordered=False)
 
    # — Resumen —
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
                        help="TRUNCATE las 8 tablas antes de sembrar")
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
            print("  → TRUNCATE de 8 tablas")
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
