"""2_generar_revision.py — Generador de hoja de revisión y control de calidad.

Compara el CSV traducido con su copia '.original' y genera una hoja CSV
(revision_<juego>.csv) estructurada para abrir y corregir en Excel o LibreOffice.

Detecta:
  ETIQUETAS      -> faltan o sobran códigos (\\C[n], \\n, %1...)
  ORDEN          -> están todos los códigos pero cambiados de sitio
  SIN_TRADUCIR   -> la línea sigue igual que en inglés
  INGLES         -> la traducción todavía contiene bastante inglés residual
  LONGITUD       -> traducción sospechosamente larga o corta (posible alucinación/corte)
  MENU           -> textos cortos de interfaz (para revisión humana rápida)
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

from traductor import config
from traductor.csv_locales import analizar_cabecera, leer_lineas, pares_traducidos, partir
from traductor.registro import configurar_logging
from traductor.texto import PATRON_CODIGOS, PATRON_ETIQUETAS, PATRON_PREFIJO, extraer_etiquetas

PALABRAS_EN = {
    "the", "you", "your", "and", "is", "are", "to", "of", "what", "that", "this",
    "with", "have", "i'm", "it's", "don't", "can't", "will", "would", "just", "there"
}


def analizar_linea(en: str, es: str) -> tuple[list[str], bool]:
    problemas = []
    tags_en, tags_es = extraer_etiquetas(en), extraer_etiquetas(es)

    if Counter(tags_en) != Counter(tags_es):
        problemas.append("ETIQUETAS")
    else:
        # Los marcadores %1, %2 pueden cambiar de orden gramaticalmente en español
        fijos_en = [t for t in tags_en if not re.fullmatch(r"%\d+", t)]
        fijos_es = [t for t in tags_es if not re.fullmatch(r"%\d+", t)]

        m_en, m_es = PATRON_PREFIJO.match(en), PATRON_PREFIJO.match(es)
        resto_en = en[len(m_en.group(0)) if m_en else 0:]
        resto_es = es[len(m_es.group(0)) if m_es else 0:]

        fb = re.match(r"^((?:%\d+|\\n|\\[A-Za-z]+\[[^\]]*\])+) (?=[¡¿A-ZÁÉÍÓÚÑ])", resto_es)
        pre_en = m_en.group(0).strip() if m_en else ""
        pre_es = m_es.group(0).strip() if m_es else ""

        if fijos_en != fijos_es or pre_en != pre_es or (fb and not resto_en.startswith(fb.group(1))):
            problemas.append("ORDEN")

    m_en = PATRON_PREFIJO.match(en)
    cuerpo_en = PATRON_CODIGOS.sub("", en[len(m_en.group(0)) if m_en else 0:]).strip()
    m_es = PATRON_PREFIJO.match(es)
    cuerpo_es = PATRON_CODIGOS.sub("", es[len(m_es.group(0)) if m_es else 0:]).strip()

    palabras = re.findall(r"[a-zA-Z']+", cuerpo_es.lower())

    if es == en and len(cuerpo_en.split()) >= 3:
        problemas.append("SIN_TRADUCIR")
    elif palabras and es != en:
        num_ingles = sum(1 for p in palabras if p in PALABRAS_EN)
        if num_ingles >= 3 or (len(palabras) >= 4 and num_ingles / len(palabras) > 0.25):
            problemas.append("INGLES")

    if len(cuerpo_en) >= 20 and cuerpo_es:
        ratio = len(cuerpo_es) / len(cuerpo_en)
        if ratio > 2.5 or ratio < 0.35:
            problemas.append("LONGITUD")

    es_menu = "\\" not in en and len(cuerpo_en.split()) <= 4 and any(c.isalpha() for c in cuerpo_en)
    return problemas, es_menu


def main():
    ap = argparse.ArgumentParser(description="Revisa la traducción de un CSV de localización.")
    ap.add_argument("--ruta", required=True, help="Carpeta del juego que contiene archivos .csv")
    ap.add_argument("--salida", help="Ruta del archivo CSV de salida resultante")
    ap.add_argument("--sin-menus", action="store_true", help="No incluir los textos cortos de menú en la revisión")
    args = ap.parse_args()

    configurar_logging()
    juego = Path(args.ruta)

    if args.salida:
        salida = Path(args.salida)
    else:
        nombre_limpio = config.slug(juego.name) or "juego"
        salida = Path(f"revision_{nombre_limpio}.csv")

    filas, resumen = [], Counter()

    for original, traducido in pares_traducidos(juego):
        _, o_lines = leer_lineas(original)
        _, t_lines = leer_lineas(traducido)

        if len(o_lines) != len(t_lines):
            print(f"AVISO: {traducido.name} no tiene las mismas líneas que el original ({len(t_lines)} vs {len(o_lines)}). Se omite.")
            continue

        delim, header, col = analizar_cabecera(o_lines)
        if col is None:
            col = 1

        for i in range(1, len(o_lines)):
            o_parts, _ = partir(o_lines[i], delim)
            t_parts, _ = partir(t_lines[i], delim)
            if len(o_parts) <= col or len(t_parts) <= col:
                continue

            en, es = o_parts[col], t_parts[col]
            if not any(c.isalpha() for c in PATRON_CODIGOS.sub("", en)):
                continue

            problemas, es_menu = analizar_linea(en, es)
            if es_menu and not args.sin_menus:
                problemas.append("MENU")
            if not problemas:
                continue

            resumen.update(problemas)
            filas.append({
                "archivo": traducido.name,
                "linea": i,
                "tag": o_parts[0] if o_parts else "",
                "problema": ",".join(problemas),
                "ingles": en,
                "traduccion_ia": es,
                "correccion": "",
            })

    # Prioridad: Primero los fallos graves (etiquetas, sin traducir, inglés), luego menús
    gravedad = {"ETIQUETAS": 0, "SIN_TRADUCIR": 1, "INGLES": 2, "LONGITUD": 3, "ORDEN": 4, "MENU": 5}
    filas.sort(key=lambda f: min(gravedad.get(p, 99) for p in f["problema"].split(",")))

    with open(salida, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["archivo", "linea", "tag", "problema", "ingles", "traduccion_ia", "correccion"],
            delimiter=";"
        )
        w.writeheader()
        w.writerows(filas)

    print(f"Revisión guardada en: {salida.resolve()}")
    print(f"Líneas a revisar: {len(filas)}")
    for k, v in resumen.most_common():
        print(f"  {k:<13} {v}")


if __name__ == "__main__":
    main()
