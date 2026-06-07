from flask import Blueprint, render_template, jsonify, request
from uuid import UUID, uuid4
from datetime import datetime
try:
    import clients.cassandra_client as cassandra
except Exception as e:
    print(f"[WARN] Cassandra deshabilitado: {e}")
    cassandra = None

try:
    import seeder
except Exception as e:
    print(f"[WARN] Seeder deshabilitado: {e}")
    seeder = None
import clients.redis_client as redis_client

try:
    import clients.mongo_client as mongo
    mongo.ensure_indexes()
except Exception as e:
    print(f"[WARN] MongoDB deshabilitado: {e}")
    mongo = None

try:
    import clients.neo4j_client as neo4j_client
except Exception as e:
    print(f"[WARN] Neo4j deshabilitado: {e}")
    neo4j_client = None


bp = Blueprint("main", __name__)

SEED_CONFIRM_PHRASE = "BORRAR Y SEMBRAR"


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/cassandra")
def cassandra_home():
    return render_template("cassandra.html")

@bp.route("/redis")
def redis_home():
    return render_template("redis.html")


# ─── Samples (poblar dropdowns de la UI) ────────────────────────────────────

@bp.route("/cassandra/samples", methods=["GET"])
def samples():
    return jsonify(cassandra.get_sample_ids())


# ─── Seed (acción destructiva, triple confirmación) ─────────────────────────

@bp.route("/cassandra/seed", methods=["POST"])
def seed():
    payload = request.get_json(silent=True) or {}
    confirm = payload.get("confirm", "")
    if confirm != SEED_CONFIRM_PHRASE:
        return jsonify({
            "error": "confirmación inválida",
            "expected": SEED_CONFIRM_PHRASE,
        }), 400

    n = int(payload.get("n", 2000))
    summary = seeder.run(n_events=n, truncate=True)
    return jsonify({"status": "ok", "summary": summary})


# ─── Q1 — eventos de un usuario ─────────────────────────────────────────────

@bp.route("/cassandra/q1/usuarios/<user_id>/eventos", methods=["GET"])
def q1(user_id):
    rows = cassandra.q1_eventos_por_usuario(UUID(user_id))
    return jsonify(rows)


# ─── Q2 — eventos de un perro ───────────────────────────────────────────────

@bp.route("/cassandra/q2/perros/<pet_id>/eventos", methods=["GET"])
def q2(pet_id):
    rows = cassandra.q2_eventos_por_perro(UUID(pet_id))
    return jsonify(rows)


# ─── Q3 — eventos de un refugio ─────────────────────────────────────────────

@bp.route("/cassandra/q3/refugios/<shelter_id>/eventos", methods=["GET"])
def q3(shelter_id):
    rows = cassandra.q3_eventos_por_refugio(UUID(shelter_id))
    return jsonify(rows)


# ─── Q4 — eventos de usuario sobre un perro específico ──────────────────────

@bp.route("/cassandra/q4/usuarios/<user_id>/perros/<pet_id>/eventos", methods=["GET"])
def q4(user_id, pet_id):
    rows = cassandra.q4_eventos_por_usuario_y_perro(UUID(user_id), UUID(pet_id))
    return jsonify(rows)


# ─── Q5 — eventos por tipo ──────────────────────────────────────────────────

@bp.route("/cassandra/q5/tipos/<event_type>/eventos", methods=["GET"])
def q5(event_type):
    rows = cassandra.q5_eventos_por_tipo(event_type)
    return jsonify(rows)


# ─── Q6 — favoritos de un usuario ───────────────────────────────────────────

@bp.route("/cassandra/q6/usuarios/<user_id>/favoritos", methods=["GET"])
def q6(user_id):
    rows = cassandra.q6_favoritos_por_usuario(UUID(user_id))
    return jsonify(rows)


# ─── Q7 — solicitudes de adopción de un usuario ─────────────────────────────

@bp.route("/cassandra/q7/usuarios/<user_id>/solicitudes", methods=["GET"])
def q7(user_id):
    rows = cassandra.q7_solicitudes_por_usuario(UUID(user_id))
    return jsonify(rows)


# ─── Q8 — eventos de un refugio en rango de fechas ──────────────────────────
# Params: ?from=2024-01-01T00:00:00&to=2024-12-31T23:59:59

@bp.route("/cassandra/q8/refugios/<shelter_id>/eventos", methods=["GET"])
def q8(shelter_id):
    date_from = datetime.fromisoformat(request.args["from"])
    date_to   = datetime.fromisoformat(request.args["to"])
    rows = cassandra.q8_eventos_por_refugio_y_fecha(UUID(shelter_id), date_from, date_to)
    return jsonify(rows)


# ─── INSERT — evento (escribe en las 6 tablas de evento) ────────────────────

@bp.route("/cassandra/eventos", methods=["POST"])
def post_evento():
    d = request.json
    cassandra.insert_evento(
        event_id   = uuid4(),
        user_id    = UUID(d["user_id"]),
        pet_id     = UUID(d["pet_id"]),
        shelter_id = UUID(d["shelter_id"]),
        event_type = d["event_type"],
        date       = datetime.fromisoformat(d["date"]),
        details    = d.get("details", ""),
    )
    return jsonify({"status": "ok"}), 201


# ─── INSERT — favorito ───────────────────────────────────────────────────────

@bp.route("/cassandra/favoritos", methods=["POST"])
def post_favorito():
    d = request.json
    cassandra.insert_favorito(
        user_id    = UUID(d["user_id"]),
        pet_id     = UUID(d["pet_id"]),
        shelter_id = UUID(d["shelter_id"]),
        date       = datetime.fromisoformat(d["date"]),
        details    = d.get("details", ""),
    )
    return jsonify({"status": "ok"}), 201


# ─── INSERT — solicitud ──────────────────────────────────────────────────────

@bp.route("/cassandra/solicitudes", methods=["POST"])
def post_solicitud():
    d = request.json
    cassandra.insert_solicitud(
        user_id    = UUID(d["user_id"]),
        event_id   = uuid4(),
        pet_id     = UUID(d["pet_id"]),
        shelter_id = UUID(d["shelter_id"]),
        date       = datetime.fromisoformat(d["date"]),
        status     = d.get("status", "pendiente"),
        details    = d.get("details", ""),
    )
    return jsonify({"status": "ok"}), 201

# ============================================================
# REDIS - SESIONES
# ============================================================

@bp.route("/redis/sesiones", methods=["POST"])
def crear_sesion():
    d = request.json

    try:
        resultado = redis_client.crear_sesion(
            person_id=d["person_id"],
            nombre=d["nombre"],
            apellido=d["apellido"],
            email=d["email"],
            rol=d.get("rol", "adoptante")
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 409

    return jsonify(resultado), 201


@bp.route("/redis/sesiones/<person_id>", methods=["GET"])
def obtener_sesion(person_id):
    sesion = redis_client.obtener_sesion(person_id)

    if not sesion:
        return jsonify({"error": "sesión no encontrada"}), 404

    return jsonify(sesion)


@bp.route("/redis/sesiones/<person_id>", methods=["PATCH"])
def actualizar_sesion(person_id):
    d = request.json

    ok = redis_client.actualizar_campo(
        person_id,
        d["campo"],
        d["valor"]
    )

    if not ok:
        return jsonify({"error": "sesión no encontrada"}), 404

    return jsonify({"status": "ok"})


@bp.route("/redis/sesiones/<person_id>/renovar", methods=["POST"])
def renovar_sesion(person_id):
    ok = redis_client.renovar_sesion(person_id)

    if not ok:
        return jsonify({"error": "sesión no encontrada"}), 404

    return jsonify({"status": "ok"})


@bp.route("/redis/sesiones/<person_id>", methods=["DELETE"])
def cerrar_sesion(person_id):
    ok = redis_client.cerrar_sesion(person_id)

    if not ok:
        return jsonify({"error": "sesión no encontrada"}), 404

    return jsonify({"status": "ok"})

# ============================================================
# REDIS - NOTIFICACIONES
# ============================================================

@bp.route("/redis/notificaciones", methods=["POST"])
def crear_notificacion():
    d = request.json

    try:
        redis_client.agregar_recordatorio(
            d["person_id"],
            d["mensaje"]
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    return jsonify({"status": "ok"}), 201


@bp.route("/redis/notificaciones/<person_id>", methods=["GET"])
def listar_notificaciones(person_id):
    return jsonify(
        redis_client.listar_recordatorios(person_id)
    )


@bp.route("/redis/notificaciones/<person_id>/count", methods=["GET"])
def contar_notificaciones(person_id):
    return jsonify({
        "cantidad": redis_client.contar_recordatorios(person_id)
    })


@bp.route("/redis/notificaciones/<person_id>/consume", methods=["POST"])
def consumir_notificacion(person_id):
    msg = redis_client.marcar_hecho(person_id)

    return jsonify({
        "mensaje": msg
    })


@bp.route("/redis/notificaciones/<person_id>/consume-all", methods=["POST"])
def consumir_todas(person_id):
    return jsonify(
        redis_client.borrar_todos(person_id)
    )

# ============================================================
# REDIS - RANKING
# ============================================================

@bp.route("/redis/animales", methods=["POST"])
def inicializar_animal():
    d = request.json

    try:
        redis_client.inicializar_animal(
            animal_id=d["animal_id"],
            nombre=d["nombre"],
            visitas_historicas=d.get("visitas_historicas", 0),
            visitas_hoy=d.get("visitas_hoy", 0)
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 409

    return jsonify({"status": "ok"}), 201


@bp.route("/redis/visitas", methods=["POST"])
def registrar_visita():
    d = request.json

    resultado = redis_client.registrar_visita(
        animal_id=d["animal_id"]
    )

    return jsonify(resultado)


@bp.route("/redis/ranking", methods=["GET"])
def ranking():
    top = int(request.args.get("top", 10))

    return jsonify(
        redis_client.obtener_ranking(top)
    )


@bp.route("/redis/ranking/<animal_id>", methods=["GET"])
def posicion(animal_id):
    try:
        resultado = redis_client.obtener_posicion(animal_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    if resultado is None:
        return jsonify({"error": "animal no encontrado en el ranking"}), 404

    return jsonify(resultado)


@bp.route("/redis/visitas/<animal_id>", methods=["GET"])
def visitas_hoy(animal_id):
    return jsonify({
        "visitas_hoy":
            redis_client.obtener_visitas_hoy(animal_id)
    })

# ════════════════════════════════════════════════════════════════════════════
# MONGODB
# ════════════════════════════════════════════════════════════════════════════

@bp.route("/mongo")
def mongo_home():
    return render_template("mongo.html")

# ─── Samples (poblar dropdowns de la UI) ────────────────────────────────────

@bp.route("/mongo/samples", methods=["GET"])
def mongo_samples():
    return jsonify(mongo.get_sample_data())

# ─── Seed ───────────────────────────────────────────────────────────────────

@bp.route("/mongo/seed", methods=["POST"])
def mongo_seed():
    payload = request.get_json(silent=True) or {}
    confirm = payload.get("confirm", "")
    if confirm != SEED_CONFIRM_PHRASE:
        return jsonify({"error": "confirmación inválida"}), 400
    if seeder is None:
        return jsonify({"error": "Seeder no disponible"}), 503
    summary = seeder.run_mongo(truncate=True)
    return jsonify({"status": "ok", "summary": summary})

# ─── C1 — animales disponibles por tipo y refugio ───────────────────────────

@bp.route("/mongo/c1/animales", methods=["GET"])
def mongo_c1():
    tipo    = request.args.get("tipo", "Perro")
    refugio = request.args.get("refugio", "Huellitas")
    return jsonify(mongo.consulta_1_animales_disponibles(tipo, refugio))

# ─── C2 — adoptantes por perfil completo ────────────────────────────────────

@bp.route("/mongo/c2/adoptantes", methods=["GET"])
def mongo_c2():
    ciudad       = request.args.get("ciudad", "Buenos Aires")
    tipo_vivienda = request.args.get("tipo_vivienda", "Casa")
    experiencia  = request.args.get("experiencia", "Alta")
    return jsonify(mongo.consulta_2_adoptantes_por_perfil(ciudad, tipo_vivienda, experiencia))

# ─── C3 — reporte agregado por estado y tipo ────────────────────────────────

@bp.route("/mongo/c3/reporte", methods=["GET"])
def mongo_c3():
    return jsonify(mongo.consulta_3_reporte_por_estado_y_tipo())

# ─── C4 — buscador de texto libre (nombre o raza) ───────────────────────────

@bp.route("/mongo/c4/animales", methods=["GET"])
def mongo_c4():
    texto = request.args.get("q", "")
    return jsonify(mongo.consulta_4_buscador(texto))

# ─── Búsqueda dinámica (typeahead: nombre / apellido / ID) ──────────────────
# Endpoint que faltaba: el front (mongo.html) llama a /mongo/buscar/<coleccion>
# tanto desde el typeahead como desde resolverId(). Sin esto, la búsqueda por
# nombre devolvía 404 y solo funcionaba el ID exacto.

@bp.route("/mongo/buscar/<coleccion>", methods=["GET"])
def mongo_buscar(coleccion):
    texto = request.args.get("q", "")
    if coleccion == "animales":
        return jsonify(mongo.buscar_animales_dinamico(texto))
    elif coleccion == "adoptantes":
        return jsonify(mongo.buscar_adoptantes_dinamico(texto))
    return jsonify({"error": "colección no reconocida"}), 400

# ─── C5 — adoptantes con animal asignado ────────────────────────────────────

@bp.route("/mongo/c5/adoptantes", methods=["GET"])
def mongo_c5():
    return jsonify(mongo.consulta_5_adoptantes_con_animal())

# ─── C6 — animales por vacuna (array embebido, $elemMatch) ───────────────────

@bp.route("/mongo/c6/animales", methods=["GET"])
def mongo_c6():
    vacuna = request.args.get("vacuna", "")
    return jsonify(mongo.consulta_6_animales_por_vacuna(vacuna))

# ─── CRUD animales ───────────────────────────────────────────────────────────

@bp.route("/mongo/animales", methods=["POST"])
def mongo_crear_animal():
    return jsonify(mongo.insertar_animal(request.json))

@bp.route("/mongo/animales/<animal_id>", methods=["GET"])
def mongo_buscar_animal(animal_id):
    return jsonify(mongo.buscar_animal_por_id(animal_id))

@bp.route("/mongo/animales/<animal_id>", methods=["PUT"])
def mongo_actualizar_animal(animal_id):
    return jsonify(mongo.actualizar_animal(animal_id, request.json))

@bp.route("/mongo/animales/<animal_id>", methods=["DELETE"])
def mongo_eliminar_animal(animal_id):
    return jsonify(mongo.eliminar_animal(animal_id))

# ─── CRUD adoptantes ─────────────────────────────────────────────────────────

@bp.route("/mongo/adoptantes", methods=["POST"])
def mongo_crear_adoptante():
    return jsonify(mongo.insertar_adoptante(request.json))

@bp.route("/mongo/adoptantes/<person_id>", methods=["GET"])
def mongo_buscar_adoptante(person_id):
    return jsonify(mongo.buscar_adoptante_por_id(person_id))

@bp.route("/mongo/adoptantes/<person_id>", methods=["PUT"])
def mongo_actualizar_adoptante(person_id):
    return jsonify(mongo.actualizar_adoptante(person_id, request.json))

@bp.route("/mongo/adoptantes/<person_id>", methods=["DELETE"])
def mongo_eliminar_adoptante(person_id):
    return jsonify(mongo.eliminar_adoptante(person_id))

# ─── Operaciones de actualización ────────────────────────────────────────────

@bp.route("/mongo/ops/update", methods=["POST"])
def mongo_update():
    d  = request.get_json(silent=True) or {}
    op = d.get("op")
    if op == "u1":
        return jsonify(mongo.update_1_cambiar_estado(d["animal_id"], d["estado"]))
    elif op == "u2":
        return jsonify(mongo.update_2_perfil_adoptante(d["person_id"], d["ciudad"], d["tipo_vivienda"], d["experiencia"]))
    elif op == "u3":
        return jsonify(mongo.update_3_incrementar_visitas(d["animal_id"]))
    elif op == "u4":
        return jsonify(mongo.update_4_agregar_vacuna(d["animal_id"], d["vacuna"]))
    elif op == "u5":
        return jsonify(mongo.update_5_quitar_campo(d["person_id"], d["campo"]))
    elif op == "u6":
        return jsonify(mongo.update_6_agregar_tag(d["animal_id"], d["tag"]))
    elif op == "u7":
        return jsonify(mongo.update_7_masivos_por_refugio(d["refugio"], d["estado"]))
    return jsonify({"error": "operación no reconocida"}), 400

# ─── Operaciones de eliminación ──────────────────────────────────────────────

@bp.route("/mongo/ops/delete", methods=["POST"])
def mongo_delete():
    d  = request.get_json(silent=True) or {}
    op = d.get("op")
    if op == "d1":
        return jsonify(mongo.delete_1_animal(d["animal_id"]))
    elif op == "d2":
        return jsonify(mongo.delete_2_adoptante(d["person_id"]))
    elif op == "d3":
        return jsonify(mongo.delete_3_animales_por_estado(d["estado"]))
    elif op == "d4":
        return jsonify(mongo.delete_4_adoptantes_sin_email())
    elif op == "d5":
        return jsonify(mongo.delete_5_animales_anteriores_a(d["fecha"]))
    elif op == "d6":
        return jsonify(mongo.delete_6_por_refugio_y_estado(d["refugio"], d["estado"]))
    elif op == "d7":
        return jsonify(mongo.delete_7_por_lista_ids(d["ids"]))
    return jsonify({"error": "operación no reconocida"}), 400

# ─── Exportar CSV ────────────────────────────────────────────────────────────

@bp.route("/mongo/exportar", methods=["GET"])
def mongo_exportar():
    from flask import send_file
    ruta = mongo.exportar_animales_csv()
    if not ruta:
        return jsonify({"error": "No hay datos para exportar"}), 404
    return send_file(ruta, as_attachment=True)
# ════════════════════════════════════════════════════════════════════════════
# NEO4J
# ════════════════════════════════════════════════════════════════════════════

@bp.route('/neo4j')
def neo4j():
    return render_template('neo4j.html')


@bp.route("/api/personas")
def api_personas():
    return jsonify(neo4j_client.todas_las_personas())


@bp.route("/api/personas/adoptantes")
def api_adoptantes():
    return jsonify(neo4j_client.personas_que_adoptaron())


@bp.route("/api/refugios")
def api_refugios():
    return jsonify(neo4j_client.todos_los_refugios())


@bp.route("/api/animales")
def api_animales():
    return jsonify(neo4j_client.todos_los_animales())


@bp.route("/api/animales/disponibles")
def api_animales_disponibles():
    return jsonify({"disponibles": neo4j_client.animales_disponibles_por_tipo()})


@bp.route("/api/personas/<person_id>/recomendaciones")
def api_recomendaciones(person_id):
    return jsonify({"recomendaciones": neo4j_client.recomendar_animales(person_id)})


@bp.route("/api/refugios/<nombre>/animales")
def api_animales_por_refugio(nombre):
    return jsonify({"animales": neo4j_client.animales_por_refugio(nombre)})


@bp.route("/api/personas/<person_id>/adopciones")
def api_adopciones(person_id):
    return jsonify({"adopciones": neo4j_client.historial_adopciones(person_id)})


@bp.route("/api/animales/<animal_id>/compatibles")
def api_compatibles(animal_id):
    return jsonify({"personas": neo4j_client.personas_compatibles(animal_id)})


@bp.route("/api/personas/<person_id>/grafo")
def api_grafo(person_id):
    return jsonify({"grafo": neo4j_client.grafo_compatibilidad(person_id)})
