#!/usr/bin/env bash
#
# Richtet die Dokumentations-Umgebung fuer Sphinx ein.
#
# Voraussetzungen: python3 (mit venv), Internetzugang zu PyPI.
# Das System-Python ist PEP-668-geschuetzt ("externally managed"), deshalb wird
# eine projektlokale virtuelle Umgebung unter .venv/ verwendet.
#
# Aufruf:  ./sphinx/setup-docs-env.sh
#
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"
PYTHON="${VENV:-python3}"

echo "==> Virtuelle Umgebung: ${VENV_DIR}"
if [ ! -d "${VENV_DIR}" ]; then
    # --without-pip, da manche Minimal-Images kein ensurepip mitbringen
    "${PYTHON}" -m venv --without-pip "${VENV_DIR}"
    # pip nachtraeglich einrichten
    curl -sSL -o /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py
    "${VENV_DIR}/bin/python" /tmp/get-pip.py -q
    rm -f /tmp/get-pip.py
fi

echo "==> Sphinx und Projekterweiterungen installieren"
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install \
    sphinx \
    autodocsumm \
    rinohtype \
    sphinx-book-theme

echo "==> Laufzeitabhaengigkeiten der App (fuer autodoc)"
if [ -f "${PROJECT_ROOT}/skill/requirements-docker.txt" ]; then
    "${VENV_DIR}/bin/pip" install -r "${PROJECT_ROOT}/skill/requirements-docker.txt"
fi
"${VENV_DIR}/bin/pip" install python-dotenv

echo "==> Fertig. Build starten mit:"
echo "    cd ${PROJECT_ROOT}/sphinx"
echo "    PATH=${VENV_DIR}/bin:\$PATH make html"
