# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Pochoir Raster - Boîte de Dialogue Graphique
                                 A QGIS plugin
 Découpe universelle de raster par emporte-pièce vectoriel & Tri de dalles CAO
                              -------------------
        begin                : 2026-09-16
        copyright            : (C) 2026 by Aguirre MAURIN
        email                : aguirre.maurin@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 3 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os
import re
from pathlib import Path

from qgis.PyQt.QtCore import Qt, QFileInfo, pyqtSignal
from qgis.PyQt.QtGui import QIcon, QFont, QPixmap
from qgis.PyQt.QtWidgets import (
    QDialog,
    QWidget,
    QTabWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QCheckBox,
    QRadioButton,
    QButtonGroup,
    QProgressBar,
    QLineEdit,
    QSpinBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QMessageBox,
    QFrame,
)
from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsMapLayerProxyModel,
    QgsApplication,
    QgsSettings,
)
from qgis.gui import QgsMapLayerComboBox
from .dalles_filter import filter_and_copy_tiles
from .pochoir_raster_worker import (
    launch_clipping_task,
    detect_raster_zoom_levels,
    generate_grid_tiles,
    get_pochoir_geometry,
    estimate_grid_tiles_count,
    PochoirRasterWorker,
)


def extract_prefix_from_raster_source(layer_name: str, layer_source: str = "", current_prefix: str = "21-2024") -> str:
    """
    Extrait automatiquement le département et/ou l'année (millésime) depuis le nom ou la source d'un raster.
    Préserve toute saisie personnalisée manuelle (hors format standard XX-YYYY).
    Si un seul élément est détecté, met à jour cet élément et conserve l'autre.
    """
    curr = str(current_prefix or "").strip()
    standard_pattern = r"^([0-9]{1,3}|2[ABab])-([0-9]{4})$"
    m_curr = re.match(standard_pattern, curr)

    # Si l'utilisateur a saisi un texte personnalisé libre (ex: 'PROJET_BVA'), on ne l'écrase jamais
    if curr and not m_curr:
        return curr

    curr_dep = m_curr.group(1) if m_curr else "21"
    curr_year = m_curr.group(2) if m_curr else "2024"

    detected_dep = None
    detected_year = None

    text_to_scan = f"{layer_name or ''} {layer_source or ''}"

    # 1. Détection combinée début de nom de dalle (ex: '21-2017-' ou '89-2021_')
    m_comb = re.search(r"(?:^|[\/\\]|\b)([0-9]{1,3}|2[ABab])-((?:199\d|20[0-3]\d))[-_]", text_to_scan)
    if m_comb:
        dep_val = m_comb.group(1)
        detected_dep = dep_val.lstrip("0") or dep_val
        detected_year = m_comb.group(2)

    # 2. Détection du département avec préfixe 'D' (ex: 'D021', 'D21', 'D089', 'D10')
    if not detected_dep:
        m_dep = re.search(
            r"(?:^|[_\-/\\ ])D(0[1-9]|[1-8][0-9]|9[0-5]|2[ABab]|97[1-6]|[0-9]{2,3})(?:[_\-/\\ .]|$)",
            text_to_scan,
            re.IGNORECASE,
        )
        if m_dep:
            dep_val = m_dep.group(1)
            detected_dep = dep_val.lstrip("0") or dep_val

    # 3. Détection de l'année (ex: '2024-01-01' ISO, ou '2021' isolé)
    if not detected_year:
        m_year_iso = re.search(r"\b((?:199\d|20[0-3]\d))-\d{2}-\d{2}\b", text_to_scan)
        if m_year_iso:
            detected_year = m_year_iso.group(1)
        else:
            m_year = re.search(r"(?:^|[_\-/\\ ])((?:199\d|20[0-3]\d))(?:[_\-/\\ .]|$)", text_to_scan)
            if m_year:
                detected_year = m_year.group(1)

    final_dep = detected_dep if detected_dep else curr_dep
    final_year = detected_year if detected_year else curr_year

    return f"{final_dep}-{final_year}"


class PochoirRasterDialog(QDialog):
    """Boîte de dialogue moderne et intuitive avec 2 onglets autonomes : Découpe unitaire & Tri de dalles."""

    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.current_worker = None

        self.setWindowTitle("RasterCutter - Découpe de Raster")
        self.setMinimumWidth(660)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._setup_ui()
        self._apply_styles()
        self._restore_settings()
        self._connect_signals()

    def _setup_ui(self):
        """Construit l'ensemble des composants de l'interface en 2 onglets."""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(14, 14, 14, 12)

        # 1. En-tête visuel
        header_frame = QFrame()
        header_frame.setObjectName("headerFrame")
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(10, 8, 10, 8)

        icon_label = QLabel()
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        if os.path.exists(icon_path):
            pix = QPixmap(icon_path).scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_label.setPixmap(pix)
        header_layout.addWidget(icon_label)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)
        title_lbl = QLabel("RASTERCUTTER")
        title_lbl.setObjectName("titleLabel")
        subtitle_lbl = QLabel("Découpe de raster par masque & Tri spatial de dalles")
        subtitle_lbl.setObjectName("subtitleLabel")
        title_layout.addWidget(title_lbl)
        title_layout.addWidget(subtitle_lbl)
        header_layout.addLayout(title_layout)
        header_layout.addStretch()

        main_layout.addWidget(header_frame)

        # 2. Système d'onglets principaux
        self.tab_widget = QTabWidget()
        self.tab_cut = QWidget()
        self.tab_filter = QWidget()

        self.tab_widget.addTab(self.tab_cut, "1. Découper au pochoir")
        self.tab_widget.addTab(self.tab_filter, "2. Trier un dossier de dalles")
        self.tab_widget.setTabToolTip(0, "Découper un raster selon l'emprise d'un masque vectoriel (pochoir)")
        self.tab_widget.setTabToolTip(1, "Filtrer et copier des dalles raster selon un masque (AutoCAD / Serveur)")
        main_layout.addWidget(self.tab_widget)

        # Construction du contenu des 2 onglets
        self._setup_tab_cut()
        self._setup_tab_filter()

    def _setup_tab_cut(self):
        """Construit l'onglet 1 : Découpage unitaire au pochoir."""
        cut_layout = QVBoxLayout(self.tab_cut)
        cut_layout.setSpacing(10)
        cut_layout.setContentsMargins(12, 12, 12, 10)

        # Groupe 1 : Couche Raster Source
        raster_group = QGroupBox("1. Couche Raster Source")
        raster_layout = QVBoxLayout(raster_group)
        raster_layout.setSpacing(6)

        raster_row = QHBoxLayout()
        self.combo_raster = QgsMapLayerComboBox()
        self.combo_raster.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.combo_raster.setAllowEmptyLayer(True)
        self.combo_raster.setLayer(None)
        raster_row.addWidget(self.combo_raster, 1)

        self.btn_browse_raster = QPushButton("Parcourir fichier...")
        self.btn_browse_raster.setToolTip("Sélectionner un fichier raster local")
        raster_row.addWidget(self.btn_browse_raster)
        raster_layout.addLayout(raster_row)

        # Panneau options de zoom (affiché pour flux distants WMS/WMTS/XYZ ou export MBTiles)
        self.frame_zoom = QFrame()
        self.frame_zoom.setObjectName("zoomFrame")
        zoom_vlayout = QVBoxLayout(self.frame_zoom)
        zoom_vlayout.setContentsMargins(8, 6, 8, 6)
        zoom_vlayout.setSpacing(4)

        self.lbl_zoom_info = QLabel("Plage de niveaux de zoom :")
        zoom_vlayout.addWidget(self.lbl_zoom_info)

        zoom_spin_row = QHBoxLayout()
        self.lbl_zoom_min = QLabel("Zoom min :")
        zoom_spin_row.addWidget(self.lbl_zoom_min)
        self.spin_zoom_min = QSpinBox()
        self.spin_zoom_min.setRange(0, 24)
        self.spin_zoom_min.setValue(10)
        zoom_spin_row.addWidget(self.spin_zoom_min)

        zoom_spin_row.addSpacing(16)
        self.lbl_zoom_max = QLabel("Zoom max :")
        zoom_spin_row.addWidget(self.lbl_zoom_max)
        self.spin_zoom_max = QSpinBox()
        self.spin_zoom_max.setRange(0, 24)
        self.spin_zoom_max.setValue(18)
        zoom_spin_row.addWidget(self.spin_zoom_max)

        self.lbl_zoom_res = QLabel("")
        self.lbl_zoom_res.setStyleSheet("color: #475569; font-style: italic;")
        zoom_spin_row.addWidget(self.lbl_zoom_res)

        self.lbl_detected_zooms = QLabel("")
        zoom_spin_row.addWidget(self.lbl_detected_zooms)
        zoom_spin_row.addStretch()

        zoom_vlayout.addLayout(zoom_spin_row)
        self.frame_zoom.hide()
        raster_layout.addWidget(self.frame_zoom)

        cut_layout.addWidget(raster_group)

        # Groupe 2 : Pochoir Vectoriel
        pochoir_group = QGroupBox("2. Masque vectoriel")
        pochoir_layout = QVBoxLayout(pochoir_group)
        pochoir_layout.setSpacing(6)

        pochoir_row = QHBoxLayout()
        self.combo_pochoir = QgsMapLayerComboBox()
        self.combo_pochoir.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.combo_pochoir.setAllowEmptyLayer(True)
        self.combo_pochoir.setLayer(None)
        pochoir_row.addWidget(self.combo_pochoir, 1)

        self.btn_browse_pochoir = QPushButton("Parcourir fichier...")
        self.btn_browse_pochoir.setToolTip("Sélectionner un fichier vecteur")
        pochoir_row.addWidget(self.btn_browse_pochoir)
        pochoir_layout.addLayout(pochoir_row)

        self.chk_filter = QCheckBox("Appliquer le filtre actif de la couche")
        self.chk_filter.setChecked(True)
        pochoir_layout.addWidget(self.chk_filter)

        self.chk_selected_only = QCheckBox("Découper uniquement sur la sélection (0 sélectionnée)")
        self.chk_selected_only.setChecked(False)
        self.chk_selected_only.setEnabled(False)
        pochoir_layout.addWidget(self.chk_selected_only)

        self.lbl_pochoir_info = QLabel("")
        pochoir_layout.addWidget(self.lbl_pochoir_info)

        cut_layout.addWidget(pochoir_group)

        # Groupe 3 : Destination & Format de sortie
        dest_group = QGroupBox("3. Destination & Format de sortie")
        dest_layout = QVBoxLayout(dest_group)
        dest_layout.setSpacing(6)

        format_row = QHBoxLayout()
        format_lbl = QLabel("Format :")
        format_lbl.setStyleSheet("font-weight: bold;")
        format_row.addWidget(format_lbl)

        self.radio_jp2 = QRadioButton("JPEG 2000 AutoCAD (.jp2 + .tab / .j2w)")
        self.radio_geotiff = QRadioButton("GeoTIFF (.tif)")
        self.radio_mbtiles = QRadioButton("MBTiles (.mbtiles)")
        self.radio_geotiff.setChecked(True)

        self.btn_group_format = QButtonGroup(self)
        self.btn_group_format.addButton(self.radio_geotiff)
        self.btn_group_format.addButton(self.radio_jp2)
        self.btn_group_format.addButton(self.radio_mbtiles)

        format_row.addWidget(self.radio_geotiff)
        format_row.addWidget(self.radio_jp2)
        format_row.addWidget(self.radio_mbtiles)
        format_row.addStretch()
        dest_layout.addLayout(format_row)

        opts_row = QHBoxLayout()
        self.chk_white_bg = QCheckBox("Fond blanc opaque")
        self.chk_white_bg.setToolTip("Remplit l'extérieur du masque en blanc au lieu de transparent.")
        opts_row.addWidget(self.chk_white_bg)

        self.chk_autocad_tfw = QCheckBox("Générer un fichier de calage (.tfw)")
        self.chk_autocad_tfw.setChecked(True)
        self.chk_autocad_tfw.setToolTip("Génère un fichier de calage .tfw associé au GeoTIFF.")
        opts_row.addWidget(self.chk_autocad_tfw)
        opts_row.addStretch()
        dest_layout.addLayout(opts_row)

        # Options spécifiques au carrelage JPEG 2000 AutoCAD
        self.grp_jp2_options = QGroupBox("Carrelage en dalles JPEG 2000")
        jp2_opts_layout = QVBoxLayout(self.grp_jp2_options)
        jp2_opts_layout.setSpacing(6)

        row_grid = QHBoxLayout()
        row_grid.addWidget(QLabel("Taille des dalles :"))
        self.combo_grid_size = QComboBox()
        self.combo_grid_size.addItem("5 km × 5 km (standard)", 5000)
        self.combo_grid_size.addItem("2 km × 2 km", 2000)
        self.combo_grid_size.addItem("1 km × 1 km", 1000)
        row_grid.addWidget(self.combo_grid_size, 1)

        row_grid.addWidget(QLabel("Préfixe des dalles :"))
        self.txt_tile_prefix = QLineEdit("21-2024")
        self.txt_tile_prefix.setMaximumWidth(120)
        self.txt_tile_prefix.setToolTip("Préfixe appliqué aux noms de dalles (ex : 21-2024)")
        row_grid.addWidget(self.txt_tile_prefix)
        jp2_opts_layout.addLayout(row_grid)

        row_reprise = QHBoxLayout()
        self.chk_skip_existing = QCheckBox("Ignorer les dalles existantes")
        self.chk_skip_existing.setChecked(True)
        self.chk_skip_existing.setToolTip("Ne recalcule pas les dalles (.jp2, .tab, .j2w) déjà présentes dans le dossier.")
        row_reprise.addWidget(self.chk_skip_existing)
        row_reprise.addStretch()
        jp2_opts_layout.addLayout(row_reprise)

        self.lbl_tile_estimate = QLabel("Estimation : <i>Calcul en cours...</i>")
        self.lbl_tile_estimate.setStyleSheet("color: #0f766e; font-weight: bold;")
        jp2_opts_layout.addWidget(self.lbl_tile_estimate)

        self.grp_jp2_options.hide()
        dest_layout.addWidget(self.grp_jp2_options)

        dest_mode_layout = QHBoxLayout()
        self.radio_temp = QRadioButton("Couche temporaire en mémoire")
        self.radio_file = QRadioButton("Enregistrer dans un fichier")
        self.radio_temp.setChecked(True)
        self.btn_group_dest = QButtonGroup(self)
        self.btn_group_dest.addButton(self.radio_temp)
        self.btn_group_dest.addButton(self.radio_file)
        dest_mode_layout.addWidget(self.radio_temp)
        dest_mode_layout.addWidget(self.radio_file)
        dest_mode_layout.addStretch()
        dest_layout.addLayout(dest_mode_layout)

        file_row = QHBoxLayout()
        self.txt_output_file = QLineEdit()
        self.txt_output_file.setPlaceholderText("Chemin du fichier de sortie...")
        self.txt_output_file.setEnabled(False)
        file_row.addWidget(self.txt_output_file, 1)

        self.btn_browse_output = QPushButton("Enregistrer sous...")
        self.btn_browse_output.setEnabled(False)
        file_row.addWidget(self.btn_browse_output)
        dest_layout.addLayout(file_row)

        cut_layout.addWidget(dest_group)

        # Actions & Progression de l'onglet 1
        action_row = QHBoxLayout()
        self.btn_run = QPushButton("Lancer le découpage")
        self.btn_run.setObjectName("btnRun")
        self.btn_run.setStyleSheet("font-weight: bold; padding: 6px 14px; background-color: #0f766e; color: white;")
        self.btn_cancel = QPushButton("Fermer")
        action_row.addStretch()
        action_row.addWidget(self.btn_run)
        action_row.addWidget(self.btn_cancel)
        cut_layout.addLayout(action_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        cut_layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("")
        cut_layout.addWidget(self.lbl_status)

    def _setup_tab_filter(self):
        """Construit l'onglet 2 : Tri spatial de dalles de serveur."""
        filter_layout = QVBoxLayout(self.tab_filter)
        filter_layout.setSpacing(10)
        filter_layout.setContentsMargins(12, 12, 12, 10)

        # 1. Dossier source
        grp_src = QGroupBox("1. Dossier source des dalles")
        l_src = QHBoxLayout(grp_src)
        self.txt_source_dir = QLineEdit()
        self.txt_source_dir.setPlaceholderText("Dossier contenant les dalles raster...")
        self.btn_browse_source_dir = QPushButton("Parcourir dossier...")
        self.btn_browse_source_dir.clicked.connect(self._browse_source_dir)
        l_src.addWidget(self.txt_source_dir, 1)
        l_src.addWidget(self.btn_browse_source_dir)
        filter_layout.addWidget(grp_src)

        # 2. Pochoir vectoriel
        grp_mask = QGroupBox("2. Masque vectoriel")
        l_mask = QHBoxLayout(grp_mask)
        self.combo_pochoir_filter = QgsMapLayerComboBox()
        self.combo_pochoir_filter.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.combo_pochoir_filter.setAllowEmptyLayer(True)
        self.combo_pochoir_filter.setLayer(None)
        self.btn_browse_mask_file = QPushButton("Parcourir fichier...")
        self.btn_browse_mask_file.clicked.connect(self._browse_mask_file)
        l_mask.addWidget(self.combo_pochoir_filter, 1)
        l_mask.addWidget(self.btn_browse_mask_file)
        filter_layout.addWidget(grp_mask)

        # 3. Dossier de destination distinct
        grp_dst = QGroupBox("3. Dossier de destination")
        l_dst = QHBoxLayout(grp_dst)
        self.txt_dest_dir = QLineEdit()
        self.txt_dest_dir.setPlaceholderText("Dossier de destination des dalles sélectionnées...")
        self.btn_browse_dest_dir = QPushButton("Parcourir dossier...")
        self.btn_browse_dest_dir.clicked.connect(self._browse_dest_dir)
        l_dst.addWidget(self.txt_dest_dir, 1)
        l_dst.addWidget(self.btn_browse_dest_dir)
        filter_layout.addWidget(grp_dst)

        # 4. Paramètres
        grp_params = QGroupBox("4. Options de traitement")
        l_params = QVBoxLayout(grp_params)
        row_buf = QHBoxLayout()
        row_buf.addWidget(QLabel("Zone tampon (mètres) :"))
        self.spin_buffer_filter = QSpinBox()
        self.spin_buffer_filter.setRange(0, 50000)
        self.spin_buffer_filter.setValue(0)
        self.spin_buffer_filter.setSuffix(" m")
        row_buf.addWidget(self.spin_buffer_filter)
        row_buf.addStretch()
        l_params.addLayout(row_buf)

        self.chk_dry_run_filter = QCheckBox("Simulation seule (aucun fichier copié)")
        l_params.addWidget(self.chk_dry_run_filter)
        filter_layout.addWidget(grp_params)

        # Actions & Progression de l'onglet 2
        action_row = QHBoxLayout()
        self.btn_run_filter = QPushButton("Lancer le tri spatial")
        self.btn_run_filter.setStyleSheet("font-weight: bold; padding: 6px 14px; background-color: #0f766e; color: white;")
        self.btn_run_filter.clicked.connect(self._run_filter_tab)
        self.btn_cancel_filter = QPushButton("Fermer")
        self.btn_cancel_filter.clicked.connect(self.close)
        action_row.addStretch()
        action_row.addWidget(self.btn_run_filter)
        action_row.addWidget(self.btn_cancel_filter)
        filter_layout.addLayout(action_row)

        self.progress_bar_filter = QProgressBar()
        self.progress_bar_filter.setRange(0, 100)
        self.progress_bar_filter.setValue(0)
        self.progress_bar_filter.hide()
        filter_layout.addWidget(self.progress_bar_filter)

        self.lbl_status_filter = QLabel("")
        filter_layout.addWidget(self.lbl_status_filter)

    def _apply_styles(self):
        """Applique une feuille de style sobre et harmonieuse."""
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                margin-top: 6px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            #headerFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0f766e, stop:1 #115e59);
                border-radius: 6px;
            }
            #titleLabel {
                color: #ffffff;
                font-size: 15px;
                font-weight: bold;
                letter-spacing: 1px;
            }
            #subtitleLabel {
                color: #99f6e4;
                font-size: 11px;
            }
            QTabWidget::pane {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                background: #fafafa;
            }
            QTabBar::tab {
                font-weight: bold;
                padding: 6px 12px;
                border: 1px solid #cbd5e1;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                background: #f1f5f9;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                border-bottom: 2px solid #0f766e;
                color: #0f766e;
            }
        """)

    def _restore_settings(self):
        """Restaure les préférences utilisateur via QgsSettings."""
        settings = QgsSettings()
        saved_fmt = settings.value("RasterCutter/output_format", "geotiff")
        if saved_fmt == "jp2":
            self.radio_jp2.setChecked(True)
        elif saved_fmt == "mbtiles":
            self.radio_mbtiles.setChecked(True)
        else:
            self.radio_geotiff.setChecked(True)
        self._on_format_changed()

    def _connect_signals(self):
        """Connecte l'ensemble des signaux et slots Qt."""
        self.combo_raster.layerChanged.connect(self._on_raster_layer_changed)
        self.combo_pochoir.layerChanged.connect(self._on_pochoir_layer_changed)

        self.btn_browse_raster.clicked.connect(self._on_browse_raster)
        self.btn_browse_pochoir.clicked.connect(self._on_browse_pochoir)

        self.radio_temp.toggled.connect(self._on_dest_mode_changed)
        self.radio_file.toggled.connect(self._on_dest_mode_changed)
        self.btn_browse_output.clicked.connect(self._on_browse_output)

        self.radio_geotiff.toggled.connect(self._on_format_changed)
        self.radio_jp2.toggled.connect(self._on_format_changed)
        self.radio_mbtiles.toggled.connect(self._on_format_changed)

        self.combo_grid_size.currentIndexChanged.connect(self._update_tile_estimate)
        self.txt_tile_prefix.textChanged.connect(self._update_tile_estimate)
        self.chk_filter.toggled.connect(self._update_tile_estimate)
        self.chk_selected_only.toggled.connect(self._update_tile_estimate)

        self.spin_zoom_min.valueChanged.connect(self._on_zoom_min_changed)
        self.spin_zoom_max.valueChanged.connect(self._on_zoom_max_changed)

        self.btn_run.clicked.connect(self.run_clipping)
        self.btn_cancel.clicked.connect(self._on_btn_cancel_clicked)

        # Initialiser l'état selon les couches déjà présentes
        self._on_raster_layer_changed(self.combo_raster.currentLayer())
        self._on_pochoir_layer_changed(self.combo_pochoir.currentLayer())

    def _on_zoom_min_changed(self, val):
        if self.radio_mbtiles.isChecked() and val > self.spin_zoom_max.value():
            self.spin_zoom_max.setValue(val)

    def _on_zoom_max_changed(self, val):
        if self.radio_mbtiles.isChecked() and val < self.spin_zoom_min.value():
            self.spin_zoom_min.setValue(val)
        self._update_zoom_resolution_label()
        self._update_tile_estimate()

    def _update_zoom_resolution_label(self):
        """Met à jour l'affichage de la résolution au sol en mètres ou cm."""
        if not hasattr(self, "lbl_zoom_res") or not hasattr(self, "spin_zoom_max"):
            return
        z = self.spin_zoom_max.value()
        if z > 0:
            res_m = 156543.03392 / (2 ** z)
            if res_m >= 1.0:
                txt = f"≈ {res_m:.1f} m/pixel"
            else:
                txt = f"≈ {res_m * 100:.0f} cm/pixel"
            self.lbl_zoom_res.setText(f"({txt})")
        else:
            self.lbl_zoom_res.setText("")

    def _on_format_changed(self):
        """Ajuste les options de sortie selon le format choisi et sauvegarde la préférence."""
        is_mbtiles = self.radio_mbtiles.isChecked()
        is_jp2 = self.radio_jp2.isChecked()

        # Persistance du choix
        fmt_code = "mbtiles" if is_mbtiles else "jp2" if is_jp2 else "geotiff"
        QgsSettings().setValue("RasterCutter/output_format", fmt_code)

        # Affichage conditionnel de la case TFW
        self.chk_autocad_tfw.setVisible(not is_mbtiles and not is_jp2)

        if is_jp2:
            self.grp_jp2_options.show()
            self.radio_temp.setText("Dossier temporaire")
            self.radio_file.setText("Enregistrer dans un dossier")
            self.txt_output_file.setPlaceholderText("Dossier de destination des dalles...")
            self.btn_browse_output.setText("Parcourir dossier...")
            self._update_tile_estimate()
        else:
            self.grp_jp2_options.hide()
            self.radio_temp.setText("Couche temporaire en mémoire")
            self.radio_file.setText("Enregistrer dans un fichier")
            self.txt_output_file.setPlaceholderText("Chemin du fichier de sortie...")
            self.btn_browse_output.setText("Enregistrer sous...")

        if is_mbtiles:
            self.radio_file.setChecked(True)
            self.radio_temp.setEnabled(False)
            current_txt = self.txt_output_file.text().strip()
            if current_txt:
                self.txt_output_file.setText(str(Path(current_txt).with_suffix(".mbtiles")))
        elif is_jp2:
            self.radio_temp.setEnabled(True)
        else:
            self.radio_temp.setEnabled(True)
            current_txt = self.txt_output_file.text().strip()
            if current_txt:
                self.txt_output_file.setText(str(Path(current_txt).with_suffix(".tif")))

        self._update_zoom_panel_visibility()

    def _update_tile_estimate(self):
        """Calcule dynamiquement le nombre de dalles estimé pour la grille JP2."""
        if not hasattr(self, "radio_jp2") or not self.radio_jp2.isChecked():
            return
        if not hasattr(self, "combo_pochoir") or not hasattr(self, "lbl_tile_estimate"):
            return

        pochoir_layer = self.combo_pochoir.currentLayer()
        if not pochoir_layer or not pochoir_layer.isValid():
            self.lbl_tile_estimate.setText("Estimation : <i>Sélectionnez une couche de masque</i>")
            return

        try:
            tile_size = self.combo_grid_size.currentData() or 5000
            count = estimate_grid_tiles_count(
                pochoir_layer,
                tile_size_m=tile_size,
                apply_filter=self.chk_filter.isChecked(),
                selected_only=self.chk_selected_only.isChecked(),
            )
            km = tile_size // 1000
            if count == -1:
                self.lbl_tile_estimate.setText(
                    "<b>Estimation :</b> <span style='color: #b91c1c;'>&gt; 1 000 dalles (veuillez filtrer ou sélectionner une entité)</span>"
                )
            elif count == -2:
                self.lbl_tile_estimate.setText(
                    "<b>Estimation :</b> <span style='color: #b45309;'>Flux distant WFS &gt; 50 dalles (veuillez filtrer ou sélectionner une entité)</span>"
                )
            else:
                z = self.spin_zoom_max.value() if hasattr(self, "spin_zoom_max") else 16
                res_m = 156543.03392 / (2 ** z) if z > 0 else 2.38
                w_px = tile_size / max(res_m, 0.01)
                mb_per_tile = max(0.1, (w_px * w_px * 0.45) / (1024 * 1024))
                est_mb = round(count * mb_per_tile)
                self.lbl_tile_estimate.setText(
                    f"<b>Estimation :</b> {count} dalle(s) de {km} km × {km} km (volume estimé ~{est_mb} Mo, soit ~{mb_per_tile:.1f} Mo/dalle au zoom {z})"
                )
        except Exception:
            self.lbl_tile_estimate.setText("Estimation : <i>Calcul impossible</i>")

    def _update_zoom_panel_visibility(self, layer=None):
        """Affiche ou masque le panneau de zoom selon la nature de la couche et le format."""
        raster_layer = layer or self.combo_raster.currentLayer()
        is_remote = False
        if raster_layer:
            provider = raster_layer.providerType().lower()
            is_remote = provider in ["wms", "wmts", "xyz", "wcs", "arcgismapserver", "arcgistileserver"]

        is_mbtiles = self.radio_mbtiles.isChecked()
        show_zoom = is_remote or is_mbtiles

        if show_zoom:
            self.frame_zoom.show()
            zoom_info = {}
            if raster_layer:
                try:
                    zoom_info = detect_raster_zoom_levels(raster_layer)
                    if zoom_info.get("zoom_levels"):
                        z_min = zoom_info.get("min_zoom", 6)
                        z_max = zoom_info.get("max_zoom", 16)
                        self.spin_zoom_min.setRange(z_min, z_max)
                        self.spin_zoom_max.setRange(z_min, z_max)
                        self.spin_zoom_min.setValue(z_min)
                        self.spin_zoom_max.setValue(z_max)
                        self.spin_zoom_min.setEnabled(True)
                        self.spin_zoom_max.setEnabled(True)
                        self.lbl_detected_zooms.setText(f"<i>(Détecté : {z_min} à {z_max})</i>")
                    else:
                        self.spin_zoom_min.setRange(0, 24)
                        self.spin_zoom_max.setRange(0, 24)
                        self.lbl_detected_zooms.setText("")
                except Exception:
                    pass

            if is_mbtiles:
                self.lbl_zoom_min.show()
                self.spin_zoom_min.show()
                self.lbl_zoom_max.setText("Zoom max :")
                self.lbl_zoom_res.hide()
            else:
                self.lbl_zoom_min.hide()
                self.spin_zoom_min.hide()
                self.lbl_zoom_max.setText("Niveau de zoom cible :")
                self.lbl_zoom_res.show()

            if zoom_info.get("label"):
                self.lbl_zoom_info.setText(zoom_info["label"])

            self._update_zoom_resolution_label()
        else:
            self.frame_zoom.hide()

    def _on_dest_mode_changed(self):
        is_file = self.radio_file.isChecked()
        self.txt_output_file.setEnabled(is_file)
        self.btn_browse_output.setEnabled(is_file)

    def _on_raster_layer_changed(self, layer):
        self._update_zoom_panel_visibility(layer)
        self._auto_detect_prefix_from_raster(layer)

    def _auto_detect_prefix_from_raster(self, layer):
        """Met à jour le préfixe de nommage des dalles depuis les métadonnées et nom du raster."""
        if not layer or not layer.isValid():
            return
        name = layer.name() or ""
        source = layer.source() or ""
        metadata_text = ""
        try:
            meta = layer.metadata()
            if meta:
                metadata_text = f"{meta.abstract()} {meta.title()} {meta.identifier()}"
        except Exception:
            pass

        current_prefix = self.txt_tile_prefix.text().strip()
        new_prefix = extract_prefix_from_raster_source(name, f"{source} {metadata_text}", current_prefix)
        if new_prefix and new_prefix != current_prefix:
            self.txt_tile_prefix.setText(new_prefix)

    def _on_pochoir_layer_changed(self, layer):
        if not layer or not layer.isValid():
            self.lbl_pochoir_info.setText("Aucune couche pochoir valide sélectionnée.")
            self.chk_selected_only.setEnabled(False)
            self.chk_selected_only.setChecked(False)
            return

        info_parts = [f"Type : {layer.geometryType()}"]
        subset = layer.subsetString()
        if subset:
            info_parts.append(f"Filtre actif : \"{subset}\"")
            self.chk_filter.setText(f"Appliquer le filtre actif (\"{subset}\")")
        else:
            self.chk_filter.setText("Appliquer le filtre actif")

        sel_count = layer.selectedFeatureCount()
        if sel_count > 0:
            self.chk_selected_only.setEnabled(True)
            self.chk_selected_only.setText(f"Découper uniquement sur la sélection ({sel_count} entité(s))")
            self.chk_selected_only.setChecked(True)
            info_parts.append(f"{sel_count} sélectionnée(s)")
        else:
            self.chk_selected_only.setEnabled(False)
            self.chk_selected_only.setChecked(False)
            self.chk_selected_only.setText("Découper uniquement sur la sélection (0 sélectionnée)")

        self.lbl_pochoir_info.setText(" | ".join(info_parts))
        self._update_tile_estimate()

        try:
            layer.selectionChanged.disconnect(self._on_selection_changed)
        except Exception:
            pass
        layer.selectionChanged.connect(self._on_selection_changed)

    def _on_selection_changed(self):
        layer = self.combo_pochoir.currentLayer()
        if layer and layer.isValid():
            self._on_pochoir_layer_changed(layer)
        else:
            self._update_tile_estimate()

    def _on_browse_raster(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Sélectionner un raster sur le poste",
            "",
            "Images Raster (*.tif *.tiff *.jp2 *.ecw *.img *.vrt *.png *.jpg *.mbtiles);;Tous les fichiers (*.*)",
        )
        if file_path:
            name = QFileInfo(file_path).baseName()
            if file_path.lower().endswith(".mbtiles"):
                new_layer = QgsRasterLayer(f"type=mbtiles&url={file_path}", name, "wms")
                if not new_layer.isValid():
                    new_layer = QgsRasterLayer(file_path, name)
            else:
                new_layer = QgsRasterLayer(file_path, name)

            if new_layer.isValid():
                QgsProject.instance().addMapLayer(new_layer)
                self.combo_raster.setLayer(new_layer)
            else:
                QMessageBox.warning(self, "Erreur", f"Impossible d'ouvrir le raster :\n{file_path}")

    def _on_browse_pochoir(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Sélectionner une couche pochoir (polygones)",
            "",
            "Couches Vecteur (*.gpkg *.shp *.geojson *.kml *.tab);;Tous les fichiers (*.*)",
        )
        if file_path:
            name = QFileInfo(file_path).baseName()
            new_layer = QgsVectorLayer(file_path, name, "ogr")
            if new_layer.isValid():
                QgsProject.instance().addMapLayer(new_layer)
                self.combo_pochoir.setLayer(new_layer)
            else:
                QMessageBox.warning(self, "Erreur", f"Impossible d'ouvrir la couche pochoir :\n{file_path}")

    def _on_browse_output(self):
        if self.radio_jp2.isChecked():
            folder_path = QFileDialog.getExistingDirectory(
                self,
                "Sélectionner le dossier de destination des dalles JPEG 2000",
                self.txt_output_file.text() or "",
            )
            if folder_path:
                self.txt_output_file.setText(folder_path)
            return

        if self.radio_mbtiles.isChecked():
            ext = "mbtiles"
            filter_str = "Tuiles MBTiles (*.mbtiles)"
        else:
            ext = "tif"
            filter_str = "Image GeoTIFF (*.tif)"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Enregistrer le raster découpé sous",
            self.txt_output_file.text() or f"decoupe.{ext}",
            f"{filter_str};;Tous les fichiers (*.*)",
        )
        if file_path:
            if not file_path.lower().endswith(f".{ext}"):
                file_path += f".{ext}"
            self.txt_output_file.setText(file_path)

    def get_configuration(self):
        """Récupère et valide l'ensemble des paramètres de l'onglet de découpe."""
        raster_layer = self.combo_raster.currentLayer()
        if not raster_layer or not raster_layer.isValid():
            raise ValueError("Veuillez sélectionner une couche raster valide.")

        pochoir_layer = self.combo_pochoir.currentLayer()
        if not pochoir_layer or not pochoir_layer.isValid():
            raise ValueError("Veuillez sélectionner une couche pochoir valide.")

        is_mbtiles = self.radio_mbtiles.isChecked()
        is_jp2 = self.radio_jp2.isChecked()
        is_temp = self.radio_temp.isChecked() and not is_mbtiles
        output_file = self.txt_output_file.text().strip() if not is_temp else ""

        if not is_temp and not output_file:
            msg = "Veuillez spécifier le dossier de destination des dalles ou choisir 'Dossier temporaire'." if is_jp2 else "Veuillez spécifier le fichier de destination ou choisir 'Couche temporaire'."
            raise ValueError(msg)

        tile_size = self.combo_grid_size.currentData() if is_jp2 else 5000
        tile_prefix = self.txt_tile_prefix.text().strip() if is_jp2 else "21-2024"
        skip_existing = self.chk_skip_existing.isChecked() if is_jp2 else True

        return {
            "raster_layer": raster_layer,
            "pochoir_layer": pochoir_layer,
            "is_mbtiles": is_mbtiles,
            "is_jp2": is_jp2,
            "is_temp": is_temp,
            "output_path": output_file,
            "apply_filter": self.chk_filter.isChecked(),
            "selected_only": self.chk_selected_only.isChecked(),
            "white_background": self.chk_white_bg.isChecked(),
            "autocad_tfw": self.chk_autocad_tfw.isChecked(),
            "zoom_min": self.spin_zoom_min.value(),
            "zoom_max": self.spin_zoom_max.value(),
            "tile_size": tile_size,
            "tile_prefix": tile_prefix,
            "skip_existing": skip_existing,
        }

    def run_clipping(self):
        """Lance l'opération de découpage asynchrone avec garde-fou de taille."""
        try:
            config = self.get_configuration()
        except ValueError as err:
            QMessageBox.warning(self, "Paramètre manquant", str(err))
            return

        # Alerte préventive pour JP2 (> 50 dalles) ou pour GeoTIFF (> 16 000 px)
        if config.get("is_jp2"):
            est_count = estimate_grid_tiles_count(
                config["pochoir_layer"],
                tile_size_m=config["tile_size"],
                apply_filter=config["apply_filter"],
                selected_only=config["selected_only"],
            )
            if est_count == -1:
                QMessageBox.warning(
                    self,
                    "Emprise trop vaste",
                    "L'emprise dépasse 1 000 dalles.\n"
                    "Filtrez la couche ou sélectionnez une entité.",
                )
                return
            if est_count == -2:
                QMessageBox.warning(
                    self,
                    "Emprise WFS trop vaste",
                    "L'emprise du flux distant WFS dépasse 50 dalles.\n"
                    "Filtrez la couche ou sélectionnez une entité.",
                )
                return

            pochoir_geom, pochoir_crs = get_pochoir_geometry(
                config["pochoir_layer"],
                apply_filter=config["apply_filter"],
                selected_only=config["selected_only"],
            )
            if pochoir_geom:
                tiles = generate_grid_tiles(
                    pochoir_geom=pochoir_geom,
                    tile_size_m=config["tile_size"],
                    prefix=config["tile_prefix"],
                    pochoir_crs=pochoir_crs,
                )
                if len(tiles) > 50:
                    km = config["tile_size"] // 1000
                    reply = QMessageBox.question(
                        self,
                        "Confirmation",
                        f"{len(tiles)} dalles de {km} km × {km} km vont être générées.\n"
                        f"Le calcul peut prendre plusieurs minutes.\n\n"
                        f"Continuer ?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,
                    )
                    if reply != QMessageBox.Yes:
                        return
        elif not config.get("is_mbtiles") and config.get("raster_layer"):
            rlayer = config["raster_layer"]
            player = config["pochoir_layer"]
            extent = player.extent()
            res = rlayer.rasterUnitsPerPixelX() if hasattr(rlayer, "rasterUnitsPerPixelX") and rlayer.rasterUnitsPerPixelX() > 0 else 0.5
            est_w = extent.width() / max(res, 1e-4)
            est_h = extent.height() / max(res, 1e-4)
            if est_w > 16000 or est_h > 16000:
                reply = QMessageBox.question(
                    self,
                    "Grande emprise",
                    "L'emprise dépasse 16 000 pixels. Le format JPEG 2000 en dalles est recommandé pour limiter la charge mémoire.\n\nContinuer en GeoTIFF unique ?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return

        self.btn_run.setEnabled(False)
        self.btn_cancel.setText("Annuler")
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.lbl_status.setText("Découpage en cours...")
        self.lbl_status.setStyleSheet("color: #0f766e; font-weight: bold;")

        self.current_worker = launch_clipping_task(
            config=config,
            iface=self.iface,
            on_progress=self._on_task_progress,
            on_finished=self._on_task_finished,
        )

    def _on_btn_cancel_clicked(self):
        if self.current_worker and hasattr(self.current_worker, "isCanceled") and not self.current_worker.isCanceled():
            self.lbl_status.setText("Annulation en cours...")
            self.lbl_status.setStyleSheet("color: #eab308; font-weight: bold;")
            self.btn_cancel.setText("Fermer")
            self.btn_cancel.setEnabled(True)
            self.current_worker.cancel()
        else:
            self.reject()

    def closeEvent(self, event):
        """Annule toute tâche d'arrière-plan en cours si la fenêtre est fermée."""
        if self.current_worker and hasattr(self.current_worker, "isCanceled") and not self.current_worker.isCanceled():
            try:
                self.current_worker.cancel()
            except Exception:
                pass
        super().closeEvent(event)

    def _on_task_progress(self, progress_pct, message):
        try:
            self.progress_bar.setValue(int(progress_pct))
            if message:
                self.lbl_status.setText(message)
        except Exception:
            pass

    def _on_task_finished(self, success, message, result_layer=None):
        self.btn_run.setEnabled(True)
        self.btn_cancel.setText("Fermer")
        self.btn_cancel.setEnabled(True)
        self.current_worker = None
        if success:
            self.progress_bar.setValue(100)
            self.lbl_status.setText(message)
            self.lbl_status.setStyleSheet("color: #15803d; font-weight: bold;")
        else:
            self.lbl_status.setText("Erreur : " + message)
            self.lbl_status.setStyleSheet("color: #b91c1c; font-weight: bold;")
            if "annul" not in message.lower():
                QMessageBox.critical(self, "Erreur lors du découpage", message)

    # -------------------------------------------------------------
    # Méthodes de l'onglet 2 : Tri spatial de dalles de serveur
    # -------------------------------------------------------------
    def _browse_source_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Sélectionner le dossier source des dalles")
        if d:
            self.txt_source_dir.setText(d)

    def _browse_mask_file(self):
        f, _ = QFileDialog.getOpenFileName(
            self,
            "Sélectionner le pochoir vectoriel",
            "",
            "Couches Vecteur (*.gpkg *.shp *.geojson);;Tous les fichiers (*.*)",
        )
        if f:
            name = Path(f).stem
            layer = QgsVectorLayer(f, name, "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                self.combo_pochoir_filter.setLayer(layer)

    def _browse_dest_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Sélectionner le dossier de destination distinct")
        if d:
            self.txt_dest_dir.setText(d)

    def _run_filter_tab(self):
        source = self.txt_source_dir.text().strip()
        dest = self.txt_dest_dir.text().strip()
        mask_layer = self.combo_pochoir_filter.currentLayer()

        if not source or not os.path.isdir(source):
            QMessageBox.warning(self, "Dossier manquant", "Veuillez sélectionner un dossier source existant.")
            return

        if not mask_layer or not mask_layer.isValid():
            QMessageBox.warning(self, "Pochoir manquant", "Veuillez sélectionner une couche pochoir vectorielle valide.")
            return

        if not dest:
            QMessageBox.warning(self, "Destination manquante", "Veuillez sélectionner un dossier de destination distinct.")
            return

        if os.path.abspath(source) == os.path.abspath(dest):
            QMessageBox.warning(self, "Sécurité", "Le dossier de destination doit être distinct du dossier source.")
            return

        mask_source = mask_layer.source()
        if "|" in mask_source:
            mask_source = mask_source.split("|")[0]

        self.btn_run_filter.setEnabled(False)
        self.progress_bar_filter.show()
        self.progress_bar_filter.setValue(0)
        self.lbl_status_filter.setText("Démarrage du tri spatial...")

        def update_progress(pct, msg):
            self.progress_bar_filter.setValue(pct)
            self.lbl_status_filter.setText(msg)
            QgsApplication.processEvents()

        try:
            stats = filter_and_copy_tiles(
                source_dir=Path(source),
                dest_dir=Path(dest),
                mask_path=Path(mask_source),
                buffer_m=float(self.spin_buffer_filter.value()),
                dry_run=self.chk_dry_run_filter.isChecked(),
                progress_callback=update_progress,
            )

            msg = (
                f"Tri terminé.\n\n"
                f"• Dalles analysées : {stats['total_rasters']}\n"
                f"• Dalles conservées : {stats['kept_count']}\n"
                f"• Dalles exclues   : {stats['excluded_count']}\n"
                f"• Volume conservé  : {stats['total_kept_mb']} Mo\n"
                f"• Espace économisé : {stats['total_saved_mb']} Mo ({stats['saved_percent']} %)"
            )

            if not self.chk_dry_run_filter.isChecked():
                shp_path = Path(dest) / "tableau_assemblage_bva.shp"
                if shp_path.exists():
                    tbl_layer = QgsVectorLayer(str(shp_path), "Tableau d'assemblage BVA", "ogr")
                    if tbl_layer.isValid():
                        QgsProject.instance().addMapLayer(tbl_layer)

            QMessageBox.information(self, "Bilan du filtrage", msg)
            self.lbl_status_filter.setText("Tri terminé.")
        except Exception as err:
            QMessageBox.critical(self, "Erreur lors du filtrage", str(err))
            self.lbl_status_filter.setText("Erreur lors du tri.")
        finally:
            self.btn_run_filter.setEnabled(True)


class FilterDallesDialog(QDialog):
    """Boîte de dialogue autonome pour le tri spatial de dalles (accès direct via menu)."""

    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Tri spatial de dalles raster (Serveur / AutoCAD)")
        self.setMinimumWidth(560)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 14)

        grp_src = QGroupBox("1. Dossier source des dalles")
        l_src = QHBoxLayout(grp_src)
        self.txt_source = QLineEdit()
        self.txt_source.setPlaceholderText("Dossier contenant les dalles raster...")
        self.btn_browse_src = QPushButton("Parcourir...")
        self.btn_browse_src.clicked.connect(self._browse_source)
        l_src.addWidget(self.txt_source, 1)
        l_src.addWidget(self.btn_browse_src)
        layout.addWidget(grp_src)

        grp_mask = QGroupBox("2. Masque vectoriel")
        l_mask = QHBoxLayout(grp_mask)
        self.combo_mask = QgsMapLayerComboBox()
        self.combo_mask.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.btn_browse_mask = QPushButton("Parcourir fichier...")
        self.btn_browse_mask.clicked.connect(self._browse_mask)
        l_mask.addWidget(self.combo_mask, 1)
        l_mask.addWidget(self.btn_browse_mask)
        layout.addWidget(grp_mask)

        grp_dst = QGroupBox("3. Dossier de destination")
        l_dst = QHBoxLayout(grp_dst)
        self.txt_dest = QLineEdit()
        self.txt_dest.setPlaceholderText("Dossier de destination des dalles sélectionnées...")
        self.btn_browse_dst = QPushButton("Parcourir...")
        self.btn_browse_dst.clicked.connect(self._browse_dest)
        l_dst.addWidget(self.txt_dest, 1)
        l_dst.addWidget(self.btn_browse_dst)
        layout.addWidget(grp_dst)

        grp_params = QGroupBox("4. Options de traitement")
        l_params = QVBoxLayout(grp_params)
        row_buf = QHBoxLayout()
        row_buf.addWidget(QLabel("Zone tampon (mètres) :"))
        self.spin_buffer = QSpinBox()
        self.spin_buffer.setRange(0, 50000)
        self.spin_buffer.setValue(0)
        self.spin_buffer.setSuffix(" m")
        row_buf.addWidget(self.spin_buffer)
        row_buf.addStretch()
        l_params.addLayout(row_buf)

        self.chk_dry_run = QCheckBox("Simulation seule (aucun fichier copié)")
        l_params.addWidget(self.chk_dry_run)
        layout.addWidget(grp_params)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("")
        layout.addWidget(self.lbl_status)

        btn_box = QHBoxLayout()
        self.btn_run = QPushButton("Lancer le tri spatial")
        self.btn_run.setStyleSheet("font-weight: bold; padding: 6px 14px; background-color: #0f766e; color: white;")
        self.btn_run.clicked.connect(self._run_filter)
        self.btn_close = QPushButton("Fermer")
        self.btn_close.clicked.connect(self.close)
        btn_box.addStretch()
        btn_box.addWidget(self.btn_run)
        btn_box.addWidget(self.btn_close)
        layout.addLayout(btn_box)

    def _browse_source(self):
        d = QFileDialog.getExistingDirectory(self, "Sélectionner le dossier source des dalles")
        if d:
            self.txt_source.setText(d)

    def _browse_mask(self):
        f, _ = QFileDialog.getOpenFileName(
            self,
            "Sélectionner le pochoir vectoriel",
            "",
            "Couches Vecteur (*.gpkg *.shp *.geojson);;Tous les fichiers (*.*)",
        )
        if f:
            name = Path(f).stem
            layer = QgsVectorLayer(f, name, "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                self.combo_mask.setLayer(layer)

    def _browse_dest(self):
        d = QFileDialog.getExistingDirectory(self, "Sélectionner le dossier de destination distinct")
        if d:
            self.txt_dest.setText(d)

    def _run_filter(self):
        source = self.txt_source.text().strip()
        dest = self.txt_dest.text().strip()
        mask_layer = self.combo_mask.currentLayer()

        if not source or not os.path.isdir(source):
            QMessageBox.warning(self, "Dossier manquant", "Veuillez sélectionner un dossier source existant.")
            return

        if not mask_layer or not mask_layer.isValid():
            QMessageBox.warning(self, "Pochoir manquant", "Veuillez sélectionner une couche pochoir vectorielle valide.")
            return

        if not dest:
            QMessageBox.warning(self, "Destination manquante", "Veuillez sélectionner un dossier de destination distinct.")
            return

        if os.path.abspath(source) == os.path.abspath(dest):
            QMessageBox.warning(self, "Sécurité", "Le dossier de destination doit être distinct du dossier source.")
            return

        mask_source = mask_layer.source()
        if "|" in mask_source:
            mask_source = mask_source.split("|")[0]

        self.btn_run.setEnabled(False)
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Démarrage du tri spatial...")

        def update_progress(pct, msg):
            self.progress_bar.setValue(pct)
            self.lbl_status.setText(msg)
            QgsApplication.processEvents()

        try:
            stats = filter_and_copy_tiles(
                source_dir=Path(source),
                dest_dir=Path(dest),
                mask_path=Path(mask_source),
                buffer_m=float(self.spin_buffer.value()),
                dry_run=self.chk_dry_run.isChecked(),
                progress_callback=update_progress,
            )

            msg = (
                f"Tri terminé.\n\n"
                f"• Dalles analysées : {stats['total_rasters']}\n"
                f"• Dalles conservées : {stats['kept_count']}\n"
                f"• Dalles exclues   : {stats['excluded_count']}\n"
                f"• Volume conservé  : {stats['total_kept_mb']} Mo\n"
                f"• Espace économisé : {stats['total_saved_mb']} Mo ({stats['saved_percent']} %)"
            )

            if not self.chk_dry_run.isChecked():
                shp_path = Path(dest) / "tableau_assemblage_bva.shp"
                if shp_path.exists():
                    tbl_layer = QgsVectorLayer(str(shp_path), "Tableau d'assemblage BVA", "ogr")
                    if tbl_layer.isValid():
                        QgsProject.instance().addMapLayer(tbl_layer)

            QMessageBox.information(self, "Bilan du filtrage", msg)
            self.lbl_status.setText("Tri terminé.")
        except Exception as err:
            QMessageBox.critical(self, "Erreur lors du filtrage", str(err))
            self.lbl_status.setText("Erreur lors du tri.")
        finally:
            self.btn_run.setEnabled(True)
