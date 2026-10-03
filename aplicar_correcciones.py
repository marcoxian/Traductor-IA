"""
Aplica la hoja de revisión (revision_<juego>.csv) al CSV del juego.

  - Filas con 'correccion' rellenada -> se escribe tu corrección en el juego.
  - Con --resetear: las filas con fallos (ETIQUETAS, ORDEN, INGLES, LONGITUD) que NO hayas
    corregido vuelven al texto original en inglés. Así, al relanzar auto_inyector.py
    (por ejemplo con --modelo IA_Traductora_v2) SOLO se retraducen esas líneas.

  - Con --diccionario: aplica archivos 'ingles;correccion' (p. ej. correcciones_hills_menus.csv)
    a TODAS las líneas cuyo texto en inglés coincida exactamente.

IMPORTANTE: no lo ejecutes mientras auto_inyector.py esté traduciendo ese mismo juego.

Uso:
  python aplicar_correcciones.py --ruta "J:\\...\\The Adventures of HILLS" --diccionario correcciones_hills_menus.csv
  python aplicar_correcciones.py --ruta "J:\\...\\The Adventures of HILLS" --revision revision_The_Adventures_of_HILLS.csv
  python aplicar_correcciones.py --ruta "..." --revision ... --resetear
"""
import argparse
import csv
import os
from pathlib import Path

PROBLEMAS_RESETEABLES = {"ETIQUETAS", "ORDEN", "INGLES", "LONGITUD"}


def leer(path):
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    return bom, raw.decode("utf-8-sig" if bom else "utf-8").split("\n")


def escribir(path, bom, lines):
    tmp = path.with_name(path.name + ".tmp")
    data = "\n".join(lines).encode("utf-8")
    tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)
    os.replace(tmp, path)


def limpiar(texto, delim):
    texto = texto.replace("\r", " ").replace("\n", " ")
    texto = texto.replace('"', "'")
    return texto.replace(delim, "," if delim != "," else ";")


def aplicar_diccionarios(ruta_juego, rutas_dic):
    dic = {}
    for ruta in rutas_dic:
        with open(ruta, encoding="utf-8-sig", newline="") as f:
            for fila in csv.DictReader(f, delimiter=";"):
                en, es = (fila.get("ingles") or "").strip(), (fila.get("correccion") or "").strip()
                if en and es:
                    dic[en] = es
    print(f"Diccionario: {len(dic)} entradas")

    for original in Path(ruta_juego).glob("**/*.csv.original"):
        destino = original.with_name(original.name[:-len(".original")])
        bom, lines = leer(destino)
        _, orig = leer(original)
        if len(lines) != len(orig):
            print(f"AVISO: {destino.name} no coincide en líneas con el original. Se omite.")
            continue
        delim = max((";", ",", "\t"), key=orig[0].count)
        cab = [c.strip().lower() for c in orig[0].rstrip("\r").split(delim)]
        col = next((cab.index(n) for n in ("en", "english", "en_us", "en-us") if n in cab), 1)

        cambios = 0
        for i in range(1, len(orig)):
            o_partes = orig[i].rstrip("\r").split(delim)
            if len(o_partes) <= col:
                continue
            en = o_partes[col]
            clave = en.strip()
            if clave not in dic:
                continue
            # Conserva los espacios de alrededor (" gained ATK Up!" va pegado al nombre)
            inicio = en[:len(en) - len(en.lstrip())]
            fin = en[len(en.rstrip()):]
            cr = "\r" if lines[i].endswith("\r") else ""
            partes = lines[i].rstrip("\r").split(delim)
            nuevo = inicio + limpiar(dic[clave], delim) + fin
            if partes[col] != nuevo:
                partes[col] = nuevo
                lines[i] = delim.join(partes) + cr
                cambios += 1
        escribir(destino, bom, lines)
        print(f"{destino.name}: {cambios} líneas actualizadas con el diccionario")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ruta", required=True)
    ap.add_argument("--revision", help="Hoja generada por revisar_traduccion.py")
    ap.add_argument("--diccionario", nargs="+", help="Archivos 'ingles;correccion' a aplicar por coincidencia exacta")
    ap.add_argument("--resetear", action="store_true",
                    help="Devolver al inglés las líneas con fallos no corregidas, para retraducirlas")
    args = ap.parse_args()

    if not args.revision and not args.diccionario:
        ap.error("indica --revision y/o --diccionario")
    if args.diccionario:
        aplicar_diccionarios(args.ruta, args.diccionario)
    if not args.revision:
        return

    with open(args.revision, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f, delimiter=";"))

    por_archivo = {}
    for fila in filas:
        por_archivo.setdefault(fila["archivo"], []).append(fila)

    for nombre, filas_archivo in por_archivo.items():
        destino = next(Path(args.ruta).glob(f"**/{nombre}"), None)
        if destino is None or not destino.with_name(nombre + ".original").exists():
            print(f"AVISO: no encuentro {nombre} (o su .original). Se omite.")
            continue
        bom, lines = leer(destino)
        _, orig = leer(destino.with_name(nombre + ".original"))
        delim = max((";", ",", "\t"), key=orig[0].count)
        cab = [c.strip().lower() for c in orig[0].rstrip("\r").split(delim)]
        col = next((cab.index(n) for n in ("en", "english", "en_us", "en-us") if n in cab), 1)

        corregidas = reseteadas = saltadas = 0
        for fila in filas_archivo:
            i = int(fila["linea"])
            cr = "\r" if lines[i].endswith("\r") else ""
            partes = lines[i].rstrip("\r").split(delim)
            o_partes = orig[i].rstrip("\r").split(delim)
            # Comprobación de seguridad: la línea debe seguir siendo la misma entrada
            if partes[0] != fila["tag"] or o_partes[col] != fila["ingles"]:
                saltadas += 1
                continue

            correccion = (fila.get("correccion") or "").strip()
            if correccion:
                partes[col] = limpiar(correccion, delim)
                corregidas += 1
            elif args.resetear and PROBLEMAS_RESETEABLES & set(fila["problema"].split(",")):
                partes[col] = o_partes[col]
                reseteadas += 1
            else:
                continue
            lines[i] = delim.join(partes) + cr

        escribir(destino, bom, lines)
        print(f"{nombre}: {corregidas} corregidas a mano | {reseteadas} devueltas al inglés para retraducir"
              f" | {saltadas} omitidas (no coincidían)")


if __name__ == "__main__":
    main()
