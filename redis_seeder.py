"""
Redis Seeder para PetMatch.

Limpia y recarga el módulo de ranking: inicializa animales con IDs y nombres
ficticios, reconstruyendo animales:mapa y ranking:animales desde cero.

Uso:
    python redis_seeder.py               # carga 1000 animales por defecto
    python redis_seeder.py --n 30        # carga 30 animales
    python redis_seeder.py --limpiar     # solo limpia sin cargar
"""

import argparse
import random
import sys
from dotenv import load_dotenv

load_dotenv()

from clients.redis_client import get_redis, _segundos_hasta_medianoche

NOMBRES = [
    "Max", "Luna", "Rocky", "Bella", "Simba", "Nala", "Thor", "Mia",
    "Bruno", "Lola", "Duke", "Coco", "Toby", "Daisy", "Zeus", "Lily",
    "Charlie", "Rosie", "Jack", "Molly", "Buddy", "Zoe", "Oscar", "Ruby",
    "Milo", "Sadie", "Buster", "Maggie", "Bear", "Sophie", "Leo", "Gracie",
    "Tucker", "Chloe", "Oliver", "Stella", "Murphy", "Penny", "Sam", "Ellie",
    "Bailey", "Willow", "Archie", "Pepper", "Louie", "Ivy", "Gus", "Hazel",
    "Bentley", "Olive", "Chester", "Nora", "Finn", "Mabel", "Jasper", "Winnie",
    "Atlas", "Cleo", "Rex", "Zara", "Loki", "Scout"
]

APELLIDOS = [
    "Rodriguez", "Gomez", "Lopez", "Martinez", "Fernandez", "Garcia", "Perez",
    "Sanchez", "Romero", "Sosa", "Torres", "Diaz", "Reyes", "Flores", "Molina",
    "Medina", "Herrera", "Vargas", "Castro", "Suarez", "Morales", "Ortiz",
    "Rios", "Guerrero", "Mendoza", "Vega", "Ruiz", "Blanco", "Acosta", "Rojas"
]


def limpiar(r):
    """Borra todas las claves del módulo de ranking."""
    pipe = r.pipeline()
    pipe.delete("ranking:animales")
    pipe.delete("animales:mapa")

    # Borrar contadores diarios de visitas
    claves_visitas = r.keys("visitas:animal:*")
    for clave in claves_visitas:
        pipe.delete(clave)

    pipe.execute()
    print(f"  Limpieza completa. ({len(claves_visitas)} contadores diarios borrados)")


def cargar(r, n):
    """Inicializa n animales con datos ficticios."""
    # Generar nombres únicos combinando nombre + apellido
    # Con 62 nombres x 30 apellidos = 1860 combinaciones únicas posibles
    combinaciones = [f"{nom}_{ape}" for nom in NOMBRES for ape in APELLIDOS]
    random.shuffle(combinaciones)

    if n > len(combinaciones):
        print(f"[WARN] Se pidieron {n} animales pero solo hay {len(combinaciones)} combinaciones únicas. Se cargarán {len(combinaciones)}.")
        n = len(combinaciones)

    nombres_disponibles = combinaciones[:n]

    pipe = r.pipeline()
    ttl = _segundos_hasta_medianoche()

    for i in range(n):
        animal_id = f"A{10000 + i}"
        nombre = nombres_disponibles[i]
        visitas_historicas = random.randint(0, 300)
        visitas_hoy = random.randint(0, min(visitas_historicas, 20))
        contador_key = f"visitas:animal:{animal_id}"

        pipe.hset("animales:mapa", animal_id, nombre)
        pipe.zadd("ranking:animales", {nombre: visitas_historicas})
        pipe.set(contador_key, visitas_hoy, ex=ttl)

    pipe.execute()
    print(f"  {n} animales cargados. Nombres con formato Nombre_Apellido.")


def main():
    parser = argparse.ArgumentParser(description="Redis Seeder — PetMatch ranking")
    parser.add_argument("--n",       type=int, default=1000, help="Cantidad de animales a cargar (default: 1000)")
    parser.add_argument("--limpiar", action="store_true",  help="Solo limpia sin cargar nuevos datos")
    args = parser.parse_args()

    try:
        r = get_redis()
    except Exception as e:
        print(f"[ERROR] No se pudo conectar a Redis: {e}")
        sys.exit(1)

    print("\n── Redis Seeder · PetMatch ──────────────────")

    print("\n[1/2] Limpiando datos anteriores...")
    limpiar(r)

    if args.limpiar:
        print("\nListo. Solo se ejecutó la limpieza.")
    else:
        print(f"\n[2/2] Cargando {args.n} animales...")
        cargar(r, args.n)
        print(f"\nListo. Podés verificar con:")
        print(f"  ZREVRANGE ranking:animales 0 9 WITHSCORES")
        print(f"  HGETALL animales:mapa\n")


if __name__ == "__main__":
    main()