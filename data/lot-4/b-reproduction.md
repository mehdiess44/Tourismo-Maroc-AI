# Lot 4 — Reproduction membre B

Commit de référence : `d56ebd0450daaab45d3e197e06db539c206668bb`.
SHA-256 du manifeste : `470e3c824518a65c380a46f8dba4d75ae39058af8ecdeba62ebf498c89a7fa87`.

## Préparation commune

Python provient de `.venv` et l'exécution ONNX utilise `CPUExecutionProvider`. Le dossier `workspace-data/lot-4/prepared-b-common` a été produit avec :

```powershell
$python = '.\.venv\Scripts\python.exe'
Copy-Item artifacts/vision.onnx workspace-data/lot-4/clip-prepared/clip.onnx
& $python -m scripts.compare_vision prepare data/lot-4/manifest.json workspace-data/lot-4/images artifacts/vision.onnx workspace-data/lot-4/prepared-b-common --clip-prepared workspace-data/lot-4/clip-prepared
```

La copie locale `clip.onnx` doit avoir le SHA-256 `583fd1110a514667812fee7d684952aaf82a99b959760c8d7dca7e0ab9839299`. Les empreintes des trois fichiers CLIP du dossier commun sont identiques à celles de `clip-prepared/prepared.json`. Le dossier commun contient les deux ONNX, les configurations et seuils, les prédictions par photo de validation, ainsi que `prepared.json` avec les empreintes des six fichiers. `resnet50.json` contient le contrôle PyTorch/ONNX sur les neuf photos de validation.

La commande `prepare` lit uniquement les JPEG `train` et `validation`. Elle entraîne la dernière couche ResNet-50 sur les 26 images `train` et calibre les seuils sur les neuf images `validation`. Ne pas lancer `check` ni `test` pour reproduire cette phase sans autorisation d'ouvrir les JPEG `test`.

## Mesures officielles sur le PC B

PostGIS doit être démarré. Le script PowerShell demande localement le mot de passe avec `Read-Host -AsSecureString`, construit l'URL de connexion uniquement dans l'environnement du processus et efface les variables en sortie. Aucun mot de passe n'est écrit dans les résultats.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\lot4_official_local.ps1
```

`scripts.lot4_official_benchmark` sélectionne explicitement `commons-152724069`, une image connue de **validation**, et vérifie son SHA-256. Il place une copie de chaque modèle dans `workspace-data/lot-4/official-benchmark-stage` sous les noms `vision.onnx` et `vision.json` ; `artifacts/vision.*` reste intact. Pour chaque modèle, il lance un seul worker de l'application `tourismo.api:app` sur `127.0.0.1:18005`, vérifie `/health` et la fiche Bab Mansour via PostGIS, effectue une reconnaissance de chauffe, puis appelle exactement `scripts.compare_vision measure` pour les vingt requêtes à chaud. Les deux workers sont exécutés successivement, sur le même port et avec la même photo.

Les sorties brutes sont `data/lot-4/b-clip-measure-v2.json` et `data/lot-4/b-resnet50-measure-v2.json`. Les conditions, le commit, les temps de démarrage et les reconnaissances de chauffe figurent dans `data/lot-4/b-official-benchmark-conditions-v2.json`. Les journaux des workers sont `data/lot-4/b-clip-worker-v2.log` et `data/lot-4/b-resnet50-worker-v2.log`. Les premières mesures officielles à mémoire invalide restent archivées dans `workspace-data/lot-4/benchmark-diagnostics`. Le benchmark isolé antérieur reste dans `data/lot-4/b-benchmark-validation.json` et n'entre pas dans ces mesures officielles.
