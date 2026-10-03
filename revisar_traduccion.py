"""
Revisa una traducción hecha por auto_inyector.py comparando el CSV traducido con su
copia '.original' y genera una hoja para revisar/corregir en Excel.

Detecta:
  ETIQUETAS      -> faltan o sobran códigos (\\C[n], \\n, %1...)
  ORDEN          -> están todos los códigos pero cambiados de sitio (típico del "fallback")
  SIN_TRADUCIR   -> la línea sigue igual que en inglés
  INGLES         -> la traducción todavía contiene bastante inglés
  LONGITUD       -> traducción sospechosamente larga o corta (posible alucinación/corte)
  MENU           -> textos cortos de interfaz (se revisan a mano, son pocos y se ven mucho)

Uso:
  python revisar_traduccion.py --ruta "J:\\...\\The Adventures of HILLS"
  python revisar_traduccion.py --ruta "..." --sin-menus      (no listar los textos de menú)

Salida: revision_<juego>.csv  (separado por ';', se abre directamente con Excel)
  Rellena la columna 'correccion' donde quieras y luego:
    - python aplicar_correcciones.py ...   -> mete tus correcciones en el juego
    - python crear_glosario_v2.py          -> las usa como ejemplos de entrenamiento
"""
import argparse
import csv
import re
from collections import Counter
from pathlib import Path

TAG_RE = re.compile(r'(%[sdfSDF]|%\d+|\\n|\\r|\{[^}]+\}|\[[^\]]+\]|\\[A-Za-z]+\[[^\]]*\])')
PREFIX_RE = re.compile(r'^(?:\\N<[^>]*>|\\[A-Za-z]+\[[^\]]*\]|\\[A-Za-z{}|.!^$<>](?![A-Za-z])|\s)+')
STRIP_RE = re.compile(r'(%[sdfSDF]|%\d+|\\n|\\r|\{[^}]+\}|\[[^\]]+\]|\\[A-Za-z]+\[[^\]]*\]|\\[A-Za-z{}<>|.!^$]|<[^>]*>)')
PALABRAS_EN = {"the", "you", "your", "and", "is", "are", "to", "of", "what", "that", "this",
               "with", "have", "i'm", "it's", "don't", "can't", "will", "would", "just", "there"}


def leer(path):
    text = path.read_bytes().decode("utf-8-sig")
    return text.split("\n")


def columnas(linea, delim):
    return linea.rstrip("\r").split(delim)


def analizar(en, es):
    problemas = []
    tags_en, tags_es = TAG_RE.findall(en), TAG_RE.findall(es)
    if Counter(tags_en) != Counter(tags_es):
        problemas.append("ETIQUETAS")
    else:
        # En español es normal reordenar %1/%2, así que esos no cuentan para el orden
        fijos_en = [t for t in tags_en if not re.fullmatch(r"%\d+", t)]
        fijos_es = [t for t in tags_es if not re.fullmatch(r"%\d+", t)]
        # Firma del "fallback de emergencia": códigos pegados al inicio seguidos de un espacio
        m_en, m_es = PREFIX_RE.match(en), PREFIX_RE.match(es)
        resto_en = en[len(m_en.group(0)) if m_en else 0:]
        resto_es = es[len(m_es.group(0)) if m_es else 0:]
        fb = re.match(r"^((?:%\d+|\\n|\\[A-Za-z]+\[[^\]]*\])+) (?=[¡¿A-ZÁÉÍÓÚÑ])", resto_es)
        pre_en = m_en.group(0).strip() if m_en else ""
        pre_es = m_es.group(0).strip() if m_es else ""
        if fijos_en != fijos_es or pre_en != pre_es or (fb and not resto_en.startswith(fb.group(1))):
            problemas.append("ORDEN")

    m = PREFIX_RE.match(en)
    cuerpo_en = STRIP_RE.sub("", en[len(m.group(0)) if m else 0:]).strip()
    m = PREFIX_RE.match(es)
    cuerpo_es = STRIP_RE.sub("", es[len(m.group(0)) if m else 0:]).strip()
    palabras = re.findall(r"[a-zA-Z']+", cuerpo_es.lower())

    if es == en and len(cuerpo_en.split()) >= 3:
        problemas.append("SIN_TRADUCIR")
    elif palabras and es != en:
        ingles = sum(1 for p in palabras if p in PALABRAS_EN)
        if ingles >= 3 or (len(palabras) >= 4 and ingles / len(palabras) > 0.25):
            problemas.append("INGLES")

    if len(cuerpo_en) >= 20 and cuerpo_es:
        ratio = len(cuerpo_es) / len(cuerpo_en)
        if ratio > 2.5 or ratio < 0.35:
            problemas.append("LONGITUD")

    es_menu = "\\" not in en and len(cuerpo_en.split()) <= 4 and any(c.isalpha() for c in cuerpo_en)
    return problemas, es_menu


def main():
    ap = argparse.ArgumentParser(description="Revisa la traducción de un CSV de localización.")
    ap.add_argument("--ruta", required=True, help="Carpeta del juego")
    ap.add_argument("--sin-menus", action="store_true", help="No incluir los textos cortos de menú")
    args = ap.parse_args()

    juego = Path(args.ruta)
    salida = Path(f"revision_{re.sub(r'[^A-Za-z0-9]+', '_', juego.name).strip('_')}.csv")
    filas, resumen = [], Counter()

    for original in juego.glob("**/*.csv.original"):
        traducido = original.with_name(original.name[:-len(".original")])
        if not traducido.exists():
            continue
        o_lines, t_lines = leer(original), leer(traducido)
        if len(o_lines) != len(t_lines):
            print(f"AVISO: {traducido.name} no tiene las mismas líneas que el original. Se omite.")
            continue

        cab = o_lines[0].rstrip("\r")
        delim = max((";", ",", "\t"), key=cab.count)
        cabecera = [c.strip().lower() for c in cab.split(delim)]
        col = next((cabecera.index(n) for n in ("en", "english", "en_us", "en-us") if n in cabecera), 1)

        for i in range(1, len(o_lines)):
            o, t = columnas(o_lines[i], delim), columnas(t_lines[i], delim)
            if len(o) <= col or len(t) <= col:
                continue
            en, es = o[col], t[col]
            if not any(c.isalpha() for c in STRIP_RE.sub("", en)):
                continue
            problemas, es_menu = analizar(en, es)
            if es_menu and not args.sin_menus:
                problemas.append("MENU")
            if not problemas:
                continue
            resumen.update(problemas)
            filas.append({"archivo": traducido.name, "linea": i, "tag": o[0],
                          "problema": ",".join(problemas), "ingles": en,
                          "traduccion_ia": es, "correccion": ""})

    # Primero los fallos graves, luego los menús
    gravedad = {"ETIQUETAS": 0, "SIN_TRADUCIR": 1, "INGLES": 2, "LONGITUD": 3, "ORDEN": 4, "MENU": 5}
    filas.sort(key=lambda f: min(gravedad[p] for p in f["problema"].split(",")))

    with open(salida, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["archivo", "linea", "tag", "problema", "ingles",
                                          "traduccion_ia", "correccion"], delimiter=";")
        w.writeheader()
        w.writerows(filas)

    print(f"Revisión guardada en: {salida.resolve()}")
    print(f"Líneas a revisar: {len(filas)}")
    for k, v in resumen.most_common():
        print(f"  {k:<13} {v}")


if __name__ == "__main__":
    main()
