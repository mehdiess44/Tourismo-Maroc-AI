from copy import deepcopy
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tourismo.api import app
from tourismo.planning import Trip, plan
from tourismo.store import DATA, read_json

client = TestClient(app)
network = read_json(DATA / "network.json")
base = {"departure": "bab-mansour", "arrival": "dar-jamai", "day": "2026-11-22",
        "start": "10:00", "hours": 3, "speed": 4, "interests": ["architecture"]}


def test_catalog_and_upload():
    assert len(client.get("/catalog").json()) == 12
    assert client.get("/catalog", params={"q": "medersa"}).json()[0]["id"] == "bou-inania"
    assert client.get("/entities/zellige").json()["related"] == ["dar-jamai"]
    assert client.get("/entities/nonexistent").status_code == 404
    assert client.post("/recognitions", data={"kind": "monument"},
                       files={"photo": ("test.jpg", b"invalid")}).status_code == 422
    assert client.post("/recognitions", data={"kind": "monument"},
                       files={"photo": ("test.jpg", b"x" * (6 * 1024 ** 2))}).status_code == 413
    image = BytesIO()
    Image.new("RGB", (16, 16), "red").save(image, "PNG")
    response = client.post("/recognitions", data={"kind": "monument"},
                           files={"photo": ("test.png", image.getvalue())})
    assert response.status_code == 200
    assert response.json()["status"] in {"unavailable", "uncertain", "candidate"}


@pytest.mark.parametrize(("hours", "speed", "interest"), [
    (h, s, i) for h in [1, 3, 6] for s, i in
    [(3, "architecture"), (4, "artisanat"), (5, "musees"), (4, "histoire")]
])
def test_walk_scenarios(hours, speed, interest):
    trip = Trip(**(base | {"hours": hours, "speed": speed, "interests": [interest]}))
    for method in ("geographic", "network", "personalized"):
        result = plan(trip, network, strategy=method)
        assert result["status"] == "ok"
        assert result["minutes"] <= hours * 60
        assert sum(sum(step[key] for key in ("walk", "wait", "visit")) for step in result["steps"]) == result["minutes"]
        assert result["geometry"][-1] == result["steps"][-1]["position"]
        stops = [step for step in result["steps"] if step["visit"]]
        if stops:
            assert len(result["warnings"]) == len(stops)
        else:
            assert "directement" in result["warnings"][0]


def test_required_closed_and_waiting():
    known = deepcopy(network)
    day = base["day"]
    known["places"]["bou-inania"]["hours"][day] = []
    trip = Trip(**base, required=["bou-inania"])
    assert plan(trip, known)["status"] == "infeasible"
    known["places"]["bou-inania"]["hours"][day] = [[630, 675]]
    planned = plan(trip, known)
    assert planned["status"] == "ok"
    stop = next(step for step in planned["steps"] if step["id"] == "bou-inania")
    assert "T10:30" <= stop["start"][10:16] <= "T10:50"


def test_twenty_successive_requests():
    for _ in range(20):
        response = client.post("/itineraries", json=base)
        assert response.status_code == 200 and response.json()["status"] == "ok"
