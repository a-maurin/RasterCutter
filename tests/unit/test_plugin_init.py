# -*- coding: utf-8 -*-
"""
Tests unitaires - Lot 1 : Socle du Plugin & Déclaration QGIS
"""

import os
import configparser
from unittest.mock import MagicMock
from pathlib import Path
from qgis.PyQt.QtGui import QImage


PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent
if not (PLUGIN_DIR / "metadata.txt").exists():
    PLUGIN_DIR = PLUGIN_DIR / "plugin_qgis" / "raster_cutter"


def test_metadata_file():
    """Vérifie la conformité du fichier metadata.txt selon les normes QGIS."""
    meta_path = PLUGIN_DIR / "metadata.txt"
    assert meta_path.exists(), "metadata.txt doit exister"

    config = configparser.ConfigParser()
    config.read(meta_path, encoding="utf-8")
    assert "general" in config.sections(), "Section [general] requise"

    gen = config["general"]
    assert gen.get("name") == "RasterCutter"
    assert gen.get("author") == "Aguirre MAURIN"
    assert "GPL" in gen.get("license")
    assert gen.get("version") == "1.0.0"
    assert gen.get("category") == "Raster"
    assert (PLUGIN_DIR / gen.get("icon")).exists(), "L'icône spécifiée doit exister"


def test_license_file():
    """Vérifie la présence et le contenu du fichier LICENSE."""
    lic_path = PLUGIN_DIR / "LICENSE"
    assert lic_path.exists(), "Le fichier LICENSE doit exister"
    content = lic_path.read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in content
    assert "Aguirre MAURIN" in content


def test_icon_validity():
    """Vérifie que l'icône est une image PNG valide et exploitable par Qt."""
    icon_path = PLUGIN_DIR / "icon.png"
    assert icon_path.exists(), "icon.png doit exister"
    img = QImage(str(icon_path))
    assert not img.isNull(), "L'image PNG doit être lisible par Qt"
    assert img.width() == 64 and img.height() == 64


def test_plugin_init_and_unload(qgis_app):
    """Vérifie le chargement, initGui et unload avec un iface simulé."""
    from pochoir_raster import classFactory
    from pochoir_raster.pochoir_raster_plugin import PochoirRasterPlugin

    mock_iface = MagicMock()
    plugin = classFactory(mock_iface)
    assert isinstance(plugin, PochoirRasterPlugin)

    plugin.initGui()
    assert len(plugin.actions) == 2
    assert mock_iface.addToolBarIcon.called
    assert mock_iface.addRasterToolBarIcon.called
    assert mock_iface.addPluginToMenu.called
    assert mock_iface.addPluginToRasterMenu.called

    plugin.unload()
    assert len(plugin.actions) == 0
    assert mock_iface.removeToolBarIcon.called
    assert mock_iface.removeRasterToolBarIcon.called
    assert mock_iface.removePluginMenu.called
    assert mock_iface.removePluginRasterMenu.called
