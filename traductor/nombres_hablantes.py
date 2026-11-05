"""Nombres de quien habla en las cajas de nombre (\\N<\\C[n]Nombre\\C[0]>).

Tabla ``workspace/<juego>/nombres_hablantes.csv`` (o ``nombres_hablantes_<juego>.csv``) con columnas
``ingles;correccion`` y lista de nombres propios ``workspace/<juego>/nombres_propios.txt`` (uno por línea) que
se dejan tal cual. La usan el Paso 5 (juego ya traducido) y el motor CSV al traducir.
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path


def cargar_tabla(ruta: Path | None) -> dict[str, str]:
    if not ruta or not ruta.exists():
        return {}
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        return {
            r["ingles"].strip(): r["correccion"].strip()
            for r in csv.DictReader(f, delimiter=";")
            if r.get("ingles") and r.get("correccion")
        }


def cargar_nombres_propios(ruta_archivo: Path | None) -> set[str]:
    nombres = set()
    if ruta_archivo and ruta_archivo.exists():
        for linea in ruta_archivo.read_text(encoding="utf-8-sig").splitlines():
            nombre = linea.strip()
            if nombre and not nombre.startswith("#"):
                nombres.add(nombre)
    return nombres


def ruta_tabla(carpeta_ws: Path, juego: str | None) -> Path | None:
    for nombre in ("nombres_hablantes.csv", f"nombres_hablantes_{juego}.csv" if juego else None):
        if nombre and (carpeta_ws / nombre).exists():
            return carpeta_ws / nombre
    return None


@lru_cache(maxsize=8)
def tabla_del_juego(juego: str | None) -> tuple[dict[str, str], frozenset[str]]:
    """(tabla, nombres propios) de ``workspace/<juego>/``; vacíos si el juego no tiene."""
    if not juego:
        return {}, frozenset()
    from . import config
    carpeta = config.carpeta_juego(juego)
    return cargar_tabla(ruta_tabla(carpeta, juego)), frozenset(cargar_nombres_propios(carpeta / "nombres_propios.txt"))


def traducir_nombre(nombre: str, tabla: dict[str, str], propios: set[str] | frozenset[str]) -> str | None:
    """'Man' -> 'Hombre' (tabla); 'Aldo' -> 'Aldo' (propio); 'Guard A' -> 'Guardia A'; None si no se sabe."""
    n = nombre.strip()
    if n in tabla:
        return tabla[n]
    if n in propios:
        return n
    if n.endswith("（？）"):
        t = traducir_nombre(n[:-3], tabla, propios)
        return f"{t}（？）" if t else None
    for sep in ("＆", " & "):
        if sep in n:
            partes = [traducir_nombre(p, tabla, propios) for p in n.split(sep)]
            return None if None in partes else " y ".join(partes)
    m = re.match(r"^(.+?)['’]s Voice$", n)
    if m and m.group(1) in propios:
        return f"Voz de {m.group(1)}"
    m = re.match(r"^(.+?) ?([A-Z])$", n)
    if m and m.group(1) in tabla:
        return f"{tabla[m.group(1)]} {m.group(2)}"
    return None
