# Lot 4 — Mesures officielles du membre B

Les mesures ont été exécutées sur le commit `d56ebd0450daaab45d3e197e06db539c206668bb`, avec le manifeste gelé SHA-256 `470e3c824518a65c380a46f8dba4d75ae39058af8ecdeba62ebf498c89a7fa87`. Les deux modèles ont utilisé la même photo connue de **validation**, `commons-152724069`, le même PC Windows, un seul worker FastAPI à la fois, PostGIS et `CPUExecutionProvider`. La préparation commune est `workspace-data/lot-4/prepared-b-common` ; ses trois fichiers CLIP ont les empreintes exactes du dossier préparé par A.

| Mesure | CLIP | ResNet-50 |
|---|---:|---:|
| Démarrage jusqu'à `/health` | 2,516 s | 2,464 s |
| Première reconnaissance, après contrôle PostGIS | 1,114 s | 0,973 s |
| Appels HTTP exploitables | 20/20 | 20/20 |
| Latence médiane à chaud | 0,1835 s | 0,198 s |
| P95 à chaud | 0,225 s | 0,227 s |
| Maximum à chaud | 0,237 s | 0,250 s |
| Pic mémoire du **worker FastAPI réel** | 222,7 Mio | 315,0 Mio |
| Limite mémoire ≤ 400 Mio | Respectée | Respectée |
| Chaque appel à chaud < 30 s | Respectée | Respectée |
| Macro-F1 sur validation | 0,8413 | 0,6296 |
| Inconnues acceptées sur validation | 0/1 | 1/1 |

Les PID des workers réels sont `29504` pour CLIP et `21216` pour ResNet-50, distincts des processus lanceurs. La lecture `/entities/bab-mansour` depuis PostGIS a répondu HTTP 200 pour chacun. Chaque modèle a été chauffé par une reconnaissance HTTP 200 avant ses vingt appels. Les deux fichiers de mesure contiennent les vingt latences individuelles, codes HTTP et corps de réponse. Le pic est le `peak_wset` du worker FastAPI complet, mesuré par `scripts.compare_vision measure`.

Preuves : `data/lot-4/b-clip-measure-v2.json`, `data/lot-4/b-resnet50-measure-v2.json`, `data/lot-4/b-official-benchmark-conditions-v2.json`, `data/lot-4/b-clip-worker-v2.log` et `data/lot-4/b-resnet50-worker-v2.log`. La procédure sans secret est dans `data/lot-4/b-reproduction.md`. Le dossier commun contient les deux ONNX, configurations, prédictions de validation et empreintes. Le benchmark isolé antérieur reste dans `data/lot-4/b-benchmark-validation.json`. Les premières mesures officielles à mémoire invalide sont conservées dans `workspace-data/lot-4/benchmark-diagnostics` et ne doivent pas être utilisées pour la décision.

Aucune image `test` n'a été ouverte. Les artefacts opérationnels `artifacts/vision.onnx` et `artifacts/vision.json` n'ont pas été remplacés. Le choix du modèle et l'évaluation finale du test restent à effectuer après partage et validation de ces preuves avec A.
