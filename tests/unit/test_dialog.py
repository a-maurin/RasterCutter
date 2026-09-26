# -*- coding: utf-8 -*-
"""
Tests unitaires - Lot 2 : Interface Graphique & Dialogue Qt
"""

from unittest.mock import MagicMock
import pytest
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
)
from pochoir_raster.pochoir_raster_dialog import PochoirRasterDialog


@pytest.fixture
def memory_layers(qgis_app):
    """Crée des couches mémoires vectorielle et raster pour les tests."""
    project = QgsProject.instance()
    project.clear()

    # Couche polygone en mémoire
    vec_layer = QgsVectorLayer("Polygon?crs=epsg:3857&field=nom:string", "Pochoir Test", "memory")
    assert vec_layer.isValid()

    pr = vec_layer.dataProvider()
    f1 = QgsFeature(vec_layer.fields())
    f1.setAttribute("nom", "Zone A")
    f1.setGeometry(
        QgsGeometry.fromPolygonXY(
            [[QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)]]
        )
    )
    f2 = QgsFeature(vec_layer.fields())
    f2.setAttribute("nom", "Zone B")
    f2.setGeometry(
        QgsGeometry.fromPolygonXY(
            [[QgsPointXY(20, 20), QgsPointXY(30, 20), QgsPointXY(30, 30), QgsPointXY(20, 30), QgsPointXY(20, 20)]]
        )
    )
    pr.addFeatures([f1, f2])
    vec_layer.updateExtents()
    project.addMapLayer(vec_layer)

    # Couche raster fictive
    raster_layer = QgsRasterLayer("type=virtual:width=100&height=100&crs=epsg:3857", "Raster Test", "virtualraster")
    if not raster_layer.isValid():
        # Fallback si virtualraster n'est pas dispo
        raster_layer = MagicMock(spec=QgsRasterLayer)
        raster_layer.isValid.return_value = True
        raster_layer.name.return_value = "Raster Test"
        raster_layer.providerType.return_value = "gdal"
    else:
        project.addMapLayer(raster_layer)

    return vec_layer, raster_layer


def test_dialog_init(qgis_app):
    """Vérifie que la boîte de dialogue s'instancie correctement sans erreur."""
    from qgis.core import QgsSettings
    QgsSettings().remove("RasterCutter/output_format")
    mock_iface = MagicMock()
    dialog = PochoirRasterDialog(iface=mock_iface)
    assert dialog.windowTitle() == "RasterCutter - Découpe de Raster"
    assert dialog.btn_run is not None
    assert dialog.combo_raster is not None
    assert dialog.combo_pochoir is not None
    assert dialog.radio_geotiff.isChecked()
    assert dialog.radio_temp.isChecked()


def test_dialog_validation_missing_layers(qgis_app):
    """Vérifie que la validation lève une exception si les couches sont manquantes."""
    mock_iface = MagicMock()
    dialog = PochoirRasterDialog(iface=mock_iface)

    with pytest.raises(ValueError, match="Veuillez sélectionner une couche raster valide"):
        dialog.get_configuration()


def test_dialog_selection_handling(qgis_app, memory_layers):
    """Vérifie la mise à jour dynamique des options lors d'une sélection vectorielle."""
    vec_layer, _ = memory_layers
    mock_iface = MagicMock()
    dialog = PochoirRasterDialog(iface=mock_iface)
    dialog.combo_pochoir.setLayer(vec_layer)

    # Initialement pas de sélection
    assert not dialog.chk_selected_only.isEnabled()
    assert not dialog.chk_selected_only.isChecked()

    # Sélectionner une entité
    first_feat_id = next(vec_layer.getFeatures()).id()
    vec_layer.selectByIds([first_feat_id])
    dialog._on_selection_changed()

    assert dialog.chk_selected_only.isEnabled()
    assert dialog.chk_selected_only.isChecked()
    assert "1 sélectionnée" in dialog.lbl_pochoir_info.text()


def test_dialog_format_switch(qgis_app):
    """Vérifie le comportement lors du passage au format MBTiles."""
    mock_iface = MagicMock()
    dialog = PochoirRasterDialog(iface=mock_iface)

    # Activer MBTiles force le mode fichier
    dialog.radio_mbtiles.setChecked(True)
    assert dialog.radio_file.isChecked()
    assert not dialog.radio_temp.isEnabled()

    # Revenir à GeoTIFF réactive le mode temporaire
    dialog.radio_geotiff.setChecked(True)
    assert dialog.radio_temp.isEnabled()


def test_dialog_cancel_button(qgis_app):
    """Vérifie la bascule du bouton Annuler / Fermer et l'appel à cancel."""
    mock_iface = MagicMock()
    dialog = PochoirRasterDialog(iface=mock_iface)
    assert dialog.btn_cancel.text() == "Fermer"

    mock_worker = MagicMock()
    mock_worker.isCanceled.return_value = False
    dialog.current_worker = mock_worker

    dialog._on_btn_cancel_clicked()
    mock_worker.cancel.assert_called_once()
    assert "Annulation" in dialog.lbl_status.text()

    dialog._on_task_finished(False, "Tâche annulée par l'utilisateur", None)
    assert dialog.btn_cancel.text() == "Fermer"


def test_filter_dalles_dialog_init(qgis_app):
    """Vérifie l'initialisation de la boîte de dialogue de tri de dalles."""
    from pochoir_raster.pochoir_raster_dialog import FilterDallesDialog

    mock_iface = MagicMock()
    dlg = FilterDallesDialog(iface=mock_iface)
    assert dlg.windowTitle() == "Tri spatial de dalles raster (Serveur / AutoCAD)"
    assert dlg.btn_run is not None
    assert dlg.txt_source is not None
    assert dlg.txt_dest is not None
    assert dlg.combo_mask is not None


def test_dialog_tabs_and_formats(qgis_app):
    """Vérifie l'organisation en 2 onglets distincts et les 3 formats de découpe."""
    dialog = PochoirRasterDialog(iface=None)
    assert dialog.tab_widget.count() == 2
    assert dialog.tab_widget.tabText(0) == "1. Découper au pochoir"
    assert dialog.tab_widget.tabText(1) == "2. Trier un dossier de dalles"
    assert "pochoir" in dialog.tab_widget.tabToolTip(0).lower()
    assert "autocad" in dialog.tab_widget.tabToolTip(1).lower()
    assert dialog.minimumWidth() >= 660

    # Vérification des radios de format
    assert dialog.radio_geotiff is not None
    assert dialog.radio_jp2 is not None
    assert dialog.radio_mbtiles is not None

    # Vérification des contrôles de l'onglet de tri
    assert dialog.txt_source_dir is not None
    assert dialog.txt_dest_dir is not None
    assert dialog.combo_pochoir_filter is not None
    assert dialog.btn_run_filter is not None


def test_dialog_jp2_settings_persistence(qgis_app):
    """Vérifie la mémorisation du format JP2 dans QgsSettings."""
    from qgis.core import QgsSettings

    dialog = PochoirRasterDialog(iface=None)
    dialog.radio_jp2.setChecked(True)
    assert QgsSettings().value("RasterCutter/output_format") == "jp2"

    dialog.radio_mbtiles.setChecked(True)
    assert QgsSettings().value("RasterCutter/output_format") == "mbtiles"

    dialog.radio_geotiff.setChecked(True)
    assert QgsSettings().value("RasterCutter/output_format") == "geotiff"


def test_dialog_jp2_grid_options(qgis_app):
    """Vérifie l'affichage dynamique des options de carrelage JP2 et des labels."""
    dialog = PochoirRasterDialog(iface=None)

    # Par défaut (GeoTIFF) le groupe de carrelage JP2 est masqué
    assert dialog.grp_jp2_options.isHidden()
    assert dialog.radio_file.text() == "Enregistrer dans un fichier"
    assert dialog.btn_browse_output.text() == "Enregistrer sous..."

    # Bascule vers JP2
    dialog.radio_jp2.setChecked(True)
    assert not dialog.grp_jp2_options.isHidden()
    assert dialog.combo_grid_size.count() == 3
    assert dialog.combo_grid_size.itemData(0) == 5000
    assert dialog.combo_grid_size.itemData(1) == 2000
    assert dialog.combo_grid_size.itemData(2) == 1000
    assert dialog.txt_tile_prefix.text() == "21-2024"
    assert dialog.chk_skip_existing.isChecked()
    assert dialog.radio_file.text() == "Enregistrer dans un dossier"
    assert dialog.btn_browse_output.text() == "Parcourir dossier..."
    assert dialog.lbl_tile_estimate is not None

