"""4_aplicar_parches.py — Aplicación de revisiones y diccionarios al juego.

Aplica la hoja de revisión (revision_<juego>.csv) o diccionarios CSV de términos
al juego, actualizando directamente las columnas traducidas.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from traductor.csv_locales import (analizar_cabecera, escribir_lineas, leer_lineas,
                                  limpiar_celda, partir, unir)
from traductor.registro import configurar_logging

PROBLEMAS_RESETEABLES = {"ETIQUETAS", "ORDEN", "INGLES", "LONGITUD"}


def aplicar_diccionarios(ruta_juego: Path, rutas_dic: list[str]) -> None:
    dic: dict[str, str] = {}
    for r_str in rutas_dic:
        r = Path(r_str)
        if not r.exists():
            print(f"Aviso: Diccionario {r} no encontrado, se omite.")
            continue
        with open(r, encoding="utf-8-sig", newline="") as f:
            for fila in csv.DictReader(f, delimiter=";"):
                en = (fila.get("ingles") or "").strip()
                es = (fila.get("correccion") or "").strip()
                if en and es:
                    dic[en] = es
    print(f"Diccionario cargado con {len(dic)} entradas.")

    for original in ruta_juego.glob("**/*.csv.original"):
        destino = original.with_name(original.name[:-len(".original")])
        bom, lines = leer_lineas(destino)
        _, orig = leer_lineas(original)
        if len(lines) != len(orig):
            print(f"AVISO: {destino.name} no coincide en líneas con el original. Se omite.")
            continue

        delim, header, col = analizar_cabecera(orig)
        if col is None:
            col = 1

        cambios = 0
        for i in range(1, len(orig)):
            o_partes, _ = partir(orig[i], delim)
            if len(o_partes) <= col:
                continue
            en = o_partes[col]
            clave = en.strip()
            if clave not in dic:
                continue

            inicio = en[:len(en) - len(en.lstrip())]
            fin = en[len(en.rstrip()):]
            partes, cr = partir(lines[i], delim)
            nuevo = inicio + limpiar_celda(dic[clave], delim, quitar_comillas=True) + fin
            if partes[col] != nuevo:
                partes[col] = nuevo
                lines[i] = unir(partes, delim, cr)
                cambios += 1

        escribir_lineas(destino, bom, lines)
        print(f"{destino.name}: {cambios} líneas actualizadas con el diccionario.")


def main():
    ap = argparse.ArgumentParser(description="Aplica hojas de revisión o diccionarios al juego.")
    ap.add_argument("--ruta", required=True, help="Carpeta del juego")
    ap.add_argument("--revision", help="Hoja generada por 2_generar_revision.py")
    ap.add_argument("--diccionario", nargs="+", help="Archivos 'ingles;correccion' a aplicar")
    ap.add_argument("--resetear", action="store_true",
                    help="Devolver al inglés las líneas con fallos no corregidas, para retraducirlas")
    ap.add_argument("--debug", action="store_true", help="Mostrar logs detallados de depuración")
    args = ap.parse_args()

    configurar_logging(detallado=args.debug)
    ruta_juego = Path(args.ruta)

    if not args.revision and not args.diccionario:
        ap.error("Indica --revision y/o --diccionario")

    if args.diccionario:
        aplicar_diccionarios(ruta_juego, args.diccionario)

    if not args.revision:
        return

    rev_path = Path(args.revision)
    if not rev_path.exists():
        ap.error(f"El archivo de revisión no existe: {rev_path}")

    with open(rev_path, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f, delimiter=";"))

    por_archivo: dict[str, list[dict]] = {}
    for fila in filas:
        por_archivo.setdefault(fila["archivo"], []).append(fila)

    for nombre, filas_archivo in por_archivo.items():
        destino = next(ruta_juego.glob(f"**/{nombre}"), None)
        if destino is None or not destino.with_name(nombre + ".original").exists():
            print(f"AVISO: No se encuentra {nombre} (o su .original). Se omite.")
            continue

        bom, lines = leer_lineas(destino)
        _, orig = leer_lineas(destino.with_name(nombre + ".original"))
        delim, header, col = analizar_cabecera(orig)
        if col is None:
            col = 1

        corregidas = reseteadas = saltadas = 0
        for fila in filas_archivo:
            i = int(fila["linea"])
            if i >= len(lines) or i >= len(orig):
                saltadas += 1
                continue

            partes, cr = partir(lines[i], delim)
            o_partes, _ = partir(orig[i], delim)

            if len(partes) <= col or len(o_partes) <= col:
                saltadas += 1
                continue

            if partes[0] != fila["tag"] or o_partes[col] != fila["ingles"]:
                saltadas += 1
                continue

            correccion = (fila.get("correccion") or "").strip()
            if correccion:
                partes[col] = limpiar_celda(correccion, delim, quitar_comillas=True)
                corregidas += 1
            elif args.resetear and PROBLEMAS_RESETEABLES & set(fila.get("problema", "").split(",")):
                partes[col] = o_partes[col]
                reseteadas += 1
            else:
                continue

            lines[i] = unir(partes, delim, cr)

        escribir_lineas(destino, bom, lines)
        print(f"{nombre}: {corregidas} corregidas a mano | {reseteadas} devueltas al inglés para retraducir | {saltadas} omitidas")


if __name__ == "__main__":
    main()
