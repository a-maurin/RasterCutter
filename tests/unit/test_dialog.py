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
    QgsRectangle,
)
from pochoir_raster.pochoir_raster_dialog import PochoirRasterDialog, extract_prefix_from_raster_source


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
    assert dialog.txt_tile_prefix.text() == ""
    assert "Auto" in dialog.txt_tile_prefix.placeholderText()
    assert dialog.chk_skip_existing.isChecked()
    assert dialog.radio_file.text() == "Enregistrer dans un dossier"
    assert dialog.btn_browse_output.text() == "Parcourir dossier..."
    assert dialog.lbl_tile_estimate is not None


def test_extract_prefix_from_raster_source():
    """Vérifie l'extraction du département et millésime dans différents formats de nom de raster."""
    # Format nom de dalle standard avec coordonnées
    assert extract_prefix_from_raster_source("21-2017-0800-6700-LA93-0M50-E080.jp2") == "21-2017"

    # Format IGN classique avec D021 et date ISO
    assert (
        extract_prefix_from_raster_source("ORTHOHR_1-0_RVB-0M20_JP2-E080_LAMB93_D021_2024-01-01")
        == "21-2024"
    )

    # Format IGN autre département (Yonne 89, 2021)
    assert extract_prefix_from_raster_source("BDORTHO_D089_2021-01-01") == "89-2021"

    # Département seul (Aube 10) : millésime conservé
    assert extract_prefix_from_raster_source("ORTHOPHOTOS_D10", current_prefix="21-2024") == "10-2024"

    # Millésime seul (2019) : département conservé
    assert extract_prefix_from_raster_source("BD_ORTHO_2019", current_prefix="21-2024") == "21-2019"

    # Raster sans motif : préfixe par défaut conservé
    assert extract_prefix_from_raster_source("mon_raster_sans_date", current_prefix="21-2024") == "21-2024"

    # Préfixe personnalisé saisi manuellement par l'utilisateur : jamais écrasé
    assert (
        extract_prefix_from_raster_source("BDORTHO_D089_2021", current_prefix="MON_PREFIXE_CUSTOM")
        == "MON_PREFIXE_CUSTOM"
    )


def test_dialog_auto_detect_prefix_on_layer_changed(qgis_app):
    """Vérifie que la sélection d'un raster met à jour le champ txt_tile_prefix."""
    dialog = PochoirRasterDialog(iface=None)

    # Couche fictive avec nom IGN
    layer_ign = MagicMock(spec=QgsRasterLayer)
    layer_ign.isValid.return_value = True
    layer_ign.name.return_value = "BDORTHO_D089_2021-01-01"
    layer_ign.source.return_value = "/data/BDORTHO_D089_2021-01-01.jp2"
    layer_ign.providerType.return_value = "gdal"
    layer_ign.metadata.return_value = None

    dialog._on_raster_layer_changed(layer_ign)
    assert dialog.txt_tile_prefix.text() == "89-2021"

    # Si l'utilisateur met un préfixe personnalisé, il n'est pas écrasé
    dialog.txt_tile_prefix.setText("MON_PROJET")
    layer_d21 = MagicMock(spec=QgsRasterLayer)
    layer_d21.isValid.return_value = True
    layer_d21.name.return_value = "21-2017-0800-6700-LA93"
    layer_d21.source.return_value = "/data/21-2017.jp2"
    layer_d21.providerType.return_value = "gdal"
    layer_d21.metadata.return_value = None

    dialog._on_raster_layer_changed(layer_d21)
    assert dialog.txt_tile_prefix.text() == "MON_PROJET"


def test_dialog_auto_detect_multi_departments_pochoir(qgis_app):
    """Vérifie que le choix d'un pochoir multi-départements applique le préfixe {DEP}-AAAA."""
    dialog = PochoirRasterDialog(iface=None)

    # Masque couvrant 21 et 89
    mask_layer = QgsVectorLayer("Polygon?crs=EPSG:2154", "Masque Multi", "memory")
    pr = mask_layer.dataProvider()
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromRect(QgsRectangle(785000.0, 6720000.0, 815000.0, 6750000.0)))
    pr.addFeatures([f])
    mask_layer.updateExtents()
    QgsProject.instance().addMapLayer(mask_layer)

    dialog.combo_pochoir.setLayer(mask_layer)
    dialog._on_pochoir_layer_changed(mask_layer)

    assert dialog.txt_tile_prefix.text() == "{DEP}-2024"
    assert "Multi-départements" in dialog.txt_tile_prefix.toolTip()


def test_query_ign_vintage_and_department():
    """Vérifie l'extraction des attributs GetFeatureInfo IGN."""
    from pochoir_raster.pochoir_raster_worker import query_ign_vintage_and_department
    from qgis.core import QgsCoordinateReferenceSystem

    mock_layer = MagicMock(spec=QgsRasterLayer)
    mock_layer.isValid.return_value = True
    mock_layer.providerType.return_value = "wms"
    mock_layer.crs.return_value = QgsCoordinateReferenceSystem("EPSG:3857")

    dp = MagicMock()
    mock_res = MagicMock()
    mock_res.isValid.return_value = True

    feat = MagicMock()
    feat_fields = MagicMock()
    feat_fields.indexFromName.side_effect = lambda name: 0 if name in ["dep", "pva"] else -1
    feat.fields.return_value = feat_fields
    feat.__getitem__.side_effect = lambda key: "021" if key == "dep" else ("2023" if key == "pva" else None)

    store = MagicMock()
    store.features.return_value = [feat]
    mock_res.results.return_value = {0: [store]}
    dp.identify.return_value = mock_res
    mock_layer.dataProvider.return_value = dp

    dep, year = query_ign_vintage_and_department(mock_layer)
    assert dep == "21"
    assert year == "2023"


def test_dialog_prefix_reset_on_deselection(qgis_app):
    """Vérifie que la désélection des couches réinitialise le préfixe à vide avec placeholder."""
    dialog = PochoirRasterDialog(iface=None)

    # 1. Sélection d'une couche raster -> préfixe calculé
    layer_ign = MagicMock(spec=QgsRasterLayer)
    layer_ign.isValid.return_value = True
    layer_ign.name.return_value = "BDORTHO_D089_2021-01-01"
    layer_ign.source.return_value = "/data/BDORTHO_D089_2021-01-01.jp2"
    layer_ign.providerType.return_value = "gdal"
    layer_ign.metadata.return_value = None

    dialog._on_raster_layer_changed(layer_ign)
    assert dialog.txt_tile_prefix.text() == "89-2021"

    # 2. Désélection (None) -> réinitialisation à vide
    dialog._on_raster_layer_changed(None)
    assert dialog.txt_tile_prefix.text() == ""
    assert "Auto" in dialog.txt_tile_prefix.placeholderText()

    # 3. Si saisie personnalisée manuelle -> conservée même à la désélection
    dialog.txt_tile_prefix.setText("MON_PROJET_PERSO")
    dialog._on_raster_layer_changed(None)
    assert dialog.txt_tile_prefix.text() == "MON_PROJET_PERSO"

    # 4. Désélection de la couche pochoir
    dialog.txt_tile_prefix.setText("21-2024")
    dialog._on_pochoir_layer_changed(None)
    assert dialog.txt_tile_prefix.text() == ""


def test_dialog_multi_layers_toggle(qgis_app, memory_layers):
    """Vérifie l'activation du mode multi-couches et les interactions associées."""
    vec_layer, _ = memory_layers
    jp2_path = "/home/e357/Documents/BTSA/stage/epage/SIG/scan25/21-2024-0795-6715-LA93.jp2"
    r_layer = QgsRasterLayer(jp2_path, "Scan25 Test")
    QgsProject.instance().addMapLayer(r_layer)

    dialog = PochoirRasterDialog(iface=None)

    # État initial : mode unitaire
    assert not dialog.chk_multi_layers.isChecked()
    assert not dialog.widget_single_raster.isHidden()
    assert dialog.frame_multi_layers.isHidden()

    # Activation multi-couches
    dialog.chk_multi_layers.setChecked(True)
    assert dialog.chk_multi_layers.isChecked()
    assert dialog.widget_single_raster.isHidden()
    assert not dialog.frame_multi_layers.isHidden()
    assert dialog.list_layers.count() >= 1

    # Boutons tout décocher / tout cocher
    dialog._deselect_all_layers()
    assert len(dialog.get_selected_raster_layers()) == 0

    dialog._select_all_layers()
    assert len(dialog.get_selected_raster_layers()) >= 1

    # Désactivation : retour en mode unitaire
    dialog.chk_multi_layers.setChecked(False)
    assert not dialog.widget_single_raster.isHidden()
    assert dialog.frame_multi_layers.isHidden()


def test_dialog_multi_layers_validation(qgis_app, memory_layers):
    """Vérifie la validation des paramètres en mode multi-couches."""
    vec_layer, _ = memory_layers
    jp2_path = "/home/e357/Documents/BTSA/stage/epage/SIG/scan25/21-2024-0795-6715-LA93.jp2"
    r_layer = QgsRasterLayer(jp2_path, "Scan25 Test")
    QgsProject.instance().addMapLayer(r_layer)

    dialog = PochoirRasterDialog(iface=None)
    dialog.combo_pochoir.setLayer(vec_layer)

    dialog.chk_multi_layers.setChecked(True)

    # 1. Erreur si aucune couche cochée
    dialog._deselect_all_layers()
    with pytest.raises(ValueError, match="Veuillez cocher au moins une couche raster"):
        dialog.get_configuration()

    # 2. Erreur si pas de dossier de sortie
    dialog._select_all_layers()
    dialog.txt_output_file.setText("")
    with pytest.raises(ValueError, match="Veuillez spécifier le dossier de destination"):
        dialog.get_configuration()

    # 3. Validation réussie avec dossier spécifié
    dialog.txt_output_file.setText("/tmp/dossier_test")
    config = dialog.get_configuration()
    assert config["is_multi_layers"] is True
    assert len(config["raster_layers"]) >= 1
    assert config["output_path"] == "/tmp/dossier_test"



