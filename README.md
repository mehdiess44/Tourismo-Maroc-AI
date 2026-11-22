# Tourismo Maroc AI · pilote de Meknès

Application en français pour consulter le patrimoine, proposer des candidats visuels et calculer une promenade. Le catalogue initial comporte 12 fiches avec des références, en cours de revue croisée. La carte prétraitée couvre huit points candidats de Meknès.

## Lancement local sous Windows

Depuis la racine dans PowerShell, avec Python 3.13 et Node 22.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
Push-Location frontend
npm.cmd ci
npm.cmd run build
Pop-Location
.\.venv\Scripts\python -m uvicorn tourismo.api:app --host 127.0.0.1 --port 8000
```

Ouvrir http://127.0.0.1:8000 pour React et http://127.0.0.1:8000/docs pour OpenAPI. Dans une autre console, lancer `.\.venv\Scripts\python -m streamlit run prototype.py` pour le prototype Streamlit. Le catalogue JSON est chargé par défaut. Pour PostgreSQL/PostGIS, démarrez le service Compose avec une valeur locale de `TOURISMO_DB_PASSWORD`, définissez `TOURISMO_DATABASE_URL` avec la chaîne de connexion du compte, puis lancez `python -m scripts.load_postgis` avant l’API. La restauration repart de `data/catalog.json` et `data/network.json`.

## Données et expériences

- **Géographie.** Extrait [OpenStreetMap](https://www.openstreetmap.org/copyright) obtenu avec l’API cartographique dans la boîte `-5.577,33.878,-5.551,33.904`. Les dérivés `data/network.json` et `data/streets.geojson` sont sous ODbL 1.0. `python -m scripts.prepare_network <extrait.osm>` régénère les chemins et la carte avec NetworkX. Les accès sont des nœuds piétons voisins à vérifier. Les durées de visite sont estimées. Le réseau utilise des horaires datés lorsque ces données sont disponibles. Ajouter dans `poi.json` des horaires datés sous la forme `"hours":{"2026-12-15":[[540,720],[840,1020]]}`, avec la source et sa date de contrôle à côté du champ. Une liste vide indique une fermeture confirmée pour ce jour.
- **Dossiers photo.** `data/photo-candidates.json` contient quatre entrées Wikimedia Commons et 109 liens de Visit Meknès pour les huit monuments. Les entrées Visit Meknès sont en attente de revue. `python -m scripts.pilot_vision` télécharge les quatre images Commons du pilote et l’encodeur CLIP quantifié, calcule les SHA-256 et crée une galerie exploratoire. En cas de limitation par Wikimedia, placez les originaux Commons dans `workspace-data/images/<id>.jpg`, puis relancez.
- **Campagne visuelle.** Exécuter `python -m scripts.audit_images data/photo-candidates.json`. Pour lancer la comparaison, créer un manifeste audité avec les mêmes champs, un `status` valant `approved`, le `kind`, le `sha256` et la `partition` (`train`, `validation`, `test`). Les inconnues ont un `label` nul et un type. Documenter les fichiers rejetés avec leur motif. Vérifier les doublons et assigner les groupes avant de geler le test. Installer `requirements-research.txt` puis lancer `python -m scripts.compare_vision <manifest.json> <images> <clip.onnx> <dossier-sortie>`. Choisir le modèle à partir des résultats et des mesures CPU, puis placer son ONNX et sa configuration sous `artifacts/vision.onnx` et `artifacts/vision.json`. Redémarrer l’API après installation du modèle.
- **Fiches.** `data/history-evaluation.json` contient cinq passages paraphrasés et 24 questions, dont huit sans preuve suffisante. Lancer un serveur llama.cpp compatible OpenAI avec un Qwen local, puis `python -m scripts.history data/history-evaluation.json <sortie.jsonl>`. Comparer les réponses brutes aux preuves avant correction. Les fiches publiques restent des textes préparés et vérifiables, indépendants de Qwen.
- **Itinéraires.** Le solveur compare des coûts géographiques et de marche, puis pondère les étapes par intérêts en mode personnalisé. Le validateur contrôle horaires connus, étapes requises et durée. Les horaires inconnus sont signalés. Les trois stratégies sont disponibles via `tourismo.planning.plan`.

## Vérification et publication

`python -m pytest -q` vérifie le catalogue, les entrées photo, les cas d’itinéraires et les requêtes successives. Le build frontend vérifie TypeScript et compile les fichiers React. Les photos visiteurs ne sont pas intégrées aux données de recherche.

Le Dockerfile construit le client et sert les deux via FastAPI. Les données fournies permettent de démarrer sans fournisseur externe. Pour une démonstration cloud, vérifier les quotas avant toute mise en ligne et prévoir un export local. Les artefacts visuels ne sont pas inclus dans l’image Docker de base.

Le premier lot d’audit reste à compléter en revue croisée. Les horodatages et mesures locales ne constituent pas une validation terrain ou une mesure sur un fournisseur d’hébergement.

## Résultats de cette première recette

- `data/walk-results.json` contient 12 demandes et 36 parcours validés. La personnalisation a changé les étapes ou leur ordre dans cinq demandes face au coût de marche seul. Dans une demande, elle a retenu une visite supplémentaire correspondant à l’intérêt choisi. Toutes les sorties restent des estimations.
- `data/cpu-smoke.json` mesure l’encodeur CLIP seul sur une image synthétique. Pour répéter la mesure après téléchargement du modèle, lancer `python -m scripts.benchmark_cpu`. L’option `--image` accepte une photo de test. Le téléchargement des quatre photos de référence et d’essai a reçu HTTP 429. La galerie et les métriques de reconnaissance restent à produire à partir des fichiers autorisés.
- PostGIS dispose d’une configuration Compose et d’un chargeur. L’exécution de la base reste à vérifier sur un Docker actif. L’évaluation Qwen et le déploiement public restent également à valider.

## Contribuer

Ouvrez une issue pour signaler une erreur ou proposer une amélioration, puis soumettez une pull request. Pour une correction du catalogue, conservez les identifiants existants et indiquez la source et le passage utilisé. Pour une photo candidate, ajoutez la page d’origine et les métadonnées disponibles au manifeste. Lancez les tests Python et le build frontend avant de proposer des changements de code.

## Licences et attributions

- Le code et la documentation originale du projet sont sous [licence MIT](LICENSE).
- `data/network.json` et `data/streets.geojson` contiennent des données © les contributeurs d’OpenStreetMap, distribuées sous [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). Voir les [attributions OpenStreetMap](https://www.openstreetmap.org/copyright).
- Le catalogue cite ses sources. Le manifeste photo publie des liens et des métadonnées. Les fichiers image et les modèles sont disponibles auprès de leurs sources selon leurs propres conditions. Pour les candidates Visit Meknès, l’auteur et la licence restent à confirmer.
