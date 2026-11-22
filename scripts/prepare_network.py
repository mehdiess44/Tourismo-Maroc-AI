import argparse
import json
from math import asin, cos, radians, sin, sqrt
import xml.etree.ElementTree as ET

import networkx as nx

from tourismo.store import DATA, read_json

WALKABLE = {"footway", "pedestrian", "steps", "path", "living_street",
            "residential", "unclassified", "service", "tertiary", "secondary",
            "primary", "track", "tertiary_link", "secondary_link", "primary_link"}


def meters(left, right):
    a, b, c, d = map(radians, (*left, *right))
    value = sin((c - a) / 2) ** 2 + cos(a) * cos(c) * sin((d - b) / 2) ** 2
    return 12_742_000 * asin(min(1, sqrt(value)))


def prepare(source):
    root = ET.parse(source).getroot()
    points = {node.get("id"): (float(node.get("lat")), float(node.get("lon"))) for node in root.findall("node")}
    graph = nx.DiGraph()
    features = []
    for way in root.findall("way"):
        tags = {tag.get("k"): tag.get("v") for tag in way.findall("tag")}
        if tags.get("highway") not in WALKABLE or tags.get("area") == "yes":
            continue
        foot = tags.get("foot", tags.get("access", "yes"))
        if foot in {"no", "private", "customers"} or tags.get("construction") or tags.get("proposed"):
            continue
        refs = [node.get("ref") for node in way.findall("nd")]
        for left, right in zip(refs, refs[1:]):
            if left not in points or right not in points or left == right:
                continue
            distance = meters(points[left], points[right])
            if tags.get("oneway:foot") != "-1":
                graph.add_edge(left, right, meters=distance)
            if tags.get("oneway:foot") not in {"yes", "1"}:
                graph.add_edge(right, left, meters=distance)
            features.append({"type":"Feature", "geometry":{"type":"LineString",
                             "coordinates":[points[left][::-1], points[right][::-1]]}, "properties":{}})
    candidates = read_json(DATA / "poi.json")
    entities = {entry["id"]: entry for entry in read_json(DATA / "catalog.json")}
    nodes, places = {}, {}
    for identifier, candidate in candidates.items():
        point = points.get(candidate["osm_node"])
        if point is None:
            print(f"{identifier}: point OSM absent de l’extrait")
            continue
        nearest = min(graph, key=lambda node: meters(point, points[node]))
        distance = meters(point, points[nearest])
        if distance > 120:
            print(f"{identifier}: aucun accès à moins de 120 m")
            continue
        nodes[identifier] = nearest
        places[identifier] = {
            "name": entities[identifier]["name"], "interests": entities[identifier]["interests"],
            "minutes": candidate["minutes"], "position": points[nearest],
            "snap_meters": round(distance), "osm_node": candidate["osm_node"],
            "hours": candidate.get("hours", {}),
        }
    paths = {}
    for left, origin in nodes.items():
        distances, routes = nx.single_source_dijkstra(graph, origin, weight="meters")
        paths[left] = {right: {"meters": round(distances[node], 2),
                        "geometry": [points[p] for p in routes[node]]}
                       for right, node in nodes.items() if node in distances}
    version = max((element.get("timestamp", "") for element in root), default="")
    network = {"source": "OpenStreetMap contributors", "license": "ODbL 1.0",
               "latest_element_timestamp": version, "places": places, "paths": paths}
    for filename, document in (("network.json", network),
                               ("streets.geojson", {"type": "FeatureCollection", "features": features})):
        (DATA / filename).write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(places)} points et {len(features)} segments")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("extract", help="Extrait .osm XML")
    prepare(parser.parse_args().extract)
