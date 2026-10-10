"""6_auditoria_semantica.py — Auditoría de coherencia y corrección de falsos amigos.

Corrige automáticamente errores comunes de traducción literal en videojuegos
(party -> grupo, item -> objeto, save -> guardar, miss -> fallo, chest -> cofre...).
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path

from traductor import config
from traductor.csv_locales import pares_traducidos
from traductor.registro import configurar_logging

csv.field_size_limit(2147483647)

# Reglas de sustitución: (palabra_ingles, regex_espanol_malo, reemplazo_espanol_bueno)
REGLAS = [
    ("item", r"\belemento\b", "objeto"),
    ("items", r"\belementos\b", "objetos"),
    ("item", r"\bartículo\b", "objeto"),
    ("item", r"\barticulo\b", "objeto"),
    ("items", r"\bartículos\b", "objetos"),
    ("items", r"\barticulos\b", "objetos"),
    ("party", r"\bfiesta\b", "grupo"),
    ("character", r"\bcarácter\b", "personaje"),
    ("characters", r"\bcaracteres\b", "personajes"),
    ("save", r"\bahorrar\b", "guardar"),
    ("save file", r"\barchivo de ahorro\b", "archivo de guardado"),
    ("swipe", r"\bdesliza\b", "roba"),
    ("swipe", r"\bdeslizar\b", "robar"),
    ("swipe", r"\bdeslizado\b", "robado"),
    ("miss", r"\bseñorita\b", "fallo"),
    ("cast", r"\belenco\b", "lanzar"),
    ("chest", r"\bpecho\b", "cofre"),
    ("drop", r"\bgota\b", "soltar"),
]


def auditar_archivos(path_orig: Path, path_trans: Path, path_dic: Path) -> int:
    orig_dict: dict[str, str] = {}
    with open(path_orig, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        for row in csv.reader(f, delimiter=";"):
            if row:
                orig_dict[row[0]] = row[1] if len(row) > 1 else ""

    existentes: set[str] = set()
    if path_dic.exists():
        with open(path_dic, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
            for row in csv.reader(f, delimiter=";"):
                if row:
                    existentes.add(row[0])

    nuevas_correcciones = []
    count = 0

    with open(path_trans, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        for row in csv.reader(f, delimiter=";"):
            if not row or len(row) < 2:
                continue
            tag, es = row[0], row[1]
            en = orig_dict.get(tag, "")
            if not en or en in existentes:
                continue

            es_modificado = es
            en_lower = en.lower()

            for en_word, bad_regex, good_word in REGLAS:
                if re.search(r"\b" + re.escape(en_word) + r"\b", en_lower):
                    def repl(match):
                        word = match.group(0)
                        if word.istitle():
                            return good_word.capitalize()
                        if word.isupper():
                            return good_word.upper()
                        return good_word

                    es_modificado = re.sub(bad_regex, repl, es_modificado, flags=re.IGNORECASE)

            if "tímida y tímida" in es_modificado:
                es_modificado = es_modificado.replace("tímida y tímida", "tímida")

            if es_modificado != es:
                nuevas_correcciones.append((en, es_modificado))
                count += 1

    if nuevas_correcciones:
        path_dic.parent.mkdir(parents=True, exist_ok=True)
        with open(path_dic, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerows(nuevas_correcciones)
        print(f"[{path_trans.name}] Se corrigieron y guardaron {count} falsos amigos en el diccionario.")
    else:
        print(f"[{path_trans.name}] No se detectaron falsos amigos con las reglas actuales.")
    return count


def main():
    parser = argparse.ArgumentParser(description="Auditoría semántica de traducciones RPG Maker / CSV.")
    parser.add_argument("--ruta", help="Ruta al directorio del juego (busca automáticamente pares .original y traducidos)")
    parser.add_argument("--original", help="Ruta al CSV original en inglés")
    parser.add_argument("--traducido", help="Ruta al CSV traducido")
    parser.add_argument("--diccionario", default=str(config.DICCIONARIO_INTERFAZ), help="Ruta al CSV de diccionario")
    args = parser.parse_args()

    configurar_logging()
    path_dic = Path(args.diccionario)

    if args.ruta:
        total = 0
        ruta_juego = Path(args.ruta)
        for orig, trans in pares_traducidos(ruta_juego):
            total += auditar_archivos(orig, trans, path_dic)
        print(f"Auditoría terminada. Total correcciones: {total}")
        return

    if not args.original or not args.traducido:
        parser.error("Debes especificar --ruta o ambos parámetros --original y --traducido")

    p_orig, p_trans = Path(args.original), Path(args.traducido)
    if not p_orig.exists():
        sys.exit(f"Aviso: Archivo original no encontrado: {p_orig}")
    if not p_trans.exists():
        sys.exit(f"Aviso: Archivo traducido no encontrado: {p_trans}")

    auditar_archivos(p_orig, p_trans, path_dic)


if __name__ == "__main__":
    main()
