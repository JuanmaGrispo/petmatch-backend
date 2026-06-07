-- ============================================================================
-- Inicialización del keyspace de Cassandra para PetMatch.
-- ============================================================================
-- Este script lo ejecuta el servicio `cassandra-init` del docker-compose una
-- vez que Cassandra está healthy. Es idempotente (IF NOT EXISTS), así que es
-- seguro re-correrlo.
--
-- Las TABLAS no se crean acá: las crea el cliente Python (`create_tables()` /
-- `truncate_tables()`) para que el modelo viva en un solo lugar y se pueda
-- evolucionar desde el código.
-- ============================================================================

CREATE KEYSPACE IF NOT EXISTS petmatch
    WITH replication = {
        'class': 'SimpleStrategy',
        'replication_factor': 1
    };
