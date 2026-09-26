# RasterCutter - Plugin QGIS

[![QGIS](https://img.shields.io/badge/QGIS-3.0%2B-589632.svg)](https://qgis.org/)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Tests](https://img.shields.io/badge/Tests-36%20passed-brightgreen.svg)]()

**RasterCutter** est une extension pour QGIS permettant de découper efficacement des rasters (locaux ou distants) selon l'emprise précise d'un masque vectoriel ("pochoir"), avec gestion avancée des filtres attributaires, du multi-résolution et du tri spatial de dalles CAO/SIG.

---

## Fonctionnalités Principales

### 1. Découpe par Pochoir Vectoriel
- **Sources raster supportées** :
  - Données locales : GeoTIFF (`.tif`), JPEG 2000 (`.jp2`), ECW, etc.
  - Flux distants : WMTS, WMS, XYZ Tiles, WCS (avec détection automatique et sélection des niveaux de zoom).
- **Masque vectoriel flexible** :
  - Couches locales (GeoPackage, Shapefile, etc.) et distantes (WFS, PostGIS).
  - Prise en compte du filtre attributaire actif sur la couche.
  - Option de restriction aux entités sélectionnées.
  - Reprojection dynamique à la volée en cas de SCR différents.

### 2. Formats d'Export & Carroyage
- **GeoTIFF** (`.tif`) : avec canal alpha de transparence hors emprise (ou fond blanc optionnel pour impression).
- **MBTiles** (`.mbtiles`) : pyramides multi-échelles pour utilisation mobile/web.
- **JPEG 2000 carrelé** (`.jp2`) : découpage en grille régulière (1 km, 2 km, 5 km) avec calages géoréférencés (`.tab`, `.j2w`, `.tfw`) et génération automatique de tableaux d'assemblage en DXF et Shapefile.

### 3. Tri Spatial & Archivage de Dalles CAO
- Filtrage rapide et archivage automatique des dalles raster (ex. dalles IGN) selon l'emprise d'un polygone.
- Réduction drastique du volume disque serveur tout en assurant la compatibilité AutoCAD et QGIS.

### 4. Moteur Asynchrone & Non-Bloquant
- Traitements exécutés en tâche de fond via `QgsTask` : l'interface QGIS reste fluide et réactive.
- Barre de progression précise et possibilité d'annulation à tout moment.
- Chargement automatique du résultat dans le projet QGIS à la fin du traitement.

---

## Structure du Dépôt

```text
raster_cutter/
├── .github/
│   └── workflows/
│       └── tests.yml             # Intégration continue (GitHub Actions)
├── tests/
│   ├── conftest.py               # Configuration de session QgsApplication headless
│   └── unit/                     # 36 tests unitaires
├── dalles_filter.py              # Moteur de tri spatial et découpe de dalles
├── icon.png                      # Icône de l'extension
├── __init__.py                   # Point d'entrée de l'extension QGIS
├── LICENSE                       # Licence GNU GPL v3
├── metadata.txt                  # Métadonnées officielles du plugin QGIS
├── package.sh                    # Script d'empaquetage ZIP pour diffusion
├── pochoir_raster_dialog.py      # Interface graphique Qt (dialogue principal)
├── pochoir_raster_plugin.py      # Gestion des menus et de l'intégration QGIS
├── pochoir_raster_worker.py      # Moteur de découpe asynchrone (QgsTask)
├── pytest.ini                    # Configuration d'exécution pytest
└── README.md                     # Documentation du projet
```

---

## Installation

### Méthode 1 : Clonage Git direct (Recommandé pour les développeurs)
Clonez directement le dépôt dans le répertoire des extensions de votre profil QGIS :

```bash
cd ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/
git clone https://github.com/AguirreM/RasterCutter.git raster_cutter
```

### Méthode 2 : Installation via Archive ZIP
1. Générez l'archive à l'aide du script fourni :
   ```bash
   ./package.sh
   ```
2. Dans QGIS, rendez-vous dans le menu **Extensions** > **Installer/Gérer les extensions** > **Installer depuis un fichier ZIP**.
3. Sélectionnez le fichier `raster_cutter.zip`.

---

## Exécution des Tests

Les tests unitaires utilisent `pytest` et une session PyQGIS headless. Pour exécuter l'ensemble de la suite (36 tests) :

```bash
pytest tests/unit
```

---

## Auteur & Licence

- **Auteur** : Aguirre MAURIN
- **Organisme** : EPAGE / SMBVA
- **Année** : 2026
- **Licence** : [GNU General Public License v3.0](LICENSE) (GNU GPL v3)
