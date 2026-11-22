from datetime import date, datetime, time, timedelta
from math import ceil
from typing import Literal
from zoneinfo import ZoneInfo

from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from pydantic import BaseModel, Field

from tourismo.store import DATA, read_json

Interest = Literal["architecture", "histoire", "musees", "artisanat"]


class Trip(BaseModel):
    departure: str
    arrival: str
    day: date
    start: time
    hours: int = Field(ge=1, le=6)
    speed: Literal[3, 4, 5] = 4
    interests: list[Interest] = Field(default_factory=list, max_length=4)
    required: list[str] = Field(default_factory=list, max_length=12)


def failure(status, reason):
    return {"status": status, "reason": reason, "steps": [], "warnings": []}


def travel(edge, speed):
    return ceil(edge["meters"] * 60 / (1000 * speed))


def opening(place, origin, duration, budget):
    # Exact date overrides avoid assuming recurring hours for Moroccan holidays.
    intervals = place.get("hours", {}).get(origin.date().isoformat())
    if intervals is None:
        return [(0, budget - duration)], True
    midnight = origin.replace(hour=0, minute=0, second=0, microsecond=0)
    offset = int((origin - midnight).total_seconds() // 60)
    windows = [(max(0, start - offset), min(budget, end - offset) - duration)
               for start, end in intervals]
    return [(lo, hi) for lo, hi in windows if lo <= hi], False


def verify(trip, origin, ordered, visits, paths, places):
    elapsed = 0
    geometry = []
    steps = []
    warnings = []
    previous = trip.departure
    used = set()
    for index, identifier in enumerate([*ordered, trip.arrival]):
        terminal = index == len(ordered)
        place = places[identifier]
        edge = paths.get(previous, {}).get(identifier)
        if edge is None:
            raise ValueError("Chemin absent")
        walking = travel(edge, trip.speed)
        arrived = elapsed + walking
        started = arrived if terminal else visits[index]
        duration = 0 if terminal else place["minutes"]
        if not terminal:
            windows, unknown = opening(place, origin, duration, trip.hours * 60)
            if identifier in used or not any(lo <= started <= hi for lo, hi in windows):
                raise ValueError("Étape répétée ou horaire incompatible")
            used.add(identifier)
            if unknown:
                warnings.append(f"Ouverture inconnue pour {place['name']}.")
        if started < arrived:
            raise ValueError("Heure de visite avant arrivée")
        elapsed = started + duration
        steps.append({
            "id": identifier, "name": place["name"], "position": place["position"],
            "walk": walking, "wait": started - arrived, "visit": duration,
            "start": (origin + timedelta(minutes=started)).isoformat(),
            "end": (origin + timedelta(minutes=elapsed)).isoformat(),
        })
        geometry.extend(edge["geometry"])
        previous = identifier
    if set(trip.required) - used or elapsed > trip.hours * 60:
        raise ValueError("Étapes imposées ou budget violés")
    if not used:
        warnings.append("Le parcours proposé relie directement le départ à l’arrivée.")
    return {"status": "ok", "steps": steps, "minutes": elapsed, "geometry": geometry,
            "warnings": warnings, "departure_position": places[trip.departure]["position"]}


def plan(trip, network=None, strategy="personalized"):
    if network is None:
        network = read_json(DATA / "network.json", {})
    places = network.get("places", {})
    paths = network.get("paths", {})
    if not places:
        return failure("unavailable", "Le réseau piéton doit être préparé.")
    requested = {trip.departure, trip.arrival, *trip.required}
    if requested - places.keys() or trip.start.tzinfo or trip.start.second or trip.start.microsecond:
        return failure("invalid", "Choisissez des lieux du pilote et une heure locale à la minute.")
    if len(set(trip.required)) != len(trip.required):
        return failure("invalid", "Une étape obligatoire figure plusieurs fois.")
    origin = datetime.combine(trip.day, trip.start, tzinfo=ZoneInfo("Africa/Casablanca"))
    budget = trip.hours * 60
    if origin.hour * 60 + origin.minute + budget > 1440:
        return failure("invalid", "La promenade doit se terminer le jour du départ.")
    direct = paths.get(trip.departure, {}).get(trip.arrival)
    if direct is None or travel(direct, trip.speed) > budget:
        return failure("infeasible", "La marche directe dépasse le budget ou aucun chemin n’est disponible.")

    candidates = []
    windows = {}
    for identifier, place in places.items():
        if identifier not in trip.required and identifier in {trip.departure, trip.arrival}:
            continue
        available, _ = opening(place, origin, place["minutes"], budget)
        if available and identifier in paths.get(trip.departure, {}) and trip.arrival in paths.get(identifier, {}):
            candidates.append(identifier)
            windows[identifier] = available
    if set(trip.required) - windows.keys():
        return failure("infeasible", "Une étape obligatoire est fermée ou inaccessible.")

    ids = [trip.departure, *candidates, trip.arrival]
    manager = pywrapcp.RoutingIndexManager(len(ids), 1, [0], [len(ids) - 1])
    routing = pywrapcp.RoutingModel(manager)
    missing = budget + 1

    def duration(before, after):
        left, right = manager.IndexToNode(before), manager.IndexToNode(after)
        edge = paths.get(ids[left], {}).get(ids[right])
        visit = places[ids[left]]["minutes"] if 0 < left < len(ids) - 1 else 0
        return travel(edge, trip.speed) + visit if edge else missing

    time_callback = routing.RegisterTransitCallback(duration)
    routing.AddDimension(time_callback, budget, budget, True, "Time")
    clock = routing.GetDimensionOrDie("Time")

    def cost(before, after):
        left, right = ids[manager.IndexToNode(before)], ids[manager.IndexToNode(after)]
        if strategy == "geographic":
            a, b = places[left]["position"], places[right]["position"]
            return round(10000 * ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5)
        edge = paths.get(left, {}).get(right)
        return travel(edge, trip.speed) if edge else missing

    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(cost))
    for node, identifier in enumerate(candidates, 1):
        index = manager.NodeToIndex(node)
        variable = clock.CumulVar(index)
        ranges = windows[identifier]
        variable.SetRange(ranges[0][0], ranges[-1][1])
        for (_, end), (begin, _) in zip(ranges, ranges[1:]):
            variable.RemoveInterval(end + 1, begin - 1)
        routing.AddVariableMinimizedByFinalizer(variable)
        if identifier not in trip.required:
            matches = len(set(trip.interests).intersection(places[identifier]["interests"]))
            penalty = 8 + 80 * matches if strategy == "personalized" and trip.interests else 40
            routing.AddDisjunction([index], penalty)
    routing.AddVariableMinimizedByFinalizer(clock.CumulVar(routing.End(0)))
    config = pywrapcp.DefaultRoutingSearchParameters()
    config.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    config.solution_limit = 100
    config.time_limit.FromMilliseconds(800)
    result = routing.SolveWithParameters(config)
    if result is None:
        if routing.status() == routing_enums_pb2.RoutingSearchStatus.ROUTING_INFEASIBLE:
            return failure("infeasible", "Aucun parcours ne respecte les contraintes.")
        return failure("no_solution", "Aucun parcours trouvé dans le temps de calcul.")
    order, starts = [], []
    current = result.Value(routing.NextVar(routing.Start(0)))
    while not routing.IsEnd(current):
        order.append(ids[manager.IndexToNode(current)])
        starts.append(result.Value(clock.CumulVar(current)))
        current = result.Value(routing.NextVar(current))
    try:
        return verify(trip, origin, order, starts, paths, places)
    except ValueError:
        return failure("invalid_solution", "Le contrôle indépendant a refusé le parcours.")
