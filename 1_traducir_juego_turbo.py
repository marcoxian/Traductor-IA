"""1_traducir_juego_turbo.py — Envoltorio retrocompatible para ejecución en modo Turbo.

Ejecuta el traductor configurando el modo 'turbo' (traducción en bloques paralelos/lotes)
utilizando el paquete unificado 'traductor'.
"""
from __future__ import annotations

import sys
from importlib import import_module

# Cargar la función principal de 1_traducir_juego
modulo_traductor = import_module("1_traducir_juego")

if __name__ == "__main__":
    # Si el usuario no especificó --modo, forzar por defecto 'turbo'
    if "--modo" not in sys.argv:
        sys.argv.extend(["--modo", "turbo"])
    modulo_traductor.main(default_mode="turbo")
