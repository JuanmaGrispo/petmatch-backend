from flask import Blueprint, render_template, jsonify, request
from uuid import UUID, uuid4
from datetime import datetime
import clients.cassandra_client as cassandra
import seeder

bp = Blueprint("main", __name__)

SEED_CONFIRM_PHRASE = "BORRAR Y SEMBRAR"


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/cassandra")
def cassandra_home():
    return render_template("cassandra.html")


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
