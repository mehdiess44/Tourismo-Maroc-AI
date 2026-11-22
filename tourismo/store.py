import json
import os
from pathlib import Path
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ARTIFACTS = ROOT / "artifacts"


def read_json(path, default=None):
    if default is not None and not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def catalog():
    if dsn := os.getenv("TOURISMO_DATABASE_URL"):
        import psycopg

        with psycopg.connect(dsn) as connection:
            rows = connection.execute("SELECT document FROM entities ORDER BY position")
            return [document for (document,) in rows]
    return read_json(DATA / "catalog.json")


def normalize(text):
    return "".join(
        char for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )
