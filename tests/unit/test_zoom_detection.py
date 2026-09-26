# -*- coding: utf-8 -*-
"""
Tests unitaires - Détection automatique et gestion des niveaux de zoom
"""

from unittest.mock import MagicMock
from qgis.core import QgsRasterLayer, QgsProject
from pochoir_raster.pochoir_raster_worker import detect_raster_zoom_levels
from pochoir_raster.pochoir_raster_dialog import PochoirRasterDialog


def test_detect_zoom_multi_zoom(qgis_app):
    """Vérifie la détection d'un flux multi-zoom (ex: Ortho 20 cm PM_6_19)."""
    uri = (
        "crs=EPSG:3857&dpiMode=7&featureCount=10&format=image/jpeg"
        "&layers=HR.ORTHOIMAGERY.ORTHOPHOTOS&styles=normal&tileMatrixSet=PM_6_19"
        "&tilePixelRatio=0&url=https://data.geopf.fr/wmts?SERVICE%3DWMTS%26VERSION%3D1.0.0%26REQUEST%3DGetCapabilities"
    )
    layer = QgsRasterLayer(uri, "Ortho 20 cm", "wms")
    info = detect_raster_zoom_levels(layer)

    assert info["is_remote"] is True
    assert info["single_zoom"] is False
    assert info["min_zoom"] == 6
    assert info["max_zoom"] == 19
    assert len(info["zoom_levels"]) == 14
    assert "14 niveaux détectés" in info["label"]


def test_detect_zoom_scan25_pyramid(qgis_app):
    """Vérifie que pour le SCAN 25, toute la pyramide (zoom 6 à 16) est détectée."""
    uri = (
        "crs=EPSG:3857&dpiMode=7&format=image/png"
        "&layers=SCAN25TOUR_PYR-JPEG_WLD_WM&styles"
        "&url=https://data.geopf.fr/private/wms-r/?version=1.3.0"
    )
    layer = QgsRasterLayer(uri, "SCAN 25 Fixe", "wms")
    info = detect_raster_zoom_levels(layer)

    assert info["min_zoom"] == 6
    assert info["max_zoom"] == 16
    assert len(info["zoom_levels"]) == 11
    assert "Tous embarqués par défaut" in info["label"]


def test_dialog_preselects_all_zoom_levels(qgis_app):
    """Vérifie que la boîte de dialogue pré-sélectionne 100% de la plage de la couche par défaut."""
    uri = "crs=EPSG:3857&layers=SCAN25TOUR_PYR-JPEG_WLD_WM"
    layer = QgsRasterLayer(uri, "SCAN 25 Fixe", "wms")
    QgsProject.instance().addMapLayer(layer)

    dialog = PochoirRasterDialog(iface=None)
    dialog.combo_raster.setLayer(layer)
    dialog._on_raster_layer_changed(layer)

    # La plage complète 6 à 16 doit être pré-sélectionnée par défaut et active
    assert dialog.spin_zoom_min.value() == 6
    assert dialog.spin_zoom_max.value() == 16
    assert dialog.spin_zoom_min.minimum() == 6
    assert dialog.spin_zoom_min.maximum() == 16
    assert dialog.spin_zoom_max.minimum() == 6
    assert dialog.spin_zoom_max.maximum() == 16

    # Test du blocage strict : impossible de dépasser 16
    dialog.spin_zoom_max.setValue(24)
    assert dialog.spin_zoom_max.value() == 16

    # Format JP2 : zoom min masqué, libellé cible et résolution affichée
    dialog.radio_jp2.setChecked(True)
    dialog._on_format_changed()
    assert dialog.spin_zoom_min.isHidden()
    assert dialog.lbl_zoom_max.text() == "Niveau de zoom cible :"
    assert "m/pixel" in dialog.lbl_zoom_res.text()

    # Format MBTiles : zoom min visible, libellé classique
    dialog.radio_mbtiles.setChecked(True)
    dialog._on_format_changed()
    assert not dialog.spin_zoom_min.isHidden()
    assert dialog.lbl_zoom_max.text() == "Zoom max :"

    assert "Tous embarqués par défaut" in dialog.lbl_zoom_info.text()

    QgsProject.instance().clear()
