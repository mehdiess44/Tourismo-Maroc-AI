# Lot 4 — Comparaison visuelle CPU

Les preuves du lot 3 servent de référence. La campagne du lot 4 utilise des partitions groupées et des inconnues. Elle se déroule localement.

## Registre et collecte

Les 131 lignes Excel ont été rapprochées du registre Git. Les 18 entrées artisanales propres au classeur sont conservées. Les quatre JPEG documentés au lot 3 gardent leur provenance et leurs empreintes. Les autres lignes du classeur restent à contrôler.

- [Registre de travail](../data/lot-4/audit-candidates.json)
- [Décisions pour les douze classes](../data/lot-4/class-decisions.csv)
- [Collecte ciblée et crédits](../data/lot-4/collection-candidates.json)

La collecte cible Bab Mansour et Heri es-Souani. Bab Berdieyinne et Bab Jama Nouar fournissent des pistes hors catalogue. Les métadonnées viennent des pages de fichiers Wikimedia Commons. Les JPEG récupérés se trouvent dans `workspace-data/lot-4/images`. Les copies redimensionnées sont signalées et leur SHA-256 porte sur la copie effectivement disponible. Commencer par les fichiers à date et crédit distincts, puis confirmer la séparation entre les séries. Pour Heri es-Souani, vérifier que le sujet correspond aux greniers ou écuries et distinguer les prises centrées sur le bassin Agdal.

Le manifeste a été gelé le 24 novembre 2026 à partir du registre reconstitué au lot 4. Il contient 45 JPEG, dont 23 de Bab Mansour, 20 de Heri es-Souani et deux portes hors catalogue. Les autres classes restent accessibles par recherche manuelle. Les séries du même auteur sont regroupées de manière conservatrice, y compris lorsqu’un auteur a photographié les deux monuments. La recherche de copies inter-partitions a combiné les SHA-256 et un contrôle perceptuel dHash.

| Classe | Train (images / groupes) | Validation (images / groupes) | Test (images / groupes) |
|---|---:|---:|---:|
| Bab Mansour | 14 / 12 | 4 / 4 | 5 / 4 |
| Heri es-Souani | 12 / 7 | 4 / 1 | 4 / 3 |
| Hors catalogue | 0 / 0 | 1 / 1 | 1 / 1 |
| Total images | 26 (58 %) | 9 (20 %) | 10 (22 %) |

Les effectifs par classe ne s’additionnent pas en nombre de groupes, car un groupe peut couvrir plusieurs classes dans la même partition. Les deux groupes hors catalogue sont distincts. Le registre historique du lot 2 reste à retrouver. [Manifeste gelé](../data/lot-4/manifest.json) · [SHA-256](../data/lot-4/manifest.sha256)

## Préparer le manifeste

Le fichier `data/lot-4/manifest.json` contient une ligne JSON par photo de campagne, dans un tableau. Renseigner `id`, `kind`, `label`, `status: "approved"`, `group`, `partition`, `sha256`, `author`, `license` et `source`. Le JPEG local s’appelle `<id>.jpg`. Réserver `label: null` aux inconnues de validation et de test. Viser 60/20/20 par type ou classe en conservant chaque groupe dans une seule partition. Documenter les proportions obtenues.

Chaque classe évaluée doit avoir 20 images, six groupes, des images dans les trois partitions et deux groupes au test. Vérifier les groupes, sources et empreintes des quatre photos du pilote avant de geler le registre. Les quatre groupes du lot 3 restent hors du test. Le registre gelé du lot 2 reste à retrouver, et la date du nouveau manifeste doit figurer dans le rapport.

```powershell
$python = '.\.venv\Scripts\python.exe'
$manifest = 'data/lot-4/manifest.json'
$images = 'workspace-data/lot-4/images'
& $python -m scripts.compare_vision check $manifest $images
```

Le contrôle vérifie les JPEG et les empreintes des trois partitions. Conserver sa sortie avec le commit et la date.

Pour récupérer la remise depuis un clone sur `main`, lancer `git pull --ff-only origin main`, puis `git lfs pull`. Les 45 JPEG, le manifeste et la configuration CLIP sont suivis par Git. Après le téléchargement du modèle, copier le fichier ONNX Git LFS sous le nom attendu par le dossier préparé de A.

```powershell
Copy-Item artifacts/vision.onnx workspace-data/lot-4/clip-prepared/clip.onnx
```

Les JPEG conservent les licences Creative Commons indiquées individuellement dans le manifeste, avec le crédit et la page d’origine. Les JPEG collectés au lot 4 ont été réencodés avec orientation appliquée et un côté maximum de 1 200 pixels. Les deux JPEG repris du pilote conservent les versions décrites dans le lot 3. [Crédits et licences](../data/lot-4/manifest.json) · [Versions des photos du pilote](lot-3-assets.md)

## Préparation, comparaison et test

Utiliser un environnement CPU avec les dépendances de développement et de recherche du dépôt. Réserver un dossier de sortie neuf pour la préparation. Cette commande lit les JPEG de train et de validation, construit les deux modèles, contrôle l’export et règle chaque seuil sur validation. Le JSON contient un résultat par photo, avec son groupe, son candidat, le score et la décision. Le label JSON `null` dans les mesures correspond à la catégorie inconnue.

```powershell
$prepared = 'workspace-data/lot-4/prepared'
& $python -m scripts.compare_vision prepare $manifest $images artifacts/vision.onnx $prepared
```

A a exécuté cette commande avec `--clip-only` et le dossier `workspace-data/lot-4/clip-prepared`. La galerie contient 26 références. Sur les neuf photos de validation, CLIP classe correctement les huit photos connues avant seuil. Après abstention, la macro-F1 vaut 0,8413 et l’unique inconnue est rejetée. Quatre photos de Heri es-Souani proviennent d’un seul groupe de validation. L’effectif d’inconnues reste d’une photo par partition. [Prédictions CLIP de validation](../data/lot-4/clip-validation.json)

B utilise `--clip-prepared workspace-data/lot-4/clip-prepared` avec la commande de préparation complète et un autre dossier de sortie pour reprendre exactement la galerie et les seuils de A. La sélection et le test comparatif utilisent cette préparation complète. Les mesures officielles du PC B et la décision figurent dans les résultats ci-dessous.

Pour comparer sur le PC B, archiver le pilote, puis installer un modèle préparé à la fois sous les noms `vision.onnx` et `vision.json`. Démarrer FastAPI avec PostGIS et un seul worker, relever le PID du worker et envoyer une première requête valide. Sur ce même worker, mesurer les 20 requêtes à chaud. Refaire sur le même PC avec le second modèle et la même photo **de validation**. Remplacer la valeur de `$workerPid` à chaque démarrage. Copier les deux sorties brutes à A.

```powershell
& $python -m scripts.compare_vision measure $photo artifacts $sortieJson --port 8000 --pid $workerPid
```

Le choix compare les deux pics mémoire et les maximums à chaud, puis la macro-F1 de validation, le taux d’inconnues acceptées et le P95. Le taux d’inconnues est calculé sur le total des inconnues des types évalués. En cas d’égalité sur les trois mesures, CLIP sert de départage final. Conserver le fichier de décision avant d’exécuter le test.

```powershell
& $python -m scripts.compare_vision choose $manifest $prepared $mesuresClip $mesuresResNet $decision
& $python -m scripts.compare_vision test $manifest $images $prepared $decision $resultatsTest
```

Le test recharge les artefacts contrôlés par empreinte. Comparer les effectifs, le Top-1 sur les connus, la macro-F1 après abstention, les inconnues acceptées, la matrice et les mesures HTTP de chaque type. Examiner les erreurs à partir des identifiants. Indiquer « non évalué » pour chaque type absent et signaler toute évaluation à classe unique.

## Décision et résultats du test final

Le choix a été enregistré le 24 novembre 2026 à 22 h 30 UTC avec les fichiers du commit `415a5dd`, avant l’inférence sur les 10 photos du test. Les deux modèles satisfont les limites CPU sur le même PC B avec PostGIS, un worker FastAPI et 20 requêtes exploitables par modèle. Le protocole retient **CLIP** pour sa meilleure macro-F1 après abstention sur la validation.

| Mesure de validation et de ressources | CLIP | ResNet-50 |
|---|---:|---:|
| Macro-F1 après abstention | 0,8413 | 0,6296 |
| Inconnues acceptées | 0/1 | 1/1 |
| P95 à chaud | 0,225 s | 0,227 s |
| Maximum à chaud | 0,237 s | 0,250 s |
| Pic mémoire du worker | 222,7 Mio | 315,0 Mio |

[Choix horodaté et empreintes](../data/lot-4/model-decision.json) · [Mesures du PC B](../data/lot-4/b-official-benchmark-summary.md)

Le test gelé contient 10 photos de six groupes, dont neuf photos connues et une hors catalogue. Les deux modèles ont été évalués avec les artefacts et les seuils figés. Les matrices de confusion et les prédictions par photo figurent dans le JSON. [Résultats bruts du test](../data/lot-4/final-test-results.json)

| Mesure sur le test gelé | CLIP | ResNet-50 |
|---|---:|---:|
| Premier candidat correct avant seuil, photos connues | 9/9 | 9/9 |
| Photos connues correctement acceptées après seuil | 2/9 | 8/9 |
| Macro-F1 après abstention | 0,2963 | 0,8519 |
| Inconnues acceptées | 0/1 | 0/1 |

Le seuil CLIP de 0,87745 laisse en état `uncertain` les cinq photos de Bab Mansour et deux des quatre photos de Heri es-Souani, malgré un premier candidat correct. ResNet-50 s’abstient sur une photo de Bab Mansour. Cet écart signale que le seuil CLIP calibré sur cette petite validation se transfère mal au test. L’unique inconnue de chaque partition limite la portée du taux d’acceptation observé.

CLIP reste la décision issue de la validation. Pour revoir le seuil ou la sélection à partir de ce constat, prévoir des groupes indépendants supplémentaires pour une nouvelle validation et un nouveau test. La recette du modèle retenu figure ci-dessous.

## Recette sur les deux PC

**Recette locale validée.** Les deux PC ont exécuté CLIP sur CPU avec la même galerie, le seuil gelé de 0,87745, les mêmes fichiers photo et un seul worker FastAPI connecté à PostGIS. B a testé `b126d4e` avec la configuration CLIP installée localement. Ses preuves sont publiées dans `9a7f218`. A a testé `cc96e80`, qui livre cette configuration dans le dépôt et ajoute le script de recette. Les fichiers du backend et le script de mesure sont identiques entre les deux révisions.

| Contrôle | PC A | PC B |
|---|---:|---:|
| Fichier invalide puis photo valide | HTTP 422 puis HTTP 200 | HTTP 422 puis HTTP 200 |
| Photo connue, premier candidat | `candidate`, Bab Mansour | `candidate`, Bab Mansour |
| Fiche de l’identifiant renvoyé dans PostGIS | HTTP 200 | HTTP 200 |
| Photo hors catalogue | `uncertain` | `uncertain` |
| Recherche manuelle de Bab Mansour | HTTP 200, fiche présente | HTTP 200, fiche présente |
| Requêtes à chaud exploitables | 20/20 | 20/20 |
| Médiane à chaud | 0,121 s | 0,115 s |
| P95 à chaud | 0,132 s | 0,143 s |
| Maximum à chaud | 0,172 s | 0,152 s |
| Pic mémoire du worker | 226,0 Mio | 223,1 Mio |

Les deux PC respectent le plafond de 400 Mio et la limite de moins de 30 s par requête chaude. Sur le PC A, le P95 passe de 0,503 s au lot 3 à 0,132 s, et le pic mémoire de 215,9 Mio à 226,0 Mio. Les essais utilisent des photos et des galeries différentes. A a importé les 12 fiches dans une base PostGIS temporaire dédiée à cette recette.

- PC A — [Recette HTTP et PostGIS](../data/lot-4/a-clip-recipe.json) · [Mesures à chaud](../data/lot-4/a-clip-warm.json)
- PC B — [Recette HTTP et PostGIS](../data/lot-4/b-clip-recipe.json) · [Mesures à chaud](../data/lot-4/b-clip-warm.json)

**Clôture du lot 4.** Le choix de CLIP est documenté, le test gelé est publié et la chaîne photo → candidat → fiche PostGIS a été reproduite sur les deux PC. Le test gelé reste la référence pour la limite d’abstention. CLIP n’a accepté que 2 photos connues sur 9 au seuil retenu.
