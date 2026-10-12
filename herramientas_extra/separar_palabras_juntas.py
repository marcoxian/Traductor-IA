"""herramientas_extra/separar_palabras_juntas.py — Reparador automático de oraciones pegadas sin espacio.

Detecta y repara en caliente en todos los archivos JSON de RPG Maker MV/MZ las frases que
quedaron unidas tras signos de puntuación (ej: 'examen.Si' -> 'examen. Si', 'progreso.¿Te gusta?' -> 'progreso. ¿Te gusta?'),
preservando intactos los prefijos de sprite de motor (ej: 'HeFrOp.', 'Br,fr,op.') y las llamadas a código JS.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Asegurar que el paquete traductor sea importable desde herramientas_extra
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Asegurar UTF-8 en Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from traductor import config
from traductor.motores.rpgmaker import PATRON_SET_VALUE_21
from traductor.registro import configurar_logging
from traductor.texto import PATRON_PREFIJO_V21, corregir_puntuacion_pegada

log = logging.getLogger(__name__)


def reparar_objeto(obj) -> int:
    """Recorre recursivamente un objeto o lista JSON y desune oraciones con puntuación pegada."""
    cambios = 0
    if isinstance(obj, dict):
        # Code 355: Diálogos en scripts setValue(21, "...")
        if obj.get("code") == 355 and obj.get("parameters") and isinstance(obj["parameters"][0], str):
            script = obj["parameters"][0]
            m = PATRON_SET_VALUE_21.search(script)
            if m:
                contenido = m.group(2)
                m_pref = PATRON_PREFIJO_V21.match(contenido)
                if m_pref:
                    prefijo = m_pref.group(1) + "."
                    dialogo = m_pref.group(2)
                else:
                    prefijo = ""
                    dialogo = contenido

                nuevo_dialogo = corregir_puntuacion_pegada(dialogo)
                if nuevo_dialogo != dialogo:
                    nuevo_script = (
                        script[:m.start()] +
                        m.group(1) + prefijo + nuevo_dialogo + m.group(3) +
                        script[m.end():]
                    )
                    obj["parameters"][0] = nuevo_script
                    cambios += 1

        # Code 401: Diálogos de ventana estándar
        elif obj.get("code") == 401 and obj.get("parameters") and isinstance(obj["parameters"][0], str):
            orig = obj["parameters"][0]
            corr = corregir_puntuacion_pegada(orig)
            if corr != orig:
                obj["parameters"][0] = corr
                cambios += 1

        # Code 102: Opciones de diálogo presentadas al jugador
        elif obj.get("code") == 102 and obj.get("parameters") and isinstance(obj["parameters"][0], list):
            opciones = obj["parameters"][0]
            for idx in range(len(opciones)):
                if isinstance(opciones[idx], str):
                    orig = opciones[idx]
                    corr = corregir_puntuacion_pegada(orig)
                    if corr != orig:
                        opciones[idx] = corr
                        cambios += 1

        # Campos de texto típicos en base de datos (Actors, Items, Skills, etc.)
        for k, v in obj.items():
            if k in ("name", "description", "message1", "message2", "message3", "nickname") and isinstance(v, str):
                corr = corregir_puntuacion_pegada(v)
                if corr != v:
                    obj[k] = corr
                    cambios += 1
            else:
                cambios += reparar_objeto(v)

    elif isinstance(obj, list):
        for item in obj:
            cambios += reparar_objeto(item)

    return cambios


def reparar_carpeta_datos(data_dir: Path) -> tuple[int, int]:
    """Repara todos los archivos JSON dentro de data_dir."""
    if not data_dir.exists():
        log.error("No existe el directorio de datos: %s", data_dir)
        return 0, 0

    archivos_modificados = 0
    total_reparaciones = 0

    for json_file in sorted(data_dir.glob("*.json")):
        if json_file.name.endswith(".bak"):
            continue
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                datos = json.load(f)
        except Exception as e:
            log.warning("No se pudo leer %s: %s", json_file.name, e)
            continue

        c = reparar_objeto(datos)
        if c > 0:
            try:
                with open(json_file, "w", encoding="utf-8") as f:
                    json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
                archivos_modificados += 1
                total_reparaciones += c
                log.info("✔ %s: %d oraciones/palabras juntas separadas con éxito.", json_file.name, c)
            except Exception as e:
                log.error("Error al guardar %s: %s", json_file.name, e)

    return archivos_modificados, total_reparaciones


def main():
    parser = argparse.ArgumentParser(description="Separar palabras u oraciones pegadas en juegos de RPG Maker.")
    parser.add_argument("--ruta", help="Ruta principal del juego (o carpeta www/data)")
    parser.add_argument("--debug", action="store_true", help="Mostrar logs detallados de depuración")
    args = parser.parse_args()

    configurar_logging(detallado=args.debug)

    ruta_str = args.ruta
    if not ruta_str:
        ruta_str = r"J:\SteamLibrary\steamapps\common\Treasure of Nadia"

    p = Path(ruta_str)
    data_dir = None
    if (p / "www" / "data").exists():
        data_dir = p / "www" / "data"
    elif (p / "data").exists():
        data_dir = p / "data"
    elif p.name == "data" and p.exists():
        data_dir = p

    if not data_dir:
        log.error("No se encontró la carpeta 'data' o 'www/data' en: %s", p)
        sys.exit(1)

    print(f"\n{'='*70}")
    print(f"🔧 [REPARADOR DE PALABRAS Y ORACIONES JUNTAS]")
    print(f"Buscando en: {data_dir}")
    print(f"{'='*70}\n")

    archivos, total = reparar_carpeta_datos(data_dir)

    print(f"\n{'='*70}")
    print(f"✔ [ÉXITO] Proceso completado.")
    print(f"• Archivos modificados: {archivos}")
    print(f"• Total de frases/palabras despegadas: {total}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
