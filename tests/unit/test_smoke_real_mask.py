# -*- coding: utf-8 -*-
"""
Test de validation Smoke sur les données réelles du projet (pochoir_bva_fix.gpkg).
"""

import os
import tempfile
import pytest
from pathlib import Path
from osgeo import gdal, osr

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsCoordinateReferenceSystem,
)
from pochoir_raster.pochoir_raster_worker import (
    prepare_mask_dataset,
    clip_local_raster_geotiff,
)


def test_smoke_with_real_pochoir(qgis_app):
    """Vérifie le découpage avec le vrai fichier pochoir_bva_fix.gpkg du projet."""
    workspace_dir = Path(__file__).resolve().parent.parent.parent
    candidates = [
        workspace_dir / "donnees" / "vecteurs" / "pochoir_bva_fix.gpkg",
        workspace_dir.parent.parent / "pariries_permanentes" / "projet_sig" / "pochoir_bva_fix.gpkg",
        workspace_dir.parent / "pochoir_bva_fix.gpkg",
    ]
    pochoir_path = next((p for p in candidates if p.exists()), None)
    if not pochoir_path:
        pytest.skip("pochoir_bva_fix.gpkg non trouvé dans l'environnement")

    vec_layer = QgsVectorLayer(str(pochoir_path), "pochoir_reel", "ogr")
    assert vec_layer.isValid()
    assert vec_layer.featureCount() >= 1

    # Préparation du masque réel
    tmp_dir = tempfile.mkdtemp(prefix="pochoir_smoke_")
    mask_path, extent, count = prepare_mask_dataset(vec_layer, vec_layer.crs(), output_dir=tmp_dir)
    assert os.path.exists(mask_path)
    assert count >= 1

    # Création d'un petit raster recouvrant le coin min du masque pour tester le clip
    raster_path = os.path.join(tmp_dir, "raster_test_reel.tif")
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(raster_path, 40, 40, 3, gdal.GDT_Byte)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3857)
    ds.SetProjection(srs.ExportToWkt())
    # Placer l'emprise raster centrée sur l'emprise du pochoir
    center_x = (extent.xMinimum() + extent.xMaximum()) / 2.0
    center_y = (extent.yMinimum() + extent.yMaximum()) / 2.0
    ds.SetGeoTransform([center_x - 200, 10, 0, center_y + 200, 0, -10])
    for b in range(1, 4):
        ds.GetRasterBand(b).Fill(120)
    ds = None

    # Découpage avec le vrai masque
    out_tif = os.path.join(tmp_dir, "reel_clipped.tif")
    res = clip_local_raster_geotiff(raster_path, mask_path, out_tif, white_background=False)
    assert os.path.exists(res)
    assert os.path.getsize(res) > 0
