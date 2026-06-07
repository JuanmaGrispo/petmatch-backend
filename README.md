# petmatch-backend

Backend de la aplicación PetMatch construido con Flask. Sirve como demostración de consultas nativas en distintos motores de base de datos (Cassandra, MongoDB, Redis, Neo4j).

---

## Estructura

```
backend/
├── app.py                  # Entry point. Crea la app Flask y registra las rutas.
├── routes.py               # Blueprint con todas las rutas HTTP del proyecto.
├── clients/
│   ├── __init__.py
│   └── cassandra_client.py # Cliente Cassandra: conexión a Astra DB y queries CQL nativos.
├── templates/
│   ├── index.html          # Menú principal con acceso a cada motor de DB.
│   └── cassandra.html      # UI interactiva para ejecutar las 8 queries del modelo Chebotko.
├── requirements.txt        # Dependencias del proyecto.
└── .gitignore
```

---

## Cómo correr

```bash
# 1. Levantar Cassandra local (docker compose)
docker compose up -d cassandra cassandra-init
# Esperá ~1–2 min la primera vez (download de imagen + bootstrap).

# 2. Crear y activar el entorno virtual
python3 -m venv venv
source venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Correr el servidor
python app.py
```

La app corre en `http://localhost:9200`. Cassandra escucha en `localhost:9042`.

### Sembrar datos

Desde la UI (pestaña Mantenimiento, frase "BORRAR Y SEMBRAR") o por CLI:

```bash
python seeder.py --truncate --n 2000
```

### Apagar / borrar todo

```bash
docker compose down              # apaga, mantiene datos
docker compose down -v           # apaga y borra el volumen (DB en cero)
```

---

## Herramientas para explorar Cassandra

- **`cqlsh` (incluido en el contenedor)** — REPL oficial:
  ```bash
  docker compose exec cassandra cqlsh -u cassandra -p cassandra
  ```
- **[AxonOps Workbench](https://axonops.com/workbench/)** — app de escritorio
  específica para Cassandra (free, multi-plataforma). Lo más cómodo para ver
  schemas, ejecutar CQL y explorar particiones.
- **[DBeaver Community](https://dbeaver.io/)** — cliente DB multi-motor;
  agrega Cassandra con un driver JDBC.

---

## Arquitectura Flask

El proyecto tiene **dos capas**:

**Capa de rutas (`routes.py`)**
Define los endpoints HTTP usando un `Blueprint`. Recibe los parámetros del request, los convierte al tipo correcto (UUID, datetime) y delega la consulta al cliente correspondiente.

**Capa de cliente (`clients/cassandra_client.py`)**
Maneja la conexión a la base de datos y ejecuta las queries en el lenguaje nativo del motor. No hay ORM ni abstracción intermedia: el CQL se escribe directamente.

---

## Cassandra — Modelo Chebotko

El modelo está diseñado query-first. Cada tabla existe para responder una consulta específica:

| Query | Tabla | Partition Key | Clustering |
|---|---|---|---|
| Q1 | `eventos_por_usuario` | `user_id` | `date DESC` |
| Q2 | `eventos_por_perro` | `pet_id` | `date DESC` |
| Q3 | `eventos_por_refugio` | `shelter_id` | `date DESC` |
| Q4 | `eventos_por_usuario_y_perro` | `(user_id, pet_id)` | `date DESC` |
| Q5 | `eventos_por_tipo` | `event_type` | `date DESC` |
| Q6 | `favoritos_por_usuario` | `user_id` | `date DESC` |
| Q7 | `solicitudes_por_usuario` | `user_id` | `date DESC` |
| Q8 | `eventos_por_refugio_y_fecha` | `shelter_id` | `date DESC` (range) |

Al insertar un evento se escribe en las 6 tablas de evento simultáneamente (denormalización característica de Cassandra).

La conexión es a **Astra DB** usando token de autenticación y SSL.
