"""7_arreglar_partida_rpgmaker.py — Parcheador en caliente de partidas .rpgsave.

Descomprime partidas guardadas de RPG Maker (formato LZ-String),
aplica los reemplazos del diccionario y correcciones semánticas,
y vuelve a comprimir la partida para probar cambios al instante sin reiniciar.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import shutil
import sys
from pathlib import Path

try:
    import lzstring
except ImportError:
    lzstring = None

from traductor import config
from traductor.registro import configurar_logging

log = logging.getLogger(__name__)

REEMPLAZOS_BRUTOS = {
    "tímida y tímida": "tímida",
    "Desliza un elemento": "Roba un objeto",
    "introducciones de caracteres": "introducción de los personajes",
}


def cargar_diccionario(ruta: Path) -> dict[str, str]:
    dic = {}
    if ruta.exists():
        with open(ruta, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
            for row in csv.reader(f, delimiter=";"):
                if len(row) >= 2 and row[0].strip() and row[1].strip():
                    dic[row[0].strip()] = row[1].strip()
    return dic


def reparar_cadenas(obj, correcciones: dict[str, str], reemplazos: dict[str, str]) -> int:
    cambios = 0
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                orig = v
                texto = v
                for malo, bueno in reemplazos.items():
                    if malo in texto:
                        texto = texto.replace(malo, bueno)
                # Reemplazo directo o de palabras si coincide con el diccionario
                if texto in correcciones:
                    texto = correcciones[texto]
                if texto != orig:
                    obj[k] = texto
                    cambios += 1
            else:
                cambios += reparar_cadenas(v, correcciones, reemplazos)
    elif isinstance(obj, list):
        for i in range(len(obj)):
            if isinstance(obj[i], str):
                orig = obj[i]
                texto = obj[i]
                for malo, bueno in reemplazos.items():
                    if malo in texto:
                        texto = texto.replace(malo, bueno)
                if texto in correcciones:
                    texto = correcciones[texto]
                if texto != orig:
                    obj[i] = texto
                    cambios += 1
            else:
                cambios += reparar_cadenas(obj[i], correcciones, reemplazos)
    return cambios


def main():
    parser = argparse.ArgumentParser(description="Reparar textos en partidas guardadas de RPG Maker (.rpgsave).")
    parser.add_argument("--ruta", help="Ruta principal del juego (busca automáticamente www/save o save)")
    parser.add_argument("--save-dir", help="Ruta a la carpeta con archivos .rpgsave")
    parser.add_argument("--diccionario", default=str(config.DICCIONARIO_INTERFAZ), help="Ruta al diccionario CSV de correcciones")
    args = parser.parse_args()

    configurar_logging()

    if lzstring is None:
        log.error("La librería 'lzstring' no está instalada. Ejecuta: pip install lzstring")
        sys.exit(1)

    save_dir = None
    if args.save_dir:
        save_dir = Path(args.save_dir)
    elif args.ruta:
        r_juego = Path(args.ruta)
        candidatos = [r_juego / "www" / "save", r_juego / "save"]
        for c in candidatos:
            if c.exists():
                save_dir = c
                break

    if not save_dir or not save_dir.exists():
        log.error("Directorio de guardado no encontrado. Especifica --ruta o --save-dir")
        sys.exit(1)

    path_dic = Path(args.diccionario)
    correcciones = cargar_diccionario(path_dic)
    log.info("Diccionario cargado con %d entradas desde %s", len(correcciones), path_dic.name)

    compresor = lzstring.LZString()
    archivos = list(save_dir.glob("*.rpgsave"))
    if not archivos:
        log.warning("No se encontraron archivos .rpgsave en %s", save_dir)
        return

    log.info("Analizando %d partida(s) guardada(s)...", len(archivos))
    for f_path in archivos:
        backup = f_path.with_suffix(".rpgsave.bak")
        if not backup.exists():
            shutil.copy2(f_path, backup)

        data = f_path.read_text(encoding="utf-8", errors="ignore")
        descomprimido = compresor.decompressFromBase64(data)
        if not descomprimido:
            log.warning("No se pudo descomprimir %s (posible archivo dañado o formato no LZ-String).", f_path.name)
            continue

        try:
            parsed = json.loads(descomprimido)
            cambios = reparar_cadenas(parsed, correcciones, REEMPLAZOS_BRUTOS)
            if cambios > 0:
                nuevo_json = json.dumps(parsed, separators=(",", ":"))
                comprimido = compresor.compressToBase64(nuevo_json)
                f_path.write_text(comprimido, encoding="utf-8")
                log.info("✔ %s parcheado con éxito (%d reemplazos aplicados).", f_path.name, cambios)
            else:
                log.info("  %s no requería cambios.", f_path.name)
        except Exception as e:
            log.error("Error al procesar JSON en %s: %s", f_path.name, e)


if __name__ == "__main__":
    main()
