# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Pochoir Raster - Plugin Principal
                                 A QGIS plugin
 Découpe universelle de raster par emporte-pièce vectoriel
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
from qgis.PyQt.QtCore import QCoreApplication, QObject
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction


class PochoirRasterPlugin:
    """Classe principale du plugin QGIS Pochoir Raster."""

    def __init__(self, iface):
        """Constructeur.

        :param iface: Référence à l'interface QGIS.
        :type iface: QgsInterface
        """
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = "&Pochoir Raster"
        self.dialog = None

    def tr(self, message):
        """Traduction de chaîne."""
        return QCoreApplication.translate("PochoirRaster", message)

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None,
    ):
        """Ajoute une action à l'interface QGIS."""
        if not isinstance(parent, QObject):
            parent = None
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)
        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar and self.iface:
            self.iface.addToolBarIcon(action)
            self.iface.addRasterToolBarIcon(action)

        if add_to_menu and self.iface:
            self.iface.addPluginToMenu(self.tr("&RasterCutter"), action)
            self.iface.addPluginToRasterMenu(self.tr("&RasterCutter"), action)

        self.actions.append(action)
        return action

    def initGui(self):
        """Initialise l'interface graphique du plugin (icônes et menus QGIS)."""
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        self.action = self.add_action(
            icon_path=icon_path,
            text=self.tr("RasterCutter - Découpe de raster par masque"),
            callback=self.run,
            parent=self.iface.mainWindow() if self.iface else None,
        )
        self.action_filter = self.add_action(
            icon_path=icon_path,
            text=self.tr("RasterCutter - Tri spatial de dalles"),
            callback=self.run_filter_dalles,
            add_to_toolbar=False,
            parent=self.iface.mainWindow() if self.iface else None,
        )

    def run_filter_dalles(self):
        """Ouvre directement l'interface de tri spatial de dalles."""
        from .pochoir_raster_dialog import FilterDallesDialog
        parent = self.iface.mainWindow() if self.iface else None
        dlg = FilterDallesDialog(iface=self.iface, parent=parent)
        dlg.exec_()

    def unload(self):
        """Décharge le plugin et nettoie les menus et barres d'outils."""
        for action in self.actions:
            if self.iface:
                self.iface.removePluginMenu(self.tr("&RasterCutter"), action)
                self.iface.removePluginRasterMenu(self.tr("&RasterCutter"), action)
                self.iface.removeToolBarIcon(action)
                self.iface.removeRasterToolBarIcon(action)
        self.actions.clear()

        if self.dialog:
            try:
                self.dialog.close()
            except Exception:
                pass
            self.dialog = None

    def _on_dialog_destroyed(self):
        """Réinitialise la référence lorsque la boîte de dialogue est détruite."""
        self.dialog = None

    def run(self):
        """Ouvre la boîte de dialogue principale du plugin."""
        from .pochoir_raster_dialog import PochoirRasterDialog

        if self.dialog is None:
            parent = self.iface.mainWindow() if self.iface else None
            self.dialog = PochoirRasterDialog(iface=self.iface, parent=parent)
            self.dialog.destroyed.connect(self._on_dialog_destroyed)

        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
