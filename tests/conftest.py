# -*- coding: utf-8 -*-
"""
Configuration globale pytest pour les tests PyQGIS du plugin RasterCutter.
"""

import sys
import importlib.util
from pathlib import Path
import pytest
from qgis.core import QgsApplication

# Assurer que la racine du plugin est dans sys.path
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

# Charger le plugin sous 'pochoir_raster' (nom de code historique du package) et 'raster_cutter'
init_path = PLUGIN_ROOT / "__init__.py"
if init_path.exists():
    spec = importlib.util.spec_from_file_location("pochoir_raster", init_path, submodule_search_locations=[str(PLUGIN_ROOT)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pochoir_raster"] = mod
    sys.modules["raster_cutter"] = mod
    spec.loader.exec_module(mod)


@pytest.fixture(scope="session")
def qgis_app():
    """Initialise une session QgsApplication headless pour toute la suite de tests."""
    QgsApplication.setPrefixPath("/usr", True)
    app = QgsApplication([], False)
    app.initQgis()
    yield app
    app.exitQgis()
