# -*- coding: utf-8 -*-
"""
Tests unitaires pour le script de filtrage spatial des dalles (filtrer_dalles_bva.py).
"""

import os
import shutil
import tempfile
from pathlib import Path
import pytest

try:
    from dalles_filter import (
        get_tile_bbox_from_name,
        find_companion_files,
        generate_world_file_if_needed,
        export_tableau_assemblage_dxf,
        filter_and_copy_tiles,
    )
except ImportError:
    from scripts.filtrer_dalles_bva import (
        get_tile_bbox_from_name,
        find_companion_files,
        generate_world_file_if_needed,
        export_tableau_assemblage_dxf,
        filter_and_copy_tiles,
    )


def test_get_tile_bbox_from_name():
    # Format standard IGN E080 (5km)
    name = "21-2017-0785-6715-LA93-0M50-E080.jp2"
    bbox = get_tile_bbox_from_name(name)
    assert bbox is not None
    xmin, ymin, xmax, ymax = bbox
    assert xmin == 785000.0
    assert ymax == 6715000.0
    assert xmax == 790000.0
    assert ymin == 6710000.0


def test_get_tile_bbox_from_name_invalid():
    assert get_tile_bbox_from_name("fichier_inconnu.tif") is None


def test_find_companion_files(tmp_path):
    dalle_jp2 = tmp_path / "21-2017-0785-6715-LA93-0M50-E080.jp2"
    dalle_tab = tmp_path / "21-2017-0785-6715-LA93-0M50-E080.tab"
    dalle_xml = tmp_path / "21-2017-0785-6715-LA93-0M50-E080.jp2.aux.xml"
    other_jp2 = tmp_path / "autre_dalle.jp2"

    dalle_jp2.write_text("dummy")
    dalle_tab.write_text("dummy")
    dalle_xml.write_text("dummy")
    other_jp2.write_text("dummy")

    companions = find_companion_files(dalle_jp2)
    names = {c.name for c in companions}
    assert names == {
        "21-2017-0785-6715-LA93-0M50-E080.jp2",
        "21-2017-0785-6715-LA93-0M50-E080.tab",
        "21-2017-0785-6715-LA93-0M50-E080.jp2.aux.xml",
    }
    assert "autre_dalle.jp2" not in names


def test_generate_world_file_if_needed(tmp_path):
    raster_file = tmp_path / "test_tile.jp2"
    raster_file.write_text("dummy")
    dest_raster = tmp_path / "dest" / "test_tile.jp2"
    dest_raster.parent.mkdir(parents=True, exist_ok=True)
    dest_raster.write_text("dummy")

    bbox = (785000.0, 6710000.0, 790000.0, 6715000.0)
    generate_world_file_if_needed(raster_file, dest_raster, bbox)

    j2w_file = tmp_path / "dest" / "test_tile.j2w"
    assert j2w_file.exists()
    content = j2w_file.read_text().splitlines()
    assert len(content) == 6
    assert float(content[0]) > 0.0
    assert float(content[3]) < 0.0


def test_export_tableau_assemblage_dxf(tmp_path):
    output_dxf = tmp_path / "assemblage.dxf"
    tiles = [
        {
            "name": "dalle_1",
            "bbox": (785000.0, 6710000.0, 790000.0, 6715000.0),
        }
    ]
    export_tableau_assemblage_dxf(tiles, output_dxf)
    assert output_dxf.exists()
    content = output_dxf.read_text(encoding="latin1")
    assert "DALLES_CONTOURS" in content
    assert "DALLES_TEXTES" in content
    assert "dalle_1" in content


def test_filter_and_copy_dry_run():
    source_dir = Path("/home/e357/Documents/BTSA/stage/epage/SIG/decoupe_raster/exemple_fichiers_smbva/ORTHOPHOTOS_D21")
    mask_path = Path("/home/e357/Documents/BTSA/stage/epage/SIG/decoupe_raster/donnees/vecteurs/pochoir_bva_fix.gpkg")

    if not source_dir.exists() or not mask_path.exists():
        pytest.skip("Données de test réelles non disponibles.")

    with tempfile.TemporaryDirectory() as tmp_dest:
        dest_dir = Path(tmp_dest)
        stats = filter_and_copy_tiles(
            source_dir=source_dir,
            dest_dir=dest_dir,
            mask_path=mask_path,
            buffer_m=0.0,
            dry_run=True,
        )

        assert stats["total_rasters"] == 97
        assert stats["kept_count"] == 83
        assert stats["excluded_count"] == 14
        assert stats["total_saved_mb"] > 0
        # En mode dry-run, aucun fichier ne doit avoir été créé dans dest_dir
        assert len(list(dest_dir.iterdir())) == 0
