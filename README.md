# RasterCutter

[![QGIS](https://img.shields.io/badge/QGIS-3.0%2B-589632.svg)](https://qgis.org/)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Tests](https://img.shields.io/badge/Tests-45%20passed-brightgreen.svg)]()

RasterCutter est une extension pour QGIS conçue pour découper des couches rasters à partir d'un masque vectoriel (« pochoir »). L'outil prend en charge aussi bien les rasters locaux que les flux distants tuilés, gère le découpage en série multi-couches, et propose des options de carroyage régulier pour l'intégration des fonds de plan dans les logiciels de dessin assisté par ordinateur (CAO) et les systèmes d'information géographique (SIG).

---

## Fonctionnalités principales

### Découpe par pochoir vectoriel
L'extension permet d'utiliser n'importe quelle couche vectorielle présente dans le projet QGIS comme masque de découpe (polygone d'emprise, périmètre de bassin versant, limites administratives ou zonages d'études). Si la couche vectorielle dispose d'un filtre attributaire actif ou d'entités sélectionnées à l'écran, le masque s'adapte automatiquement pour ne retenir que la géométrie ciblée. La reprojection dynamique est prise en charge à la volée lorsque les systèmes de coordonnées de référence (SCR) du raster et du masque diffèrent.

Les sources rasters traitées incluent les fichiers locaux (GeoTIFF, JPEG 2000, ECW) ainsi que les flux géographiques distants tuilés (WMS, WMTS comme l'Ortho HR de l'IGN, XYZ Tiles et WCS). Pour les flux distants, l'extension détecte automatiquement les niveaux de zoom disponibles et calcule la résolution optimale selon l'échelle de travail.

### Formats d'export et carroyage spatial
Plusieurs modes de sortie répondent aux besoins de publication cartographique ou d'échange technique :
- Le format GeoTIFF produit un raster géoréférencé avec canal alpha pour assurer une transparence complète en dehors du masque, ou avec un fond blanc uni adapté aux contraintes d'impression.
- Le format MBTiles génère une pyramide de tuiles multi-échelles compacte, directement exploitable sur le terrain ou dans des applications cartographiques mobiles.
- Le format JPEG 2000 carrelé permet de découper l'emprise selon une grille régulière paramétrable (dalles de 1 km, 2 km ou 5 km). Ce mode génère automatiquement les fichiers de calage associés (fichiers TAB pour MapInfo, J2W et TFW pour AutoCAD et QGIS) ainsi que les tableaux d'assemblage vectoriels aux formats Shapefile et DXF.

### Traitement séquentiel multi-couches et exécution asynchrone
Lorsque plusieurs rasters sont sélectionnés, l'extension les traite de manière séquentielle dans un même dossier de destination. Chaque raster génère son propre sous-dossier ordonné, et les résultats peuvent être automatiquement chargés et regroupés dans l'arbre des couches QGIS au sein d'un groupe dédié.

L'ensemble des calculs lourds s'exécute en tâche de fond grâce à l'architecture asynchrone QgsTask. L'interface graphique de QGIS reste parfaitement fluide et réactive pendant le traitement, avec une barre de progression détaillée et la possibilité d'interrompre l'opération à tout moment sans perte de données.

### Tri spatial et archivage de dalles
L'extension intègre un moteur de filtrage rapide permettant de trier des répertoires entiers de dalles cartographiques (par exemple les dalles départementales de l'IGN) selon l'emprise d'un polygone. Les dalles intersectant le périmètre sont identifiées, copiées et accompagnées de leurs fichiers de calage, réduisant ainsi le volume de stockage serveur tout en assurant une parfaite compatibilité avec les outils métiers.

---

## Structure du dépôt

```text
rastercutter/
├── .github/
│   └── workflows/
│       └── tests.yml             # Intégration continue (GitHub Actions)
├── data/                         # Données de référence géographiques intégrées
├── tests/
│   ├── conftest.py               # Initialisation de la session PyQGIS headless
│   └── unit/                     # Suite complète de 45 tests unitaires
├── dalles_filter.py              # Moteur de tri spatial et gestion des dalles
├── icon.png                      # Icône de l'extension
├── __init__.py                   # Point d'entrée de l'extension QGIS
├── LICENSE                       # Licence libre GNU GPL v3
├── metadata.txt                  # Métadonnées officielles du plugin QGIS
├── package.sh                    # Script de génération de l'archive ZIP
├── pochoir_raster_dialog.py      # Interface graphique Qt
├── pochoir_raster_plugin.py      # Intégration dans les menus et barres d'outils QGIS
├── pochoir_raster_worker.py      # Moteur de traitement asynchrone (QgsTask)
├── pytest.ini                    # Configuration d'exécution pytest
└── README.md                     # Documentation du projet
```

---

## Installation

### Méthode 1 : liaison symbolique directe (recommandée pour le développement)
Pour lier directement le dépôt actif à votre profil utilisateur QGIS sans duplication de fichiers :

```bash
ln -s /media/e357/Windows/Users/aguirre.maurin/Documents/GitHub/rastercutter ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/raster_cutter
```

### Méthode 2 : installation par archive ZIP
Il est également possible de générer une archive d'installation autonome à l'aide du script fourni :

```bash
./package.sh
```

Dans QGIS, ouvrez le menu Extensions, choisissez Installer depuis un fichier ZIP, puis sélectionnez l'archive `raster_cutter.zip` générée.

---

## Exécution des tests

La suite de tests unitaires valide l'interface, les calculs géométriques, les conversions raster et le moteur asynchrone dans un environnement PyQGIS autonome :

```bash
pytest
```

---

## Auteur et licence

L'extension RasterCutter est développée par Aguirre Maurin.

Ce projet est distribué sous licence libre GNU General Public License v3.0 (GPL-3.0-or-later). Consulter le fichier LICENSE pour le texte complet des conditions d'utilisation et de redistribution.
