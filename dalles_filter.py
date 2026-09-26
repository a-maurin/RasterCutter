# -*- coding: utf-8 -*-
"""
Moteur de tri spatial et d'archivage des dalles raster pour le Bassin Versant de l'Armançon (BVA).
Module autonome utilisable en ligne de commande et depuis l'extension QGIS.
Auteur : Aguirre MAURIN (EPAGE / SMBVA) - 2026
"""

import csv
import datetime
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from osgeo import gdal, ogr, osr
    gdal.UseExceptions()
    ogr.UseExceptions()
except ImportError:
    pass

RASTER_EXTENSIONS = {".jp2", ".tif", ".tiff", ".ecw", ".img"}
DOC_EXTENSIONS = {".pdf", ".xml", ".txt", ".doc", ".docx", ".html", ".htm", ".md5"}


def get_tile_bbox_from_name(filename: str) -> Optional[Tuple[float, float, float, float]]:
    """Détecte rapidement l'emprise (xmin, ymin, xmax, ymax) en Lambert-93 depuis la convention IGN."""
    m = re.search(r"(\d{2,3})-(\d{4})-(\d{4})-(\d{4})", filename)
    if not m:
        m2 = re.search(r"(?:^|[^\d])(\d{4})[-_](\d{4})(?:[^\d]|$)", filename)
        if m2:
            xmin = float(m2.group(1)) * 1000.0
            ymax = float(m2.group(2)) * 1000.0
            return (xmin, ymax - 5000.0, xmin + 5000.0, ymax)
        return None

    xmin = float(m.group(3)) * 1000.0
    ymax = float(m.group(4)) * 1000.0
    taille = 5000.0
    if "E080" in filename.upper() or "5KM" in filename.upper():
        taille = 5000.0
    elif "1KM" in filename.upper():
        taille = 1000.0

    return (xmin, ymax - taille, xmin + taille, ymax)


def get_tile_bbox_from_gdal(file_path: Path) -> Optional[Tuple[float, float, float, float, Tuple[float, float]]]:
    """Lit l'emprise géographique réelle et la résolution via GDAL."""
    try:
        ds = gdal.Open(str(file_path), gdal.GA_ReadOnly)
        if not ds:
            return None
        gt = ds.GetGeoTransform()
        if not gt or (gt[1] == 1.0 and gt[5] == 1.0 and gt[0] == 0.0 and gt[3] == 0.0):
            return None
        xmin = gt[0]
        res_x = gt[1]
        ymax = gt[3]
        res_y = gt[5]
        xmax = xmin + res_x * ds.RasterXSize
        ymin = ymax + res_y * ds.RasterYSize
        if ymin > ymax:
            ymin, ymax = ymax, ymin
        return (xmin, ymin, xmax, ymax, (res_x, res_y))
    except Exception:
        return None


def load_mask_geometry(mask_path: Path, target_epsg: int = 2154, buffer_m: float = 0.0) -> "ogr.Geometry":
    """Charge le pochoir vectoriel et le reprojette en Lambert-93 avec buffer optionnel."""
    ds = ogr.Open(str(mask_path), 0)
    if not ds:
        raise FileNotFoundError(f"Impossible d'ouvrir le fichier de pochoir vectoriel : {mask_path}")
    lyr = ds.GetLayer(0)
    srs_src = lyr.GetSpatialRef()

    srs_dst = osr.SpatialReference()
    srs_dst.ImportFromEPSG(target_epsg)
    srs_dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    tx = None
    if srs_src and not srs_src.IsSame(srs_dst):
        srs_src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        tx = osr.CoordinateTransformation(srs_src, srs_dst)

    geoms = []
    for feat in lyr:
        geom = feat.GetGeometryRef()
        if geom:
            g_clone = geom.Clone()
            if tx:
                g_clone.Transform(tx)
            geoms.append(g_clone)

    if not geoms:
        raise ValueError("Le pochoir vectoriel ne contient aucune géométrie valide.")

    unified = geoms[0]
    for g in geoms[1:]:
        unified = unified.Union(g)

    if buffer_m > 0:
        unified = unified.Buffer(buffer_m)
    return unified


def find_companion_files(raster_file: Path) -> List[Path]:
    """Identifie tous les fichiers associés à une dalle (.tab, .aux.xml, .tfw, .j2w, etc.)."""
    stem = raster_file.stem
    parent = raster_file.parent
    companions = []
    prefix = stem + "."
    for item in parent.iterdir():
        if item.is_file() and (item.name == raster_file.name or item.name.startswith(prefix)):
            companions.append(item)
    return companions


def generate_world_file_if_needed(raster_file: Path, dest_raster_file: Path, bbox: Tuple[float, float, float, float]):
    """Génère un fichier World file (.tfw ou .j2w) si aucun fichier .tab ou .tfw/.j2w n'existe."""
    dest_dir = dest_raster_file.parent
    ext = raster_file.suffix.lower()
    wf_ext = ".tfw" if ext in {".tif", ".tiff"} else ".j2w" if ext == ".jp2" else ".wld"
    tab_file = dest_dir / (raster_file.stem + ".tab")
    wf_file = dest_dir / (raster_file.stem + wf_ext)

    if not tab_file.exists() and not wf_file.exists():
        xmin, ymin, xmax, ymax = bbox[:4]
        res_info = get_tile_bbox_from_gdal(raster_file)
        if res_info and len(res_info) > 4:
            res_x, res_y = res_info[4]
        else:
            res_x = 0.50
            res_y = -0.50

        x_center = xmin + abs(res_x) / 2.0
        y_center = ymax - abs(res_y) / 2.0
        lines = [
            f"{abs(res_x):.6f}\n",
            "0.000000\n",
            "0.000000\n",
            f"{-abs(res_y):.6f}\n",
            f"{x_center:.6f}\n",
            f"{y_center:.6f}\n",
        ]
        with open(wf_file, "w", encoding="ascii") as f:
            f.writelines(lines)


def export_tableau_assemblage_dxf(tiles: List[Dict], output_dxf: Path):
    """Génère un fichier DXF léger avec contours sur DALLES_CONTOURS et noms centrés sur DALLES_TEXTES."""
    lines = [
        "0\nSECTION\n2\nHEADER\n0\nENDSEC\n",
        "0\nSECTION\n2\nTABLES\n0\nTABLE\n2\nLAYER\n",
        "0\nLAYER\n2\nDALLES_CONTOURS\n70\n0\n62\n4\n6\nCONTINUOUS\n0\n",
        "0\nLAYER\n2\nDALLES_TEXTES\n70\n0\n62\n7\n6\nCONTINUOUS\n0\n",
        "ENDTAB\n0\nENDSEC\n",
        "0\nSECTION\n2\nENTITIES\n",
    ]

    for t in tiles:
        xmin, ymin, xmax, ymax = t["bbox"]
        name = t["name"]
        cx = (xmin + xmax) / 2.0
        cy = (ymin + ymax) / 2.0
        text_height = 150.0

        lines.append(
            f"0\nLWPOLYLINE\n8\nDALLES_CONTOURS\n90\n4\n70\n1\n"
            f"10\n{xmin:.2f}\n20\n{ymin:.2f}\n"
            f"10\n{xmax:.2f}\n20\n{ymin:.2f}\n"
            f"10\n{xmax:.2f}\n20\n{ymax:.2f}\n"
            f"10\n{xmin:.2f}\n20\n{ymax:.2f}\n"
        )
        lines.append(
            f"0\nTEXT\n8\nDALLES_TEXTES\n"
            f"10\n{cx:.2f}\n20\n{cy:.2f}\n30\n0.0\n"
            f"40\n{text_height:.1f}\n1\n{name}\n"
            f"72\n1\n73\n2\n"
            f"11\n{cx:.2f}\n21\n{cy:.2f}\n31\n0.0\n"
        )

    lines.append("0\nENDSEC\n0\nEOF\n")
    with open(output_dxf, "w", encoding="latin1", errors="replace") as f:
        f.writelines(lines)


def export_tableau_assemblage_shp(tiles: List[Dict], output_shp: Path, epsg: int = 2154):
    """Génère un tableau d'assemblage Shapefile polygonale avec attributs."""
    driver = ogr.GetDriverByName("ESRI Shapefile")
    if output_shp.exists():
        driver.DeleteDataSource(str(output_shp))

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    ds = driver.CreateDataSource(str(output_shp))
    lyr = ds.CreateLayer("tableau_assemblage_bva", srs, ogr.wkbPolygon)

    lyr.CreateField(ogr.FieldDefn("NOM", ogr.OFTString))
    lyr.CreateField(ogr.FieldDefn("FORMAT", ogr.OFTString))
    field_size = ogr.FieldDefn("TAILLE_MO", ogr.OFTReal)
    field_size.SetPrecision(2)
    lyr.CreateField(field_size)
    lyr.CreateField(ogr.FieldDefn("CHEMIN", ogr.OFTString))

    for t in tiles:
        xmin, ymin, xmax, ymax = t["bbox"]
        ring = ogr.Geometry(ogr.wkbLinearRing)
        ring.AddPoint(xmin, ymin)
        ring.AddPoint(xmax, ymin)
        ring.AddPoint(xmax, ymax)
        ring.AddPoint(xmin, ymax)
        ring.AddPoint(xmin, ymin)

        poly = ogr.Geometry(ogr.wkbPolygon)
        poly.AddGeometry(ring)

        feat = ogr.Feature(lyr.GetLayerDefn())
        feat.SetField("NOM", t["name"])
        feat.SetField("FORMAT", t["extension"].upper().lstrip("."))
        feat.SetField("TAILLE_MO", round(t["total_size_bytes"] / (1024 * 1024), 2))
        feat.SetField("CHEMIN", t["rel_path"])
        feat.SetGeometry(poly)
        lyr.CreateFeature(feat)

    ds = None


def filter_and_copy_tiles(
    source_dir: Path,
    dest_dir: Path,
    mask_path: Path,
    buffer_m: float = 0.0,
    dry_run: bool = False,
    skip_existing: bool = True,
    copy_docs: bool = True,
    progress_callback=None,
) -> Dict:
    """Scanne les dalles de la source, filtre selon le masque et copie vers la destination."""
    source_dir = Path(source_dir).resolve()
    dest_dir = Path(dest_dir).resolve()
    mask_path = Path(mask_path).resolve()

    if not source_dir.is_dir():
        raise NotADirectoryError(f"Le dossier source n'existe pas : {source_dir}")

    mask_geom = load_mask_geometry(mask_path, target_epsg=2154, buffer_m=buffer_m)

    raster_files = []
    doc_files = []
    for root, dirs, files in os.walk(source_dir):
        root_path = Path(root)
        for f in files:
            p = root_path / f
            ext = p.suffix.lower()
            if ext in RASTER_EXTENSIONS:
                raster_files.append(p)
            elif copy_docs and ext in DOC_EXTENSIONS and not p.name.endswith(".aux.xml"):
                doc_files.append(p)

    raster_files.sort()
    total_rasters = len(raster_files)
    kept_tiles = []
    excluded_tiles = []
    total_scanned_bytes = 0
    total_kept_bytes = 0
    total_excluded_bytes = 0

    for idx, r_file in enumerate(raster_files):
        if progress_callback:
            progress_callback(int((idx / max(total_rasters, 1)) * 70), f"Analyse : {r_file.name}")

        rel_path = r_file.relative_to(source_dir)
        companions = find_companion_files(r_file)
        tile_size_bytes = sum(c.stat().st_size for c in companions if c.exists())
        total_scanned_bytes += tile_size_bytes

        bbox = get_tile_bbox_from_name(r_file.name)
        if not bbox:
            gdal_info = get_tile_bbox_from_gdal(r_file)
            if gdal_info:
                bbox = gdal_info[:4]

        if not bbox:
            excluded_tiles.append({
                "path": r_file,
                "rel_path": str(rel_path),
                "reason": "Emprise géographique indétectable",
                "size_bytes": tile_size_bytes,
            })
            total_excluded_bytes += tile_size_bytes
            continue

        xmin, ymin, xmax, ymax = bbox
        ring = ogr.Geometry(ogr.wkbLinearRing)
        ring.AddPoint(xmin, ymin)
        ring.AddPoint(xmax, ymin)
        ring.AddPoint(xmax, ymax)
        ring.AddPoint(xmin, ymax)
        ring.AddPoint(xmin, ymin)
        tile_poly = ogr.Geometry(ogr.wkbPolygon)
        tile_poly.AddGeometry(ring)

        intersects = mask_geom.Intersects(tile_poly)

        tile_info = {
            "name": r_file.stem,
            "path": r_file,
            "rel_path": str(rel_path),
            "bbox": (xmin, ymin, xmax, ymax),
            "extension": r_file.suffix,
            "companions": companions,
            "total_size_bytes": tile_size_bytes,
        }

        if intersects:
            kept_tiles.append(tile_info)
            total_kept_bytes += tile_size_bytes
        else:
            excluded_tiles.append({
                "path": r_file,
                "rel_path": str(rel_path),
                "reason": "Hors périmètre bassin versant",
                "size_bytes": tile_size_bytes,
            })
            total_excluded_bytes += tile_size_bytes

    copied_files_count = 0
    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)
        total_to_copy = len(kept_tiles)

        for idx, t in enumerate(kept_tiles):
            if progress_callback:
                pct = 70 + int((idx / max(total_to_copy, 1)) * 25)
                progress_callback(pct, f"Copie ({idx+1}/{total_to_copy}) : {t['name']}")

            for comp in t["companions"]:
                rel_comp = comp.relative_to(source_dir)
                target_comp = dest_dir / rel_comp
                target_comp.parent.mkdir(parents=True, exist_ok=True)

                if skip_existing and target_comp.exists() and target_comp.stat().st_size == comp.stat().st_size:
                    continue
                shutil.copy2(comp, target_comp)
                copied_files_count += 1

            dest_raster = dest_dir / t["rel_path"]
            generate_world_file_if_needed(t["path"], dest_raster, t["bbox"])

        for doc in doc_files:
            target_doc = dest_dir / doc.relative_to(source_dir)
            target_doc.parent.mkdir(parents=True, exist_ok=True)
            if not target_doc.exists():
                shutil.copy2(doc, target_doc)

        if kept_tiles:
            if progress_callback:
                progress_callback(96, "Génération des index DXF et Shapefile...")
            dxf_path = dest_dir / "tableau_assemblage_bva.dxf"
            shp_path = dest_dir / "tableau_assemblage_bva.shp"
            export_tableau_assemblage_dxf(kept_tiles, dxf_path)
            export_tableau_assemblage_shp(kept_tiles, shp_path)

        report_txt = dest_dir / "bilan_filtrage.txt"
        report_csv = dest_dir / "bilan_filtrage.csv"
        _write_reports(
            report_txt,
            report_csv,
            source_dir,
            dest_dir,
            mask_path,
            buffer_m,
            total_rasters,
            kept_tiles,
            excluded_tiles,
            total_scanned_bytes,
            total_kept_bytes,
            total_excluded_bytes,
            dry_run=False,
        )

    if progress_callback:
        progress_callback(100, "Tri terminé.")

    return {
        "total_rasters": total_rasters,
        "kept_count": len(kept_tiles),
        "excluded_count": len(excluded_tiles),
        "total_scanned_mb": round(total_scanned_bytes / (1024 * 1024), 2),
        "total_kept_mb": round(total_kept_bytes / (1024 * 1024), 2),
        "total_saved_mb": round(total_excluded_bytes / (1024 * 1024), 2),
        "saved_percent": round((total_excluded_bytes / max(total_scanned_bytes, 1)) * 100, 1),
        "kept_tiles": kept_tiles,
        "excluded_tiles": excluded_tiles,
        "copied_files_count": copied_files_count,
    }


def _write_reports(
    report_txt: Path,
    report_csv: Path,
    source_dir: Path,
    dest_dir: Path,
    mask_path: Path,
    buffer_m: float,
    total_rasters: int,
    kept_tiles: List[Dict],
    excluded_tiles: List[Dict],
    total_bytes: int,
    kept_bytes: int,
    saved_bytes: int,
    dry_run: bool,
):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    saved_pct = round((saved_bytes / max(total_bytes, 1)) * 100, 1)

    with open(report_txt, "w", encoding="utf-8") as f:
        f.write("======================================================================\n")
        f.write("                  BILAN DU TRI SPATIAL DE DALLES                     \n")
        f.write("======================================================================\n\n")
        f.write(f"Date d'exécution   : {now_str}\n")
        f.write(f"Mode               : {'SIMULATION (DRY-RUN)' if dry_run else 'RÉEL'}\n")
        f.write(f"Dossier source     : {source_dir}\n")
        f.write(f"Dossier destination: {dest_dir}\n")
        f.write(f"Masque vectoriel   : {mask_path} (Zone tampon: {buffer_m} m)\n\n")
        f.write("STATISTIQUES DES DALLES :\n")
        f.write(f"  * Dalles analysées         : {total_rasters}\n")
        f.write(f"  * Dalles conservées        : {len(kept_tiles)} ({(len(kept_tiles)/max(total_rasters,1))*100:.1f} %)\n")
        f.write(f"  * Dalles écartées          : {len(excluded_tiles)} ({saved_pct} %)\n\n")
        f.write("VOLUMÉTRIE :\n")
        f.write(f"  * Volume initial scanné    : {total_bytes / (1024**3):.2f} Go ({total_bytes / (1024**2):.1f} Mo)\n")
        f.write(f"  * Volume conservé          : {kept_bytes / (1024**3):.2f} Go ({kept_bytes / (1024**2):.1f} Mo)\n")
        f.write(f"  * Espace économisé         : {saved_bytes / (1024**3):.2f} Go ({saved_bytes / (1024**2):.1f} Mo)\n")
        f.write(f"  * Pourcentage d'économie   : {saved_pct} %\n\n")
        f.write("INDEXATIONS GÉNÉRÉES :\n")
        f.write("  * Tableau d'assemblage DXF : tableau_assemblage_bva.dxf\n")
        f.write("  * Tableau d'assemblage SHP : tableau_assemblage_bva.shp\n\n")
        f.write("======================================================================\n")

    with open(report_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["NOM", "STATUT", "TAILLE_MO", "CHEMIN_RELATIF", "RAISON"])
        for t in kept_tiles:
            writer.writerow([t["name"], "CONSERVEE", round(t["total_size_bytes"] / (1024 * 1024), 2), t["rel_path"], "Intersecte le bassin versant"])
        for e in excluded_tiles:
            writer.writerow([Path(e["path"]).stem, "ECARTEE", round(e["size_bytes"] / (1024 * 1024), 2), e["rel_path"], e["reason"]])
