"""extraer_corpus_nadia.py
Extrae pares bilingües inglés-español alineando los archivos JSON de RPG Maker MV de Treasure of Nadia.
Compara la versión en inglés (original) con la versión en español (parche).
Genera:
- datasets/corpus_videojuegos/dataset_extra_nadia.jsonl (pares de diálogo limpios y de alta calidad)
- glosarios/glosario_nadia.json (términos de inventario, objetos y habilidades)
"""

import json
import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TAG_REGEX = re.compile(r'^([A-Za-z0-9!<>^#~_%@\-+=]+?[\.#>:]+)(.*)$', re.DOTALL)
V21_REGEX = re.compile(r'\$gameVariables\.setValue\(21,\s*"([^"]+)"\)', re.DOTALL)

def limpiar_texto(t: str) -> str:
    if not isinstance(t, str):
        return ""
    return t.strip()

def separar_etiqueta_v21(texto: str):
    """Separa la etiqueta interna de personaje/emoción (ej: 'HeFrOp.') del diálogo real."""
    if not texto:
        return "", ""
    m = TAG_REGEX.match(texto)
    if m:
        tag = m.group(1).strip()
        dialogo = m.group(2).strip()
        return tag, dialogo
    return "", texto.strip()

def extraer_dialogo_comando(cmd: dict):
    """Extrae el texto de un comando RPG Maker MV (código 401, 102 o v21)."""
    code = cmd.get("code")
    params = cmd.get("parameters", [])
    if not params:
        return None, None

    # Código 401: texto de diálogo estándar
    if code == 401 and isinstance(params[0], str):
        texto = params[0].strip()
        if texto:
            return "dialogo", texto

    # Código 355 / 655: Script call (ej: $gameVariables.setValue(21, "..."))
    if code in (355, 655) and isinstance(params[0], str):
        p = params[0]
        if "$gameVariables.setValue(21," in p:
            m = V21_REGEX.search(p)
            if m:
                return "v21", m.group(1).strip()

    # Código 102: Opciones de elección (Choices)
    if code == 102 and isinstance(params[0], list):
        opciones = [o.strip() for o in params[0] if isinstance(o, str) and o.strip()]
        if opciones:
            return "choices", opciones

    return None, None

def procesar_corpus(dir_en: Path, dir_es: Path, output_jsonl: Path, output_glosario: Path):
    print("=== EXTRACCIÓN Y ALINEACIÓN BILINGÜE: TREASURE OF NADIA ===")
    print(f"Directorio EN: {dir_en}")
    print(f"Directorio ES: {dir_es}")

    pares = []
    glosario = {}
    vistos = set()

    def agregar_par(en_text, es_text, contexto):
        en_clean = limpiar_texto(en_text)
        es_clean = limpiar_texto(es_text)
        if not en_clean or not es_clean:
            return
        if en_clean == es_clean:
            return
        # Descartar si son solo símbolos, números o códigos puros
        if not re.search(r'[a-zA-ZáéíóúñÁÉÍÓÚÑ]', en_clean) or not re.search(r'[a-zA-ZáéíóúñÁÉÍÓÚÑ]', es_clean):
            return

        clave = (en_clean, es_clean)
        if clave not in vistos:
            vistos.add(clave)
            pares.append({
                "ingles": en_clean,
                "espanol": es_clean,
                "contexto": contexto
            })

    # 1. Procesar bases de datos (Items, Skills, Weapons, Armors)
    db_archivos = ["Items.json", "Skills.json", "Weapons.json", "Armors.json"]
    for db_nombre in db_archivos:
        f_en = dir_en / db_nombre
        f_es = dir_es / db_nombre
        if not f_en.exists() or not f_es.exists():
            continue

        try:
            items_en = json.loads(f_en.read_text(encoding="utf-8"))
            items_es = json.loads(f_es.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Error leyendo {db_nombre}: {e}")
            continue

        for it_en, it_es in zip(items_en, items_es):
            if not it_en or not it_es:
                continue
            name_en = limpiar_texto(it_en.get("name", ""))
            name_es = limpiar_texto(it_es.get("name", ""))
            desc_en = limpiar_texto(it_en.get("description", ""))
            desc_es = limpiar_texto(it_es.get("description", ""))

            tipo = db_nombre.replace(".json", "").lower()
            if name_en and name_es and name_en.lower() != name_es.lower():
                glosario[name_en] = name_es
                agregar_par(name_en, name_es, f"nadia_{tipo}_nombre")

            if desc_en and desc_es:
                agregar_par(desc_en, desc_es, f"nadia_{tipo}_desc")

    # 2. Procesar Eventos Comunes y Mapas
    map_files = ["CommonEvents.json"] + sorted([f.name for f in dir_en.glob("Map*.json")])

    total_lineas_dialogo = 0
    total_lineas_v21 = 0

    for fname in map_files:
        f_en = dir_en / fname
        f_es = dir_es / fname
        if not f_en.exists() or not f_es.exists():
            continue

        try:
            d_en = json.loads(f_en.read_text(encoding="utf-8"))
            d_es = json.loads(f_es.read_text(encoding="utf-8"))
        except Exception:
            continue

        lista_eventos_en = []
        lista_eventos_es = []

        if isinstance(d_en, list) and isinstance(d_es, list):
            lista_eventos_en = d_en
            lista_eventos_es = d_es
        elif isinstance(d_en, dict) and isinstance(d_es, dict):
            lista_eventos_en = d_en.get("events", []) or []
            lista_eventos_es = d_es.get("events", []) or []

        for ev_en, ev_es in zip(lista_eventos_en, lista_eventos_es):
            if not ev_en or not ev_es:
                continue

            pages_en = ev_en.get("pages", [ev_en]) if "pages" in ev_en else [ev_en]
            pages_es = ev_es.get("pages", [ev_es]) if "pages" in ev_es else [ev_es]

            for pg_en, pg_es in zip(pages_en, pages_es):
                if not pg_en or not pg_es:
                    continue
                cmds_en = pg_en.get("list", []) or []
                cmds_es = pg_es.get("list", []) or []

                if len(cmds_en) == len(cmds_es):
                    for c_en, c_es in zip(cmds_en, cmds_es):
                        tipo_en, txt_en = extraer_dialogo_comando(c_en)
                        tipo_es, txt_es = extraer_dialogo_comando(c_es)

                        if tipo_en and tipo_es and tipo_en == tipo_es:
                            if tipo_en == "choices":
                                for opt_en, opt_es in zip(txt_en, txt_es):
                                    agregar_par(opt_en, opt_es, "nadia_eleccion")
                            elif tipo_en == "v21":
                                total_lineas_v21 += 1
                                # Separar prefijo/etiqueta
                                tag_en, clean_en = separar_etiqueta_v21(txt_en)
                                tag_es, clean_es = separar_etiqueta_v21(txt_es)

                                # Añadir diálogo limpio
                                if clean_en and clean_es:
                                    agregar_par(clean_en, clean_es, "nadia_dialogo")

                                # Añadir par completo con etiqueta para robustez técnica
                                if txt_en and txt_es and (clean_en or clean_es):
                                    agregar_par(txt_en, txt_es, "nadia_v21_con_etiqueta")
                            elif tipo_en == "dialogo":
                                total_lineas_dialogo += 1
                                agregar_par(txt_en, txt_es, "nadia_dialogo_401")

    print(f"\nEstadísticas:")
    print(f"- Diálogos v21 procesados: {total_lineas_v21}")
    print(f"- Diálogos 401 procesados: {total_lineas_dialogo}")
    print(f"- Total pares únicos bilingües generados: {len(pares)}")
    print(f"- Términos extraídos en glosario: {len(glosario)}")

    # Guardar JSONL
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with open(output_jsonl, "w", encoding="utf-8") as f:
        for p in pares:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"\n[OK] Dataset guardado en: {output_jsonl}")

    # Guardar Glosario
    output_glosario.parent.mkdir(parents=True, exist_ok=True)
    with open(output_glosario, "w", encoding="utf-8") as f:
        json.dump(glosario, f, ensure_ascii=False, indent=2)
    print(f"[OK] Glosario guardado en: {output_glosario}")

    return len(pares), len(glosario)

if __name__ == "__main__":
    dir_steam = Path(r"J:\SteamLibrary\steamapps\common\Treasure of Nadia\www\data")
    dir_en_backup = Path(r"workspace\nadia_en_data")
    dir_es = Path(r"workspace\nadia_es_data")
    output_jsonl = Path(r"datasets\corpus_videojuegos\dataset_extra_nadia.jsonl")
    output_glosario = Path(r"glosarios\glosario_nadia.json")

    # Copiar Steam EN a workspace\nadia_en_data si no se ha copiado
    if dir_steam.exists():
        import shutil
        dir_en_backup.mkdir(parents=True, exist_ok=True)
        print("Copiando archivos en inglés a workspace/nadia_en_data...")
        for f in dir_steam.glob("*.json"):
            shutil.copy2(f, dir_en_backup / f.name)

    procesar_corpus(dir_en_backup, dir_es, output_jsonl, output_glosario)
