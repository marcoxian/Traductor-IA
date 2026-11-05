"""6_auditoria_semantica.py — Auditoría de coherencia y corrección de falsos amigos.

Corrige automáticamente errores comunes de traducción literal en videojuegos
(party -> grupo, item -> objeto, save -> guardar, miss -> fallo, chest -> cofre...).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

from traductor import config
from traductor.csv_locales import pares_traducidos
from traductor.motores.rpgmaker import PATRON_SET_VALUE_21
from traductor.registro import configurar_logging
from traductor.texto import PATRON_PREFIJO_V21, corregir_puntuacion_pegada, postprocesar_traduccion

csv.field_size_limit(2147483647)

# Reglas de sustitución: (palabra_ingles, regex_espanol_malo, reemplazo_espanol_bueno)
REGLAS = [
    ("item", r"\belemento\b", "objeto"),
    ("items", r"\belementos\b", "objetos"),
    ("item", r"\bartículo\b", "objeto"),
    ("item", r"\barticulo\b", "objeto"),
    ("items", r"\bartículos\b", "objetos"),
    ("items", r"\barticulos\b", "objetos"),
    ("party", r"\bmiembros de la fiesta\b", "miembros del grupo"),
    ("party", r"\bmiembro de la fiesta\b", "miembro del grupo"),
    ("party", r"\blíder de la fiesta\b", "líder del grupo"),
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
    ("earlier today", r"\bmás temprano hoy\b", "hace un rato"),
    ("earlier", r"\bmás temprano\b", "hace un rato"),
    ("looks like", r"\bluce como(?!\s+si\b)\b", "parece"),
    ("sounds like", r"\bsuena como que\b", "parece que"),
    ("sounds like", r"\bsuena como(?!\s+si\b)\b", "suena a"),
    ("feel like", r"\bsiento como si\b", "me da la sensación de que"),
]

# Frases cortas que a veces quedan en inglés sin traducir
TRADUCCIONES_RESIDUALES_EN = {
    "Nope...": "Qué va...",
    "Nope.": "Qué va.",
    "Sure!": "¡Claro!",
    "Sure...": "Claro...",
    "Sure.": "Claro.",
    "Oh god.": "Oh, Dios.",
    "Oh, my god...": "Oh, Dios mío...",
    "Oh, uhh... Sure.": "Oh, eh... Claro.",
    "Blowjob": "Mamada",
    "Cowgirl": "Vaquera",
    "Piledrive": "Martinete",
    "Titfuck": "Cubana",
}

# Correcciones exactas (inglés, traducción mala) -> traducción buena, para líneas desalineadas o erratas conocidas.
REEMPLAZOS_EXACTOS_PAR: dict[tuple[str, str], str] = {}

# Lo propio de cada juego (objetos, frases concretas) va en un archivo PRIVADO que no se sube al repositorio:
# glosarios/auditoria_semantica_local.json (formato en glosarios/auditoria_semantica_local.ejemplo.json).
_ARCHIVO_LOCAL = Path(__file__).resolve().parent / "glosarios" / "auditoria_semantica_local.json"
try:
    _local = json.loads(_ARCHIVO_LOCAL.read_text(encoding="utf-8"))
    TRADUCCIONES_RESIDUALES_EN.update(_local.get("residuales") or {})
    REEMPLAZOS_EXACTOS_PAR.update({(en, malo): bueno for en, malo, bueno in _local.get("exactos") or ()})
except (OSError, ValueError, TypeError):
    pass

_PATRON_PREFIJO_CORRUPTO = re.compile(
    r"^(?:¡Je!\s*¡Ha!\s*¡Cl!\s*(?:#>\.)?\s*|"
    r"¡?[A-Za-z0-9!<>^#~_%@\-+=,]+\s+c\.\s*|"
    r"¡[A-Za-z0-9!<>^#~_%@\-+=,]{4,18}\.\s*|"
    r"[A-Za-z0-9!<>^#~_%@\-+=,]{2,10}\.[A-Za-z0-9!<>^#~_%@\-+=,]{1,8}\.\s*)"
)

_PATRON_SET_VALUE_TEXTO = re.compile(
    r"(\$gameVariables\.setValue\(\s*(?:21|94|95|107)\s*,\s*[\"'])(.*?)([\"']\s*\))"
)


def _limpiar_cuerpo_v21_corrupto(val_trans: str) -> str:
    """Extrae el diálogo español cuando el prefijo V21 fue alterado o traducido por error."""
    m_corrupto = _PATRON_PREFIJO_CORRUPTO.match(val_trans)
    if m_corrupto:
        return val_trans[m_corrupto.end():]
    m_v21 = PATRON_PREFIJO_V21.match(val_trans)
    if m_v21:
        return m_v21.group(2)
    return val_trans


def aplicar_reglas_par(en: str, es: str) -> str:
    """Aplica las reglas semánticas, postprocesado y corrección de puntuación a un par (en, es)."""
    es_modificado = es
    en_strip = en.strip() if en else ""
    es_strip = es_modificado.strip()
    if (en_strip, es_strip) in REEMPLAZOS_EXACTOS_PAR:
        es_modificado = REEMPLAZOS_EXACTOS_PAR[(en_strip, es_strip)]
    elif en_strip and es_strip == en_strip and en_strip in TRADUCCIONES_RESIDUALES_EN:
        es_modificado = TRADUCCIONES_RESIDUALES_EN[en_strip]

    en_lower = en.lower() if en else ""

    if en_lower:
        for en_word, bad_regex, good_word in REGLAS:
            if re.search(r"\b" + re.escape(en_word) + r"\b", en_lower):
                def repl(match, gw=good_word):
                    word = match.group(0)
                    if word.istitle():
                        return gw.capitalize()
                    if word.isupper():
                        return gw.upper()
                    return gw

                es_modificado = re.sub(bad_regex, repl, es_modificado, flags=re.IGNORECASE)

    if "tímida y tímida" in es_modificado:
        es_modificado = es_modificado.replace("tímida y tímida", "tímida")

    es_modificado = postprocesar_traduccion(es_modificado, en)
    es_modificado = corregir_puntuacion_pegada(es_modificado)
    return es_modificado


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
    filas_salida = []
    count = 0

    with open(path_trans, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        for row in csv.reader(f, delimiter=";"):
            if not row or len(row) < 2:
                filas_salida.append(row)
                continue
            tag, es = row[0], row[1]
            en = orig_dict.get(tag, "")
            if not en:
                filas_salida.append(row)
                continue

            es_modificado = aplicar_reglas_par(en, es)

            if es_modificado != es:
                row = [tag, es_modificado] + row[2:]
                if en not in existentes:
                    nuevas_correcciones.append((en, es_modificado))
                    existentes.add(en)
                count += 1
            filas_salida.append(row)

    if count > 0:
        with open(path_trans, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerows(filas_salida)

    if nuevas_correcciones:
        path_dic.parent.mkdir(parents=True, exist_ok=True)
        with open(path_dic, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerows(nuevas_correcciones)

    if count > 0:
        print(f"[{path_trans.name}] Se corrigieron {count} cadenas en el archivo y diccionario.")
    else:
        print(f"[{path_trans.name}] No se detectaron falsos amigos con las reglas actuales.")
    return count


def _es_lista_comandos(lst) -> bool:
    return (
        isinstance(lst, list)
        and len(lst) > 0
        and isinstance(lst[0], dict)
        and "code" in lst[0]
        and "parameters" in lst[0]
    )


def _auditar_nodo_json(orig_node, trans_node, en_System_terms: bool = False) -> int:
    """Recorre recursivamente un árbol JSON de RPG Maker alineando eventos y comandos."""
    cambios = 0
    if isinstance(trans_node, dict):
        if "name" in trans_node and "volume" in trans_node and "pitch" in trans_node:
            return 0
        orig_dict = orig_node if isinstance(orig_node, dict) else {}
        code = trans_node.get("code")

        if code in (355, 655) and trans_node.get("parameters") and isinstance(trans_node["parameters"][0], str):
            st = trans_node["parameters"][0]
            so = (
                orig_dict["parameters"][0]
                if orig_dict.get("code") in (355, 655)
                and orig_dict.get("parameters")
                and isinstance(orig_dict["parameters"][0], str)
                else ""
            )
            mt = _PATRON_SET_VALUE_TEXTO.search(st)
            if mt:
                mo = _PATRON_SET_VALUE_TEXTO.search(so) if so else None
                vt = mt.group(2)
                vo = mo.group(2) if mo else ""
                es_v21 = "setValue(21" in mt.group(1)
                pvo = PATRON_PREFIJO_V21.match(vo) if (es_v21 and vo) else None
                if pvo:
                    pref = pvo.group(1) + "."
                    cuerpo_en = pvo.group(2)
                    if vt.startswith(pref):
                        cuerpo_es = vt[len(pref):]
                    else:
                        cuerpo_es = _limpiar_cuerpo_v21_corrupto(vt)
                    if cuerpo_en == "/success":
                        nuevo_cuerpo = "/success"
                    else:
                        if cuerpo_es.startswith(" ") and not cuerpo_en.startswith(" "):
                            cuerpo_es = cuerpo_es.lstrip(" ")
                        nuevo_cuerpo = aplicar_reglas_par(cuerpo_en, cuerpo_es)
                    nuevo_vt = pref + nuevo_cuerpo
                elif es_v21:
                    pvt = PATRON_PREFIJO_V21.match(vt)
                    if pvt:
                        pref_t = pvt.group(1) + "."
                        cuerpo_es = pvt.group(2).lstrip(" ")
                        nuevo_vt = pref_t + aplicar_reglas_par(vo, cuerpo_es)
                    else:
                        nuevo_vt = aplicar_reglas_par(vo, vt)
                else:
                    nuevo_vt = aplicar_reglas_par(vo, vt)

                if nuevo_vt != vt:
                    comilla = mt.group(1)[-1]
                    if comilla == '"':
                        seguro = nuevo_vt.replace('\\"', "'").replace('"', "'")
                    else:
                        seguro = nuevo_vt.replace("\\'", '"').replace("'", '"')
                    seguro = seguro.rstrip("\\")
                    trans_node["parameters"][0] = (
                        st[:mt.start()] + mt.group(1) + seguro + mt.group(3) + st[mt.end():]
                    )
                    cambios += 1
            elif so and "replace(/" in so and st != so:
                trans_node["parameters"][0] = so
                cambios += 1
            return cambios

        if code == 102 and trans_node.get("parameters") and isinstance(trans_node["parameters"][0], list):
            opts_es = trans_node["parameters"][0]
            opts_en = (
                orig_dict["parameters"][0]
                if orig_dict.get("code") == 102
                and orig_dict.get("parameters")
                and isinstance(orig_dict["parameters"][0], list)
                else []
            )
            for idx in range(len(opts_es)):
                if isinstance(opts_es[idx], str) and opts_es[idx].strip():
                    s_en = opts_en[idx] if idx < len(opts_en) and isinstance(opts_en[idx], str) else ""
                    nuevo = aplicar_reglas_par(s_en, opts_es[idx])
                    if nuevo != opts_es[idx]:
                        opts_es[idx] = nuevo
                        cambios += 1
            return cambios

        if code == 402 and trans_node.get("parameters") and len(trans_node["parameters"]) > 1:
            if isinstance(trans_node["parameters"][1], str) and trans_node["parameters"][1].strip():
                s_es = trans_node["parameters"][1]
                s_en = (
                    orig_dict["parameters"][1]
                    if orig_dict.get("code") == 402
                    and orig_dict.get("parameters")
                    and len(orig_dict["parameters"]) > 1
                    and isinstance(orig_dict["parameters"][1], str)
                    else ""
                )
                nuevo = aplicar_reglas_par(s_en, s_es)
                if nuevo != s_es:
                    trans_node["parameters"][1] = nuevo
                    cambios += 1
            return cambios

        if code is not None:
            return 0

        campos_db = {"name", "description", "message1", "message2", "message3", "message4", "nickname", "profile", "gameTitle"}
        for k, v in trans_node.items():
            orig_v = orig_dict.get(k)
            if isinstance(v, str) and v.strip() and (k in campos_db or en_System_terms):
                en_str = orig_v if isinstance(orig_v, str) else ""
                nuevo = aplicar_reglas_par(en_str, v)
                if nuevo != v:
                    trans_node[k] = nuevo
                    cambios += 1
            elif isinstance(v, (dict, list)):
                cambios += _auditar_nodo_json(orig_v, v, en_System_terms=(en_System_terms or k == "terms"))

    elif isinstance(trans_node, list):
        orig_list = orig_node if isinstance(orig_node, list) else []
        if _es_lista_comandos(trans_node):
            io, it = 0, 0
            while it < len(trans_node):
                ct = trans_node[it].get("code") if isinstance(trans_node[it], dict) else None
                co = orig_list[io].get("code") if io < len(orig_list) and isinstance(orig_list[io], dict) else None
                if ct == 401 or co == 401:
                    lineas_en = []
                    while io < len(orig_list) and isinstance(orig_list[io], dict) and orig_list[io].get("code") == 401:
                        p = orig_list[io].get("parameters")
                        if p and isinstance(p[0], str):
                            lineas_en.append(p[0])
                        io += 1
                    en_full = " ".join(lineas_en)
                    while it < len(trans_node) and isinstance(trans_node[it], dict) and trans_node[it].get("code") == 401:
                        p = trans_node[it].get("parameters")
                        if p and isinstance(p[0], str) and p[0].strip():
                            s_es = p[0]
                            nuevo = aplicar_reglas_par(en_full, s_es)
                            if nuevo != s_es:
                                p[0] = nuevo
                                cambios += 1
                        it += 1
                else:
                    orig_item = orig_list[io] if io < len(orig_list) else None
                    cambios += _auditar_nodo_json(orig_item, trans_node[it], en_System_terms=en_System_terms)
                    io += 1
                    it += 1
        else:
            for i, v in enumerate(trans_node):
                orig_v = orig_list[i] if i < len(orig_list) else None
                if isinstance(v, str) and v.strip() and en_System_terms:
                    en_str = orig_v if isinstance(orig_v, str) else ""
                    nuevo = aplicar_reglas_par(en_str, v)
                    if nuevo != v:
                        trans_node[i] = nuevo
                        cambios += 1
                elif isinstance(v, (dict, list)):
                    cambios += _auditar_nodo_json(orig_v, v, en_System_terms=en_System_terms)
    return cambios


def auditar_rpgmaker_json(ruta_juego: Path) -> int:
    """Audita y corrige in-place archivos .json de RPG Maker que tengan respaldo .json.bak."""
    import json

    total = 0
    for bak_path in sorted(ruta_juego.rglob("*.json.bak")):
        json_path = bak_path.with_suffix("")
        if not json_path.exists():
            continue
        try:
            orig_data = json.loads(bak_path.read_text(encoding="utf-8-sig"))
            trans_data = json.loads(json_path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue

        cambios = _auditar_nodo_json(orig_data, trans_data)
        if cambios > 0:
            json_path.write_text(
                json.dumps(trans_data, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            print(f"[{json_path.name}] Se corrigieron {cambios} cadenas en JSON.")
            total += cambios
    return total


def main():
    parser = argparse.ArgumentParser(description="Auditoría semántica de traducciones RPG Maker / CSV.")
    parser.add_argument("--ruta", help="Ruta al directorio del juego (busca automáticamente pares .original y JSONs)")
    parser.add_argument("--original", help="Ruta al CSV original en inglés")
    parser.add_argument("--traducido", help="Ruta al CSV traducido")
    parser.add_argument("--diccionario", default=str(config.DICCIONARIO_INTERFAZ), help="Ruta al CSV de diccionario")
    parser.add_argument("--debug", action="store_true", help="Mostrar logs detallados de depuración")
    args = parser.parse_args()

    configurar_logging(detallado=args.debug)
    path_dic = Path(args.diccionario)

    if args.ruta:
        total = 0
        ruta_juego = Path(args.ruta)
        for orig, trans in pares_traducidos(ruta_juego):
            total += auditar_archivos(orig, trans, path_dic)
        total += auditar_rpgmaker_json(ruta_juego)
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
