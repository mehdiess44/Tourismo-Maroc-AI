from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from tourismo.planning import Trip, plan
from tourismo.store import ARTIFACTS, DATA, ROOT, catalog, normalize, read_json
from tourismo.vision import MAX_BYTES, decode, recognize

app = FastAPI(title="Tourismo AI")


@app.middleware("http")
async def limit_photo_form(request: Request, call_next):
    if request.method == "POST" and request.url.path.rstrip("/") == "/recognitions":
        length = request.headers.get("content-length", "")
        if not length.isascii() or not length.isdecimal() or len(length) > 10:
            return JSONResponse({"detail": "Taille de l’envoi requise."}, status_code=411)
        if int(length) > MAX_BYTES + 64 * 1024:
            return JSONResponse({"detail": "La photo dépasse 5 Mio."}, status_code=413)
    return await call_next(request)


@app.get("/health")
def health():
    catalog()
    return {"status": "ok", "vision_configured": all(
        (ARTIFACTS / name).is_file() for name in ("vision.json", "vision.onnx")
    ), "network_ready": (DATA / "network.json").is_file()}


@app.get("/catalog")
def find(q: str = "", kind: Literal["monument", "artisanat"] | None = None):
    needle = normalize(q.strip())
    return [entry for entry in catalog() if (kind is None or entry["kind"] == kind)
            and any(needle in normalize(name) for name in [entry["name"], *entry["aliases"]])]


@app.get("/entities/{identifier}")
def entity(identifier: str):
    for entry in catalog():
        if entry["id"] == identifier:
            return entry
    raise HTTPException(404, "Fiche introuvable.")


@app.post("/recognitions")
def recognition(kind: Literal["monument", "artisanat"] = Form(), photo: UploadFile = File()):
    try:
        image = decode(photo.file.read(MAX_BYTES + 1))
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    finally:
        photo.file.close()
    return recognize(image, kind, {entry["id"] for entry in catalog() if entry["kind"] == kind})


@app.get("/places")
def places():
    return read_json(DATA / "network.json", {}).get("places", {})


@app.get("/map")
def map_data():
    return read_json(DATA / "streets.geojson", {"type": "FeatureCollection", "features": []})


@app.post("/itineraries")
def itinerary(trip: Trip):
    return plan(trip)


dist = ROOT / "frontend" / "dist"
if dist.is_dir():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(dist / "index.html")
