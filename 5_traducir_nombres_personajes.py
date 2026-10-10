"""5_traducir_nombres_personajes.py — Homogeneización de nombres de hablantes en diálogos.

Traduce los nombres de quien habla en los diálogos (\\N<\\C[n]Nombre\\C[0]>)
utilizando una tabla de equivalencias (ingles;correccion) y protegiendo los nombres propios.
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

from traductor import config
from traductor.csv_locales import escribir_lineas, leer_lineas
from traductor.registro import configurar_logging
from traductor.texto import PATRON_NOMBRE_HABLANTE


def cargar_tabla(ruta: Path) -> dict[str, str]:
    if not ruta.exists():
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


def traducir_nombre(nombre: str, tabla: dict[str, str], propios: set[str]) -> str | None:
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


def main():
    ap = argparse.ArgumentParser(description="Traduce nombres de hablantes en diálogos.")
    ap.add_argument("--ruta", required=True, help="Carpeta del juego")
    ap.add_argument("--juego", help="Nombre del juego en workspace/<juego>/")
    ap.add_argument("--tabla", help="Ruta al archivo CSV con correspondencias 'ingles;correccion'")
    ap.add_argument("--propios", help="Archivo .txt con un nombre propio por línea para no traducir")
    ap.add_argument("--simular", action="store_true", help="Solo muestra lo que cambiaría sin escribir en disco")
    args = ap.parse_args()

    configurar_logging()
    ruta_juego = Path(args.ruta)
    nombre_juego = config.resolver_juego(args.juego, ruta_juego)
    carpeta_ws = config.carpeta_juego(nombre_juego)

    # 1. Localizar tabla de hablantes
    tabla_path = None
    if args.tabla:
        tabla_path = Path(args.tabla)
    elif (carpeta_ws / "nombres_hablantes.csv").exists():
        tabla_path = carpeta_ws / "nombres_hablantes.csv"
    elif (carpeta_ws / f"nombres_hablantes_{nombre_juego}.csv").exists():
        tabla_path = carpeta_ws / f"nombres_hablantes_{nombre_juego}.csv"
    elif Path("nombres_hablantes_hills.csv").exists():
        tabla_path = Path("nombres_hablantes_hills.csv")

    tabla = cargar_tabla(tabla_path) if tabla_path else {}
    print(f"Tabla de hablantes cargada ({len(tabla)} equivalencias): {tabla_path}")

    # 2. Localizar nombres propios protegidos
    propios_path = Path(args.propios) if args.propios else (carpeta_ws / "nombres_propios.txt")
    propios = cargar_nombres_propios(propios_path)
    if not propios:
        # Añadir al menos los nombres protegidos del perfil
        perfil = config.cargar_perfil(nombre_juego)
        propios.update(perfil.nombres_protegidos.keys())
    print(f"Nombres propios protegidos: {len(propios)}")

    for original in ruta_juego.glob("**/*.csv.original"):
        destino = original.with_name(original.name[:-len(".original")])
        bom, lines = leer_lineas(destino)
        _, orig = leer_lineas(original)
        if len(lines) != len(orig):
            print(f"AVISO: {destino.name} no coincide en líneas con el original. Se omite.")
            continue

        cambios, sin_traducir = Counter(), Counter()
        for i in range(1, len(orig)):
            o_parts = orig[i].rstrip("\r").split(";")
            c_parts = lines[i].rstrip("\r").split(";")
            if len(o_parts) < 2 or len(c_parts) != len(o_parts):
                continue

            mo = PATRON_NOMBRE_HABLANTE.match(o_parts[1])
            mc = PATRON_NOMBRE_HABLANTE.match(c_parts[1])
            if not mo or not mc:
                continue

            nombre_orig = mo.group(2)
            nuevo = traducir_nombre(nombre_orig, tabla, propios)
            if nuevo is None:
                sin_traducir[nombre_orig] += 1
                continue

            nuevo = nuevo.replace(";", ",").replace('"', "'")
            c_in = mc.group(1) or ""
            c_out = mc.group(3) or ""
            if mc.group(2) != nuevo:
                c_parts[1] = f"\\N<{c_in}{nuevo}{c_out}>{c_parts[1][mc.end():]}"
                lines[i] = ";".join(c_parts) + ("\r" if lines[i].endswith("\r") else "")
                cambios[f"{nombre_orig} -> {nuevo}"] += 1

        print(f"{destino.name}: {sum(cambios.values())} líneas actualizadas ({len(cambios)} nombres distintos).")
        if sin_traducir:
            print("  Nombres sin traducir (conservados igual):", dict(sin_traducir.most_common(10)))

        if args.simular:
            for k, v in cambios.most_common(10):
                print(f"  [SIMULACIÓN] {v:5d}  {k}")
            continue

        escribir_lineas(destino, bom, lines)


if __name__ == "__main__":
    main()
