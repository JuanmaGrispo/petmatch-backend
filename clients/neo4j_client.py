from neo4j import GraphDatabase
import os

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        uri      = os.environ.get("NEO4J_URI", "neo4j+s://5b094d32.databases.neo4j.io")
        user     = os.environ.get("NEO4J_USER", "5b094d32")
        password = os.environ.get("NEO4J_PASSWORD", "Cz66NRtkrzU0Mwy8oMme_GFLG1bLmvlN9E2I8Sdfjy8")
        _driver  = GraphDatabase.driver(uri, auth=(user, password))
    return _driver


def recomendar_animales(person_id):
    with get_driver().session() as session:
        result = session.run("""
            MATCH (p:Persona {person_id: $person_id})-[:COMPATIBLE_CON]->(a:Animal)
            WHERE a.estado = 'Disponible'
            RETURN a.animal_id AS id, a.nombre AS nombre,
                   a.tipo AS tipo, a.raza AS raza
            LIMIT 5
        """, person_id=person_id)
        return [dict(r) for r in result]


def animales_por_refugio(nombre_refugio):
    with get_driver().session() as session:
        result = session.run("""
            MATCH (a:Animal)-[:PERTENECE_A]->(r:Refugio {nombre: $nombre})
            RETURN a.animal_id AS id, a.nombre AS nombre,
                   a.tipo AS tipo, a.estado AS estado
        """, nombre=nombre_refugio)
        return [dict(r) for r in result]


def historial_adopciones(person_id):
    with get_driver().session() as session:
        result = session.run("""
            MATCH (p:Persona {person_id: $person_id})-[:ADOPTO]->(a:Animal)
            RETURN a.animal_id AS id, a.nombre AS nombre,
                   a.tipo AS tipo, a.raza AS raza
        """, person_id=person_id)
        return [dict(r) for r in result]


def animales_disponibles_por_tipo():
    with get_driver().session() as session:
        result = session.run("""
            MATCH (a:Animal)
            WHERE a.estado = 'Disponible'
            RETURN a.tipo AS tipo, count(a) AS cantidad
            ORDER BY cantidad DESC
        """)
        return [dict(r) for r in result]


def personas_compatibles(animal_id):
    with get_driver().session() as session:
        result = session.run("""
            MATCH (p:Persona)-[:COMPATIBLE_CON]->(a:Animal {animal_id: $animal_id})
            RETURN p.person_id AS id, p.nombre AS nombre,
                   p.ciudad AS ciudad, p.tipo_vivienda AS vivienda
            LIMIT 5
        """, animal_id=animal_id)
        return [dict(r) for r in result]