-- ============================================================================
-- PetMatch — Modelo Cassandra (Chebotko)
-- ============================================================================
-- En Astra DB el keyspace `petmatch` ya existe (no se puede ejecutar
-- CREATE KEYSPACE allí). Este archivo es la referencia equivalente para
-- correr el modelo en una Cassandra local (`cqlsh localhost 9042 -f cql/create_keyspace.cql`).
-- Las 8 tablas de abajo son las mismas que `cassandra_client.create_tables()`
-- crea programáticamente en Astra.
-- ============================================================================

CREATE KEYSPACE IF NOT EXISTS petmatch
    WITH replication = {
        'class': 'SimpleStrategy',
        'replication_factor': 1
    };

USE petmatch;

-- ─── Q1 — eventos de un usuario, por fecha DESC ─────────────────────────────
CREATE TABLE IF NOT EXISTS eventos_por_usuario (
    user_id    UUID,
    date       TIMESTAMP,
    event_type TEXT,
    pet_id     UUID,
    shelter_id UUID,
    details    TEXT,
    PRIMARY KEY (user_id, date)
) WITH CLUSTERING ORDER BY (date DESC);

-- ─── Q2 — eventos de un perro, por fecha DESC ───────────────────────────────
CREATE TABLE IF NOT EXISTS eventos_por_perro (
    pet_id     UUID,
    date       TIMESTAMP,
    event_type TEXT,
    event_id   UUID,
    user_id    UUID,
    shelter_id UUID,
    details    TEXT,
    PRIMARY KEY (pet_id, date)
) WITH CLUSTERING ORDER BY (date DESC);

-- ─── Q3 — eventos de un refugio, por fecha DESC ─────────────────────────────
CREATE TABLE IF NOT EXISTS eventos_por_refugio (
    shelter_id UUID,
    date       TIMESTAMP,
    event_type TEXT,
    event_id   UUID,
    pet_id     UUID,
    user_id    UUID,
    details    TEXT,
    PRIMARY KEY (shelter_id, date)
) WITH CLUSTERING ORDER BY (date DESC);

-- ─── Q4 — eventos de un usuario sobre un perro, por fecha DESC ──────────────
-- Composite partition key: (user_id, pet_id)
CREATE TABLE IF NOT EXISTS eventos_por_usuario_y_perro (
    user_id    UUID,
    pet_id     UUID,
    date       TIMESTAMP,
    event_type TEXT,
    event_id   UUID,
    shelter_id UUID,
    details    TEXT,
    PRIMARY KEY ((user_id, pet_id), date)
) WITH CLUSTERING ORDER BY (date DESC);

-- ─── Q5 — eventos de un tipo, por fecha DESC ────────────────────────────────
CREATE TABLE IF NOT EXISTS eventos_por_tipo (
    event_type TEXT,
    date       TIMESTAMP,
    event_id   UUID,
    pet_id     UUID,
    user_id    UUID,
    shelter_id UUID,
    details    TEXT,
    PRIMARY KEY (event_type, date)
) WITH CLUSTERING ORDER BY (date DESC);

-- ─── Q6 — favoritos de un usuario, por fecha DESC ───────────────────────────
CREATE TABLE IF NOT EXISTS favoritos_por_usuario (
    user_id    UUID,
    date       TIMESTAMP,
    pet_id     UUID,
    shelter_id UUID,
    details    TEXT,
    PRIMARY KEY (user_id, date)
) WITH CLUSTERING ORDER BY (date DESC);

-- ─── Q7 — solicitudes de adopción de un usuario, por fecha DESC ─────────────
CREATE TABLE IF NOT EXISTS solicitudes_por_usuario (
    user_id    UUID,
    date       TIMESTAMP,
    event_id   UUID,
    pet_id     UUID,
    shelter_id UUID,
    status     TEXT,
    details    TEXT,
    PRIMARY KEY (user_id, date)
) WITH CLUSTERING ORDER BY (date DESC);

-- ─── Q8 — eventos de un refugio en rango de fechas, por fecha DESC ──────────
CREATE TABLE IF NOT EXISTS eventos_por_refugio_y_fecha (
    shelter_id UUID,
    date       TIMESTAMP,
    event_type TEXT,
    event_id   UUID,
    pet_id     UUID,
    user_id    UUID,
    details    TEXT,
    PRIMARY KEY (shelter_id, date)
) WITH CLUSTERING ORDER BY (date DESC);
