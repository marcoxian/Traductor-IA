"""Logging con colores para la consola (también en el CMD de Windows)."""
from __future__ import annotations

import logging
import os
import sys

VERDE = "\033[92m"
AMARILLO = "\033[93m"
AZUL = "\033[94m"
ROJO = "\033[91m"
RESET = "\033[0m"

_COLORES = {logging.WARNING: AMARILLO, logging.ERROR: ROJO, logging.CRITICAL: ROJO}


class _FormatoColor(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        texto = super().format(record)
        color = _COLORES.get(record.levelno)
        return f"{color}{texto}{RESET}" if color else texto


def configurar_logging(detallado: bool = False) -> None:
    """Configura el logging raíz una sola vez.

    - Fuerza UTF-8 en la consola para que las tildes y la ñ no revienten en cp1252.
    - Activa las secuencias de color ANSI en el CMD de Windows.
    """
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if os.name == "nt":
        os.system("")  # habilita el modo VT (colores ANSI) en la consola de Windows

    manejador = logging.StreamHandler(sys.stdout)
    manejador.setFormatter(_FormatoColor("%(asctime)s - %(levelname)s - %(message)s", "%H:%M:%S"))
    raiz = logging.getLogger()
    raiz.handlers[:] = [manejador]
    raiz.setLevel(logging.DEBUG if detallado else logging.INFO)
    # urllib3 es muy ruidoso en DEBUG
    logging.getLogger("urllib3").setLevel(logging.WARNING)
