"""reanudar_traduccion.py — Utilidad para procesar mapas y archivos específicos pendientes."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Reanuda la traducción para una lista de archivos seleccionados.")
    parser.add_argument("--ruta", required=True, help="Ruta principal del juego")
    parser.add_argument("--archivos", nargs="+", help="Archivos específicos a traducir (ej. Map008.json States.json)")
    args = parser.parse_args()

    ruta_juego = Path(args.ruta)
    script_traductor = Path(__file__).resolve().parent.parent / "1_traducir_juego.py"

    archivos_objetivo = args.archivos or [
        "MapInfos.json", "States.json", "Tilesets.json", "Troops.json"
    ] + [f"Map{i:03d}.json" for i in range(8, 35)]

    for filename in archivos_objetivo:
        print(f"\n>>> Procesando {filename}...")
        cmd = [sys.executable, str(script_traductor), "--ruta", str(ruta_juego), "--archivo", filename, "--modo", "turbo"]
        subprocess.run(cmd)


if __name__ == "__main__":
    main()
