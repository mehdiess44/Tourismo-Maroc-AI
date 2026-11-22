import os

import psycopg
from psycopg.types.json import Jsonb

from tourismo.store import DATA, read_json


def main():
    network = read_json(DATA / "network.json", {})
    entities = read_json(DATA / "catalog.json")
    with psycopg.connect(os.environ["TOURISMO_DATABASE_URL"]) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        conn.execute("""CREATE TABLE IF NOT EXISTS entities (
            id text PRIMARY KEY, position integer NOT NULL, document jsonb NOT NULL,
            location geometry(Point,4326))""")
        for position, entry in enumerate(entities):
            point = network.get("places", {}).get(entry["id"], {}).get("position")
            lon, lat = point[::-1] if point else (None, None)
            conn.execute("""INSERT INTO entities VALUES (%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326))
                ON CONFLICT (id) DO UPDATE SET position=EXCLUDED.position, document=EXCLUDED.document,
                location=EXCLUDED.location""", (entry["id"], position, Jsonb(entry), lon, lat))
        conn.execute("DELETE FROM entities WHERE NOT (id = ANY(%s))", ([entry["id"] for entry in entities],))


if __name__ == "__main__":
    main()
