"""Compare the itinerary strategies on the same twelve requests."""
import json
from time import perf_counter

from tourismo.planning import Trip, plan
from tourismo.store import DATA, read_json


def evaluate():
    network = read_json(DATA / "network.json")
    places = network["places"]
    cases = []
    for hours in (1, 3, 6):
        for speed, interest in ((3,"architecture"),(4,"artisanat"),(5,"musees"),(4,"histoire")):
            arrival = "dar-jamai" if interest in {"architecture", "histoire"} else "bab-el-khemis"
            trip = Trip(departure="bab-mansour", arrival=arrival, day="2026-11-22",
                        start="10:00", hours=hours, speed=speed, interests=[interest])
            row = {"request":trip.model_dump(mode="json"), "strategies":{}}
            for strategy in ("geographic", "network", "personalized"):
                start = perf_counter()
                result = plan(trip, network, strategy)
                elapsed = round((perf_counter() - start) * 1000, 2)
                stops = [step for step in result["steps"] if step["visit"]]
                tags = [set(places[step["id"]]["interests"]) for step in stops]
                row["strategies"][strategy] = {
                    "status":result["status"], "duration":result.get("minutes"),
                    "walking":sum(step["walk"] for step in result["steps"]),
                    "visits":[step["id"] for step in stops],
                    "interest_matches":sum(interest in group for group in tags),
                    "distinct_interests":len(set().union(*tags)),
                    "compute_ms":elapsed,
                }
            cases.append(row)
    return cases


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
