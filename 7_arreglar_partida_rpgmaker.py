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
from traductor.texto import corregir_puntuacion_pegada, postprocesar_traduccion

log = logging.getLogger(__name__)

REEMPLAZOS_BRUTOS = {
    "tímida y tímida": "tímida",
    "Desliza un elemento": "Roba un objeto",
    "introducciones de caracteres": "introducción de los personajes",
    "Fallo Janet": "Señorita Janet",
    "Fallo Grey": "Señorita Grey",
    "Fallo Vesper": "Señorita Vesper",
    "Fallo Garner": "Señorita Garner",
    "Fallo Faye": "Señorita Faye",
    "la Fallo Grey": "la señorita Grey",
}


CLAVES_IGNORAR = {
    "system", "_gBtns", "image", "img", "bitmap",
    "characterName", "faceName", "battlerName", "tilesetNames",
    "bgm", "bgs", "me", "se", "audio",
    "filename", "switches", "_switches", "selfSwitches", "_selfSwitches",
    "tone", "color", "textColor", "action", "location",
}

VALORES_IGNORAR = {
    "Skip", "Hide", "ON", "OFF", "True", "False", "true", "false",
    "ok", "cancel", "shift", "up", "down", "left", "right", "map", "menu",
}


def cargar_diccionario(ruta: Path) -> dict[str, str]:
    dic = {}
    if ruta.exists():
        with open(ruta, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
            for row in csv.reader(f, delimiter=";"):
                if len(row) >= 2 and row[0].strip() and row[1].strip():
                    orig = row[0].strip()
                    trad = row[1].strip()
                    # Nunca incorporar al diccionario de partidas valores del sistema o nombres de botón
                    if orig in VALORES_IGNORAR:
                        continue
                    dic[orig] = trad
    return dic


def reparar_cadenas(obj, correcciones: dict[str, str], reemplazos: dict[str, str], clave_padre: str = "") -> int:
    cambios = 0
    if isinstance(obj, dict):
        for k, v in obj.items():
            clave_str = str(k)
            if clave_str in CLAVES_IGNORAR or clave_padre in CLAVES_IGNORAR:
                continue
            # Ignorar objetos de audio (tienen volume, pitch, pan, name)
            if clave_str == "name" and ("volume" in obj or "pitch" in obj or "pan" in obj):
                continue
            if isinstance(v, str):
                if v in VALORES_IGNORAR or v.endswith((".png", ".rpgmvp", ".ogg", ".m4a", ".wav")):
                    continue
                orig = v
                texto = v
                for malo, bueno in reemplazos.items():
                    if malo in texto:
                        texto = texto.replace(malo, bueno)
                texto = postprocesar_traduccion(texto)
                # Separar oraciones pegadas solo en diálogos reales, no en scripts o códigos con etiqueta
                if not texto.startswith("$game") and not ("." in texto and len(texto.split(".")[0]) <= 8 and " " not in texto.split(".")[0]):
                    texto = corregir_puntuacion_pegada(texto)
                # Reemplazo directo o de palabras si coincide con el diccionario
                if texto in correcciones and texto not in VALORES_IGNORAR:
                    texto = correcciones[texto]
                if texto != orig:
                    obj[k] = texto
                    cambios += 1
            else:
                cambios += reparar_cadenas(v, correcciones, reemplazos, clave_padre=clave_str)
    elif isinstance(obj, list):
        if clave_padre in CLAVES_IGNORAR:
            return 0
        for i in range(len(obj)):
            if isinstance(obj[i], str):
                val = obj[i]
                if val in VALORES_IGNORAR or val.endswith((".png", ".rpgmvp", ".ogg", ".m4a", ".wav")):
                    continue
                orig = val
                texto = val
                for malo, bueno in reemplazos.items():
                    if malo in texto:
                        texto = texto.replace(malo, bueno)
                texto = postprocesar_traduccion(texto)
                if not texto.startswith("$game") and not ("." in texto and len(texto.split(".")[0]) <= 8 and " " not in texto.split(".")[0]):
                    texto = corregir_puntuacion_pegada(texto)
                if texto in correcciones and texto not in VALORES_IGNORAR:
                    texto = correcciones[texto]
                if texto != orig:
                    obj[i] = texto
                    cambios += 1
            else:
                cambios += reparar_cadenas(obj[i], correcciones, reemplazos, clave_padre=clave_padre)
    return cambios


def main():
    parser = argparse.ArgumentParser(description="Reparar textos en partidas guardadas de RPG Maker (.rpgsave).")
    parser.add_argument("--ruta", help="Ruta principal del juego (busca automáticamente www/save o save)")
    parser.add_argument("--save-dir", help="Ruta a la carpeta con archivos .rpgsave")
    parser.add_argument("--diccionario", default=str(config.DICCIONARIO_INTERFAZ), help="Ruta al diccionario CSV de correcciones")
    parser.add_argument("--debug", action="store_true", help="Mostrar logs detallados de depuración")
    args = parser.parse_args()

    configurar_logging(detallado=args.debug)

    if lzstring is None:
        log.error("La librería 'lzstring' no está instalada. Ejecuta: pip install lzstring")
        sys.exit(1)

    save_dir = None
    if args.save_dir:
        save_dir = Path(args.save_dir)
    elif args.ruta:
        r_juego = Path(args.ruta)
        candidatos = [
            r_juego / "www" / "save",
            r_juego / "save",
            r_juego / "www" / "saves",
            r_juego / "saves",
        ]
        if os.name == "nt":
            appdata_local = Path(os.environ.get("LOCALAPPDATA", ""))
            if appdata_local.exists():
                candidatos.extend([
                    appdata_local / "User Data",
                    appdata_local / "User Data" / "Default",
                    appdata_local / r_juego.name / "save",
                    appdata_local / r_juego.name,
                    appdata_local / config.slug(r_juego.name) / "save",
                    appdata_local / config.slug(r_juego.name),
                ])
        # Primero buscar una carpeta que realmente contenga archivos .rpgsave
        for c in candidatos:
            if c.exists() and list(c.glob("*.rpgsave")):
                save_dir = c
                break
        # Si ninguna tiene .rpgsave pero existe la carpeta de guardado
        if not save_dir:
            for c in candidatos:
                if c.exists():
                    save_dir = c
                    break

    if not save_dir or not save_dir.exists():
        print(f"\n{'='*70}")
        print("ℹ️  [INFORMACIÓN DE PARTIDAS GUARDADAS (.rpgsave)]")
        print(f"{'='*70}")
        print("No se encontró ninguna carpeta de partidas guardadas ('save/' o 'www/save/').")
        print("• Si aún no has guardado ninguna partida dentro del juego, esto es completamente normal.")
        print("• Toda la traducción ya está inyectada en los archivos del juego (Paso 1).")
        print("• Cualquier partida nueva que comiences ya se guardará en español.")
        print("• Si tus partidas están en otra ruta, especifícala con: --save-dir <ruta>")
        print(f"{'='*70}\n")
        return

    archivos = list(save_dir.glob("*.rpgsave"))
    if not archivos:
        print(f"\n{'='*70}")
        print("ℹ️  [INFORMACIÓN DE PARTIDAS GUARDADAS (.rpgsave)]")
        print(f"{'='*70}")
        print(f"La carpeta '{save_dir.name}' existe, pero no contiene archivos .rpgsave.")
        print("• Aún no has guardado ninguna partida en este juego.")
        print("• Las nuevas partidas que inicies ya saldrán traducidas al 100%.")
        print(f"{'='*70}\n")
        return

    # Obtener el título traducido del juego desde System.json para sincronizar los títulos de los slots
    titulo_juego_actual = None
    if args.ruta:
        for pj in [Path(args.ruta) / "www" / "data" / "System.json", Path(args.ruta) / "data" / "System.json"]:
            if pj.exists():
                try:
                    with open(pj, "r", encoding="utf-8") as f:
                        titulo_juego_actual = json.load(f).get("gameTitle")
                    break
                except Exception:
                    pass

    path_dic = Path(args.diccionario)
    correcciones = cargar_diccionario(path_dic)
    log.info("Diccionario cargado con %d entradas desde %s", len(correcciones), path_dic.name)

    compresor = lzstring.LZString()
    log.info("Analizando %d archivo(s) de partida en: %s...", len(archivos), save_dir)
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
            cambios = 0
            # Si es el archivo índice global de partidas (global.rpgsave o Defaultglobal.rpgsave)
            if isinstance(parsed, list):
                if titulo_juego_actual:
                    for slot in parsed:
                        if isinstance(slot, dict) and "title" in slot:
                            if slot["title"] != titulo_juego_actual:
                                slot["title"] = titulo_juego_actual
                                cambios += 1
            else:
                cambios = reparar_cadenas(parsed, correcciones, REEMPLAZOS_BRUTOS)

            if cambios > 0:
                nuevo_json = json.dumps(parsed, separators=(",", ":"))
                comprimido = compresor.compressToBase64(nuevo_json)
                f_path.write_text(comprimido, encoding="utf-8")
                log.info("✔ %s sincronizado con éxito (%d ajustes aplicados).", f_path.name, cambios)
            else:
                log.info("  %s no requería cambios.", f_path.name)
        except Exception as e:
            log.error("Error al procesar JSON en %s: %s", f_path.name, e)


if __name__ == "__main__":
    main()
