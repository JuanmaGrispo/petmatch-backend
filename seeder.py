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

from clients import cassandra_client


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


# ─── CLI ────────────────────────────────────────────────────────────────────

def _cli():
    parser = argparse.ArgumentParser(description="Seeder de Cassandra para PetMatch")
    parser.add_argument("--n", type=int, default=DEFAULT_N_EVENTS,
                        help=f"Cantidad de eventos (default: {DEFAULT_N_EVENTS})")
    parser.add_argument("--truncate", action="store_true",
                        help="TRUNCATE las 8 tablas antes de sembrar")
    parser.add_argument("--seed", type=int, default=None,
                        help="Semilla para reproducibilidad")
    args = parser.parse_args()

    def _progress(done: int, total: int):
        pct = 100 * done / total
        print(f"  {done:>5}/{total} ({pct:5.1f}%)")

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


if __name__ == "__main__":
    _cli()
