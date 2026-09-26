#!/usr/bin/env bash
# Script d'empaquetage standard pour extension QGIS RasterCutter
# Génère une archive raster_cutter.zip prête pour l'installation manuelle ou le dépôt officiel QGIS.

set -e

PLUGIN_ID="raster_cutter"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_ZIP="${SCRIPT_DIR}/${PLUGIN_ID}.zip"
TEMP_DIR=$(mktemp -d)

trap 'rm -rf "${TEMP_DIR}"' EXIT

echo "--> Préparation du paquet ${PLUGIN_ID}..."
mkdir -p "${TEMP_DIR}/${PLUGIN_ID}"

# Copie des fichiers essentiels du plugin
cp "${SCRIPT_DIR}/__init__.py" "${TEMP_DIR}/${PLUGIN_ID}/"
cp "${SCRIPT_DIR}/metadata.txt" "${TEMP_DIR}/${PLUGIN_ID}/"
cp "${SCRIPT_DIR}/icon.png" "${TEMP_DIR}/${PLUGIN_ID}/"
cp "${SCRIPT_DIR}/LICENSE" "${TEMP_DIR}/${PLUGIN_ID}/"
cp "${SCRIPT_DIR}/README.md" "${TEMP_DIR}/${PLUGIN_ID}/"
cp "${SCRIPT_DIR}/pochoir_raster_plugin.py" "${TEMP_DIR}/${PLUGIN_ID}/"
cp "${SCRIPT_DIR}/pochoir_raster_dialog.py" "${TEMP_DIR}/${PLUGIN_ID}/"
cp "${SCRIPT_DIR}/pochoir_raster_worker.py" "${TEMP_DIR}/${PLUGIN_ID}/"
cp "${SCRIPT_DIR}/dalles_filter.py" "${TEMP_DIR}/${PLUGIN_ID}/"

# Nettoyage des résidus éventuels
find "${TEMP_DIR}/${PLUGIN_ID}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "${TEMP_DIR}/${PLUGIN_ID}" -name "*.pyc" -delete 2>/dev/null || true

# Création de l'archive ZIP
rm -f "${OUTPUT_ZIP}"
(cd "${TEMP_DIR}" && zip -r -9 "${OUTPUT_ZIP}" "${PLUGIN_ID}")

echo "--> Archive générée avec succès : ${OUTPUT_ZIP}"
ls -lh "${OUTPUT_ZIP}"
