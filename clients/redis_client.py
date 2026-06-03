import os
import redis
from datetime import datetime

_redis_client = None

SESSION_TTL = 1800
TTL_CONTADOR_DIARIO = 86400


def get_redis():
    global _redis_client

    if _redis_client is None:
        _redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            password=os.getenv("REDIS_PASSWORD"),
            decode_responses=True
        )

        _redis_client.ping()

    return _redis_client


# ============================================================
# SESIONES
# ============================================================

def crear_sesion(
    person_id,
    nombre,
    apellido,
    email,
    rol="adoptante"
):
    r = get_redis()

    key = f"sesion:usuario:{person_id}"

    if r.exists(key):
        raise ValueError(f"Ya existe una sesión activa para el ID '{person_id}'")

    datos = {
        "person_id": person_id,
        "nombre": nombre,
        "apellido": apellido,
        "email": email,
        "rol": rol,
        "activo": "true",
        "inicio": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    r.hset(key, mapping=datos)
    r.expire(key, SESSION_TTL)

    return datos


def obtener_sesion(person_id):
    r = get_redis()

    key = f"sesion:usuario:{person_id}"

    datos = r.hgetall(key)

    if not datos:
        return None

    return datos


def obtener_campo(person_id, campo):
    r = get_redis()

    key = f"sesion:usuario:{person_id}"

    return r.hget(key, campo)


def actualizar_campo(person_id, campo, valor):
    r = get_redis()

    key = f"sesion:usuario:{person_id}"

    if not r.exists(key):
        return False

    r.hset(key, campo, valor)

    return True


def renovar_sesion(person_id):
    r = get_redis()

    key = f"sesion:usuario:{person_id}"

    if not r.exists(key):
        return False

    r.expire(key, SESSION_TTL)

    return True


def cerrar_sesion(person_id):
    r = get_redis()

    key = f"sesion:usuario:{person_id}"

    return r.delete(key) > 0


# ============================================================
# NOTIFICACIONES
# ============================================================

def agregar_recordatorio(person_id, mensaje):
    r = get_redis()

    key = f"recordatorios:usuario:{person_id}"

    return r.rpush(key, mensaje)


def listar_recordatorios(person_id):
    r = get_redis()

    key = f"recordatorios:usuario:{person_id}"

    return r.lrange(key, 0, -1)


def contar_recordatorios(person_id):
    r = get_redis()

    key = f"recordatorios:usuario:{person_id}"

    return r.llen(key)


def marcar_hecho(person_id):
    r = get_redis()

    key = f"recordatorios:usuario:{person_id}"

    return r.lpop(key)


def borrar_todos(person_id):
    r = get_redis()

    key = f"recordatorios:usuario:{person_id}"

    mensajes = []

    while True:
        msg = r.lpop(key)

        if msg is None:
            break

        mensajes.append(msg)

    return mensajes


# ============================================================
# RANKING Y VISITAS
# ============================================================

def _get_nombre(r, animal_id):
    """Resuelve el nombre de un animal a partir de su ID usando el Hash de mapeo."""
    nombre = r.hget("animales:mapa", animal_id)
    if not nombre:
        raise ValueError(f"Animal ID '{animal_id}' no encontrado en el sistema")
    return nombre


def inicializar_animal(
    animal_id,
    nombre,
    visitas_historicas=0,
    visitas_hoy=0
):
    r = get_redis()

    if r.hexists("animales:mapa", animal_id):
        raise ValueError(f"Ya existe un animal registrado con el ID '{animal_id}'")

    contador_key = f"visitas:animal:{animal_id}"

    pipe = r.pipeline()

    # Guardar mapeo id → nombre
    pipe.hset("animales:mapa", animal_id, nombre)

    pipe.zadd(
        "ranking:animales",
        {nombre: visitas_historicas}
    )

    pipe.set(
        contador_key,
        visitas_hoy,
        ex=TTL_CONTADOR_DIARIO
    )

    pipe.execute()

    return True


def registrar_visita(animal_id):
    r = get_redis()

    nombre = _get_nombre(r, animal_id)
    contador_key = f"visitas:animal:{animal_id}"

    pipe = r.pipeline()

    pipe.zincrby(
        "ranking:animales",
        1,
        nombre
    )

    pipe.incr(contador_key)

    pipe.expire(
        contador_key,
        TTL_CONTADOR_DIARIO
    )

    resultados = pipe.execute()

    return {
        "animal_id": animal_id,
        "nombre": nombre,
        "historico": int(resultados[0]),
        "hoy": int(resultados[1])
    }


def obtener_ranking(top=10):
    r = get_redis()

    ranking = r.zrevrange(
        "ranking:animales",
        0,
        top - 1,
        withscores=True
    )

    return [
        {
            "nombre": nombre,
            "visitas_historicas": int(score)
        }
        for nombre, score in ranking
    ]


def obtener_posicion(animal_id):
    r = get_redis()

    nombre = _get_nombre(r, animal_id)

    posicion = r.zrevrank(
        "ranking:animales",
        nombre
    )

    score = r.zscore(
        "ranking:animales",
        nombre
    )

    if posicion is None:
        return None

    return {
        "animal_id": animal_id,
        "nombre": nombre,
        "posicion": posicion + 1,
        "visitas_historicas": int(score)
    }


def obtener_visitas_hoy(animal_id):
    r = get_redis()

    key = f"visitas:animal:{animal_id}"

    valor = r.get(key)

    return int(valor) if valor else 0


def obtener_total_animales_ranking():
    r = get_redis()

    return r.zcard("ranking:animales")