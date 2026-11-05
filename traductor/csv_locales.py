"""Lectura/escritura de CSV de localización tipo DKTools_Localization / Godot.

Se trabaja línea a línea partiendo por '\\n' (igual que el plugin, que NO interpreta comillas),
respetando el BOM y los '\\r' originales. Lo usan los pasos 1, 2, 4 y 5.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

BOM = b"\xef\xbb\xbf"
NOMBRES_COLUMNA_INGLES = ("en", "english", "en_us", "en-us")
SUFIJO_ORIGINAL = ".original"


def leer_lineas(ruta: Path) -> tuple[bool, list[str]]:
    """Devuelve (tenía_bom, líneas)."""
    crudo = ruta.read_bytes()
    bom = crudo.startswith(BOM)
    return bom, crudo.decode("utf-8-sig").split("\n")


def escribir_lineas(ruta: Path, bom: bool, lineas: list[str]) -> None:
    """Escritura atómica respetando BOM y saltos de línea originales."""
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_bytes((BOM if bom else b"") + "\n".join(lineas).encode("utf-8"))
    os.replace(tmp, ruta)


def detectar_delimitador(cabecera: str) -> str:
    return max((";", ",", "\t"), key=cabecera.count)


def partir(linea: str, delim: str) -> tuple[list[str], str]:
    """'a;b\\r' -> (['a', 'b'], '\\r')."""
    cr = "\r" if linea.endswith("\r") else ""
    return (linea[:-1] if cr else linea).split(delim), cr


def unir(partes: list[str], delim: str, cr: str) -> str:
    return delim.join(partes) + cr


def analizar_cabecera(lineas: list[str]) -> tuple[str, list[str], int | None]:
    """Devuelve (delimitador, cabecera en minúsculas, índice de la columna de inglés o None)."""
    cab = lineas[0].rstrip("\r") if lineas else ""
    delim = detectar_delimitador(cab)
    cabecera = [c.strip().lower() for c in cab.split(delim)]
    col = next((cabecera.index(n) for n in NOMBRES_COLUMNA_INGLES if n in cabecera), None)
    return delim, cabecera, col


def limpiar_celda(texto: str, delim: str, quitar_comillas: bool = True) -> str:
    """El plugin parte por el separador y por saltos de línea sin entender comillas:
    una celda no puede contener ninguno de los dos."""
    texto = texto.replace("\r", " ").replace("\n", " ")
    if quitar_comillas:
        texto = texto.replace('"', "'")
    return texto.replace(delim, "," if delim != "," else ";")


def ruta_original(ruta: Path) -> Path:
    return ruta.with_name(ruta.name + SUFIJO_ORIGINAL)


def pares_traducidos(ruta_juego: Path) -> Iterator[tuple[Path, Path]]:
    """Recorre los CSV ya traducidos: (copia_original_en_inglés, csv_traducido)."""
    for original in sorted(Path(ruta_juego).glob(f"**/*.csv{SUFIJO_ORIGINAL}")):
        traducido = original.with_name(original.name[:-len(SUFIJO_ORIGINAL)])
        if traducido.exists():
            yield original, traducido
