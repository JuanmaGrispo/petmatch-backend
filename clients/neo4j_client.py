from neo4j import GraphDatabase
import os
import math

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        uri      = os.environ.get("NEO4J_URI",      "neo4j+s://5b094d32.databases.neo4j.io")
        user     = os.environ.get("NEO4J_USER",     "5b094d32")
        password = os.environ.get("NEO4J_PASSWORD", "Cz66NRtkrzU0Mwy8oMme_GFLG1bLmvlN9E2I8Sdfjy8")
        _driver  = GraphDatabase.driver(uri, auth=(user, password))
    return _driver


def _clean(records):
    result = []
    for row in records:
        d = dict(row)
        result.append({k: (None if isinstance(v, float) and math.isnan(v) else v)
                       for k, v in d.items()})
    return result


def todas_las_personas():
    with get_driver().session() as session:
        result = session.run("""
            MATCH (p:Persona)
            WHERE p.person_id IS NOT NULL
              AND (p)-[:COMPATIBLE_CON]->(:Animal)
            RETURN p.person_id AS id, p.nombre AS nombre
            ORDER BY p.nombre
        """)
        return _clean(result)


def todos_los_refugios():
    with get_driver().session() as session:
        result = session.run("""
            MATCH (r:Refugio)
            RETURN r.nombre AS nombre
            ORDER BY r.nombre
        """)
        return _clean(result)


def todos_los_animales():
    with get_driver().session() as session:
        result = session.run("""
            MATCH (a:Animal)
            RETURN a.animal_id AS id, a.nombre AS nombre, a.tipo AS tipo
            ORDER BY a.nombre
        """)
        return _clean(result)


def recomendar_animales(person_id):
    with get_driver().session() as session:
        result = session.run("""
            MATCH (p:Persona {person_id: $pid})-[:COMPATIBLE_CON]->(a:Animal)
            RETURN a.animal_id AS id, a.nombre AS nombre,
                   a.tipo AS tipo, a.raza AS raza
            LIMIT 5
        """, pid=person_id)
        return _clean(result)


def animales_por_refugio(nombre_refugio):
    with get_driver().session() as session:
        result = session.run("""
            MATCH (a:Animal)-[:PERTENECE_A]->(r:Refugio {nombre: $nombre})
            RETURN a.animal_id AS id, a.nombre AS nombre,
                   a.tipo AS tipo, a.estado AS estado
            LIMIT 25
        """, nombre=nombre_refugio)
        return _clean(result)
    with get_driver().session() as session:
        result = session.run("""
            MATCH (a:Animal)-[:PERTENECE_A]->(r:Refugio {nombre: $nombre})
            RETURN a.animal_id AS id, a.nombre AS nombre,
                   a.tipo AS tipo, a.estado AS estado
        """, nombre=nombre_refugio)
        return _clean(result)


def historial_adopciones(person_id):
    with get_driver().session() as session:
        result = session.run("""
            MATCH (p:Persona {person_id: $pid})-[:ADOPTO]->(a:Animal)
            RETURN a.animal_id AS id, a.nombre AS nombre,
                   a.tipo AS tipo, a.raza AS raza
        """, pid=person_id)
        return _clean(result)


def animales_disponibles_por_tipo():
    with get_driver().session() as session:
        result = session.run("""
            MATCH (a:Animal)
            WHERE a.estado = 'Disponible'
            RETURN a.tipo AS tipo, count(a) AS cantidad
            ORDER BY cantidad DESC
        """)
        return _clean(result)


def personas_compatibles(animal_id):
    with get_driver().session() as session:
        result = session.run("""
            MATCH (p:Persona)-[:COMPATIBLE_CON]->(a:Animal {animal_id: $aid})
            RETURN p.person_id AS id, p.nombre AS nombre,
                   p.ciudad AS ciudad, p.tipo_vivienda AS vivienda
            LIMIT 5
        """, aid=animal_id)
        return _clean(result)
    

def personas_que_adoptaron():
    with get_driver().session() as session:
        result = session.run("""
            MATCH (p:Persona)-[:ADOPTO]->(:Animal)
            RETURN DISTINCT p.person_id AS id, p.nombre AS nombre
            ORDER BY p.nombre
        """)
        return _clean(result)