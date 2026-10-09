# -*- coding: utf-8 -*-
"""
Tests unitaires pour l'export JPEG 2000 (.jp2) et ses fichiers de calage AutoCAD (.tab, .j2w).
"""

import os
from pathlib import Path
import pytest
from osgeo import gdal, osr

from pochoir_raster.pochoir_raster_worker import (
    generate_tab_file,
    generate_j2w_file,
    convert_geotiff_to_jp2,
    generate_grid_tiles,
    get_departments_intersecting_geometry,
)


def test_generate_tab_file(tmp_path):
    jp2_path = tmp_path / "test_dalle.jp2"
    jp2_path.write_bytes(b"dummy")

    bbox = (785000.0, 6710000.0, 790000.0, 6715000.0)
    generate_tab_file(str(jp2_path), bbox, width=10000, height=10000)

    tab_path = tmp_path / "test_dalle.tab"
    assert tab_path.exists()
    content = tab_path.read_text(encoding="latin1")
    assert "!table" in content
    assert 'File "test_dalle.jp2"' in content
    assert "785000.00,6715000.00" in content
    assert "790000.00,6710000.00" in content
    assert "Lambert" in content or "CoordSys" in content


def test_generate_j2w_file(tmp_path):
    jp2_path = tmp_path / "test_dalle.jp2"
    jp2_path.write_bytes(b"dummy")

    bbox = (785000.0, 6710000.0, 790000.0, 6715000.0)
    generate_j2w_file(str(jp2_path), bbox, width=10000, height=10000)

    j2w_path = tmp_path / "test_dalle.j2w"
    assert j2w_path.exists()
    lines = j2w_path.read_text(encoding="ascii").splitlines()
    assert len(lines) == 6
    assert float(lines[0]) == pytest.approx(0.5, rel=1e-3)
    assert float(lines[3]) == pytest.approx(-0.5, rel=1e-3)
    assert float(lines[4]) == pytest.approx(785000.25, rel=1e-3)
    assert float(lines[5]) == pytest.approx(6714999.75, rel=1e-3)


def test_convert_geotiff_to_jp2(tmp_path):
    # Création d'un GeoTIFF test
    tif_path = tmp_path / "source.tif"
    jp2_path = tmp_path / "dest.jp2"

    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(str(tif_path), 50, 50, 3, gdal.GDT_Byte)
    ds.SetGeoTransform([785000.0, 1.0, 0.0, 6715000.0, 0.0, -1.0])
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(2154)
    ds.SetSpatialRef(srs)
    ds = None

    result = convert_geotiff_to_jp2(str(tif_path), str(jp2_path), target_epsg=2154)
    assert Path(result).exists()
    assert Path(result).stat().st_size > 0

    # Vérification des fichiers de calage
    tab_path = tmp_path / "dest.tab"
    j2w_path = tmp_path / "dest.j2w"
    assert tab_path.exists()
    assert j2w_path.exists()


def test_generate_grid_tiles(qgis_app):
    from qgis.core import QgsGeometry, QgsPointXY
    from pochoir_raster.pochoir_raster_worker import generate_grid_tiles

    # Polygoe en Lambert-93 couvrant de 786000, 6711000 à 791000, 6716000
    # Ce polygone chevauche 4 dalles de 5km :
    # (785-6715), (785-6720), (790-6715), (790-6720)
    geom = QgsGeometry.fromPolygonXY([[
        QgsPointXY(786000, 6711000),
        QgsPointXY(791000, 6711000),
        QgsPointXY(791000, 6716000),
        QgsPointXY(786000, 6716000),
        QgsPointXY(786000, 6711000)
    ]])
    tiles = generate_grid_tiles(geom, tile_size_m=5000, prefix="21-2024")
    assert len(tiles) == 4
    names = [t["name"] for t in tiles]
    assert "21-2024-0785-6715-LA93.jp2" in names
    assert "21-2024-0785-6720-LA93.jp2" in names
    assert "21-2024-0790-6715-LA93.jp2" in names
    assert "21-2024-0790-6720-LA93.jp2" in names

    # Test grille 1 km
    tiles_1k = generate_grid_tiles(geom, tile_size_m=1000, prefix="BVA-2024")
    assert len(tiles_1k) == 25
    assert all("BVA-2024" in t["name"] for t in tiles_1k)


def test_extract_grid_tile_jp2(tmp_path, qgis_app):
    from qgis.core import QgsRasterLayer
    from pochoir_raster.pochoir_raster_worker import extract_grid_tile_jp2

    # Créer un GeoTIFF local en Lambert-93
    tif_src = tmp_path / "local_ortho.tif"
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(str(tif_src), 100, 100, 3, gdal.GDT_Byte)
    ds.SetGeoTransform([785000.0, 50.0, 0.0, 6715000.0, 0.0, -50.0])
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(2154)
    ds.SetSpatialRef(srs)
    for b in range(1, 4):
        ds.GetRasterBand(b).Fill(150)
    ds = None

    rl = QgsRasterLayer(str(tif_src), "Ortho Source", "gdal")
    assert rl.isValid()

    tile_dict = {
        "name": "21-2024-0785-6715-LA93.jp2",
        "bbox": (785000.0, 6710000.0, 790000.0, 6715000.0),
    }
    dst_jp2 = tmp_path / "21-2024-0785-6715-LA93.jp2"
    extract_grid_tile_jp2(rl, tile_dict, str(dst_jp2))

    assert dst_jp2.exists()
    assert dst_jp2.stat().st_size > 0
    assert (tmp_path / "21-2024-0785-6715-LA93.tab").exists()
    assert (tmp_path / "21-2024-0785-6715-LA93.j2w").exists()


def test_estimate_grid_tiles_count(qgis_app):
    from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsRectangle
    from pochoir_raster.pochoir_raster_worker import estimate_grid_tiles_count

    vl = QgsVectorLayer("Polygon?crs=EPSG:2154", "TestMask", "memory")
    pr = vl.dataProvider()
    feat = QgsFeature()
    # Emprise de 5 km x 5 km : [785000, 6710000, 790000, 6715000]
    feat.setGeometry(QgsGeometry.fromRect(QgsRectangle(785000.0, 6710000.0, 790000.0, 6715000.0)))
    pr.addFeatures([feat])
    vl.updateExtents()

    count_5k = estimate_grid_tiles_count(vl, tile_size_m=5000)
    assert count_5k == 1

    count_1k = estimate_grid_tiles_count(vl, tile_size_m=1000)
    assert count_1k == 25

    # Test garde-fou > 1000 dalles
    vl_huge = QgsVectorLayer("Polygon?crs=EPSG:2154", "HugeMask", "memory")
    pr_h = vl_huge.dataProvider()
    f_h = QgsFeature()
    # Emprise géante de 500 km x 500 km -> 100 x 100 = 10 000 dalles de 5 km
    f_h.setGeometry(QgsGeometry.fromRect(QgsRectangle(500000.0, 6000000.0, 1000000.0, 6500000.0)))
    pr_h.addFeatures([f_h])
    vl_huge.updateExtents()
    assert estimate_grid_tiles_count(vl_huge, tile_size_m=5000) == -1


def test_task_cancellation_during_run(tmp_path, qgis_app):
    from unittest.mock import MagicMock
    from qgis.core import QgsVectorLayer
    from pochoir_raster.pochoir_raster_worker import extract_grid_tile_jp2, PochoirRasterTask

    mock_task = MagicMock()
    mock_task.isCanceled.return_value = True

    mock_layer = MagicMock()
    mock_layer.providerType.return_value = "gdal"
    mock_layer.source.return_value = "test.tif"

    tile = {"name": "test.jp2", "bbox": (0, 0, 1000, 1000)}
    res = extract_grid_tile_jp2(mock_layer, tile, str(tmp_path / "test.jp2"), task=mock_task)
    assert res is None


def test_generate_grid_tiles_multi_departments(qgis_app):
    """Vérifie le découpage et le nommage dynamique {DEP} sur plusieurs départements."""
    from qgis.core import QgsGeometry, QgsRectangle

    # Emprise à cheval sur la Côte-d'Or (21) et l'Yonne (89)
    # X de 785 km à 815 km, Y de 6720 km à 6750 km
    rect = QgsRectangle(785000.0, 6720000.0, 815000.0, 6750000.0)
    geom = QgsGeometry.fromRect(rect)

    # 1. Test avec {DEP}-2023
    tiles = generate_grid_tiles(geom, tile_size_m=5000, prefix="{DEP}-2023")
    assert len(tiles) > 0

    dept_prefixes = set()
    for t in tiles:
        # Extraire le préfixe XX-2023
        name = t["name"]
        prefix_part = name.split("-")[0]
        dept_prefixes.add(prefix_part)

    # Doit contenir au moins 21 et 89
    assert "21" in dept_prefixes
    assert "89" in dept_prefixes

    # 2. Test avec préfixe fixe sans {DEP} (ex: 21-2024) : toutes les dalles restent en 21
    tiles_fixed = generate_grid_tiles(geom, tile_size_m=5000, prefix="21-2024")
    for t in tiles_fixed:
        assert t["name"].startswith("21-2024-")

