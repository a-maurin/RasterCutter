# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Pochoir Raster
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


def classFactory(iface):
    """Factory function instantiating the plugin.
    
    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    from .pochoir_raster_plugin import PochoirRasterPlugin

    return PochoirRasterPlugin(iface)
