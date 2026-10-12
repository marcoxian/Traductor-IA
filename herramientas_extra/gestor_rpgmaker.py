"""gestor_rpgmaker.py — Herramienta unificada para buscar, inspeccionar y parchear diálogos en RPG Maker MV.

Evita tener que crear decenas de scripts individuales para cada búsqueda o corrección.
Mantiene un registro de auditoría en 'parches_aplicados.json' y valida automáticamente:
  - Formato JSON y codificación UTF-8.
  - Validación del prefijo de 9 caracteres de Variable 21 (XX,YY,ZZ.) en Lust Epidemic.
  - Comparación en paralelo con copias de seguridad (.bak) en inglés.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

# Asegurar compatibilidad UTF-8 en consolas Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_DATA_DIR = Path(r"J:\SteamLibrary\steamapps\common\Lust Epidemic\www\data")
REGISTRO_PARCHES = Path(__file__).resolve().parent / "parches_aplicados.json"

PREFIX_V21_REGEX = re.compile(r'^\$gameVariables\.setValue\(21,\s*"([A-Za-z0-9]{2}),([A-Za-z0-9]{2}),([A-Za-z0-9]{2})\.(.*)"\);?$')


def obtener_ruta_data(ruta_arg: str | None) -> Path:
    if ruta_arg:
        p = Path(ruta_arg)
        if p.exists():
            return p
    if DEFAULT_DATA_DIR.exists():
        return DEFAULT_DATA_DIR
    raise FileNotFoundError(f"No se encuentra la carpeta de datos de RPG Maker: {DEFAULT_DATA_DIR}")


def leer_json(ruta: Path) -> dict | list | None:
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERROR] No se pudo leer {ruta.name}: {e}", file=sys.stderr)
        return None


def guardar_json(ruta: Path, datos: dict | list) -> bool:
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[ERROR] Error al guardar {ruta.name}: {e}", file=sys.stderr)
        return False


def extraer_dialogos_de_comandos(lista_comandos: list[dict]) -> list[dict]:
    dialogos = []
    for idx, cmd in enumerate(lista_comandos):
        code = cmd.get("code")
        params = cmd.get("parameters", [])
        
        # 401: Texto estándar de RPG Maker
        if code == 401 and params and isinstance(params[0], str):
            dialogos.append({
                "cmd_idx": idx,
                "code": code,
                "tipo": "msg",
                "texto": params[0],
                "raw": params[0]
            })
        # 355 o 655: Script (usado frecuentemente para $gameVariables.setValue(21, ...))
        elif code in (355, 655) and params and isinstance(params[0], str):
            raw_script = params[0]
            if "$gameVariables.setValue(21" in raw_script:
                match = PREFIX_V21_REGEX.match(raw_script)
                if match:
                    char_id, emo, mouth, text = match.groups()
                    dialogos.append({
                        "cmd_idx": idx,
                        "code": code,
                        "tipo": "v21",
                        "char": char_id,
                        "emo": emo,
                        "mouth": mouth,
                        "texto": text,
                        "raw": raw_script
                    })
                else:
                    dialogos.append({
                        "cmd_idx": idx,
                        "code": code,
                        "tipo": "v21_raw",
                        "texto": raw_script,
                        "raw": raw_script
                    })
            elif "banner" in raw_script.lower() or "kamasutra" in raw_script.lower() or "orangehud" in raw_script.lower():
                dialogos.append({
                    "cmd_idx": idx,
                    "code": code,
                    "tipo": "script_misc",
                    "texto": raw_script,
                    "raw": raw_script
                })
    return dialogos


def buscar_en_archivo(ruta_json: Path, termino: str, case_sensitive: bool = False) -> list[dict]:
    datos = leer_json(ruta_json)
    if datos is None:
        return []

    ruta_bak = ruta_json.with_suffix(".json.bak")
    datos_bak = leer_json(ruta_bak) if ruta_bak.exists() else None

    termino_cmp = termino if case_sensitive else termino.lower()
    coincidencias = []

    # Caso 1: Archivo de Mapa
    if isinstance(datos, dict) and "events" in datos:
        eventos = datos.get("events") or []
        eventos_bak = datos_bak.get("events") if isinstance(datos_bak, dict) else None

        for ev in eventos:
            if not ev:
                continue
            ev_id = ev.get("id")
            ev_name = ev.get("name", "Sin Nombre")
            
            ev_bak = None
            if eventos_bak and ev_id < len(eventos_bak):
                ev_bak = eventos_bak[ev_id]

            for page_idx, page in enumerate(ev.get("pages", [])):
                comandos = page.get("list", [])
                page_bak_cmds = []
                if ev_bak and "pages" in ev_bak and page_idx < len(ev_bak["pages"]):
                    page_bak_cmds = ev_bak["pages"][page_idx].get("list", [])

                dialogos = extraer_dialogos_de_comandos(comandos)
                for d in dialogos:
                    texto_a_comparar = d["texto"] if case_sensitive else d["texto"].lower()
                    if termino_cmp in texto_a_comparar:
                        # Extraer original en inglés si existe
                        orig_en = None
                        cmd_idx = d["cmd_idx"]
                        if cmd_idx < len(page_bak_cmds):
                            bak_cmd = page_bak_cmds[cmd_idx]
                            if bak_cmd.get("parameters"):
                                orig_en = bak_cmd["parameters"][0]

                        coincidencias.append({
                            "archivo": ruta_json.name,
                            "tipo_fuente": "mapa",
                            "evento_id": ev_id,
                            "evento_nombre": ev_name,
                            "pagina": page_idx + 1,
                            "cmd_idx": cmd_idx,
                            "dialogo": d,
                            "original_en": orig_en
                        })

    # Caso 2: CommonEvents.json
    elif isinstance(datos, list) and ruta_json.name == "CommonEvents.json":
        for ce in datos:
            if not ce:
                continue
            ce_id = ce.get("id")
            ce_name = ce.get("name", "Sin Nombre")
            comandos = ce.get("list", [])

            ce_bak_cmds = []
            if datos_bak and isinstance(datos_bak, list) and ce_id < len(datos_bak) and datos_bak[ce_id]:
                ce_bak_cmds = datos_bak[ce_id].get("list", [])

            dialogos = extraer_dialogos_de_comandos(comandos)
            for d in dialogos:
                texto_a_comparar = d["texto"] if case_sensitive else d["texto"].lower()
                if termino_cmp in texto_a_comparar:
                    orig_en = None
                    cmd_idx = d["cmd_idx"]
                    if cmd_idx < len(ce_bak_cmds):
                        bak_cmd = ce_bak_cmds[cmd_idx]
                        if bak_cmd.get("parameters"):
                            orig_en = bak_cmd["parameters"][0]

                    coincidencias.append({
                        "archivo": ruta_json.name,
                        "tipo_fuente": "common_event",
                        "evento_id": ce_id,
                        "evento_nombre": ce_name,
                        "pagina": 1,
                        "cmd_idx": cmd_idx,
                        "dialogo": d,
                        "original_en": orig_en
                    })

    return coincidencias


def cmd_buscar(args: argparse.Namespace) -> None:
    data_dir = obtener_ruta_data(args.ruta)
    termino = args.termino
    archivos = [Path(args.archivo)] if args.archivo else sorted(data_dir.glob("*.json"))

    total = 0
    print(f"\n🔍 Buscando '{termino}' en {data_dir}...")
    for f in archivos:
        if f.name.endswith(".bak"):
            continue
        matches = buscar_en_archivo(f, termino, args.case)
        if matches:
            for m in matches:
                total += 1
                ev_str = f"EV {m['evento_id']} ('{m['evento_nombre']}') [Pág {m['pagina']}]" if m['tipo_fuente'] == "mapa" else f"CE {m['evento_id']} ('{m['evento_nombre']}')"
                print("\n" + "=" * 80)
                print(f"📍 {m['archivo']} | {ev_str} | Cmd #{m['cmd_idx']}")
                d = m['dialogo']
                if d['tipo'] == 'v21':
                    print(f"👤 Personaje: [{d['char']}] | Emoción: [{d['emo']}] | Boca: [{d['mouth']}]")
                    print(f"🇪🇸 ES: {d['texto']}")
                else:
                    print(f"🇪🇸 ES ({d['tipo']}): {d['texto']}")
                
                if m['original_en']:
                    print(f"🇬🇧 EN (bak): {m['original_en']}")
                print("=" * 80)

    print(f"\n✅ Total de coincidencias encontradas: {total}\n")


def cmd_inspeccionar(args: argparse.Namespace) -> None:
    data_dir = obtener_ruta_data(args.ruta)
    archivo_path = data_dir / args.archivo
    if not archivo_path.exists():
        print(f"[ERROR] El archivo {archivo_path} no existe.", file=sys.stderr)
        return

    datos = leer_json(archivo_path)
    ruta_bak = archivo_path.with_suffix(".json.bak")
    datos_bak = leer_json(ruta_bak) if ruta_bak.exists() else None

    cmds_es = []
    cmds_en = []

    if args.archivo == "CommonEvents.json":
        ce_id = args.evento
        if not (0 <= ce_id < len(datos)) or not datos[ce_id]:
            print(f"[ERROR] CE {ce_id} no encontrado.")
            return
        cmds_es = datos[ce_id].get("list", [])
        if datos_bak and ce_id < len(datos_bak) and datos_bak[ce_id]:
            cmds_en = datos_bak[ce_id].get("list", [])
        print(f"\n📜 Inspeccionando Common Event #{ce_id}: '{datos[ce_id].get('name')}'")
    else:
        ev_id = args.evento
        events = datos.get("events", [])
        if not (0 <= ev_id < len(events)) or not events[ev_id]:
            print(f"[ERROR] Evento #{ev_id} no encontrado en {args.archivo}.")
            return
        ev = events[ev_id]
        p_idx = args.pagina - 1
        pages = ev.get("pages", [])
        if not (0 <= p_idx < len(pages)):
            print(f"[ERROR] Página #{args.pagina} no encontrada en Evento #{ev_id}.")
            return
        cmds_es = pages[p_idx].get("list", [])
        if datos_bak:
            ev_bak = datos_bak.get("events", [])[ev_id] if ev_id < len(datos_bak.get("events", [])) else None
            if ev_bak and "pages" in ev_bak and p_idx < len(ev_bak["pages"]):
                cmds_en = ev_bak["pages"][p_idx].get("list", [])
        print(f"\n📜 Inspeccionando {args.archivo} | Evento #{ev_id}: '{ev.get('name')}' | Pág {args.pagina}")

    dialogos = extraer_dialogos_de_comandos(cmds_es)
    print("-" * 80)
    for d in dialogos:
        idx = d["cmd_idx"]
        en_raw = ""
        if idx < len(cmds_en) and cmds_en[idx].get("parameters"):
            en_raw = cmds_en[idx]["parameters"][0]

        if d["tipo"] == "v21":
            print(f"[{idx:03d}] {d['char']} ({d['emo']}, {d['mouth']})")
            print(f"     ES: {d['texto']}")
            if en_raw:
                # Extraer texto del en_raw si es v21
                m = PREFIX_V21_REGEX.match(en_raw) if isinstance(en_raw, str) else None
                en_clean = m.group(4) if m else str(en_raw)
                print(f"     EN: {en_clean}")
        else:
            print(f"[{idx:03d}] [{d['tipo']}]")
            print(f"     ES: {d['texto']}")
            if en_raw:
                print(f"     EN: {en_raw}")
        print()
    print("-" * 80)


def aplicar_parche_individual(data_dir: Path, archivo: str, buscar_txt: str, reemplazo_txt: str, nota: str = "", todos: bool = False) -> bool:
    archivo_path = data_dir / archivo
    if not archivo_path.exists():
        print(f"[ERROR] {archivo_path} no existe.", file=sys.stderr)
        return False

    datos = leer_json(archivo_path)
    if datos is None:
        return False

    # Validar formato si parece ser script Variable 21
    if "$gameVariables.setValue(21" in reemplazo_txt:
        m = re.search(r'\$gameVariables\.setValue\(21,\s*"([^"]+)"\)', reemplazo_txt)
        if m:
            interior = m.group(1)
            if not (len(interior) >= 9 and interior[2] == ',' and interior[5] == ',' and interior[8] == '.'):
                print(f"[AVISO CRÍTICO] El prefijo de Variable 21 '{interior[:12]}...' no mide 9 caracteres exactos (XX,YY,ZZ.).")
                print("Esto cortará el texto en pantalla.")
                return False

    reemplazos_hechos = 0

    def procesar_comandos(lista_comandos: list[dict]) -> None:
        nonlocal reemplazos_hechos
        partes_buscar = buscar_txt.split("&&") if "&&" in buscar_txt else [buscar_txt]
        for cmd in lista_comandos:
            params = cmd.get("parameters", [])
            for p_idx, p in enumerate(params):
                if isinstance(p, str) and all(pb in p for pb in partes_buscar):
                    if p.startswith("$gameVariables.setValue(21") and reemplazo_txt.startswith("$gameVariables.setValue(21"):
                        params[p_idx] = reemplazo_txt
                    else:
                        params[p_idx] = p.replace(buscar_txt, reemplazo_txt)
                    reemplazos_hechos += 1
                    if not todos and reemplazos_hechos >= 1:
                        return

    # Buscar en mapas o CommonEvents
    if isinstance(datos, dict) and "events" in datos:
        for ev in datos.get("events") or []:
            if not ev:
                continue
            for page in ev.get("pages", []):
                procesar_comandos(page.get("list", []))
                if not todos and reemplazos_hechos >= 1:
                    break
            if not todos and reemplazos_hechos >= 1:
                break
    elif isinstance(datos, list):
        for item in datos:
            if not item:
                continue
            if "list" in item:
                procesar_comandos(item.get("list", []))
                if not todos and reemplazos_hechos >= 1:
                    break

    if reemplazos_hechos == 0:
        print(f"[ERROR] No se encontró el texto exacto en {archivo}:")
        print(f"  Buscado: {buscar_txt[:80]}...")
        return False

    # Backup si no existe
    bak_path = archivo_path.with_suffix(".json.bak")
    if not bak_path.exists():
        with open(archivo_path, "r", encoding="utf-8") as f_orig, open(bak_path, "w", encoding="utf-8") as f_bak:
            f_bak.write(f_orig.read())
        print(f"📦 Backup de seguridad creado en {bak_path.name}")

    with open(archivo_path, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(',', ':'))

    # Registrar en auditoría
    registro = []
    if REGISTRO_PARCHES.exists():
        try:
            with open(REGISTRO_PARCHES, "r", encoding="utf-8") as f:
                registro = json.load(f)
        except Exception:
            registro = []

    registro.append({
        "fecha": datetime.datetime.now().isoformat(),
        "archivo": archivo,
        "buscar": buscar_txt,
        "reemplazo": reemplazo_txt,
        "descripcion": nota or "Parche aplicado con gestor_rpgmaker"
    })

    with open(REGISTRO_PARCHES, "w", encoding="utf-8") as f:
        json.dump(registro, f, ensure_ascii=False, indent=2)

    print(f"✅ Parche aplicado con éxito en {archivo} ({reemplazos_hechos} reemplazo/s)")
    return True


def cmd_parchear(args: argparse.Namespace) -> None:
    data_dir = obtener_ruta_data(args.ruta)
    
    # Modo por lote
    if args.lote:
        lote_path = Path(args.lote)
        if not lote_path.exists():
            print(f"[ERROR] El archivo de lote {lote_path} no existe.", file=sys.stderr)
            return
        with open(lote_path, "r", encoding="utf-8") as f:
            parches = json.load(f)
        
        exitos = 0
        print(f"\n🚀 Aplicando {len(parches)} parches desde {lote_path.name}...")
        for p in parches:
            ok = aplicar_parche_individual(
                data_dir=data_dir,
                archivo=p["archivo"],
                buscar_txt=p["buscar"],
                reemplazo_txt=p["reemplazar"],
                nota=p.get("nota", ""),
                todos=p.get("todos", False)
            )
            if ok:
                exitos += 1
        print(f"\n🏁 Finalizado: {exitos}/{len(parches)} parches aplicados correctamente.\n")
        return

    # Modo directo por argumentos
    if not args.archivo or not args.buscar or not args.reemplazar:
        print("[ERROR] Debes especificar --archivo, --buscar y --reemplazar (o bien --lote).", file=sys.stderr)
        return

    aplicar_parche_individual(
        data_dir=data_dir,
        archivo=args.archivo,
        buscar_txt=args.buscar,
        reemplazo_txt=args.reemplazar,
        nota=args.nota or "",
        todos=args.todos
    )


def cmd_escanear(args: argparse.Namespace) -> None:
    data_dir = obtener_ruta_data(args.ruta)
    archivos = [data_dir / args.archivo] if args.archivo else sorted(data_dir.glob("*.json"))

    print(f"\n🕵️ Iniciando auditoría heurística en {data_dir}...")
    
    # Patrones de advertencia
    PATRON_BUCLE = re.compile(r'(\b[a-zA-ZáéíóúÁÉÍÓÚñÑ]{3,20}\b(?:\s+[a-zA-ZáéíóúÁÉÍÓÚñÑ]{1,20}\b){0,3})(?:\s+\1){2,}', re.IGNORECASE)
    
    LISTA_NEGRA = [
        (r"\bFúmeme\b", "Traducción errónea de 'Fuck me'"),
        (r"\bcargamento de caca\b", "Traducción literal corrupta de 'a load'"),
        (r"\bde antes de tiempo\b", "Traducción literal de 'from the before time'"),
        (r"\bpicos de papel\b", "Traducción literal de 'hitting on'"),
        (r"\btírame los dados\b", "Traducción errónea de 'toss them'"),
        (r"\bayudar a correr\b", "Traducción errónea de 'help me cum'"),
        (r"\bayudes a correr\b", "Traducción errónea de 'help me cum'"),
        (r"\bnecesito correr\b", "Traducción errónea de 'need to cum'"),
        (r"\beres muy cerrada\b", "Traducción errónea de 'very tight' en contexto sexual"),
        (r"\bpersona loca\b", "Traducción literal de 'crazy person'"),
        (r"\bcállate el pico\b", "Traducción mecánica de 'shut the fuck up'"),
        (r"\bVa1erie\b", "Error de OCR dev con número 1 en vez de letra l"),
        (r"\bKa1herine\b", "Error de OCR dev con número 1"),
        (r"\ufffd", "Carácter corrupto de codificación"),
    ]

    total_problemas = 0

    for f in archivos:
        if f.name.endswith(".bak"):
            continue
        datos = leer_json(f)
        if not datos:
            continue

        comandos_revisar = []
        if isinstance(datos, dict) and "events" in datos:
            for ev in datos.get("events") or []:
                if not ev: continue
                ev_id = ev.get("id")
                ev_name = ev.get("name", "")
                for p_idx, page in enumerate(ev.get("pages", [])):
                    for c_idx, cmd in enumerate(page.get("list", [])):
                        comandos_revisar.append((f.name, f"EV {ev_id} ('{ev_name}') Pág {p_idx+1}", c_idx, cmd))
        elif isinstance(datos, list):
            for item in datos:
                if not item: continue
                ce_id = item.get("id")
                ce_name = item.get("name", "")
                for c_idx, cmd in enumerate(item.get("list", [])):
                    comandos_revisar.append((f.name, f"CE {ce_id} ('{ce_name}')", c_idx, cmd))

        for archivo_nombre, origen_str, c_idx, cmd in comandos_revisar:
            params = cmd.get("parameters", [])
            for p in params:
                if not isinstance(p, str):
                    continue

                texto_analizar = p
                # Extraer texto de Variable 21 si aplica
                if "$gameVariables.setValue(21" in p:
                    m = PREFIX_V21_REGEX.match(p)
                    if m:
                        texto_analizar = m.group(4)
                    else:
                        # Prefijo posiblemente roto
                        m_interior = re.search(r'\$gameVariables\.setValue\(21,\s*"([^"]+)"\)', p)
                        if m_interior:
                            interior = m_interior.group(1)
                            if not (len(interior) >= 9 and interior[2] == ',' and interior[5] == ',' and interior[8] == '.'):
                                total_problemas += 1
                                print(f"⚠️ [PREFIJO V21 ROTO] {archivo_nombre} | {origen_str} | Cmd #{c_idx}")
                                print(f"   Contenido: {interior[:30]}...")
                                continue

                # 1. Chequeo de bucles de alucinación
                m_bucle = PATRON_BUCLE.search(texto_analizar)
                if m_bucle:
                    total_problemas += 1
                    print(f"🔄 [BUCLE INFINITO] {archivo_nombre} | {origen_str} | Cmd #{c_idx}")
                    print(f"   Fragmento repetido: '{m_bucle.group(1)}'")
                    print(f"   Texto: {texto_analizar[:100]}...\n")

                # 2. Chequeo de lista negra
                for patron_regex, motivo in LISTA_NEGRA:
                    if re.search(patron_regex, texto_analizar, re.IGNORECASE):
                        total_problemas += 1
                        print(f"🚩 [FALSO AMIGO / ERROR] {archivo_nombre} | {origen_str} | Cmd #{c_idx}")
                        print(f"   Detectado: patrón '{patron_regex}' ({motivo})")
                        print(f"   Texto: {texto_analizar[:120]}...\n")

    if total_problemas == 0:
        print("\n✨ ¡Enhorabuena! No se detectaron bucles ni falsos amigos conocidos en los archivos analizados.\n")
    else:
        print(f"\n⚠️ Total de problemas detectados: {total_problemas}\n")


def main():
    parser = argparse.ArgumentParser(description="Gestor unificado de diálogos para RPG Maker MV.")
    subparsers = parser.add_subparsers(dest="comando", required=True)

    # Subcomando: buscar
    p_buscar = subparsers.add_parser("buscar", help="Busca texto en todos los mapas y eventos comunes.")
    p_buscar.add_argument("termino", help="Cadena o frase a buscar")
    p_buscar.add_argument("--archivo", help="Limitar la búsqueda a un archivo JSON específico (ej: Map038.json)")
    p_buscar.add_argument("--ruta", help="Ruta de la carpeta data del juego")
    p_buscar.add_argument("--case", action="store_true", help="Búsqueda sensible a mayúsculas")
    p_buscar.set_defaults(func=cmd_buscar)

    # Subcomando: inspeccionar
    p_insp = subparsers.add_parser("inspeccionar", help="Vuelca la conversación completa de un evento.")
    p_insp.add_argument("--archivo", required=True, help="Nombre del archivo (ej: Map038.json o CommonEvents.json)")
    p_insp.add_argument("--evento", required=True, type=int, help="ID del evento o ID del Common Event")
    p_insp.add_argument("--pagina", type=int, default=1, help="Número de página (por defecto 1)")
    p_insp.add_argument("--ruta", help="Ruta de la carpeta data del juego")
    p_insp.set_defaults(func=cmd_inspeccionar)

    # Subcomando: parchear
    p_parch = subparsers.add_parser("parchear", help="Aplica una sustitución segura a un archivo JSON (directo o por lote).")
    p_parch.add_argument("--archivo", help="Archivo JSON objetivo (ej: Map038.json)")
    p_parch.add_argument("--buscar", help="Texto exacto a reemplazar")
    p_parch.add_argument("--reemplazar", help="Nuevo texto o comando de script")
    p_parch.add_argument("--lote", help="Ruta a un archivo JSON con lista de parches [{'archivo': ..., 'buscar': ..., 'reemplazar': ...}]")
    p_parch.add_argument("--nota", help="Nota opcional describiendo el cambio para el registro de auditoría")
    p_parch.add_argument("--todos", action="store_true", help="Reemplazar todas las apariciones si hay más de una")
    p_parch.add_argument("--ruta", help="Ruta de la carpeta data del juego")
    p_parch.set_defaults(func=cmd_parchear)

    # Subcomando: escanear
    p_scan = subparsers.add_parser("escanear", help="Audita heurísticamente bucles de repetición y falsos amigos.")
    p_scan.add_argument("--archivo", help="Limitar el análisis a un archivo específico")
    p_scan.add_argument("--ruta", help="Ruta de la carpeta data del juego")
    p_scan.set_defaults(func=cmd_escanear)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
