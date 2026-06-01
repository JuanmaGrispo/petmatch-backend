from flask import Blueprint, render_template, jsonify, request
from uuid import UUID, uuid4
from datetime import datetime
import clients.cassandra_client as cassandra
import clients.neo4j_client as neo4j


bp = Blueprint("main", __name__)



@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/cassandra")
def cassandra_home():
    return render_template("cassandra.html")

@bp.route("/neo4j")
def neo4j_home():
    return render_template("neo4j.html")

# ─── Setup ──────────────────────────────────────────────────────────────────

@bp.route("/cassandra/setup", methods=["POST"])
def setup():
    cassandra.create_tables()
    return jsonify({"status": "tablas creadas"})


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

# ════════════════════════════════════════════════════════════════════════════
# NEO4J
# ════════════════════════════════════════════════════════════════════════════
 
@bp.route("/api/personas/<person_id>/recomendaciones", methods=["GET"])
def get_recomendaciones(person_id):
    data = neo4j.recomendar_animales(person_id)
    return jsonify({"person_id": person_id, "recomendaciones": data})
 
 
@bp.route("/api/refugios/<nombre>/animales", methods=["GET"])
def get_animales_refugio(nombre):
    data = neo4j.animales_por_refugio(nombre)
    return jsonify({"refugio": nombre, "animales": data})
 
 
@bp.route("/api/personas/<person_id>/adopciones", methods=["GET"])
def get_historial(person_id):
    data = neo4j.historial_adopciones(person_id)
    return jsonify({"person_id": person_id, "adopciones": data})
 
 
@bp.route("/api/animales/disponibles", methods=["GET"])
def get_disponibles():
    data = neo4j.animales_disponibles_por_tipo()
    return jsonify({"disponibles": data})
 
 
@bp.route("/api/animales/<animal_id>/compatibles", methods=["GET"])
def get_personas_compatibles(animal_id):
    data = neo4j.personas_compatibles(animal_id)
    return jsonify({"animal_id": animal_id, "personas": data})

@bp.route("/api/personas", methods=["GET"])
def get_personas():
    return jsonify(neo4j.todas_las_personas())

@bp.route("/api/refugios", methods=["GET"])
def get_refugios():
    return jsonify(neo4j.todos_los_refugios())

@bp.route("/api/animales", methods=["GET"])
def get_animales():
    return jsonify(neo4j.todos_los_animales())


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
