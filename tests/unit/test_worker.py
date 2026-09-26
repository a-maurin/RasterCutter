# -*- coding: utf-8 -*-
"""
Tests unitaires - Lot 3 : Moteur de Traitement Asynchrone & Découpage
"""

import os
import shutil
import tempfile
import pytest
from osgeo import gdal, osr

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsCoordinateReferenceSystem,
)
from pochoir_raster.pochoir_raster_worker import (
    prepare_mask_dataset,
    clip_local_raster_geotiff,
    PochoirRasterTask,
)


@pytest.fixture
def sample_dataset(qgis_app):
    """Crée un raster local GeoTIFF et un masque vectoriel de test."""
    tmp_dir = tempfile.mkdtemp(prefix="pochoir_test_")

    # 1. Raster synthétique 60x60 pixels EPSG:3857
    raster_path = os.path.join(tmp_dir, "test_input.tif")
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(raster_path, 60, 60, 3, gdal.GDT_Byte)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3857)
    ds.SetProjection(srs.ExportToWkt())
    ds.SetGeoTransform([0, 10, 0, 600, 0, -10])  # Emprise: 0..600, 0..600
    for b in range(1, 4):
        ds.GetRasterBand(b).Fill(80 * b)
    ds = None
    raster_layer = QgsRasterLayer(raster_path, "Raster Input", "gdal")
    assert raster_layer.isValid()

    # 2. Couche vectorielle de pochoir avec 2 entités
    vector_layer = QgsVectorLayer("Polygon?crs=epsg:3857&field=zone:string", "Pochoir Input", "memory")
    pr = vector_layer.dataProvider()

    # Entité 1 (Zone Centre) : carré de 100 à 300
    f1 = QgsFeature(vector_layer.fields())
    f1.setAttribute("zone", "Centre")
    f1.setGeometry(
        QgsGeometry.fromPolygonXY(
            [[QgsPointXY(100, 100), QgsPointXY(300, 100), QgsPointXY(300, 300), QgsPointXY(100, 300), QgsPointXY(100, 100)]]
        )
    )

    # Entité 2 (Zone Est) : carré de 400 à 500
    f2 = QgsFeature(vector_layer.fields())
    f2.setAttribute("zone", "Est")
    f2.setGeometry(
        QgsGeometry.fromPolygonXY(
            [[QgsPointXY(400, 100), QgsPointXY(500, 100), QgsPointXY(500, 200), QgsPointXY(400, 200), QgsPointXY(400, 100)]]
        )
    )
    pr.addFeatures([f1, f2])
    vector_layer.updateExtents()
    assert vector_layer.isValid()

    project = QgsProject.instance()
    project.addMapLayers([raster_layer, vector_layer])

    yield {
        "dir": tmp_dir,
        "raster_layer": raster_layer,
        "raster_path": raster_path,
        "vector_layer": vector_layer,
    }

    project.clear()
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_prepare_mask_all_features(sample_dataset):
    """Vérifie la préparation du masque avec toutes les entités."""
    vl = sample_dataset["vector_layer"]
    mask_path, extent, count = prepare_mask_dataset(vl, vl.crs())

    assert os.path.exists(mask_path)
    assert count == 2
    assert extent.xMinimum() == 100
    assert extent.xMaximum() == 500


def test_prepare_mask_selected_only(sample_dataset):
    """Vérifie la préparation du masque en mode entités sélectionnées uniquement."""
    vl = sample_dataset["vector_layer"]
    first_id = next(vl.getFeatures()).id()
    vl.selectByIds([first_id])

    mask_path, extent, count = prepare_mask_dataset(vl, vl.crs(), selected_only=True)
    assert count == 1
    assert extent.xMaximum() == 300


def test_prepare_mask_reprojection(sample_dataset):
    """Vérifie la reprojection automatique du masque si les SCR diffèrent."""
    vl = sample_dataset["vector_layer"]
    # SCR cible Lambert-93 (EPSG:2154)
    target_crs = QgsCoordinateReferenceSystem("EPSG:2154")
    mask_path, extent, count = prepare_mask_dataset(vl, target_crs)

    assert os.path.exists(mask_path)
    assert count == 2
    # Les coordonnées reprojetées doivent différer du système 3857
    assert extent.xMinimum() != 100


def test_clip_local_raster_geotiff(sample_dataset):
    """Vérifie la découpe effective d'un raster local par le masque."""
    vl = sample_dataset["vector_layer"]
    raster_path = sample_dataset["raster_path"]
    tmp_dir = sample_dataset["dir"]

    mask_path, _, _ = prepare_mask_dataset(vl, vl.crs())
    out_tif = os.path.join(tmp_dir, "output_clipped.tif")

    res_path = clip_local_raster_geotiff(raster_path, mask_path, out_tif, white_background=False)
    assert os.path.exists(res_path)
    assert os.path.getsize(res_path) > 0

    # Vérification avec GDAL
    ds = gdal.Open(res_path)
    assert ds is not None
    # 4 bandes attendues (RGB + Alpha de transparence)
    assert ds.RasterCount == 4
    ds = None


def test_pochoir_task_execution(sample_dataset):
    """Vérifie l'exécution synchrone complète d'une tâche PochoirRasterTask."""
    rl = sample_dataset["raster_layer"]
    vl = sample_dataset["vector_layer"]
    tmp_dir = sample_dataset["dir"]
    out_tif = os.path.join(tmp_dir, "task_out.tif")

    config = {
        "raster_layer": rl,
        "pochoir_layer": vl,
        "is_mbtiles": False,
        "is_temp": False,
        "output_path": out_tif,
        "apply_filter": True,
        "selected_only": False,
        "white_background": False,
    }

    finished_called = []

    def on_finished(success, message, layer):
        finished_called.append((success, message))

    task = PochoirRasterTask(config, iface=None, on_finished=on_finished)
    success = task.run()
    assert success is True
    assert os.path.exists(out_tif)

    task.finished(True)
    assert len(finished_called) == 1
    assert finished_called[0][0] is True
    from qgis.core import QgsProject
    QgsProject.instance().clear()


def test_progress_feedback_continuous(sample_dataset):
    """Vérifie le fonctionnement fluide des relais de feedback et l'émission des statuts."""
    from pochoir_raster.pochoir_raster_worker import (
        TaskProcessingFeedback,
        TaskRasterFeedback,
    )

    class MockTask:
        def __init__(self):
            self.history = []
            self._prog = 0.0
            self._canceled = False

        def update_progress(self, pct, msg):
            self._prog = pct
            self.history.append((pct, msg))

        def progress(self):
            return self._prog

        def isCanceled(self):
            return self._canceled

    mock = MockTask()
    fb_proc = TaskProcessingFeedback(mock, start_pct=15.0, end_pct=95.0, step_prefix="Génération")
    fb_proc.setProgress(50.0)
    assert abs(mock._prog - 55.0) < 1e-4
    assert "50%" in mock.history[-1][1]

    fb_raster = TaskRasterFeedback(mock, start_pct=20.0, end_pct=75.0, step_prefix="Téléchargement")
    fb_raster.setProgress(100.0)
    assert abs(mock._prog - 75.0) < 1e-4
    assert "100%" in mock.history[-1][1]

