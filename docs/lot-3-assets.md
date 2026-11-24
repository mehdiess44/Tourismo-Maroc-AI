# Lot 3 — actifs CLIP et mesure CPU du membre B

Ce document accompagne les fichiers du pilote. Les empreintes SHA-256 portent sur les fichiers publiés, pas nécessairement sur les originaux en pleine résolution des pages sources.

## Photos du pilote

| Fichier publié | Fichier indiqué par Wikimedia Commons | Version publiée et dimensions | Auteur | Source | Licence | Groupe | Rôle | SHA-256 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `workspace-data/images/bab-mansour-2007.jpg` | `Bab_Mansour_in_Meknes_2007.jpg` | Original, 1 783 × 1 148 px | Radosław Botev | [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Bab_Mansour_in_Meknes_2007.jpg) | [CC BY 3.0 PL](https://creativecommons.org/licenses/by/3.0/pl/) | `botev-2007` | `reference` | `80f9dfac330bdd7799ab3f449f202fd59f36c5c64d7bf9f14d8d1178bffe5753` |
| `workspace-data/images/bab-mansour-2018.jpg` | `Bab_Mansour_Meknes_2018_1.jpg` | Version Wikimedia `960px-Bab_Mansour_Meknes_2018_1.jpg`, 960 × 636 px | Steven Lek | [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Bab_Mansour_Meknes_2018_1.jpg) | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | `lek-2018` | `smoke` | `bfface3852a2a976fd18d70d354a05dec5b75c17784d2e28d7fb6f3aedd91608` |
| `workspace-data/images/zellige-dar-jamai.jpg` | `Dar_jamai_DSCF5529.jpg` | Version Wikimedia `960px-Dar_jamai_DSCF5529.jpg`, 960 × 1 280 px | Robert Prazeres | [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Dar_jamai_DSCF5529.jpg) | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | `prazeres-2015` | `reference` | `312526e5d3275bf4d420026455c20b54e5f231cdf0efa1f7cd6d3abfc53c67e6` |
| `workspace-data/images/zellige-meknes.jpg` | `Meknes_DSC03660_Morocco_(15276103936).jpg` | Version Wikimedia `960px-Meknes_DSC03660_Morocco_(15276103936).jpg`, 960 × 1 280 px | Ian Cochrane | [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Meknes_DSC03660_Morocco_(15276103936).jpg) | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/) | `cochrane-2014` | `smoke` | `8ea444365e30d463d633e2dad38fc0575b1eff160b558bdfb835c25e31e41b7b` |

Les trois fichiers préfixés `960px-` sont des versions redimensionnées, pas les originaux en pleine résolution. Leurs empreintes dans `data/pilot-manifest.json` correspondent aux versions locales ci-dessus. Les groupes `reference` et `smoke` sont distincts. L'indépendance de ces groupes vis-à-vis du test final gelé du Lot 2 reste à confirmer : aucun registre de ce test n'était présent dans le dépôt lors de la préparation.

## Modèle et galerie

- Modèle : encodeur visuel CLIP ViT-B/32 quantifié au format ONNX, issu de [Xenova/clip-vit-base-patch32](https://huggingface.co/Xenova/clip-vit-base-patch32), dérivé de `openai/clip-vit-base-patch32`. La page du modèle Xenova indique la licence **MIT**.
- Fichier téléchargé : [`onnx/vision_model_quantized.onnx`](https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/onnx/vision_model_quantized.onnx), publié ici sous `artifacts/vision.onnx`.
- SHA-256 de `artifacts/vision.onnx` : `583fd1110a514667812fee7d684952aaf82a99b959760c8d7dca7e0ab9839299`.
- SHA-256 de `artifacts/vision.json` : `5dd6757ce432db8d8e6cea13e8adc285496b3c8c8766ddd409ddb41ed7d8ba65`.
- Galerie : deux vecteurs de 512 valeurs, issus uniquement de `bab-mansour-2007` (`bab-mansour`) et `zellige-dar-jamai` (`zellige`). Les photos `smoke`, notamment `bab-mansour-2018`, n'y figurent pas. La session ONNX a été vérifiée avec `CPUExecutionProvider` uniquement. Les seuils de classification restent vides dans `vision.json`.

## Mesure CPU sur une vraie photo

Commande depuis la racine du dépôt :

```powershell
py -3.12 -m scripts.benchmark_cpu --image ".\workspace-data\images\bab-mansour-2018.jpg"
```

Sortie brute : `workspace-data/benchmark_cpu_bab_mansour_2018.json` (SHA-256 `6781e644e28512b3563ede5058ef235fd20f98783d8e521c53b15f645d9ecfb1`). Chargement du modèle : **0,600 s** ; prétraitement et première inférence : **0,085 s** ; vecteur : **1 × 512** ; pic du processus Python : **164,4 Mio**. Environnement mesuré : AMD Ryzen 7 PRO 5850U, Windows 11 Pro 64 bits, Python 3.12.0, ONNX Runtime 1.25.1, NumPy 2.4.4, Pillow 12.2.0 et psutil 7.2.2.

Ces valeurs concernent l'encodeur exécuté dans le script de benchmark, pas l'application FastAPI/PostGIS complète. Elles ne démontrent pas à elles seules la reconnaissance correcte de Bab Mansour.

## Récupération

Le modèle est suivi avec Git LFS. Après installation de Git LFS, le membre A peut exécuter `git lfs install`, puis `git pull` et `git lfs pull` depuis son dépôt. Les fichiers du pilote sont publiés aux chemins utilisés par les scripts.
