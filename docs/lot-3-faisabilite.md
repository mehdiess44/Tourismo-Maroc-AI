# Tourismo AI – Lot 3 : Faisabilité CPU
**Date d'exécution :** 2026-11-23
**Auteur :** Membre A
**Dépôt :** https://github.com/mehdiess44/Tourismo-Maroc-AI
**Commit de référence :** `414001e` (Publier le prototype Tourismo Maroc AI)
**Environnement :** Windows 11 Home, 12th Gen Intel Core i5-1240P, 15,7 Gio RAM, Python 3.12/3.13, Docker 29.5.2, PostgreSQL 17 / PostGIS 3.5

---

## 1. Identification de la copie de travail et environnement

| Élément | Valeur constatée |
|---|---|
| Copie Git utilisée | Copie locale de publication |
| Commit de référence | `414001e` – *Publier le prototype Tourismo Maroc AI* |
| Système d'exploitation | Microsoft Windows 11 Home |
| Processeur | 12th Gen Intel(R) Core(TM) i5-1240P (16 threads logiques) |
| RAM installée | 15,7 Gio |
| Python système | 3.12.12 (Anaconda) |
| Python du venv (`.venv`) | Python 3.13.x |
| Dépendances installées | `fastapi 0.165.0`, `uvicorn 0.54.0`, `psycopg 3.3.9`, `onnxruntime 1.32.0`, `pillow 12.3.0`, `numpy 2.5.5`, `psutil 7.2.2`, `httpx 0.28.1` |
| Docker & Docker Compose | Docker version 29.5.2, Docker Compose v5.1.3 |

---

## 2. Preuve PostGIS et lecture en base (Exécutée et validée)

### 2.1 Démarrage de la base locale dédiée

La base locale dédiée est configurée via le fichier `compose.yaml` avec l'image officielle `postgis/postgis:17-3.5`.
Le mot de passe de test a été injecté exclusivement en mémoire de session via `$env:TOURISMO_DB_PASSWORD` et `$env:TOURISMO_DATABASE_URL` (format `postgresql://tourismo:<mot_de_passe_masqué>@127.0.0.1:5432/tourismo`). Aucune valeur secrète n'est inscrite dans le code, les fichiers suivis ou ce rapport.

Le volume `tourismo-marocai_tourismo-db` a été initialisé proprement sans écraser de volume préexistant.

```powershell
$env:TOURISMO_DB_PASSWORD = Read-Host 'Mot de passe de la base locale' -MaskInput
$dbPasswordEncoded = [uri]::EscapeDataString($env:TOURISMO_DB_PASSWORD)
$env:TOURISMO_DATABASE_URL = "postgresql://tourismo:$($dbPasswordEncoded)@127.0.0.1:5432/tourismo"
Remove-Variable dbPasswordEncoded
docker compose up -d db
docker compose exec db pg_isready -U tourismo -d tourismo
```
**Preuve observée :** `/var/run/postgresql:5432 - accepting connections` (Up, port `127.0.0.1:5432->5432/tcp`).

### 2.2 Import du catalogue et contrôles SQL

Exécution de l'import :
```powershell
.\.venv\Scripts\python.exe -m scripts.load_postgis
```

Contrôles SQL exécutés directement dans le conteneur :
1. **Version de PostGIS :**
   ```sql
   SELECT PostGIS_Version();
   ```
   **Résultat obtenu :** `3.5 USE_GEOS=1 USE_PROJ=1 USE_STATS=1`
2. **Nombre d’entités (1er import) :**
   ```sql
   SELECT COUNT(*) FROM entities;
   ```
   **Résultat obtenu :** `12` (conforme aux 12 fiches de `data/catalog.json`)
3. **Géométrie de Bab Mansour :**
   ```sql
   SELECT id, ST_AsText(location) AS geom_wkt, ST_SRID(location) AS srid FROM entities WHERE id = 'bab-mansour';
   ```
   **Résultat obtenu :**
   - `id` : `bab-mansour`
   - `geom_wkt` : `POINT(-5.564607 33.8928645)`
   - `srid` : `4326`
4. **Idempotence (2e import consécutif) :**
   Exécution à nouveau de `scripts.load_postgis` puis comptage :
   ```sql
   SELECT COUNT(*) FROM entities;
   ```
   **Résultat obtenu :** `12` (aucun doublon, mise à jour en place confirmée).

### 2.3 Preuve de lecture et résilience sur la même instance FastAPI

Le script `scripts/prove_postgis.py` a démarré une instance unique de FastAPI (PID 38100, 1 worker, sans reload) avec `TOURISMO_DATABASE_URL` configurée, et a enchaîné les trois états sur la même instance :

| Étape | Action | Statut HTTP | Latence | Données relevées |
|---|---|---|---|---|
| **1. Santé** | `GET /health` | **200 OK** | 0,05 s | `{"status": "ok", "vision_configured": false, "network_ready": true}` |
| **2. Base active** | `GET /entities/bab-mansour` | **200 OK** | 0,0459 s | Nom : *Bab Mansour*<br>Fait : *« La porte est connue sous le nom de Bab Mansour Laalej. »*<br>Source : `https://visit-meknes.com/fr/portfolio/bab-mansour-laalej-2/` |
| **3. Base arrêtée** | `docker compose stop db` puis `GET /entities/bab-mansour` | **Échec (Timeout)** | 5,0177 s | Connexion PostgreSQL interrompue, FastAPI refuse la requête en erreur |
| **4. Base restaurée** | `docker compose start db` (pg_isready 0 s) puis `GET /entities/bab-mansour` | **200 OK** | 0,0252 s | Fiche complète immédiatement disponible à nouveau sur la même instance (PID 38100) |

Les données brutes de cette séquence sont enregistrées dans [`data/postgis-proof.json`](../data/postgis-proof.json).

### 2.4 Mesure de latence de lecture d'entité sur PostGIS

Exécution de 10 requêtes successives de lecture sur `GET /entities/bab-mansour` (script `scripts/measure_entity.py`) :
- **Nombre d'appels :** 10
- **Succès HTTP :** 10 / 10 (100 %)
- **Latence 1er appel (création pool/connexion) :** 0,5827 s
- **Latences appels suivants :** 0,0495 s, 0,0197 s, 0,0446 s, 0,0616 s, 0,0639 s, 0,0604 s, 0,0608 s, 0,0510 s, 0,0557 s
- **Médiane :** **0,0581 s** (~58 ms)
- **Fichier brut :** [`data/entity-measures.json`](../data/entity-measures.json)

---

## 3. Mesures préliminaires (Historique et limitations)

Les mesures ci-dessous ont été réalisées lors de la première passe sans les livrables du membre B :

> [!WARNING]
> **Limitations des mesures préliminaires :**
> 1. Appels HTTP effectués avec un `vision.json` absent (`vision_configured: false`), renvoyant un statut métier `unavailable` et 0 candidat exploitable.
> 2. Benchmark de l'encodeur réalisé sur image synthétique (640×480 gris).
> 3. La mémoire de 63 Mio correspond au RSS du processus FastAPI sans le modèle CLIP complet chargé en mémoire. Les objectifs de moins de 400 Mio et de moins de 30 s devront être validés définitivement sur la chaîne complète avec la vraie photo.

### 3.1 Benchmark de l'encodeur ONNX (synthétique)

Fichier testé : `artifacts/vision.onnx` (89 117 001 octets, SHA-256 : `583fd1110a514667812fee7d684952aaf82a99b959760c8d7dca7e0ab9839299`).
Commande : `python -m scripts.benchmark_cpu`

| Métrique | Lot 3 préliminaire (2026-11-23) | Lot 2 historique |
|---|---|---|
| Entrée | Synthétique (640×480 gris) | Synthétique |
| Temps chargement modèle | **0,452 s** | 0,281 s |
| 1ère inférence | **0,072 s** | 0,046 s |
| Forme du vecteur de sortie | `[1, 512]` | `[1, 512]` |
| Pic Working Set (`peak_wset`) | **163,2 Mio** | 165,2 Mio |

### 3.2 Trois démarrages indépendants de FastAPI

Script : `scripts/measure_startup.py`
Données brutes : [`data/startup-measures.json`](../data/startup-measures.json) et [`data/startup-measures.csv`](../data/startup-measures.csv).

| Run | Délai lancement → premier `/health` réussi | PID |
|---|---|---|
| 1 | 3,325 s | 33360 |
| 2 | 2,161 s | 37164 |
| 3 | 2,197 s | 18756 |
| **Médiane** | **2,197 s** | — |

### 3.3 Série de 20 requêtes préliminaires

Script : `scripts/measure_requests.py --synthetic`
Données brutes : [`data/request-measures.json`](../data/request-measures.json) et [`data/request-measures.csv`](../data/request-measures.csv).

| Métrique | Valeur observée |
|---|---|
| Requêtes envoyées | 20 |
| Succès HTTP 200 | 20 / 20 (100 %) |
| Succès métier (`candidate` / `uncertain`) | **0 / 20** (statut `unavailable` car `vision.json` absent) |
| Latence du premier appel sans modèle chargé | 0,901 s |
| Latence médiane (sur les 20 requêtes) | **0,030 s** |
| Latence P95 (19e valeur triée sur 20) | **0,095 s** |
| Latence maximale | 0,901 s |
| RSS FastAPI en fin de série | **63,0 Mio** (PID 10024) |

---

## 4. Préparation du build Docker de démonstration

### 4.1 Correction de l'exclusion des artefacts (`Dockerfile.demo.dockerignore`)

Le fichier `.dockerignore` standard du dépôt exclut `artifacts/` pour ne pas versionner les modèles lourds. Lors d'un build d'image de démonstration autonome, l'instruction `COPY artifacts/vision.onnx` échouerait si le dossier est exclu du contexte.

Pour résoudre ce point sans modifier le `.dockerignore` global du projet, nous avons créé [`Dockerfile.demo.dockerignore`](../Dockerfile.demo.dockerignore) :
```dockerignore
.deps
.venv
**/__pycache__
frontend/node_modules
tmp
output
workspace-data
.env
.env.*
.git
.pytest_cache
Dataset_Images_Tourismo.xlsx

# Exclure le dossier artifacts sauf les deux fichiers strictement nécessaires :
artifacts/*
!artifacts/vision.onnx
!artifacts/vision.json
```

### 4.2 Dockerfile de démonstration (`Dockerfile.demo`)

Fichier : [`Dockerfile.demo`](../Dockerfile.demo)
Ce fichier copie le frontend construit (Node 22), installe les dépendances Python, copie le code applicatif, puis copie explicitement `artifacts/vision.onnx` et `artifacts/vision.json` avant d'exécuter un contrôle d'empreinte :
```dockerfile
COPY artifacts/vision.json ./artifacts/vision.json
COPY artifacts/vision.onnx ./artifacts/vision.onnx
RUN sha256sum artifacts/vision.onnx artifacts/vision.json
```

### 4.3 Commandes de construction et exécution sous limite mémoire

> [!NOTE]
> Le build attend obligatoirement `vision.json`. Aucun fichier factice n'a été créé pour simuler le build. Dès réception du fichier par B, les commandes exactes à lancer sont :

1. **Construction avec BuildKit (qui applique nativement `Dockerfile.demo.dockerignore`) :**
   ```powershell
   $env:DOCKER_BUILDKIT = "1"
   docker build -f Dockerfile.demo -t tourismo-demo .
   ```
2. **Contrôle d'empreinte dans l'image :**
   ```bash
   docker run --rm tourismo-demo sha256sum artifacts/vision.onnx artifacts/vision.json
   ```
3. **Lancement sous limite mémoire Render Free (512 Mio) relié à PostGIS :**
   ```powershell
   $dbPasswordEncoded = [uri]::EscapeDataString($env:TOURISMO_DB_PASSWORD)
   $databaseUrlLocal = $env:TOURISMO_DATABASE_URL
   $env:TOURISMO_DATABASE_URL = "postgresql://tourismo:$($dbPasswordEncoded)@db:5432/tourismo"
   docker run --rm -d --name tourismo-app `
     --memory 512m `
     --network tourismo-marocai_default `
     -e TOURISMO_DATABASE_URL `
     -p 8000:8000 `
     tourismo-demo
   $env:TOURISMO_DATABASE_URL = $databaseUrlLocal
   Remove-Variable dbPasswordEncoded, databaseUrlLocal
   ```
4. **Rejouer la reconnaissance et lire la fiche du premier candidat sur le conteneur.**
   ```powershell
   Invoke-WebRequest -Uri "http://127.0.0.1:8000/health"
   $photo = 'workspace-data/images/bab-mansour-essai.jpg'
   $response = curl.exe --fail-with-body -sS "http://127.0.0.1:8000/recognitions" -F "kind=monument" -F "photo=@$photo"
   if ($LASTEXITCODE -ne 0) { throw 'Échec de la reconnaissance' }
   $candidate = ($response | ConvertFrom-Json).candidates | Select-Object -First 1
   if (-not $candidate.id) { throw 'Aucun candidat retourné' }
   Invoke-WebRequest -Uri "http://127.0.0.1:8000/entities/$($candidate.id)"
   ```

---

## 5. Préparation de la reprise dès livraison par le Membre B

### 5.1 Éléments précis attendus du membre B

Le membre B doit fournir les éléments suivants, placés dans les répertoires indiqués :

1. `artifacts/vision.json` :
   - Fichier de métadonnées du modèle CLIP (dimensions `size`, moyennes `mean`, écarts-types `std`, labels, vecteurs de la galerie `gallery`, seuils par catégorie `thresholds`).
   - Fournir l'empreinte SHA-256 calculée.
2. `workspace-data/images/bab-mansour-ref.jpg` (Photo de référence) :
   - Photo servant à constituer l'entrée de galerie pour Bab Mansour.
   - Doit provenir d'une prise indépendante et d'un groupe distinct de ceux du test final gelé au lot 2.
   - Fournir la source, l'auteur, les droits/licence, la date de prise et l'empreinte SHA-256.
3. `workspace-data/images/bab-mansour-essai.jpg` (Photo d'essai) :
   - Vraie photo d'essai pour la démonstration.
   - **Doit impérativement rester hors de la galerie**.
   - Prise indépendante et groupe distinct du test final gelé.
   - Fournir la source, l'auteur, les droits/licence, la date de prise et l'empreinte SHA-256.

### 5.2 Chaîne de validation automatisée préparée (`scripts/run_proof_chain.py`)

Dès réception de la photo d'essai et de `vision.json`, exécuter :
```powershell
.\.venv\Scripts\python.exe scripts\run_proof_chain.py --image workspace-data\images\bab-mansour-essai.jpg
```

Ce script exécute et consigne automatiquement :
1. La vérification des 3 fichiers et leurs SHA-256.
2. `scripts.benchmark_cpu` sur la vraie photo.
3. Le démarrage de FastAPI avec la base PostGIS.
4. L'envoi d'un fichier invalide (texte) -> vérification du rejet HTTP 422.
5. L'envoi immédiat de la photo valide à `POST /recognitions` (`kind=monument`).
6. La vérification que le statut n'est ni `unavailable` ni une liste vide (`candidate` ou `uncertain` avec candidats).
7. La lecture de `GET /entities/{top_id}` avec l'identifiant retourné pour valider la chaîne bout-en-bout.
8. L'écriture du rapport d'exécution dans `data/final-proof.json`.

### 5.3 Protocole de mesures définitives avec B

Depuis la racine du dépôt, avec PostGIS actif, les deux artefacts en place et la connexion locale configurée comme en §2.1, lancez :

~~~powershell
.\.venv\Scripts\python.exe -m scripts.measure_startup --image workspace-data\images\bab-mansour-essai.jpg
~~~

Le script démarre trois processus successifs avec un seul worker. Après chaque premier /health réussi, il envoie et chronomètre une première reconnaissance à froid. Si la troisième reconnaissance produit des candidats, il lance 20 appels supplémentaires sur ce même processus. Il conserve l’ordre des appels, les réponses, la médiane, le P95 (19e valeur triée), le maximum et le pic du Working Set Windows lorsqu’il est disponible. Le RSS de fin de série est enregistré séparément.

Les résultats sont écrits dans workspace-data/lot-3-measures.json. Les fichiers data/startup-measures.* et data/request-measures.* conservent les résultats historiques. Utilisez les mêmes fichiers sur les deux ordinateurs et comparez le pic du backend à 400 Mio et les latences après chargement à l’objectif de moins de 30 s.

B reproduit l’installation PostGIS et la chaîne de reconnaissance sur son ordinateur. L’essai Render et Supabase attend la preuve locale et l’autorisation de créer les services.

---

## 6. Synthèse d'avancement du Lot 3

| Objectif du cahier de recette | Statut | Preuve observée / Emplacement |
|---|---|---|
| **1. Identifier copie de travail** | ✅ **Validé** | `414001e`, venv configuré, inventaire documenté (§1) |
| **2. Monter PostGIS** | ✅ **Validé** | Conteneur `postgis:17-3.5` Up, extensions PostGIS 3.5 chargées |
| **3. Importer catalogue (12 entités)** | ✅ **Validé** | 12 entités, point SRID 4326 Bab Mansour, 2e import idempotent |
| **4. Lecture fiche Bab Mansour en base** | ✅ **Validé** | HTTP 200 en 46 ms, fait et source vérifiés |
| **5. Résilience base (UP -> DOWN -> UP)** | ✅ **Validé** | Timeout sous coupure, retour immédiat (25 ms) à la reprise ([`data/postgis-proof.json`](../data/postgis-proof.json)) |
| **6. Latence 10 lectures PostGIS** | ✅ **Validé** | Médiane 58 ms, max 582 ms ([`data/entity-measures.json`](../data/entity-measures.json)) |
| **7. vision.onnx vérifié** | ✅ **Validé** | 89 117 001 octets, SHA-256 `583fd1...9299` |
| **8. Benchmark CPU encodeur (synthétique)** | ✅ **Validé** | Chargement 0,452 s, inférence 0,072 s, pic 163,2 Mio |
| **9. 3 démarrages FastAPI** | ✅ **Validé** | Médiane 2,197 s sur la configuration préliminaire ([`data/startup-measures.json`](../data/startup-measures.json)) |
| **10. 20 requêtes de reconnaissance** | **Préliminaire, 0 reconnaissance exploitable sur 20** | P95 0,095 s, RSS 63 Mio ([`data/request-measures.json`](../data/request-measures.json)) |
| **11. Configuration Docker de démonstration** | **Préparée, build à exécuter** | [`Dockerfile.demo`](../Dockerfile.demo) et [`Dockerfile.demo.dockerignore`](../Dockerfile.demo.dockerignore) prêts |
| **12. Script de chaîne complète** | **Préparé, essai sur vraie photo à exécuter** | [`scripts/run_proof_chain.py`](../scripts/run_proof_chain.py) prêt pour B |
| **13. Reconnaissance sur vraie photo** | ⏸ **En attente B** | Bloqué par `vision.json` et photo d'essai de Bab Mansour |
| **14. Build image finale tourismo-demo** | ⏸ **En attente B** | Bloqué par l'absence de `vision.json` (aucun faux créé) |
| **15. Déploiement Render / Supabase** | ⏸ **En attente** | Nécessite validation locale complète et autorisation explicite |
