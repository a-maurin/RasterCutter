# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Pochoir Raster - Moteur de Découpe Asynchrone (QgsTask)
                                 A QGIS plugin
 Découpe universelle de raster par emporte-pièce vectoriel
                              -------------------
        begin                : 2026-09-16
        copyright            : (C) 2026 by Aguirre MAURIN
        email                : aguirre.maurin@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 3 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os
import sys
import tempfile
import shutil
import re
import math
import datetime
from pathlib import Path

# Assurer l'accès à processing
if "/usr/share/qgis/python/plugins" not in sys.path:
    sys.path.append("/usr/share/qgis/python/plugins")

from qgis.PyQt.QtCore import pyqtSignal, Qt
from qgis.core import (
    QgsTask,
    QgsApplication,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsVectorFileWriter,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsCoordinateReferenceSystem,
    QgsRectangle,
    QgsRasterFileWriter,
    QgsRasterPipe,
    QgsProcessingFeedback,
    QgsRasterBlockFeedback,
    QgsInvertedPolygonRenderer,
    QgsSingleSymbolRenderer,
    QgsFillSymbol,
)


def detect_raster_zoom_levels(layer):
    """Analyse dynamiquement une couche raster pour identifier les niveaux de zoom disponibles.

    Gère les flux distants WMTS/WMS/XYZ ainsi que les rasters locaux mono ou multi-résolution.
    :return: dict avec 'is_remote', 'zoom_levels', 'min_zoom', 'max_zoom', 'single_zoom', 'label'
    """
    if not layer:
        return {
            "is_remote": False,
            "zoom_levels": [10],
            "min_zoom": 10,
            "max_zoom": 18,
            "single_zoom": False,
            "label": "",
        }

    provider = layer.providerType().lower()
    is_remote = provider in ["wms", "wmts", "xyz", "wcs", "arcgismapserver", "arcgistileserver"]
    source = layer.source()
    name = layer.name().lower()
    zooms = set()

    # 1. Analyse TileMatrixSet dans la source WMTS (ex: PM_6_19, PM_16_16, PM_16)
    tms_match = re.search(r"tileMatrixSet=[^&]*?(\d+)[_-](\d+)", source)
    if tms_match:
        z1, z2 = int(tms_match.group(1)), int(tms_match.group(2))
        for z in range(min(z1, z2), max(z1, z2) + 1):
            zooms.add(z)
    else:
        tms_single = re.search(r"tileMatrixSet=[^&]*?_(\d+)(?:&|$)", source)
        if tms_single:
            zooms.add(int(tms_single.group(1)))

    # 2. Analyse paramètres zmin et zmax (tuiles XYZ)
    zmin_m = re.search(r"zmin=(\d+)", source)
    zmax_m = re.search(r"zmax=(\d+)", source)
    if zmin_m and zmax_m:
        for z in range(int(zmin_m.group(1)), int(zmax_m.group(1)) + 1):
            zooms.add(z)

    # 3. Analyse nativeResolutions du fournisseur (WMS / WMTS)
    dp = layer.dataProvider()
    if dp and hasattr(dp, "nativeResolutions"):
        try:
            resolutions = dp.nativeResolutions()
            if resolutions:
                for r in resolutions:
                    if r > 0:
                        z = round(math.log2(156543.03392 / r))
                        if 0 <= z <= 24:
                            zooms.add(z)
        except Exception:
            pass

    # 4. Détection spécifique SCAN 25 / SCAN 100 / Ortho / Plan IGN
    source_lower = source.lower()
    if ("scan25" in name or "scan 25" in name or "scan25" in source_lower):
        # La pyramide complète SCAN 25 IGN s'étend du zoom 6 au zoom 16
        if not zooms or len(zooms) <= 1:
            zooms = set(range(6, 17))
    elif ("scan100" in name or "scan 100" in name or "scan100" in source_lower):
        if not zooms:
            zooms = set(range(6, 15))
    elif ("ortho" in name or "orthoimagery" in source_lower):
        if not zooms:
            zooms = set(range(6, 20))
    elif ("planign" in name or "plan ign" in name or "geographicalgridsystems" in source_lower):
        if not zooms:
            zooms = set(range(0, 20))

    # 5. Détection pour rasters locaux (GeoTIFF, etc.)
    if not is_remote:
        try:
            res_x = layer.rasterUnitsPerPixelX()
            if res_x > 0:
                eq_z = max(0, min(22, round(math.log2(156543.03392 / res_x))))
                zooms = set(range(max(0, eq_z - 6), eq_z + 1))
        except Exception:
            pass

    if not zooms:
        zooms = set(range(6, 19))

    sorted_zooms = sorted(list(zooms))
    min_z, max_z = sorted_zooms[0], sorted_zooms[-1]
    single = (len(sorted_zooms) == 1)

    if single:
        lbl = f"1 niveau détecté (Zoom {min_z})"
    else:
        lbl = f"{len(sorted_zooms)} niveaux détectés (Zoom {min_z} à {max_z}) — Tous embarqués par défaut"

    return {
        "is_remote": is_remote,
        "zoom_levels": sorted_zooms,
        "min_zoom": min_z,
        "max_zoom": max_z,
        "single_zoom": single,
        "label": lbl,
    }


def _init_processing():
    """Initialise le registre d'algorithmes Processing si nécessaire."""
    try:
        import processing
        from processing.core.Processing import Processing
        Processing.initialize()
        return processing
    except Exception:
        return None


class TaskProcessingFeedback(QgsProcessingFeedback):
    """Relais d'avancement fluide pour les algorithmes QGIS Processing."""

    def __init__(self, task, start_pct=15.0, end_pct=95.0, step_prefix="Calcul"):
        super().__init__()
        self.task = task
        self.start_pct = start_pct
        self.end_pct = end_pct
        self.step_prefix = step_prefix
        self.current_text = ""
        self.progressChanged.connect(self._on_progress_changed)

    def _on_progress_changed(self, progress):
        mapped = self.start_pct + (progress / 100.0) * (self.end_pct - self.start_pct)
        if self.task:
            txt = self.current_text or f"{self.step_prefix} : {int(progress)}%"
            self.task.update_progress(mapped, txt)

    def setProgress(self, progress):
        super().setProgress(progress)
        self._on_progress_changed(progress)

    def setProgressText(self, text):
        super().setProgressText(text)
        if text:
            self.current_text = text
            if self.task:
                self.task.update_progress(self.task.progress(), f"{self.step_prefix} — {text}")

    def pushInfo(self, info):
        super().pushInfo(info)
        if info:
            self.current_text = info
            if self.task:
                self.task.update_progress(self.task.progress(), f"{self.step_prefix} — {info}")

    def isCanceled(self):
        if self.task and self.task.isCanceled():
            return True
        return super().isCanceled()


class TaskRasterFeedback(QgsRasterBlockFeedback):
    """Relais d'avancement pour le téléchargement direct de flux raster."""

    def __init__(self, task, start_pct=15.0, end_pct=75.0, step_prefix="Téléchargement du flux", show_pct=True):
        super().__init__()
        self.task = task
        self.start_pct = start_pct
        self.end_pct = end_pct
        self.step_prefix = step_prefix
        self.show_pct = show_pct
        self.progressChanged.connect(self._on_progress_changed)

    def _on_progress_changed(self, progress):
        mapped = self.start_pct + (progress / 100.0) * (self.end_pct - self.start_pct)
        if self.task:
            txt = f"{self.step_prefix} : {int(progress)}%" if self.show_pct else self.step_prefix
            self.task.update_progress(mapped, txt)

    def setProgress(self, progress):
        super().setProgress(progress)
        self._on_progress_changed(progress)

    def isCanceled(self):
        if self.task and self.task.isCanceled():
            return True
        return super().isCanceled()


def prepare_mask_dataset(vector_layer, raster_crs, apply_filter=True, selected_only=False, output_dir=None):
    """Extrait le pochoir vectoriel (filtré/sélectionné) et le reprojette dans le SCR du raster.

    :return: (chemin_du_gpkg_masque, emprise_reprojetee, nombre_entites)
    """
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="pochoir_mask_")

    mask_path = os.path.join(output_dir, "pochoir_masque.gpkg")

    # Déterminer la source des entités
    if selected_only and vector_layer.selectedFeatureCount() > 0:
        feature_iter = vector_layer.getSelectedFeatures()
    else:
        # getFeatures() respecte nativement le filtre attributaire (subsetString) de la couche
        feature_iter = vector_layer.getFeatures()

    # Reprojection vers le SCR du raster si différent
    source_crs = vector_layer.crs()
    need_reproject = source_crs.isValid() and raster_crs.isValid() and source_crs != raster_crs
    transform = None
    if need_reproject:
        transform = QgsCoordinateTransform(source_crs, raster_crs, QgsProject.instance())

    # Créer une couche temporaire en mémoire
    crs_auth = raster_crs.authid() if raster_crs.isValid() else source_crs.authid()
    mem_mask = QgsVectorLayer(f"Polygon?crs={crs_auth}", "masque_pochoir", "memory")
    pr = mem_mask.dataProvider()

    features_to_add = []
    total_extent = QgsRectangle()
    total_extent.setNull()

    count = 0
    for feat in feature_iter:
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue

        geom_copy = QgsGeometry(geom)
        if need_reproject and transform is not None:
            geom_copy.transform(transform)

        new_feat = QgsFeature()
        new_feat.setGeometry(geom_copy)
        features_to_add.append(new_feat)

        if total_extent.isNull():
            total_extent = geom_copy.boundingBox()
        else:
            total_extent.combineExtentWith(geom_copy.boundingBox())
        count += 1

    if count == 0:
        raise ValueError("Aucune entité géométrique valide trouvée pour constituer le pochoir.")

    pr.addFeatures(features_to_add)
    mem_mask.updateExtents()

    # Sauvegarder dans un fichier GeoPackage temporaire
    save_opts = QgsVectorFileWriter.SaveVectorOptions()
    save_opts.driverName = "GPKG"
    save_opts.layerName = "pochoir"
    res = QgsVectorFileWriter.writeAsVectorFormatV3(
        mem_mask,
        mask_path,
        QgsCoordinateTransformContext(),
        save_opts,
    )
    if res[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"Échec lors de l'export du masque vectoriel ({res[1]}).")

    return mask_path, total_extent, count


def get_pochoir_geometry(vector_layer, apply_filter=True, selected_only=False):
    """Extrait et fusionne la géométrie du pochoir vectoriel."""
    if not vector_layer or not vector_layer.isValid():
        return None, None

    geoms = []
    if selected_only and vector_layer.selectedFeatureCount() > 0:
        it = vector_layer.getSelectedFeatures()
    else:
        req = QgsFeatureRequest()
        if apply_filter and vector_layer.subsetString():
            req.setFilterExpression(vector_layer.subsetString())
        it = vector_layer.getFeatures(req)

    for f in it:
        if f.hasGeometry() and not f.geometry().isEmpty():
            g = f.geometry()
            if not g.isGeosValid():
                vg = g.makeValid()
                if vg and not vg.isEmpty():
                    geoms.append(vg)
                else:
                    geoms.append(g)
            else:
                geoms.append(g)

    if not geoms:
        return None, vector_layer.crs()

    if len(geoms) == 1:
        merged = geoms[0]
    else:
        try:
            merged = QgsGeometry.unaryUnion(geoms)
        except Exception:
            merged = QgsGeometry.collectGeometry(geoms)

    return merged, vector_layer.crs()


def estimate_grid_tiles_count(vector_layer, tile_size_m=5000, apply_filter=True, selected_only=False):
    """
    Estime rapidement le nombre de dalles de la grille intersectant le pochoir
    en utilisant l'index spatial natif QGIS (aucun unaryUnion lourd sur le thread UI).
    """
    if not vector_layer or not vector_layer.isValid():
        return 0

    layer_crs = vector_layer.crs()
    target_crs = QgsCoordinateReferenceSystem("EPSG:2154")

    # Calcul de l'emprise
    use_selection = selected_only and vector_layer.selectedFeatureCount() > 0
    if use_selection:
        extent = QgsRectangle()
        for f in vector_layer.getSelectedFeatures():
            if f.hasGeometry() and not f.geometry().isEmpty():
                extent.combineExtentWith(f.geometry().boundingBox())
    else:
        extent = vector_layer.extent()

    if extent.isEmpty():
        return 0

    transform_from_2154 = None
    if layer_crs.isValid() and layer_crs != target_crs:
        ctx = QgsCoordinateTransformContext()
        transform_to_2154 = QgsCoordinateTransform(layer_crs, target_crs, ctx)
        transform_from_2154 = QgsCoordinateTransform(target_crs, layer_crs, ctx)
        extent_2154 = transform_to_2154.transformBoundingBox(extent)
    else:
        extent_2154 = extent

    x_min = math.floor(extent_2154.xMinimum() / tile_size_m) * tile_size_m
    y_min = math.floor(extent_2154.yMinimum() / tile_size_m) * tile_size_m
    x_max = math.ceil(extent_2154.xMaximum() / tile_size_m) * tile_size_m
    y_max = math.ceil(extent_2154.yMaximum() / tile_size_m) * tile_size_m

    cols = int(math.ceil((x_max - x_min) / tile_size_m))
    rows = int(math.ceil((y_max - y_min) / tile_size_m))
    total_potential_cells = cols * rows

    # Garde-fou 1 : Si l'emprise englobante dépasse 1 000 dalles (couches nationales/mondiales)
    if total_potential_cells > 1000:
        return -1

    # Garde-fou 2 : Pour les flux distants WFS, plafond strict à 50 dalles pour protéger le réseau
    is_wfs = (vector_layer.providerType().lower() == "wfs")
    if is_wfs and total_potential_cells > 50:
        return -2

    subset = vector_layer.subsetString() if apply_filter else ""
    selected_ids = set(vector_layer.selectedFeatureIds()) if use_selection else None

    count = 0
    x = x_min
    while x < x_max:
        y = y_min
        while y < y_max:
            cell_rect_2154 = QgsRectangle(x, y, x + tile_size_m, y + tile_size_m)
            query_rect = transform_from_2154.transformBoundingBox(cell_rect_2154) if transform_from_2154 else cell_rect_2154

            req = QgsFeatureRequest().setFilterRect(query_rect)
            if subset:
                req.setFilterExpression(subset)

            intersects = False
            for feat in vector_layer.getFeatures(req):
                if selected_ids is not None and feat.id() not in selected_ids:
                    continue
                if feat.hasGeometry() and not feat.geometry().isEmpty():
                    intersects = True
                    break

            if intersects:
                count += 1
            y += tile_size_m
        x += tile_size_m

    return count


_CACHED_DEPARTMENTS = None


def get_departments_data():
    """
    Charge les géométries et codes des départements en Lambert-93 (EPSG:2154).
    Recherche en priorité dans le projet actif (couche 'dep_smbva' ou avec champ INSEE_DEP),
    puis dans les fichiers GPKG disponibles (embarqué ou local).
    """
    global _CACHED_DEPARTMENTS
    if _CACHED_DEPARTMENTS is not None:
        return _CACHED_DEPARTMENTS

    results = []
    target_crs = QgsCoordinateReferenceSystem("EPSG:2154")
    layer = None

    project = QgsProject.instance()
    if project:
        for lyr in project.mapLayers().values():
            if isinstance(lyr, QgsVectorLayer) and lyr.isValid():
                if "dep" in lyr.name().lower() or (lyr.fields() and lyr.fields().indexFromName("INSEE_DEP") != -1):
                    layer = lyr
                    break

    if not layer:
        base_dir = os.path.dirname(__file__)
        candidates = [
            os.path.join(base_dir, "data", "dep_smbva.gpkg"),
            os.path.abspath(os.path.join(base_dir, "..", "..", "..", "dep_smbva.gpkg")),
            os.path.abspath(os.path.join(base_dir, "..", "..", "..", "..", "dep_smbva.gpkg")),
        ]
        for c in candidates:
            if os.path.isfile(c):
                layer = QgsVectorLayer(f"{c}|layername=dep_smbva", "dep_smbva", "ogr")
                if layer.isValid():
                    break

    if layer and layer.isValid():
        src_crs = layer.crs()
        transform = None
        if src_crs.isValid() and src_crs != target_crs:
            transform = QgsCoordinateTransform(src_crs, target_crs, QgsCoordinateTransformContext())

        fields = layer.fields()
        code_field = "INSEE_DEP" if fields.indexFromName("INSEE_DEP") != -1 else None
        if not code_field:
            for f in fields:
                if "dep" in f.name().lower() or "code" in f.name().lower():
                    code_field = f.name()
                    break

        for feat in layer.getFeatures():
            code = str(feat[code_field]).strip() if code_field and feat[code_field] is not None else ""
            if not code:
                continue
            geom = QgsGeometry(feat.geometry())
            if transform and not geom.isEmpty():
                geom.transform(transform)
            if not geom.isGeosValid():
                v = geom.makeValid()
                if v and not v.isEmpty():
                    geom = v
            clean_code = code.lstrip("0") or code
            results.append({
                "code": clean_code,
                "name": str(feat["NOM_DEP"]) if fields.indexFromName("NOM_DEP") != -1 else "",
                "geometry": geom,
            })

    _CACHED_DEPARTMENTS = results
    return _CACHED_DEPARTMENTS


def get_departments_intersecting_geometry(geom_2154):
    """Retourne la liste triée des codes de départements intersectant une géométrie Lambert-93."""
    if not geom_2154 or geom_2154.isEmpty():
        return []
    dept_data = get_departments_data()
    intersected = set()
    for d in dept_data:
        if d["geometry"].intersects(geom_2154):
            intersected.add(d["code"])
    return sorted(list(intersected), key=lambda x: int(x) if x.isdigit() else x)


def query_ign_vintage_and_department(raster_layer, point_2154=None):
    """
    Interroge les attributs d'un flux WMS/WMTS IGN Géoplateforme à une coordonnée donnée.
    Retourne (dep, year) si trouvé, sinon (None, None).
    """
    if not raster_layer or not raster_layer.isValid():
        return None, None

    dp = raster_layer.dataProvider()
    if not dp:
        return None, None

    provider = raster_layer.providerType().lower()
    if provider not in ["wms", "wmts"]:
        return None, None

    target_crs = raster_layer.crs()
    if point_2154:
        crs_2154 = QgsCoordinateReferenceSystem("EPSG:2154")
        if target_crs.isValid() and target_crs != crs_2154:
            transform = QgsCoordinateTransform(crs_2154, target_crs, QgsCoordinateTransformContext())
            pt_query = transform.transform(point_2154)
        else:
            pt_query = point_2154
    else:
        extent = raster_layer.extent()
        pt_query = extent.center()

    try:
        from qgis.core import QgsRaster
        res = dp.identify(pt_query, QgsRaster.IdentifyFormatFeature)
        if res and res.isValid():
            for k, store_list in res.results().items():
                for store in store_list:
                    for feat in store.features():
                        fields = feat.fields()
                        dep = None
                        year = None
                        if fields:
                            if fields.indexFromName("dep") != -1 and feat["dep"]:
                                dep = str(feat["dep"]).strip()
                            if fields.indexFromName("pva") != -1 and feat["pva"]:
                                year = str(feat["pva"]).strip()
                            elif fields.indexFromName("date_vol") != -1 and feat["date_vol"]:
                                m = re.search(r"\b(199\d|20[0-3]\d)\b", str(feat["date_vol"]))
                                if m:
                                    year = m.group(1)
                        if dep or year:
                            clean_dep = dep.lstrip("0") if dep else None
                            return clean_dep, year
    except Exception:
        pass

    return None, None


def generate_grid_tiles(pochoir_geom, tile_size_m=5000, prefix="21-2024", pochoir_crs=None):
    """
    Découpe l'emprise du pochoir en mailles carrées calées sur les coordonnées rondes Lambert-93 (EPSG:2154).
    Retourne la liste des dalles intersectant le pochoir avec leurs coordonnées et nommage officiel IGN.
    Supporte le préfixe dynamique multi-départements si '{DEP}' ou 'Auto-' est présent.
    """
    if not pochoir_geom or pochoir_geom.isEmpty():
        return []

    target_crs = QgsCoordinateReferenceSystem("EPSG:2154")
    if pochoir_crs and pochoir_crs.isValid() and pochoir_crs != target_crs:
        ctx = QgsCoordinateTransformContext()
        transform = QgsCoordinateTransform(pochoir_crs, target_crs, ctx)
        geom_2154 = QgsGeometry(pochoir_geom)
        geom_2154.transform(transform)
    else:
        geom_2154 = pochoir_geom

    if not geom_2154.isGeosValid():
        v = geom_2154.makeValid()
        if v and not v.isEmpty():
            geom_2154 = v

    bbox = geom_2154.boundingBox()
    x_min = math.floor(bbox.xMinimum() / tile_size_m) * tile_size_m
    y_min = math.floor(bbox.yMinimum() / tile_size_m) * tile_size_m
    x_max = math.ceil(bbox.xMaximum() / tile_size_m) * tile_size_m
    y_max = math.ceil(bbox.yMaximum() / tile_size_m) * tile_size_m

    clean_prefix = (prefix or "21-2024").strip()
    has_dynamic_dep = "{dep}" in clean_prefix.lower() or clean_prefix.upper().startswith("AUTO-")
    dept_data = get_departments_data() if has_dynamic_dep else []

    tiles = []
    x = x_min
    while x < x_max:
        y = y_min
        while y < y_max:
            cell_rect = QgsRectangle(x, y, x + tile_size_m, y + tile_size_m)
            cell_geom = QgsGeometry.fromRect(cell_rect)
            if cell_geom.intersects(geom_2154):
                if has_dynamic_dep:
                    tile_dep = "21"
                    pt_center = cell_geom.centroid()
                    found = False
                    for d in dept_data:
                        if d["geometry"].contains(pt_center):
                            tile_dep = d["code"]
                            found = True
                            break
                    if not found:
                        max_area = 0.0
                        for d in dept_data:
                            inter = cell_geom.intersection(d["geometry"])
                            if not inter.isEmpty() and inter.area() > max_area:
                                max_area = inter.area()
                                tile_dep = d["code"]

                    if "{dep}" in clean_prefix.lower():
                        tile_prefix = re.sub(r"\{dep\}", tile_dep, clean_prefix, flags=re.IGNORECASE)
                    else:
                        year_part = clean_prefix[5:] if len(clean_prefix) > 5 else "2024"
                        tile_prefix = f"{tile_dep}-{year_part}"
                else:
                    tile_prefix = clean_prefix

                x_km = int(x // 1000)
                y_top_km = int((y + tile_size_m) // 1000)
                tile_base_name = f"{tile_prefix}-{x_km:04d}-{y_top_km:04d}-LA93"
                tiles.append({
                    "name": f"{tile_base_name}.jp2",
                    "base_name": tile_base_name,
                    "bbox": (x, y, x + tile_size_m, y + tile_size_m),
                    "geometry": cell_geom,
                    "rect": cell_rect,
                    "x_min": x,
                    "y_min": y,
                    "x_max": x + tile_size_m,
                    "y_max": y + tile_size_m,
                    "total_size_bytes": 0,
                    "extension": ".jp2",
                    "rel_path": f"{tile_base_name}.jp2",
                })
            y += tile_size_m
        x += tile_size_m

    return tiles


def extract_grid_tile_jp2(
    raster_layer,
    tile_dict,
    dst_jp2,
    target_zoom=None,
    task=None,
    start_pct=15.0,
    end_pct=75.0,
    step_label="Traitement en cours...",
):
    """
    Extrait une dalle carrée sur l'emprise exacte tile_dict['bbox'] (en EPSG:2154),
    puis la convertit en JPEG 2000 avec ses calages AutoCAD (.tab et .j2w).
    """
    if task and task.isCanceled():
        return None

    xmin, ymin, xmax, ymax = tile_dict["bbox"]
    extent_2154 = QgsRectangle(xmin, ymin, xmax, ymax)
    provider_type = raster_layer.providerType().lower()
    is_remote = provider_type in ["wms", "wmts", "xyz", "wcs", "arcgismapserver", "arcgistileserver"]

    tmp_dir = tempfile.mkdtemp(prefix="tile_extract_")
    tmp_tif = os.path.join(tmp_dir, "tile_raw.tif")

    try:
        if is_remote:
            pipe = QgsRasterPipe()
            pipe.set(raster_layer.dataProvider().clone())

            raster_crs = raster_layer.crs()
            extent_req = extent_2154
            if raster_crs.isValid() and raster_crs != QgsCoordinateReferenceSystem("EPSG:2154"):
                tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:2154"), raster_crs, QgsCoordinateTransformContext())
                extent_req = tr.transformBoundingBox(extent_2154)

            # Calcul des dimensions selon le niveau de zoom
            if target_zoom is not None and target_zoom > 0:
                res = 156543.03392 / (2 ** target_zoom)
                width = max(10, min(16384, int(extent_req.width() / res)))
                height = max(10, min(16384, int(extent_req.height() / res)))
            else:
                tile_span = xmax - xmin
                width = max(500, min(10000, int(tile_span)))
                height = width

            feedback = (
                TaskRasterFeedback(task, start_pct=start_pct, end_pct=end_pct, step_prefix=step_label, show_pct=False)
                if task
                else None
            )
            writer = QgsRasterFileWriter(tmp_tif)
            writer.writeRaster(
                pipe,
                width,
                height,
                extent_req,
                raster_crs,
                QgsCoordinateTransformContext(),
                feedback,
            )
        else:
            from osgeo import gdal
            gdal.UseExceptions()
            warp_opts = gdal.WarpOptions(
                dstSRS="EPSG:2154",
                outputBounds=[xmin, ymin, xmax, ymax],
                resampleAlg=gdal.GRA_Bilinear,
            )
            warp_ds = gdal.Warp(tmp_tif, raster_layer.source(), options=warp_opts)
            warp_ds = None

        if task and task.isCanceled():
            return None

        if not os.path.exists(tmp_tif) or os.path.getsize(tmp_tif) == 0:
            if task and task.isCanceled():
                return None
            raise RuntimeError(f"Échec de l'extraction de la dalle {tile_dict['name']}")

        convert_geotiff_to_jp2(tmp_tif, dst_jp2, target_epsg=2154, target_bounds=tile_dict.get("bbox"))
        return dst_jp2

    finally:
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)


def clip_local_raster_geotiff(raster_source, mask_path, output_path, white_background=False, nodata_val=None, autocad_tfw=True, feedback=None):
    """Découpe directe d'un raster local par le masque vectoriel via GDAL."""
    processing = _init_processing()
    if not processing:
        raise RuntimeError("Le module QGIS Processing est introuvable.")

    params = {
        "INPUT": raster_source,
        "MASK": mask_path,
        "ALPHA_BAND": not white_background,
        "CROP_TO_CUTLINE": True,
        "KEEP_RESOLUTION": True,
        "OUTPUT": output_path,
    }
    if autocad_tfw:
        params["EXTRA"] = "-co TFW=YES"

    if white_background:
        # Pour fond blanc sans bande alpha, on ne force pas le NoData
        pass
    elif nodata_val is not None:
        params["NODATA"] = nodata_val

    result = processing.run("gdal:cliprasterbymasklayer", params, feedback=feedback)
    return result.get("OUTPUT", output_path)


def generate_tab_file(jp2_path: str, bbox: tuple, width: int, height: int):
    """Génère un fichier de calage MapInfo .tab pour AutoCAD Map 3D / Covadis / MapInfo."""
    xmin, ymin, xmax, ymax = bbox
    jp2_name = os.path.basename(jp2_path)
    tab_path = os.path.splitext(jp2_path)[0] + ".tab"
    content = f"""!table
!version 300
!charset WindowsLatin1

Definition Table
File "{jp2_name}"
Type "RASTER"
({xmin:.2f},{ymax:.2f}) (0,0) Label "Pt 1",
({xmax:.2f},{ymax:.2f}) ({width},0) Label "Pt 2",
({xmax:.2f},{ymin:.2f}) ({width},{height}) Label "Pt 3",
({xmin:.2f},{ymin:.2f}) (0,{height}) Label "Pt 4"
CoordSys Earth Projection 2003, 33, 7, 3, 46.5, 44, 49.00000000001, 700000, 6600000, -792421, 5278231, 3520778, 9741029
Units "m"
"""
    with open(tab_path, "w", encoding="latin1") as f:
        f.write(content)


def generate_j2w_file(jp2_path: str, bbox: tuple, width: int, height: int):
    """Génère un World file .j2w pour AutoCAD classique / CAO."""
    xmin, ymin, xmax, ymax = bbox
    res_x = (xmax - xmin) / max(width, 1)
    res_y = -(ymax - ymin) / max(height, 1)
    x_center = xmin + abs(res_x) / 2.0
    y_center = ymax - abs(res_y) / 2.0
    j2w_path = os.path.splitext(jp2_path)[0] + ".j2w"
    lines = [
        f"{abs(res_x):.6f}\n",
        "0.000000\n",
        "0.000000\n",
        f"{-abs(res_y):.6f}\n",
        f"{x_center:.6f}\n",
        f"{y_center:.6f}\n",
    ]
    with open(j2w_path, "w", encoding="ascii") as f:
        f.writelines(lines)


def convert_geotiff_to_jp2(src_tif: str, dst_jp2: str, target_epsg: int = 2154, target_bounds: tuple = None):
    """Convertit un GeoTIFF en JPEG 2000 (.jp2) avec pilote JP2OpenJPEG et calages associés."""
    from osgeo import gdal
    gdal.UseExceptions()

    ds_src = gdal.Open(src_tif, gdal.GA_ReadOnly)
    if not ds_src:
        raise RuntimeError(f"Impossible d'ouvrir le raster source : {src_tif}")

    src_srs = ds_src.GetSpatialRef()
    needs_reproject = False
    if src_srs:
        epsg_code = src_srs.GetAuthorityCode(None)
        if epsg_code and str(epsg_code) != str(target_epsg):
            needs_reproject = True
    ds_src = None

    tmp_reprojected = None
    trans_src = src_tif
    if needs_reproject or target_bounds:
        tmp_reprojected = src_tif.replace(".tif", "_reproj.tif")
        warp_opts = gdal.WarpOptions(
            dstSRS=f"EPSG:{target_epsg}",
            outputBounds=list(target_bounds) if target_bounds else None,
            resampleAlg=gdal.GRA_Bilinear,
        )
        warp_ds = gdal.Warp(tmp_reprojected, src_tif, options=warp_opts)
        warp_ds = None
        trans_src = tmp_reprojected

    translate_options = gdal.TranslateOptions(
        format="JP2OpenJPEG",
        creationOptions=["QUALITY=20", "REVERSIBLE=NO"],
    )
    tr_ds = gdal.Translate(dst_jp2, trans_src, options=translate_options)
    if tr_ds:
        width = tr_ds.RasterXSize
        height = tr_ds.RasterYSize
        gt = tr_ds.GetGeoTransform()
        xmin = gt[0]
        ymax = gt[3]
        xmax = xmin + gt[1] * width
        ymin = ymax + gt[5] * height
        if ymin > ymax:
            ymin, ymax = ymax, ymin
        bbox = (xmin, ymin, xmax, ymax)
        tr_ds = None

        generate_tab_file(dst_jp2, bbox, width, height)
        generate_j2w_file(dst_jp2, bbox, width, height)

    if tmp_reprojected and os.path.exists(tmp_reprojected):
        try:
            os.remove(tmp_reprojected)
        except Exception:
            pass

    return dst_jp2


def clip_remote_raster_geotiff(raster_layer, mask_path, extent, output_path, white_background=False, target_zoom=None, task=None):
    """Découpe d'un flux raster distant (WMS/WMTS/XYZ) en GeoTIFF avec retour de progression."""
    processing = _init_processing()
    if not processing:
        raise RuntimeError("Le module QGIS Processing est introuvable.")

    tmp_dir = tempfile.mkdtemp(prefix="pochoir_wms_")
    tmp_raw_tif = os.path.join(tmp_dir, "raw_extract.tif")

    try:
        # 1. Extraction du flux sur l'emprise du masque via QgsRasterFileWriter
        if task:
            task.update_progress(18, "Connexion et téléchargement du flux raster...")
        pipe = QgsRasterPipe()
        pipe.set(raster_layer.dataProvider().clone())

        # Calcul précis des dimensions selon le niveau de zoom cible
        if target_zoom is not None and target_zoom > 0:
            res = 156543.03392 / (2 ** target_zoom)
            width = max(1, min(16384, int(extent.width() / res)))
            height = max(1, min(16384, int(extent.height() / res)))
        else:
            width = 2048
            aspect = extent.width() / max(extent.height(), 1e-6)
            height = max(int(width / max(aspect, 1e-6)), 1)
            if height > 4096:
                height = 4096
                width = max(int(height * aspect), 1)

        raster_fb = TaskRasterFeedback(task, start_pct=20.0, end_pct=75.0, step_prefix="Téléchargement du flux") if task else None

        writer = QgsRasterFileWriter(tmp_raw_tif)
        writer.writeRaster(
            pipe,
            width,
            height,
            extent,
            raster_layer.crs(),
            QgsCoordinateTransformContext(),
            raster_fb,
        )

        if task and task.isCanceled():
            return None

        # 2. Découpe au pochoir avec GDAL
        if task:
            task.update_progress(75, "Découpe par masque vectoriel (GDAL)...")
        gdal_fb = TaskProcessingFeedback(task, start_pct=75.0, end_pct=95.0, step_prefix="Découpe GDAL") if task else None

        clipped = clip_local_raster_geotiff(
            raster_source=tmp_raw_tif,
            mask_path=mask_path,
            output_path=output_path,
            white_background=white_background,
            feedback=gdal_fb,
        )
        return clipped
    finally:
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)


def generate_mbtiles_clip(raster_layer, mask_path, extent, zoom_min, zoom_max, output_path, white_background=False, feedback=None):
    """Génération de tuiles multi-zoom MBTiles découpées au pochoir avec retour d'avancement."""
    processing = _init_processing()
    if not processing:
        raise RuntimeError("Le module QGIS Processing est introuvable.")

    # Format de tuile : 1 pour JPG (fond blanc), 0 pour PNG (transparence)
    tile_format = 1 if white_background else 0

    params = {
        "EXTENT": extent,
        "ZOOM_MIN": zoom_min,
        "ZOOM_MAX": zoom_max,
        "DPI": 96,
        "TILE_FORMAT": tile_format,
        "QUALITY": 75,
        "OUTPUT_FILE": output_path,
    }

    result = processing.run("native:tilesxyzmbtiles", params, feedback=feedback)
    return result.get("OUTPUT_FILE", output_path)


class PochoirRasterTask(QgsTask):
    """Tâche d'arrière-plan QgsTask pour un traitement non-bloquant avec barre de progression continue."""
    step_progress = pyqtSignal(float, str)

    def __init__(self, config, iface=None, on_progress=None, on_finished=None):
        super().__init__("Découpage RasterCutter", QgsTask.CanCancel)
        self.config = config
        self.iface = iface
        self.on_progress = on_progress
        self.on_finished = on_finished
        self.current_message = "Initialisation..."

        self.raster_layer = config["raster_layer"]
        self.pochoir_layer = config["pochoir_layer"]
        self.is_mbtiles = config.get("is_mbtiles", False)
        self.is_jp2 = config.get("is_jp2", False)
        self.is_temp = config.get("is_temp", True)
        self.output_path = config.get("output_path", "")
        self.apply_filter = config.get("apply_filter", True)
        self.selected_only = config.get("selected_only", False)
        self.white_background = config.get("white_background", False)
        self.zoom_min = config.get("zoom_min", 10)
        self.zoom_max = config.get("zoom_max", 18)
        self.autocad_tfw = config.get("autocad_tfw", True)
        self.tile_size = config.get("tile_size", 5000)
        self.tile_prefix = config.get("tile_prefix", "21-2024")
        self.skip_existing = config.get("skip_existing", True)
        self.tiles_count = 0

        self.raster_name = self.raster_layer.name()
        self.raster_source = self.raster_layer.source()
        self.raster_crs = self.raster_layer.crs()
        self.provider_type = self.raster_layer.providerType().lower()
        self.is_remote = self.provider_type in ["wms", "wmts", "xyz", "wcs", "arcgismapserver"]

        self.temp_dir = None
        self.final_output_file = None
        self.error_message = None
        self.success = False

    def update_progress(self, pct, message=None):
        """Met à jour la progression et diffuse le pourcentage et le statut textuel."""
        if message:
            self.current_message = message
        self.setProgress(pct)
        try:
            self.step_progress.emit(pct, self.current_message)
        except Exception:
            pass

    def run(self):
        """Exécution sur le thread de travail en arrière-plan."""
        try:
            self.update_progress(5, "Initialisation...")
            self.temp_dir = tempfile.mkdtemp(prefix="pochoir_run_")

            # 1. Déterminer le fichier ou dossier de sortie final
            if self.is_jp2:
                if self.is_temp or not self.output_path:
                    self.final_output_file = os.path.join(self.temp_dir, f"{self.raster_name}_dalles_jp2")
                else:
                    self.final_output_file = self.output_path
                os.makedirs(self.final_output_file, exist_ok=True)
            else:
                if self.is_temp or not self.output_path:
                    ext = ".mbtiles" if self.is_mbtiles else ".tif"
                    self.final_output_file = os.path.join(self.temp_dir, f"{self.raster_name}_decoupe{ext}")
                else:
                    self.final_output_file = self.output_path

            if self.isCanceled():
                return False

            # 2. Préparation du pochoir vectoriel
            self.update_progress(10, "Préparation du masque vectoriel...")
            mask_gpkg, extent, feat_count = prepare_mask_dataset(
                vector_layer=self.pochoir_layer,
                raster_crs=self.raster_crs,
                apply_filter=self.apply_filter,
                selected_only=self.selected_only,
                output_dir=self.temp_dir,
            )

            if self.isCanceled():
                return False

            self.update_progress(15, "Calcul en cours...")

            # 3. Exécution selon le format cible
            if self.is_mbtiles:
                fb = TaskProcessingFeedback(
                    self,
                    start_pct=15.0,
                    end_pct=95.0,
                    step_prefix="Génération des tuiles MBTiles",
                )
                generate_mbtiles_clip(
                    raster_layer=self.raster_layer,
                    mask_path=mask_gpkg,
                    extent=extent,
                    zoom_min=self.zoom_min,
                    zoom_max=self.zoom_max,
                    output_path=self.final_output_file,
                    white_background=self.white_background,
                    feedback=fb,
                )
            elif self.is_jp2:
                self.update_progress(10, "Calcul du carroyage...")
                pochoir_geom, pochoir_crs = get_pochoir_geometry(
                    self.pochoir_layer,
                    apply_filter=self.apply_filter,
                    selected_only=self.selected_only,
                )
                if not pochoir_geom:
                    raise RuntimeError("Aucune géométrie valide trouvée dans la couche pochoir.")

                tiles = generate_grid_tiles(
                    pochoir_geom=pochoir_geom,
                    tile_size_m=self.tile_size,
                    prefix=self.tile_prefix,
                    pochoir_crs=pochoir_crs,
                )
                if not tiles:
                    raise RuntimeError("Aucune dalle de la grille n'intersecte le pochoir sélectionné.")

                dest_dir = self.final_output_file
                total_tiles = len(tiles)
                processed_tiles = []

                for idx, t in enumerate(tiles):
                    if self.isCanceled():
                        return False

                    dst_jp2 = os.path.join(dest_dir, t["name"])
                    tab_file = os.path.splitext(dst_jp2)[0] + ".tab"
                    j2w_file = os.path.splitext(dst_jp2)[0] + ".j2w"

                    tile_start = 5.0 + (idx / total_tiles) * 85.0
                    tile_end = 5.0 + ((idx + 1) / total_tiles) * 85.0
                    step_msg = f"Traitement des dalles : {idx + 1} / {total_tiles}"

                    self.update_progress(tile_start, step_msg)

                    if self.skip_existing and os.path.exists(dst_jp2) and os.path.getsize(dst_jp2) > 0 and os.path.exists(tab_file) and os.path.exists(j2w_file):
                        t["total_size_bytes"] = os.path.getsize(dst_jp2)
                        processed_tiles.append(t)
                        self.update_progress(tile_end, step_msg)
                        continue

                    extract_grid_tile_jp2(
                        raster_layer=self.raster_layer,
                        tile_dict=t,
                        dst_jp2=dst_jp2,
                        target_zoom=self.zoom_max,
                        task=self,
                        start_pct=tile_start,
                        end_pct=tile_end,
                        step_label=step_msg,
                    )

                    if self.isCanceled():
                        return False

                    if os.path.exists(dst_jp2):
                        t["total_size_bytes"] = os.path.getsize(dst_jp2)
                        processed_tiles.append(t)

                    self.update_progress(tile_end, step_msg)

                if self.isCanceled():
                    return False

                self.update_progress(92, "Génération du tableau d'assemblage (DXF & SHP)...")
                from .dalles_filter import export_tableau_assemblage_dxf, export_tableau_assemblage_shp
                export_tableau_assemblage_dxf(processed_tiles, Path(dest_dir) / "tableau_assemblage.dxf")
                export_tableau_assemblage_shp(processed_tiles, Path(dest_dir) / "tableau_assemblage.shp", epsg=2154)

                bilan_path = os.path.join(dest_dir, "bilan_carrelage.txt")
                total_mb = sum(t["total_size_bytes"] for t in processed_tiles) / (1024 * 1024)
                with open(bilan_path, "w", encoding="utf-8") as f:
                    f.write(f"Bilan du carrelage JPEG 2000 AutoCAD\n")
                    f.write(f"Date : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"Source raster : {self.raster_name}\n")
                    f.write(f"Taille des dalles : {self.tile_size} m\n")
                    f.write(f"Dalles générées : {len(processed_tiles)}\n")
                    f.write(f"Volume total : {total_mb:.2f} Mo\n\n")
                    for t in processed_tiles:
                        f.write(f"- {t['name']} ({t['total_size_bytes'] / (1024*1024):.2f} Mo) - BBox: {t['bbox']}\n")

                self.tiles_count = len(processed_tiles)
                self.success = len(processed_tiles) > 0
            else:
                if not self.is_remote and os.path.exists(self.raster_source):
                    fb = TaskProcessingFeedback(
                        self,
                        start_pct=15.0,
                        end_pct=95.0,
                        step_prefix="Découpe GDAL du raster",
                    )
                    clip_local_raster_geotiff(
                        raster_source=self.raster_source,
                        mask_path=mask_gpkg,
                        output_path=self.final_output_file,
                        white_background=self.white_background,
                        autocad_tfw=self.autocad_tfw,
                        feedback=fb,
                    )
                else:
                    clip_remote_raster_geotiff(
                        raster_layer=self.raster_layer,
                        mask_path=mask_gpkg,
                        extent=extent,
                        output_path=self.final_output_file,
                        white_background=self.white_background,
                        target_zoom=self.zoom_max,
                        task=self,
                    )

            if self.isCanceled():
                return False

            self.update_progress(96, "Vérification du résultat...")
            if not self.is_jp2:
                self.success = os.path.exists(self.final_output_file) and os.path.getsize(self.final_output_file) > 0
                if not self.success:
                    raise RuntimeError("Le fichier découpé n'a pas pu être généré ou est vide.")

            self.update_progress(100, "Découpage terminé.")
            return True

        except Exception as exc:
            self.error_message = str(exc)
            return False

    def finished(self, result):
        """Exécuté sur le thread principal (UI) à la fin de la tâche."""
        result_layer = None
        if result and self.success and self.final_output_file and os.path.exists(self.final_output_file):
            layer_name = f"{self.raster_name}_decoupe"
            if self.is_jp2:
                shp_path = os.path.join(self.final_output_file, "tableau_assemblage.shp")
                if os.path.exists(shp_path):
                    result_layer = QgsVectorLayer(shp_path, f"Tableau d'assemblage ({self.raster_name})", "ogr")
                    if result_layer and result_layer.isValid():
                        QgsProject.instance().addMapLayer(result_layer)
                        if self.iface:
                            self.iface.setActiveLayer(result_layer)
                count_str = f"{self.tiles_count} dalles générées" if getattr(self, "tiles_count", 0) else "Dalles générées"
                msg = f"Dallage terminé : {count_str}.\nTableau d'assemblage ajouté au projet."
            elif self.final_output_file.lower().endswith(".mbtiles"):
                result_layer = QgsRasterLayer(f"type=mbtiles&url={self.final_output_file}", layer_name, "wms")
                if result_layer and result_layer.isValid():
                    QgsProject.instance().addMapLayer(result_layer)
                    if self.iface:
                        self.iface.setActiveLayer(result_layer)
                msg = f"Découpage terminé. Couche '{layer_name}' ajoutée au projet."
            else:
                result_layer = QgsRasterLayer(self.final_output_file, layer_name, "gdal")
                if result_layer and result_layer.isValid():
                    QgsProject.instance().addMapLayer(result_layer)
                    if self.iface:
                        self.iface.setActiveLayer(result_layer)
                msg = f"Découpage terminé. Couche '{layer_name}' ajoutée au projet."

            if self.on_finished:
                self.on_finished(True, msg, result_layer)
        else:
            msg = "Opération annulée par l'utilisateur." if self.isCanceled() else (self.error_message or "Erreur inconnue.")
            if self.on_finished:
                self.on_finished(False, msg, None)


class LayerTaskAdapter:
    """Adaptateur relayant la progression d'une couche individuelle vers la tâche multi-couches globale."""

    def __init__(self, parent_task, idx: int, total: int, layer_name: str):
        self.parent_task = parent_task
        self.idx = idx
        self.total = max(total, 1)
        self.layer_name = layer_name

    def update_progress(self, pct: float, message: str = None):
        base_pct = (self.idx / self.total) * 100.0
        layer_scale = 100.0 / self.total
        mapped = min(100.0, base_pct + (float(pct) / 100.0) * layer_scale)
        prefix = f"[{self.idx + 1}/{self.total}] {self.layer_name}"
        msg = f"{prefix} — {message}" if message else prefix
        self.parent_task.update_progress(mapped, msg)

    def isCanceled(self) -> bool:
        return self.parent_task.isCanceled()

    def progress(self) -> float:
        return self.parent_task.progress()


class PochoirMultiRasterTask(QgsTask):
    """Tâche d'arrière-plan QgsTask pour le traitement par lot séquentiel de plusieurs couches rasters."""
    step_progress = pyqtSignal(float, str)

    def __init__(self, config, iface=None, on_progress=None, on_finished=None):
        super().__init__("Découpage multi-couches RasterCutter", QgsTask.CanCancel)
        self.config = config
        self.iface = iface
        self.on_progress = on_progress
        self.on_finished = on_finished
        self.current_message = "Initialisation du traitement par lot..."

        self.raster_layers = config.get("raster_layers", [])
        self.pochoir_layer = config["pochoir_layer"]
        self.dest_root = config.get("output_path", "")
        self.is_mbtiles = config.get("is_mbtiles", False)
        self.is_jp2 = config.get("is_jp2", False)
        self.apply_filter = config.get("apply_filter", True)
        self.selected_only = config.get("selected_only", False)
        self.white_background = config.get("white_background", False)
        self.autocad_tfw = config.get("autocad_tfw", True)
        self.zoom_min = config.get("zoom_min", 10)
        self.zoom_max = config.get("zoom_max", 18)
        self.tile_size = config.get("tile_size", 5000)
        self.tile_prefix = config.get("tile_prefix", "21-2024")
        self.skip_existing = config.get("skip_existing", True)

        self.temp_dir = None
        self.error_message = None
        self.success = False
        self.produced_outputs = []

    def update_progress(self, pct: float, message: str = None):
        """Met à jour le pourcentage d'avancement et diffuse l'état textuel."""
        if message:
            self.current_message = message
        self.setProgress(pct)
        try:
            self.step_progress.emit(pct, self.current_message)
        except Exception:
            pass

    def run(self):
        """Exécution sur le thread de travail en arrière-plan."""
        try:
            total_layers = len(self.raster_layers)
            if total_layers == 0:
                raise RuntimeError("Aucune couche raster sélectionnée pour le découpage.")

            self.update_progress(2, "Création du dossier de destination...")
            os.makedirs(self.dest_root, exist_ok=True)
            self.temp_dir = tempfile.mkdtemp(prefix="pochoir_multi_")

            for idx, rlayer in enumerate(self.raster_layers):
                if self.isCanceled():
                    return False

                layer_name = rlayer.name()
                clean_name = re.sub(r'[\\/*?:"<>|]', "_", layer_name).strip() or f"couche_{idx+1}"
                clean_name = re.sub(r"\s+", "_", clean_name)

                # Création du sous-dossier dédié par couche
                subfolder = os.path.join(self.dest_root, clean_name)
                os.makedirs(subfolder, exist_ok=True)

                adapter = LayerTaskAdapter(self, idx, total_layers, layer_name)
                adapter.update_progress(5, "Analyse et préparation du pochoir...")

                # Détection automatique de la meilleure résolution pour les flux distants
                z_info = detect_raster_zoom_levels(rlayer)
                layer_zoom_max = z_info.get("max_zoom", self.zoom_max)
                layer_zoom_min = z_info.get("min_zoom", self.zoom_min)

                # Préparation du pochoir vectoriel reprojeté dans le SCR du raster
                mask_gpkg, extent, _ = prepare_mask_dataset(
                    vector_layer=self.pochoir_layer,
                    raster_crs=rlayer.crs(),
                    apply_filter=self.apply_filter,
                    selected_only=self.selected_only,
                    output_dir=self.temp_dir,
                )

                if self.isCanceled():
                    return False

                provider_type = rlayer.providerType().lower()
                is_remote = provider_type in ["wms", "wmts", "xyz", "wcs", "arcgismapserver", "arcgistileserver"]

                if self.is_mbtiles:
                    out_file = os.path.join(subfolder, f"{clean_name}.mbtiles")
                    fb = TaskProcessingFeedback(
                        adapter,
                        start_pct=15.0,
                        end_pct=95.0,
                        step_prefix="Génération MBTiles",
                    )
                    generate_mbtiles_clip(
                        raster_layer=rlayer,
                        mask_path=mask_gpkg,
                        extent=extent,
                        zoom_min=layer_zoom_min,
                        zoom_max=layer_zoom_max,
                        output_path=out_file,
                        white_background=self.white_background,
                        feedback=fb,
                    )
                    self.produced_outputs.append({
                        "name": layer_name,
                        "path": out_file,
                        "type": "mbtiles",
                    })

                elif self.is_jp2:
                    adapter.update_progress(10, "Calcul du carroyage...")
                    pochoir_geom, pochoir_crs = get_pochoir_geometry(
                        self.pochoir_layer,
                        apply_filter=self.apply_filter,
                        selected_only=self.selected_only,
                    )
                    tiles = generate_grid_tiles(
                        pochoir_geom=pochoir_geom,
                        tile_size_m=self.tile_size,
                        prefix=self.tile_prefix,
                        pochoir_crs=pochoir_crs,
                    )
                    t_count = len(tiles)
                    processed_tiles = []
                    for t_idx, t in enumerate(tiles):
                        if self.isCanceled():
                            return False

                        dst_jp2 = os.path.join(subfolder, t["name"])
                        t_start = 10.0 + (t_idx / max(t_count, 1)) * 80.0
                        adapter.update_progress(t_start, f"Dalle {t_idx+1}/{t_count}")

                        extract_grid_tile_jp2(
                            raster_layer=rlayer,
                            tile_dict=t,
                            dst_jp2=dst_jp2,
                            target_zoom=layer_zoom_max,
                            task=adapter,
                        )
                        processed_tiles.append(t)

                    if processed_tiles:
                        try:
                            from .dalles_filter import export_tableau_assemblage_dxf, export_tableau_assemblage_shp
                        except ImportError:
                            from dalles_filter import export_tableau_assemblage_dxf, export_tableau_assemblage_shp
                        export_tableau_assemblage_dxf(processed_tiles, Path(subfolder) / "tableau_assemblage.dxf")
                        export_tableau_assemblage_shp(processed_tiles, Path(subfolder) / "tableau_assemblage.shp", epsg=2154)

                    self.produced_outputs.append({
                        "name": layer_name,
                        "path": subfolder,
                        "type": "jp2",
                    })

                else:
                    out_file = os.path.join(subfolder, f"{clean_name}.tif")
                    if not is_remote and os.path.exists(rlayer.source()):
                        fb = TaskProcessingFeedback(
                            adapter,
                            start_pct=15.0,
                            end_pct=95.0,
                            step_prefix="Découpe GDAL",
                        )
                        clip_local_raster_geotiff(
                            raster_source=rlayer,
                            mask_path=mask_gpkg,
                            output_path=out_file,
                            white_background=self.white_background,
                            autocad_tfw=self.autocad_tfw,
                            feedback=fb,
                        )
                    else:
                        clip_remote_raster_geotiff(
                            raster_layer=rlayer,
                            mask_path=mask_gpkg,
                            extent=extent,
                            output_path=out_file,
                            white_background=self.white_background,
                            target_zoom=layer_zoom_max,
                            task=adapter,
                        )
                    self.produced_outputs.append({
                        "name": layer_name,
                        "path": out_file,
                        "type": "geotiff",
                    })

                adapter.update_progress(100, "Couche découpée avec succès.")

            self.update_progress(100, f"Découpage terminé pour les {total_layers} couches.")
            self.success = True
            return True

        except Exception as exc:
            self.error_message = str(exc)
            return False
        finally:
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)

    def finished(self, result):
        """Exécuté sur le thread principal (UI) à la fin de la tâche pour charger le groupe QGIS."""
        if result and self.success and not self.isCanceled():
            pochoir_name = self.pochoir_layer.name() if hasattr(self.pochoir_layer, "name") else "Pochoir"
            group_name = f"Découpe - {pochoir_name}"
            project = QgsProject.instance()
            root = project.layerTreeRoot()
            group = root.addGroup(group_name)

            for item in self.produced_outputs:
                if item["type"] == "geotiff" and os.path.exists(item["path"]):
                    layer = QgsRasterLayer(item["path"], f"{item['name']}_decoupe", "gdal")
                    if layer and layer.isValid():
                        project.addMapLayer(layer, False)
                        group.addLayer(layer)
                elif item["type"] == "mbtiles" and os.path.exists(item["path"]):
                    layer = QgsRasterLayer(f"type=mbtiles&url={item['path']}", f"{item['name']}_decoupe", "wms")
                    if layer and layer.isValid():
                        project.addMapLayer(layer, False)
                        group.addLayer(layer)
                elif item["type"] == "jp2":
                    shp_path = os.path.join(item["path"], "tableau_assemblage.shp")
                    if os.path.exists(shp_path):
                        layer = QgsVectorLayer(shp_path, f"Tableau d'assemblage ({item['name']})", "ogr")
                        if layer and layer.isValid():
                            project.addMapLayer(layer, False)
                            group.addLayer(layer)

            msg = f"Découpe terminée avec succès pour {len(self.produced_outputs)} couche(s).\nRésultats rangés dans le groupe '{group_name}'."
            if self.on_finished:
                self.on_finished(True, msg, None)
        else:
            msg = "Opération annulée par l'utilisateur." if self.isCanceled() else (self.error_message or "Erreur inconnue.")
            if self.on_finished:
                self.on_finished(False, msg, None)


def launch_clipping_task(config, iface=None, on_progress=None, on_finished=None):
    """Instancie et enregistre la tâche dans le gestionnaire QGIS."""
    if config.get("is_multi_layers"):
        task = PochoirMultiRasterTask(config, iface=iface, on_progress=on_progress, on_finished=on_finished)
    else:
        task = PochoirRasterTask(config, iface=iface, on_progress=on_progress, on_finished=on_finished)

    if on_progress:
        task.step_progress.connect(on_progress, Qt.QueuedConnection)

    # Ajout au TaskManager de QGIS
    QgsApplication.taskManager().addTask(task)
    return task


PochoirRasterWorker = PochoirRasterTask

