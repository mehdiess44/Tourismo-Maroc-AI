"""Retrouve des passages et enregistre les réponses brutes d'un modèle local."""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

from tourismo.store import normalize, read_json


def run(dataset, output, port):
    document = read_json(dataset)
    with output.open("w", encoding="utf-8") as stream:
        for item in document["questions"]:
            tokens = set(normalize(item["question"]).split())
            passages = sorted(document["passages"], key=lambda p: len(
                tokens.intersection(normalize(p["text"]).split())), reverse=True)[:4]
            context = "\n".join(f"[{p['id']}] {p['text']}" for p in passages)
            prompt = ("Réponds en français uniquement avec les passages fournis. "
                      "Indique l'identifiant du passage utilisé. Si aucune preuve ne suffit, "
                      "écris « information inconnue ».\n\n" + context + "\n\n" + item["question"])
            payload = {"messages":[{"role":"user","content":prompt}], "temperature":0, "max_tokens":160}
            request = Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                              data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
            with urlopen(request, timeout=180) as response:
                raw = json.load(response)["choices"][0]["message"]["content"]
            stream.write(json.dumps({"id":item["id"], "retrieved":[p["id"] for p in passages],
                                     "raw":raw}, ensure_ascii=False) + "\n")
            stream.flush()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    run(args.dataset, args.output, args.port)
