"""
clients/mongo_client.py
=======================
Cliente MongoDB para PetMatch.

Patrón: singleton de conexión (igual que cassandra_client.py y neo4j_client.py).
La variable _client se inicializa una sola vez y se reutiliza en cada request.

Colecciones:
    - animales   → datos maestros de animales del refugio
    - adoptantes → perfiles de personas interesadas en adoptar

Buenas prácticas aplicadas:
    - Conexión lazy (se abre al primer uso, no al importar)
    - Índices creados en ensure_indexes() — se llama una sola vez al levantar la app
    - Proyecciones explícitas en todas las consultas (sin _id en respuestas JSON)
    - Manejo de excepciones en cada función
    - Funciones puras: reciben parámetros, retornan datos, no imprimen a stdout
"""

import os
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import PyMongoError, DuplicateKeyError
from dotenv import load_dotenv

load_dotenv()

# ─── Configuración ───────────────────────────────────────────────────────────

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB  = os.environ.get("MONGO_DB", "petmatch")

_client = None  # Singleton — se inicializa en get_client()


# ─── Conexión ────────────────────────────────────────────────────────────────

def get_client():
    """
    Retorna el cliente MongoDB, creándolo si todavía no existe.
    Patrón idéntico al get_session() de Cassandra y get_driver() de Neo4j.
    """
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        # Ping para validar la conexión al primer uso
        _client.admin.command("ping")
    return _client


def get_db():
    """Retorna la base de datos 'petmatch'."""
    return get_client()[MONGO_DB]


def ensure_indexes():
    """
    Crea los índices necesarios si no existen.
    Idempotente: MongoDB no los duplica si ya están creados.
    Se llama una vez al iniciar la app desde app.py.

    Buena práctica: los índices se definen acá, no en el seeder,
    para que existan independientemente de si se sembró la DB.
    """
    db = get_db()

    # — animales —
    db["animales"].create_index("animal_id", unique=True, name="idx_animal_id")
    db["animales"].create_index("tipo",      name="idx_tipo")
    db["animales"].create_index("estado",    name="idx_estado")
    db["animales"].create_index("refugio",   name="idx_refugio")
    # Índice compuesto para la consulta más frecuente: tipo + estado + refugio
    db["animales"].create_index(
        [("tipo", ASCENDING), ("estado", ASCENDING), ("refugio", ASCENDING)],
        name="idx_tipo_estado_refugio"
    )

    # — adoptantes —
    db["adoptantes"].create_index("person_id", unique=True, name="idx_person_id")
    db["adoptantes"].create_index("ciudad",    name="idx_ciudad")
    db["adoptantes"].create_index("animal_id", name="idx_animal_id_adoptante")
    # Índice compuesto para búsqueda por perfil
    db["adoptantes"].create_index(
        [("ciudad", ASCENDING), ("tipo_vivienda", ASCENDING), ("experiencia_mascotas", ASCENDING)],
        name="idx_perfil_adoptante"
    )


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _clean(doc):
    """
    Convierte el ObjectId de MongoDB (_id) a string para que sea
    serializable a JSON por Flask. Retorna el doc modificado.
    """
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


def _clean_list(docs):
    return [_clean(d) for d in docs]


# ════════════════════════════════════════════════════════════════════════════
# CRUD — ANIMALES
# ════════════════════════════════════════════════════════════════════════════

# ─── CREATE ──────────────────────────────────────────────────────────────────

def insertar_animal(datos: dict) -> dict:
    """
    Inserta un nuevo animal en la colección 'animales'.

    Campos esperados: animal_id, nombre, tipo, raza, color,
                      fecha_nacimiento, fecha_ingreso, sexo, estado, refugio
    """
    try:
        col = get_db()["animales"]
        resultado = col.insert_one(datos)
        return {"inserted_id": str(resultado.inserted_id), "ok": True}
    except DuplicateKeyError:
        return {"error": f"Ya existe un animal con animal_id '{datos.get('animal_id')}'", "ok": False}
    except PyMongoError as e:
        return {"error": str(e), "ok": False}


# ─── READ ─────────────────────────────────────────────────────────────────────

def buscar_animal_por_id(animal_id: str) -> dict | None:
    """Busca un animal por su animal_id de negocio (no el _id de Mongo)."""
    try:
        doc = get_db()["animales"].find_one(
            {"animal_id": animal_id},
            {"_id": 0}
        )
        return doc
    except PyMongoError as e:
        return {"error": str(e)}


def listar_animales(limite: int = 20) -> list:
    """Retorna los primeros N animales. Usado para poblar dropdowns en la UI."""
    try:
        cursor = get_db()["animales"].find({}, {"_id": 0}).limit(limite)
        return list(cursor)
    except PyMongoError as e:
        return []


def buscar_animales_por_filtros(tipo=None, refugio=None, estado=None, sexo=None) -> list:
    """
    Búsqueda flexible con filtros opcionales combinados.
    Solo incluye en el filtro los parámetros que vienen con valor.
    """
    try:
        filtro = {}
        if tipo:    filtro["tipo"]    = tipo
        if refugio: filtro["refugio"] = refugio
        if estado:  filtro["estado"]  = estado
        if sexo:    filtro["sexo"]    = sexo

        cursor = get_db()["animales"].find(filtro, {"_id": 0})
        return list(cursor)
    except PyMongoError as e:
        return []


# ─── UPDATE ───────────────────────────────────────────────────────────────────

def actualizar_animal(animal_id: str, nuevos_datos: dict) -> dict:
    """Actualiza campos de un animal con $set."""
    try:
        res = get_db()["animales"].update_one(
            {"animal_id": animal_id},
            {"$set": nuevos_datos}
        )
        return {"modified": res.modified_count, "ok": True}
    except PyMongoError as e:
        return {"error": str(e), "ok": False}


# ─── DELETE ───────────────────────────────────────────────────────────────────

def eliminar_animal(animal_id: str) -> dict:
    """Elimina un animal por su animal_id."""
    try:
        res = get_db()["animales"].delete_one({"animal_id": animal_id})
        return {"deleted": res.deleted_count, "ok": True}
    except PyMongoError as e:
        return {"error": str(e), "ok": False}


# ════════════════════════════════════════════════════════════════════════════
# CRUD — ADOPTANTES
# ════════════════════════════════════════════════════════════════════════════

# ─── CREATE ──────────────────────────────────────────────────────────────────

def insertar_adoptante(datos: dict) -> dict:
    """
    Inserta un nuevo adoptante en la colección 'adoptantes'.

    Campos esperados: person_id, nombre, apellido, fecha_nacimiento,
                      edad, sexo, ciudad, provincia, telefono, email,
                      tipo_vivienda, experiencia_mascotas, animal_id
    """
    try:
        col = get_db()["adoptantes"]
        resultado = col.insert_one(datos)
        return {"inserted_id": str(resultado.inserted_id), "ok": True}
    except DuplicateKeyError:
        return {"error": f"Ya existe un adoptante con person_id '{datos.get('person_id')}'", "ok": False}
    except PyMongoError as e:
        return {"error": str(e), "ok": False}


# ─── READ ─────────────────────────────────────────────────────────────────────

def buscar_adoptante_por_id(person_id: str) -> dict | None:
    """Busca un adoptante por su person_id."""
    try:
        return get_db()["adoptantes"].find_one({"person_id": person_id}, {"_id": 0})
    except PyMongoError as e:
        return {"error": str(e)}


def listar_adoptantes(limite: int = 20) -> list:
    """Retorna los primeros N adoptantes. Usado para poblar dropdowns."""
    try:
        cursor = get_db()["adoptantes"].find({}, {"_id": 0}).limit(limite)
        return list(cursor)
    except PyMongoError as e:
        return []


def buscar_adoptantes_por_ciudad(ciudad: str) -> list:
    """Retorna todos los adoptantes de una ciudad específica."""
    try:
        cursor = get_db()["adoptantes"].find(
            {"ciudad": ciudad},
            {"_id": 0}
        )
        return list(cursor)
    except PyMongoError as e:
        return []


# ─── UPDATE ───────────────────────────────────────────────────────────────────

def actualizar_adoptante(person_id: str, nuevos_datos: dict) -> dict:
    """Actualiza campos de un adoptante con $set."""
    try:
        res = get_db()["adoptantes"].update_one(
            {"person_id": person_id},
            {"$set": nuevos_datos}
        )
        return {"modified": res.modified_count, "ok": True}
    except PyMongoError as e:
        return {"error": str(e), "ok": False}


# ─── DELETE ───────────────────────────────────────────────────────────────────

def eliminar_adoptante(person_id: str) -> dict:
    """Elimina un adoptante por su person_id."""
    try:
        res = get_db()["adoptantes"].delete_one({"person_id": person_id})
        return {"deleted": res.deleted_count, "ok": True}
    except PyMongoError as e:
        return {"error": str(e), "ok": False}


# ════════════════════════════════════════════════════════════════════════════
# CONSULTAS AVANZADAS (requisito cátedra: mínimo 5)
# ════════════════════════════════════════════════════════════════════════════

def consulta_1_animales_disponibles(tipo: str, refugio: str) -> list:
    """
    C1 — Filtro combinado: animales disponibles por tipo Y refugio.
    Usa el índice compuesto idx_tipo_estado_refugio.
    """
    try:
        cursor = get_db()["animales"].find(
            {"estado": "Disponible", "tipo": tipo, "refugio": refugio},
            {"_id": 0, "animal_id": 1, "nombre": 1, "raza": 1,
             "color": 1, "sexo": 1, "fecha_ingreso": 1}
        )
        return list(cursor)
    except PyMongoError:
        return []


def consulta_2_adoptantes_por_perfil(ciudad: str, tipo_vivienda: str, experiencia: str) -> list:
    """
    C2 — Filtro combinado: adoptantes que coinciden con ciudad +
    tipo de vivienda + nivel de experiencia con mascotas.
    Usa el índice compuesto idx_perfil_adoptante.
    """
    try:
        cursor = get_db()["adoptantes"].find(
            {
                "ciudad"              : ciudad,
                "tipo_vivienda"       : tipo_vivienda,
                "experiencia_mascotas": experiencia
            },
            {"_id": 0, "person_id": 1, "nombre": 1, "apellido": 1,
             "sexo": 1, "telefono": 1, "email": 1}
        )
        return list(cursor)
    except PyMongoError:
        return []


def consulta_3_reporte_por_estado_y_tipo() -> list:
    """
    C3 — Agregación: conteo de animales agrupados por estado + tipo + refugio.
    Pipeline: $group → $project → $sort
    """
    try:
        pipeline = [
            {
                "$group": {
                    "_id"  : {"estado": "$estado", "tipo": "$tipo", "refugio": "$refugio"},
                    "total": {"$sum": 1}
                }
            },
            {
                "$project": {
                    "_id"    : 0,
                    "estado" : "$_id.estado",
                    "tipo"   : "$_id.tipo",
                    "refugio": "$_id.refugio",
                    "total"  : 1
                }
            },
            {"$sort": {"total": DESCENDING}}
        ]
        return list(get_db()["animales"].aggregate(pipeline))
    except PyMongoError:
        return []


def consulta_4_animales_por_inicial(letra: str) -> list:
    """
    C4 — Regex: animales cuyo nombre empieza con la letra dada,
    sin distinguir mayúsculas/minúsculas ($options: 'i').
    """
    try:
        cursor = get_db()["animales"].find(
            {"nombre": {"$regex": f"^{letra}", "$options": "i"}},
            {"_id": 0, "animal_id": 1, "nombre": 1, "tipo": 1,
             "raza": 1, "estado": 1, "refugio": 1}
        )
        return list(cursor)
    except PyMongoError:
        return []


def consulta_5_adoptantes_con_animal() -> list:
    """
    C5 — Join manual en Python: adoptantes con animal_id asignado,
    enriquecidos con el nombre y tipo del animal desde la colección 'animales'.

    Nota de diseño: no se usa $lookup porque las colecciones son independientes
    por arquitectura. El join lo orquesta Python, igual que en el módulo Neo4j.
    """
    try:
        db = get_db()
        adoptantes = list(db["adoptantes"].find(
            {"animal_id": {"$ne": None, "$exists": True}},
            {"_id": 0}
        ).limit(50))

        for adoptante in adoptantes:
            animal = db["animales"].find_one(
                {"animal_id": adoptante.get("animal_id")},
                {"_id": 0, "nombre": 1, "tipo": 1, "estado": 1}
            )
            adoptante["animal_info"] = animal or {}

        return adoptantes
    except PyMongoError:
        return []


# ════════════════════════════════════════════════════════════════════════════
# OPERACIONES DE ACTUALIZACIÓN (requisito cátedra: mínimo 7)
# ════════════════════════════════════════════════════════════════════════════

def update_1_cambiar_estado(animal_id: str, nuevo_estado: str) -> dict:
    """U1 — $set: cambia el estado de un animal (ej: Disponible → Adoptado)."""
    try:
        res = get_db()["animales"].update_one(
            {"animal_id": animal_id},
            {"$set": {"estado": nuevo_estado}}
        )
        return {"op": "$set estado", "modified": res.modified_count}
    except PyMongoError as e:
        return {"error": str(e)}


def update_2_perfil_adoptante(person_id: str, ciudad: str, tipo_vivienda: str, experiencia: str) -> dict:
    """U2 — $set múltiple: actualiza ciudad + tipo_vivienda + experiencia en un solo comando."""
    try:
        res = get_db()["adoptantes"].update_one(
            {"person_id": person_id},
            {"$set": {
                "ciudad"              : ciudad,
                "tipo_vivienda"       : tipo_vivienda,
                "experiencia_mascotas": experiencia
            }}
        )
        return {"op": "$set perfil", "modified": res.modified_count}
    except PyMongoError as e:
        return {"error": str(e)}


def update_3_incrementar_visitas(animal_id: str, cantidad: int = 1) -> dict:
    """U3 — $inc: incrementa el contador de visitas. Si no existe el campo, lo crea en 0 y suma."""
    try:
        res = get_db()["animales"].update_one(
            {"animal_id": animal_id},
            {"$inc": {"visitas": cantidad}}
        )
        return {"op": "$inc visitas", "modified": res.modified_count}
    except PyMongoError as e:
        return {"error": str(e)}


def update_4_agregar_vacuna(animal_id: str, vacuna: str) -> dict:
    """U4 — $push: agrega una vacuna al array 'vacunas' del animal."""
    try:
        res = get_db()["animales"].update_one(
            {"animal_id": animal_id},
            {"$push": {"vacunas": vacuna}}
        )
        return {"op": "$push vacuna", "modified": res.modified_count}
    except PyMongoError as e:
        return {"error": str(e)}


def update_5_quitar_campo(person_id: str, campo: str) -> dict:
    """U5 — $unset: elimina un campo del documento del adoptante."""
    try:
        res = get_db()["adoptantes"].update_one(
            {"person_id": person_id},
            {"$unset": {campo: ""}}
        )
        return {"op": f"$unset {campo}", "modified": res.modified_count}
    except PyMongoError as e:
        return {"error": str(e)}


def update_6_agregar_tag(animal_id: str, tag: str) -> dict:
    """U6 — $addToSet: agrega un tag al array 'tags' solo si no existe ya (evita duplicados)."""
    try:
        res = get_db()["animales"].update_one(
            {"animal_id": animal_id},
            {"$addToSet": {"tags": tag}}
        )
        return {"op": "$addToSet tag", "modified": res.modified_count}
    except PyMongoError as e:
        return {"error": str(e)}


def update_7_masivos_por_refugio(refugio: str, nuevo_estado: str) -> dict:
    """
    U7 — updateMany: cambia el estado de TODOS los animales de un refugio.
    Demuestra actualización masiva (update_many vs update_one).
    """
    try:
        res = get_db()["animales"].update_many(
            {"refugio": refugio},
            {"$set": {"estado": nuevo_estado}}
        )
        return {"op": "updateMany por refugio", "modified": res.modified_count}
    except PyMongoError as e:
        return {"error": str(e)}


# ════════════════════════════════════════════════════════════════════════════
# OPERACIONES DE ELIMINACIÓN (requisito cátedra: mínimo 7)
# ════════════════════════════════════════════════════════════════════════════

def delete_1_animal(animal_id: str) -> dict:
    """D1 — delete_one por animal_id."""
    try:
        res = get_db()["animales"].delete_one({"animal_id": animal_id})
        return {"op": "delete animal", "deleted": res.deleted_count}
    except PyMongoError as e:
        return {"error": str(e)}


def delete_2_adoptante(person_id: str) -> dict:
    """D2 — delete_one por person_id."""
    try:
        res = get_db()["adoptantes"].delete_one({"person_id": person_id})
        return {"op": "delete adoptante", "deleted": res.deleted_count}
    except PyMongoError as e:
        return {"error": str(e)}


def delete_3_animales_por_estado(estado: str) -> dict:
    """D3 — delete_many: elimina todos los animales con un estado determinado."""
    try:
        res = get_db()["animales"].delete_many({"estado": estado})
        return {"op": f"delete_many estado={estado}", "deleted": res.deleted_count}
    except PyMongoError as e:
        return {"error": str(e)}


def delete_4_adoptantes_sin_email() -> dict:
    """D4 — delete_many con $or + $exists: elimina adoptantes sin email registrado."""
    try:
        filtro = {"$or": [
            {"email": {"$exists": False}},
            {"email": None},
            {"email": ""}
        ]}
        res = get_db()["adoptantes"].delete_many(filtro)
        return {"op": "delete adoptantes sin email", "deleted": res.deleted_count}
    except PyMongoError as e:
        return {"error": str(e)}


def delete_5_animales_anteriores_a(fecha_limite: str) -> dict:
    """D5 — delete_many con $lt: elimina animales ingresados antes de una fecha."""
    try:
        res = get_db()["animales"].delete_many(
            {"fecha_ingreso": {"$lt": fecha_limite}}
        )
        return {"op": f"delete antes de {fecha_limite}", "deleted": res.deleted_count}
    except PyMongoError as e:
        return {"error": str(e)}


def delete_6_por_refugio_y_estado(refugio: str, estado: str) -> dict:
    """D6 — delete_many con filtro compuesto (AND implícito): refugio + estado."""
    try:
        res = get_db()["animales"].delete_many(
            {"refugio": refugio, "estado": estado}
        )
        return {"op": f"delete {estado} en {refugio}", "deleted": res.deleted_count}
    except PyMongoError as e:
        return {"error": str(e)}


def delete_7_por_lista_ids(lista_ids: list) -> dict:
    """D7 — delete_many con $in: elimina todos los animales de una lista de IDs."""
    try:
        res = get_db()["animales"].delete_many(
            {"animal_id": {"$in": lista_ids}}
        )
        return {"op": f"delete $in {len(lista_ids)} ids", "deleted": res.deleted_count}
    except PyMongoError as e:
        return {"error": str(e)}


# ════════════════════════════════════════════════════════════════════════════
# EXPORTACIÓN A CSV (requisito cátedra: pandas)
# ════════════════════════════════════════════════════════════════════════════

def exportar_animales_csv() -> str:
    """
    Consulta los animales disponibles y exporta el resultado a CSV con pandas.
    Retorna la ruta del archivo generado (para enviársela al browser como descarga).

    Buena práctica: encoding='utf-8-sig' para compatibilidad con Excel en español.
    """
    import pandas as pd
    from datetime import datetime
    import os

    try:
        cursor = get_db()["animales"].find(
            {"estado": "Disponible"},
            {"_id": 0, "animal_id": 1, "nombre": 1, "tipo": 1,
             "raza": 1, "sexo": 1, "refugio": 1, "fecha_ingreso": 1}
        ).sort([("refugio", ASCENDING), ("tipo", ASCENDING)])

        df = pd.DataFrame(list(cursor))

        if df.empty:
            return None

        os.makedirs("exports", exist_ok=True)
        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta = f"exports/animales_disponibles_{fecha}.csv"
        df.to_csv(ruta, index=False, encoding="utf-8-sig")
        return ruta

    except PyMongoError:
        return None


# ════════════════════════════════════════════════════════════════════════════
# HELPERS PARA LA UI (poblar dropdowns)
# ════════════════════════════════════════════════════════════════════════════

def get_sample_data() -> dict:
    """
    Retorna IDs y valores de muestra para poblar los dropdowns de la UI.
    Mismo patrón que get_sample_ids() en cassandra_client.py.
    """
    try:
        db = get_db()

        animales = list(db["animales"].find(
            {}, {"_id": 0, "animal_id": 1, "nombre": 1, "tipo": 1}
        ).limit(30))

        adoptantes = list(db["adoptantes"].find(
            {}, {"_id": 0, "person_id": 1, "nombre": 1, "apellido": 1}
        ).limit(30))

        # Valores únicos para filtros
        tipos    = db["animales"].distinct("tipo")
        refugios = db["animales"].distinct("refugio")
        estados  = db["animales"].distinct("estado")
        ciudades = db["adoptantes"].distinct("ciudad")
        viviendas    = db["adoptantes"].distinct("tipo_vivienda")
        experiencias = db["adoptantes"].distinct("experiencia_mascotas")

        return {
            "animales"   : animales,
            "adoptantes" : adoptantes,
            "tipos"      : tipos,
            "refugios"   : refugios,
            "estados"    : estados,
            "ciudades"   : ciudades,
            "viviendas"  : viviendas,
            "experiencias": experiencias,
        }
    except PyMongoError:
        return {}