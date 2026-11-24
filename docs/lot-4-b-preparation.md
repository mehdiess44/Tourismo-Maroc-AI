# Lot 4 — préparation technique ResNet-50 sur le PC B

Cette phase a été exécutée sur `main` au commit
`e1b8339ac133645a1fba6a0ce110ce1f1e9dd51d`. Elle vérifie seulement le
chargement et l'export du modèle ImageNet préentraîné. Aucun entraînement,
réglage de seuil ou examen des photos du test final n'a eu lieu.

## Environnement et poids

| Élément | Version ou valeur |
| --- | --- |
| Python | 3.12.0 (`.venv`) |
| PyTorch | 2.15.0+cpu |
| torchvision | 0.29.2+cpu |
| ONNX | 1.23.2 |
| ONNX Runtime | 1.32.0 |
| Fournisseur ONNX | `CPUExecutionProvider` seul |
| Graine | 42 |
| Poids | `ResNet50_Weights.IMAGENET1K_V2` |
| Source | `https://download.pytorch.org/models/resnet50-11ad3fa6.pth` |
| SHA-256 des poids | `11ad3fa62ca79e40addfd354a8ec4b7c75143b3038b8d2a807fbc68deab379ca` |

Le prétraitement vient de `ResNet50_Weights.IMAGENET1K_V2.transforms()` :
image RGB après correction EXIF, redimensionnement du petit côté à 232 pixels
par interpolation bilinéaire, découpe centrale de 224 × 224, conversion en
tenseur et normalisation avec moyenne `[0.485, 0.456, 0.406]` et écart type
`[0.229, 0.224, 0.225]`. L'entrée du modèle a la forme `1 × 3 × 224 × 224` ;
les logits ImageNet ont la forme `1 × 1000`.

## Essai du prototype

Commande, depuis la racine du dépôt :

```powershell
.\.venv\Scripts\python.exe -m scripts.lot4_resnet50_prototype
```

Le script utilise seulement les deux photos marquées `smoke` dans
`data/pilot-manifest.json`, après vérification de leur SHA-256. Elles servent à
une vérification technique de l'inférence, sans calcul de performance Tourismo.
Les sorties PyTorch et ONNX sont finies et leur premier index ImageNet concorde.

| Photo pilote | Premier index PyTorch / ONNX | Écart maximal absolu des logits |
| --- | ---: | ---: |
| `bab-mansour-2018.jpg` | 668 / 668 | 0,000003338 |
| `zellige-meknes.jpg` | 857 / 857 | 0,000009656 |

Ces index sont des indices ImageNet, sans correspondance avec les classes du
projet. Le rapport brut est `data/lot-4/b-resnet50-prototype.json`. L'export
technique est `artifacts/lot-4-prototype-resnet50-imagenet-v2.onnx` (SHA-256
`85853f54bdf57c69fe2938c12761eb7d46507145734c17ed4e73767a91b12fab`).
Le nom indique son statut de prototype. Les artefacts CLIP `vision.onnx` et
`vision.json` n'ont pas été remplacés.

## Pipeline préparé, encore non exécuté

`scripts.compare_vision` entraîne, calibre et évalue le test dans un même
appel. Pour respecter la séparation demandée aux pages 3–4 du cahier des
charges, `scripts.lot4_resnet50_phases` offre trois commandes distinctes :

1. `train` vérifie l'empreinte du manifeste, les décisions de classe et les
   groupes, lit uniquement les JPEG train avec leurs SHA-256, fige le réseau
   préentraîné, entraîne seulement la tête et écrit la tête, l'ONNX et la
   configuration avec ordre des labels, poids, prétraitement et graine.
2. `validate` recharge la tête et l'ONNX, vérifie leurs empreintes, compare les
   sorties PyTorch et ONNX sur les JPEG validation, enregistre chaque
   prédiction et calibre les seuils ONNX par type. Une inconnue de validation
   est requise pour chaque type évalué.
3. `test` charge seulement l'ONNX et les seuils déjà gelés, vérifie leurs
   empreintes et lit uniquement les JPEG test. Il écrit des prédictions, sans
   entraînement ni recalibration. Cette commande reste interdite avant le gel
   commun du choix et des artefacts.

Le **seul adaptateur provisoire** est `adapt_manifest()` dans le script des
phases. Le schéma final de A n'est pas encore connu. L'adaptateur exige pour
l'instant un objet avec `photos` et `class_decisions`. Les lignes photo
suivent les champs utilisés par `scripts.compare_vision` : `id`, `status`,
`partition`, `group`, `sha256`, `kind`, `label` et éventuellement `file`
(chemin relatif à `--images`; sinon `<id>.jpg`). Chaque décision contient
`label`, `kind` et un booléen `admissible`. Le script refuse un manifeste
sans décision explicite, filtre les classes non admissibles et ne déduit
aucun nombre de classes d'un seuil d'effectif. **Confirmer et adapter ce seul
point avec A avant le premier entraînement réel.**

Commandes prévues, depuis la racine du dépôt ; les chemins entre chevrons
seront remplacés après la remise de A :

```powershell
.\.venv\Scripts\python.exe -m scripts.lot4_resnet50_phases train --manifest <manifeste-gele.json> --manifest-sha256 <sha256-de-A> --images <dossier-jpeg> --output <dossier-artefacts-resnet>
.\.venv\Scripts\python.exe -m scripts.lot4_resnet50_phases validate --manifest <manifeste-gele.json> --images <dossier-jpeg> --artifacts <dossier-artefacts-resnet>
```

La sortie est `resnet50-head.pt`, `resnet50.onnx`,
`resnet50-trained.json`, puis `resnet50-calibrated.json` et
`validation-predictions.json`. Les commandes refusent d'écraser ces sorties.
Après le choix commun et le gel, la phase finale sera lancée séparément :

```powershell
.\.venv\Scripts\python.exe -m scripts.lot4_resnet50_phases test --manifest <manifeste-gele.json> --images <dossier-jpeg> --artifacts <dossier-artefacts-resnet> --output <predictions-test.json>
```

## Benchmark HTTP équitable à réaliser sur validation

`scripts.lot4_benchmark` démarre tour à tour une seule instance FastAPI avec
un worker pour CLIP et pour ResNet-50, en CPU. Il envoie la même séquence de
20 JPEG validés, triés par identifiant et répétés si nécessaire, après une
requête de chauffe pour chaque modèle. Il conserve chaque code HTTP, réponse,
durée, la médiane, le P95, le maximum, le pic réel `peak_wset` du worker sous
Windows, les empreintes des artefacts et les versions. Il contrôle les limites
de moins de 30 s par requête chaude et de 400 Mio de pic mémoire. Cette
mesure isolée concerne la reconnaissance HTTP, sans PostGIS ; la recette
complète de l'API vient après la sélection du modèle.

```powershell
.\.venv\Scripts\python.exe -m scripts.lot4_benchmark --manifest <manifeste-gele.json> --manifest-sha256 <sha256-de-A> --images <dossier-jpeg> --clip-onnx <clip-gele.onnx> --clip-config <clip-calibre.json> --resnet-artifacts <dossier-artefacts-resnet> --port 18004 --output data/lot-4/b-benchmark-validation.json
```

La configuration CLIP devra exposer les mêmes labels admissibles et des
seuils de validation pour chaque type évalué. Le benchmark refuse les ports
occupés et n'écrase pas un rapport existant. Il ne doit être lancé qu'après
le gel de la galerie et des seuils des deux modèles. Les tests logiciels
actuels ont utilisé uniquement des images et de petits modèles ONNX fictifs ;
ils ne constituent aucune mesure scientifique du Lot 4.

## Contrôles logiciels de cette phase

`python -m pytest -q` dans `.venv` : 23 tests réussis, dont 8 nouveaux tests
du Lot 4 sur le schéma provisoire, les décisions de classe, les fuites de
groupe, la calibration de validation et l'égalité exacte du prétraitement
NumPy/PIL du backend avec torchvision sur quatre images synthétiques.

Un essai éphémère avec quatre JPEG synthétiques a exécuté `train` et
`validate` : deux photos train, deux photos validation, tête et ONNX écrits,
prédictions de validation présentes. Le manifeste fictif comportait aussi
une ligne test pointant vers un fichier absent ; les deux phases ont réussi
sans ouvrir ce fichier. La commande `test` n'a pas été appelée.

Un essai HTTP éphémère avec deux petits modèles ONNX fictifs a vérifié le
banc complet : 20 réponses exploitables sur 20 pour CLIP et 20 sur 20 pour
ResNet, mêmes JPEG dans le même ordre, un worker CPU par modèle. Ces données
ont été générées pour tester le logiciel et n'entrent pas dans les résultats
du Lot 4.

## Intégration réversible après le choix du modèle

1. Conserver `artifacts/vision.onnx` et `artifacts/vision.json` avec leurs
   empreintes SHA-256 dans un dossier d'archive daté, hors des deux chemins
   actifs. Vérifier que les deux copies correspondent aux originaux.
2. Pour CLIP, contrôler que la galerie, l'ordre des labels, les seuils et les
   empreintes correspondent aux artefacts gelés de A. Pour ResNet-50,
   contrôler `resnet50-calibrated.json`, l'ordre des labels, les seuils et le
   prétraitement avant toute copie.
3. **Point de code à traiter après le choix :** `tourismo.vision.preprocess`
   utilise aujourd'hui `ImageOps.fit`, tandis que les poids ResNet V2 exigent
   resize 232 puis crop central 224. Une branche ResNet de prétraitement et
   une configuration API compatible sont donc nécessaires si ResNet est
   retenu. Ne pas installer l'ONNX ResNet sous `vision.onnx` avant ce contrôle.
4. Copier les deux artefacts retenus sous les noms actifs, vérifier leurs
   empreintes, redémarrer une seule instance FastAPI avec PostGIS puis rejouer
   `/health`, photo connue → candidat → `GET /entities/{id}`, photo hors
   catalogue, fichier invalide HTTP 422 suivi d'un fichier valide, et 20
   requêtes chaudes. Les scripts `run_proof_chain` et `measure_startup` du
   Lot 3 fournissent les points de départ pour cette recette.
5. En cas d'échec, arrêter cette instance, restaurer les deux copies archivées
   et revérifier leurs empreintes avant de redémarrer l'API. Ne toucher ni au
   conteneur ni au volume PostGIS des autres projets.

## Dépendances à obtenir de A

A doit remettre le manifeste gelé daté et son SHA-256, le schéma concret à
adapter, les fichiers locaux et empreintes, la décision explicite
d'admissibilité de chaque classe, les partitions par groupe, les exemples
hors catalogue de validation et test, la confirmation que les quatre groupes
du pilote restent hors test, puis la galerie CLIP et ses seuils calibrés.
Le choix commun du modèle et les seuils doivent être gelés avant le test final.
