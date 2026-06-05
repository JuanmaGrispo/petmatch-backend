import os
import redis
from datetime import datetime, timedelta

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


def _segundos_hasta_medianoche():
    ahora = datetime.now()
    medianoche = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    medianoche_siguiente = medianoche + timedelta(days=1)
    return int((medianoche_siguiente - ahora).total_seconds())


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


def _limpiar_si_expiro(r, person_id):
    sesion_key = f"sesion:usuario:{person_id}"
    if not r.exists(sesion_key):
        r.delete(f"recordatorios:usuario:{person_id}")


def obtener_sesion(person_id):
    r = get_redis()

    key = f"sesion:usuario:{person_id}"

    datos = r.hgetall(key)

    if not datos:
        _limpiar_si_expiro(r, person_id)
        return None

    datos["ttl"] = str(r.ttl(key))

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

    eliminada = r.delete(key) > 0

    if eliminada:
        r.delete(f"recordatorios:usuario:{person_id}")

    return eliminada


# ============================================================
# RECORDATORIOS
# ============================================================

def agregar_recordatorio(person_id, mensaje):
    r = get_redis()

    if not r.exists(f"sesion:usuario:{person_id}"):
        raise ValueError(f"No existe una sesión activa para el ID '{person_id}'")

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

    nombre = nombre.strip().title()

    if nombre in [n.title() for n in r.hvals("animales:mapa")]:
        raise ValueError(f"Ya existe un animal registrado con el nombre '{nombre}'")

    contador_key = f"visitas:animal:{animal_id}"

    pipe = r.pipeline()

    pipe.hset("animales:mapa", animal_id, nombre)

    pipe.zadd(
        "ranking:animales",
        {animal_id: visitas_historicas}
    )

    pipe.set(
        contador_key,
        visitas_hoy,
        ex=_segundos_hasta_medianoche()
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
        animal_id
    )

    pipe.incr(contador_key)

    pipe.expire(
        contador_key,
        _segundos_hasta_medianoche()
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
            "animal_id": animal_id,
            "nombre": r.hget("animales:mapa", animal_id) or animal_id,
            "visitas_historicas": int(score)
        }
        for animal_id, score in ranking
    ]


def obtener_posicion(animal_id):
    r = get_redis()

    nombre = _get_nombre(r, animal_id)

    posicion = r.zrevrank(
        "ranking:animales",
        animal_id
    )

    score = r.zscore(
        "ranking:animales",
        animal_id
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