"""
Traduce los nombres de quien habla en los diálogos (\\N<\\C[n]Nombre\\C[0]>) del CSV del juego.

  - Usa nombres_hablantes_hills.csv ('ingles;correccion'). Los nombres propios se dejan igual.
  - Entiende variantes: sufijos de letra ("Homeless Man B", "GuardA"), parejas ("Hills＆Reda"),
    "(？)" al final y "X's Voice" con nombre propio ("Voz de Emily").
  - Solo cambia el nombre; el texto del diálogo no se toca.

Uso:
  python traducir_hablantes.py --ruta "J:\\...\\The Adventures of HILLS" [--simular]
"""
import argparse
import csv
import os
import re
from collections import Counter
from pathlib import Path

PRE = re.compile(r"^(\\N<\\C\[\d+\])(.+?)(\\C\[0\]>)")
PROPIOS = {"Hills", "Micoco", "Reda", "Aldora", "Miya", "Cove", "Charbel", "Albert", "Misty", "Dune",
           "Spike", "Sika", "Savannah", "Wilson", "Bellerose", "Lily", "Emily", "Kiki", "Kenny", "Emma",
           "Richard", "Julie", "Mai", "Justin", "John", "Sarah", "Allison", "Howard", "Violet", "Mico",
           "Dochi", "Misty", "？？？"}


def cargar_tabla(ruta):
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        return {r["ingles"].strip(): r["correccion"].strip()
                for r in csv.DictReader(f, delimiter=";") if r["ingles"] and r["correccion"]}


def traducir(nombre, tabla):
    """Devuelve la traducción o None si no se sabe traducir."""
    n = nombre.strip()
    if n in tabla:
        return tabla[n]
    if n in PROPIOS:
        return n
    if n.endswith("（？）"):
        t = traducir(n[:-3], tabla)
        return t and t + "（？）"
    for sep in ("＆", " & "):
        if sep in n:
            partes = [traducir(p, tabla) for p in n.split(sep)]
            return None if None in partes else " y ".join(partes)
    m = re.match(r"^(.+?)['’]s Voice$", n)
    if m and m.group(1) in PROPIOS:
        return f"Voz de {m.group(1)}"
    m = re.match(r"^(.+?) ?([A-Z])$", n)
    if m and m.group(1) in tabla:
        return f"{tabla[m.group(1)]} {m.group(2)}"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ruta", required=True)
    ap.add_argument("--tabla", default=str(Path(__file__).with_name("nombres_hablantes_hills.csv")))
    ap.add_argument("--simular", action="store_true", help="Solo muestra lo que cambiaría")
    args = ap.parse_args()
    tabla = cargar_tabla(args.tabla)

    for original in Path(args.ruta).glob("**/*.csv.original"):
        destino = original.with_name(original.name[:-len(".original")])
        raw = destino.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        lines = raw.decode("utf-8-sig").split("\n")
        orig = original.read_bytes().decode("utf-8-sig").split("\n")
        if len(lines) != len(orig):
            print(f"AVISO: {destino.name} no coincide en líneas con el original. Se omite.")
            continue
        cambios, sin_traducir = Counter(), Counter()
        for i in range(1, len(orig)):
            o = orig[i].rstrip("\r").split(";")
            c = lines[i].rstrip("\r").split(";")
            if len(o) < 2 or len(c) != len(o):
                continue
            mo, mc = PRE.match(o[1]), PRE.match(c[1])
            if not mo or not mc:
                continue
            nuevo = traducir(mo.group(2), tabla)
            if nuevo is None:
                sin_traducir[mo.group(2)] += 1
                continue
            nuevo = nuevo.replace(";", ",").replace('"', "'")
            if mc.group(2) != nuevo:
                c[1] = mc.group(1) + nuevo + mc.group(3) + c[1][mc.end():]
                lines[i] = ";".join(c) + ("\r" if lines[i].endswith("\r") else "")
                cambios[f"{mo.group(2)} -> {nuevo}"] += 1
        print(f"{destino.name}: {sum(cambios.values())} líneas con el nombre traducido "
              f"({len(cambios)} nombres distintos)")
        if sin_traducir:
            print("  Sin traducción (se quedan igual):", dict(sin_traducir))
        if args.simular:
            for k, v in sorted(cambios.items(), key=lambda kv: -kv[1]):
                print(f"  {v:5d}  {k}")
            continue
        tmp = destino.with_name(destino.name + ".tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + "\n".join(lines).encode("utf-8"))
        os.replace(tmp, destino)


if __name__ == "__main__":
    main()
