# Tourismo AI — Faisabilité CPU du lot 3

Synthèse des essais du 24 novembre 2026, branche `lot-3-faisabilite`. A a testé le commit `58da036`. B a testé `24ac5f4` et publié ses preuves dans `729cb5b`.

**Sur A, sur B et dans Docker**, la vraie photo est passée par l’encodeur CLIP sur CPU. FastAPI a renvoyé HTTP 200, état `uncertain`, avec Bab Mansour au rang 1 (score 0,757849). Le premier identifiant renvoyé, `bab-mansour`, a ouvert sa fiche PostGIS via la même instance. Dans les trois environnements, le rejet explicite du fichier invalide (HTTP 422) a été suivi d’une reconnaissance valide. La galerie comporte une seule référence monument. Le rang observé établit la faisabilité de la démonstration.

**Recette locale validée.** La démonstration a été reproduite et mesurée sur les deux PC et dans Docker. **Remise commune en attente** du registre gelé du lot 2, du volet hébergé et de la relecture par B.

## Entrées communes

- Référence de Bab Mansour — `bab-mansour-2007.jpg`, Radosław Botev, CC BY 3.0 PL, groupe `botev-2007`.
- Photo d’essai — `bab-mansour-2018.jpg`, Steven Lek, CC BY-SA 4.0, groupe `lek-2018`, 960 × 636 px et hors de la galerie.
- Galerie de deux références au total. Les quatre fichiers photo locaux correspondent aux empreintes du manifeste. Le modèle quantifié est récupérable via Git LFS et l’encodeur utilise `CPUExecutionProvider`. Les preuves de A, de B et de Docker consignent les mêmes empreintes pour le modèle, la galerie et la photo d’essai. [Fichiers, sources, licences et empreintes](lot-3-assets.md)
- **Indépendance vis-à-vis du test final non vérifiable, registre gelé manquant.** Le classeur d’audit local contient 131 lignes avec la colonne **Partition** vide. La recherche dans les copies du projet, l’historique Git, les téléchargements et Google Drive n’a pas permis de retrouver le registre. Dès réception, B relève sa version et compare les groupes `botev-2007`, `lek-2018`, `prazeres-2015` et `cochrane-2014`, les sources et les SHA-256 aux entrées du test final. En cas de recoupement, remplacer l’image concernée, reconstruire la galerie si une référence change et rejouer la chaîne et les mesures sur A, B et Docker. [Manifeste des photos](../data/pilot-manifest.json)

## Environnements et preuves

| Élément | Ordinateur A | Ordinateur B |
|---|---|---|
| Système | Windows 11 Famille | Windows 11 Pro 64 bits |
| Processeur | Intel Core i5-1240P | AMD Ryzen 7 PRO 5850U |
| RAM | 15,7 Gio | 15,31 Gio |
| Python | 3.13.3 | 3.12.0 |
| Dépendances observées | FastAPI 0.165.0, Uvicorn 0.54.0, Psycopg 3.3.9, ONNX Runtime 1.32.0, NumPy 2.5.5, Pillow 12.3.0, psutil 7.2.2 | FastAPI 0.165.0, Uvicorn 0.54.0, Psycopg 3.3.9, ONNX Runtime 1.32.0, NumPy 2.5.5, Pillow 12.3.0, psutil 7.2.2 |

Sur A, une base PostGIS 3.5 isolée a reçu deux imports successifs de 12 fiches. La géométrie de Bab Mansour est `POINT(-5.564607 33.8928645)` en SRID 4326. L’essai historique sur l’instance locale dédiée montre la suite HTTP 200 → délai dépassé après arrêt de la base → HTTP 200 après reprise, sur le même serveur. [Environnement et contrôles A](../data/lot-3/a-environment.json) · [Preuve historique PostGIS](../data/postgis-proof.json) · [Lectures historiques de la fiche](../data/entity-measures.json)

Sur B, PostGIS 3.5 a également donné 12 fiches après chacun des deux imports, avec le même point Bab Mansour en SRID 4326. La lecture répond HTTP 200 en 0,048 s, expire pendant la coupure puis répond HTTP 200 en 0,082 s après le redémarrage de la base. Le PID et l’heure de démarrage de FastAPI sont identiques aux trois étapes. [Environnement B](../data/lot-3/b-environment.json) · [Deux imports PostGIS](../data/lot-3/b-postgis-imports.txt) · [Arrêt et reprise de PostGIS](../data/lot-3/b-postgis-recovery.json)

## Mesures brutes et synthèse

| Mesure | A (Windows) | B (Windows) | Docker local (Linux) | Render / Supabase |
|---|---:|---:|---:|---|
| Démarrage jusqu’à `/health`, médiane | 2,437 s | 2,439 s | — | — |
| Chargement de l’encodeur CPU | 0,460 s | 0,600 s | — | — |
| Prétraitement et première inférence de l’encodeur | 0,077 s | 0,085 s | — | — |
| Première reconnaissance HTTP | 2,360 s (médiane sur trois démarrages) | 1,055 s (médiane sur trois démarrages) | 0,901 s (un essai) | — |
| À chaud, médiane / P95 / max | 0,367 / 0,503 / 0,535 s | 0,150 / 0,178 / 0,200 s | 0,121 / 0,137 / 0,141 s | — |
| Réponses exploitables à chaud | 20/20 | 20/20 | 20/20 | — |
| Lecture HTTP de la fiche | 0,033 s | 0,056 s | 0,023 s | — |
| Pic backend | 215,9 Mio | 211,9 Mio | 276,31 Mio | — |
| Pic encodeur seul | 168,8 Mio | 164,4 Mio | — | — |
| Réveil après veille réelle | Sans objet | Sans objet | Sans objet | À mesurer |

Sur A, les trois processus FastAPI ont répondu en 2,625 / 2,430 / 2,437 s à `/health` avec PostGIS actif. Les premières reconnaissances ont duré 2,360 / 2,429 / 2,120 s. Sur B, les démarrages ont pris 2,534 / 2,439 / 2,427 s et les premières reconnaissances 1,164 / 1,055 / 1,037 s. Sur chaque PC, le troisième processus a enchaîné les 20 requêtes à chaud. Le pic correspond au *Working Set* Windows du worker. Dans Docker, `memory.peak` (cgroup v2) couvre la durée de vie du conteneur, avec une limite de 512 Mio et sans arrêt pour manque de mémoire. Chaque P95 est la 19ᵉ latence triée sur 20. A, B et Docker respectent les objectifs de 400 Mio et de moins de 30 s à chaud.

- A — [encodeur](../data/lot-3/a-encoder.json), [chaîne et fiche](../data/lot-3/a-chain.json), [trois démarrages et 20 requêtes](../data/lot-3/a-measures.json).
- B — [chaîne et fiche](../data/lot-3/b-chain.json), [trois démarrages et 20 requêtes](../data/lot-3/b-measures.json), [mesure distincte de l’encodeur seul](../workspace-data/benchmark_cpu_bab_mansour_2018.json). Cette dernière utilise ONNX Runtime 1.25.1, NumPy 2.4.4, Pillow 12.2.0 et psutil 7.2.2.
- Docker — [chaîne et 20 requêtes](../data/lot-3/docker-chain.json), [empreintes, limite et pic](../data/lot-3/docker-environment.json).
- Historique avant intégration des fichiers de B — [démarrages](../data/startup-measures.json) et [appels synthétiques](../data/request-measures.json), avec zéro reconnaissance exploitable lors de cette première série.

## Reproduction sur le second ordinateur

Récupérer la branche `lot-3-faisabilite`, exécuter `git lfs pull` et relever `git rev-parse HEAD`. Depuis la racine du dépôt, avec Docker Desktop démarré, lancer les commandes suivantes dans PowerShell. Le mot de passe doit correspondre à celui du volume si la base existe déjà.

~~~powershell
py -3.12 -m venv .venv
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install -r requirements-dev.txt
$env:TOURISMO_DB_PASSWORD = Read-Host 'Mot de passe de la base locale' -MaskInput
$dbPasswordEncoded = [uri]::EscapeDataString($env:TOURISMO_DB_PASSWORD)
$env:TOURISMO_DATABASE_URL = "postgresql://tourismo:${dbPasswordEncoded}@127.0.0.1:5432/tourismo"
Remove-Variable dbPasswordEncoded
docker compose up -d db
docker compose exec db pg_isready -U tourismo -d tourismo
~~~

Une fois PostgreSQL prêt, lancer l’import et la commande SQL ci-dessous deux fois. Vérifier les 12 fiches après chaque import, la version de PostGIS et le SRID 4326. Sur la base de test, faire un GET de la fiche, arrêter puis relancer la base, et rejouer ce GET après chacune des deux transitions en gardant la même instance FastAPI.

~~~powershell
& $python -m scripts.load_postgis
docker compose exec db psql -U tourismo -d tourismo -c "SELECT PostGIS_Version(), COUNT(*) FROM entities; SELECT id, ST_SRID(location), ST_AsText(location) FROM entities WHERE id='bab-mansour';"
~~~

Une fois la base rétablie, rejouer la chaîne et le protocole à froid et à chaud.

~~~powershell
$photo = 'workspace-data/images/bab-mansour-2018.jpg'
& $python -m scripts.run_proof_chain --image $photo --port 18000 --output data/lot-3/b-chain.json
& $python -m scripts.measure_startup --image $photo --port 18001 --output data/lot-3/b-measures.json
~~~

Pour une nouvelle exécution, conserver le commit, l’environnement et les résultats bruts. Comparer le rang, les 20 succès et les seuils avec les résultats du tableau.

## Reproduction Docker et hébergement

Construire l’image avec `docker build -f Dockerfile.demo -t tourismo-demo .`, puis vérifier les deux empreintes avec `docker run --rm tourismo-demo sha256sum artifacts/vision.onnx artifacts/vision.json`. Lancer un conteneur sous `--memory 512m` sur le réseau de PostGIS et transmettre `TOURISMO_DATABASE_URL` au démarrage. La connexion utilise `db` comme nom d’hôte. Publier le port de l’API sur la boucle locale. Une fois `/health` prêt, indiquer ce port à `scripts.run_proof_chain --existing-server --warm` et relever `/sys/fs/cgroup/memory.peak` dans le conteneur.

Après autorisation de créer les services et vérification du coût à 0 DH sur les comptes, utiliser le profil Render Free et le Dockerfile de démonstration. Vérifier que le build distant récupère le binaire LFS. Sur Supabase Free, activer PostGIS, importer les 12 fiches et configurer la connexion dans les variables du service. Rejouer sur la version hébergée et relever le délai de réveil après la mise en veille réelle, la première reconnaissance qui suit, les latences à chaud et le pic accessible. Les comptes n’ont pas été vérifiés. [Conditions Render Free](https://render.com/docs/free) · [Offre gratuite Supabase](https://supabase.com/pricing) · [PostGIS sur Supabase](https://supabase.com/docs/guides/database/extensions/postgis)

**Statut au 24 novembre 2026** — essai non réalisé. La création des services reste à autoriser et les quotas ainsi que le coût à 0 DH restent à confirmer sur les comptes. La documentation publique de Render indique 0,1 CPU et 512 MB pour un service web gratuit, avec mise en veille après 15 minutes sans trafic entrant. Supabase affiche une offre à 0 $ et une limite de deux projets gratuits actifs. Ces conditions publiques donnent le cadre du test. Les mesures de réveil, de reconnaissance et de mémoire hébergées restent à relever. [Profil de calcul Render](https://render.com/docs/compute-plans) · [Mise en veille Render](https://render.com/docs/free) · [Tarifs Supabase](https://supabase.com/pricing)
