import json
import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

NADIA_DIR = Path(r"J:\SteamLibrary\steamapps\common\Treasure of Nadia\www\data")

def analizar_textos():
    print("=== ANÁLISIS DE IDIOMAS EN TREASURE OF NADIA ===")
    
    total_textos = 0
    en_espanol = 0
    en_ingles = 0
    
    palabras_es = {"que", "de", "el", "la", "en", "un", "una", "los", "las", "por", "para", "con", "no", "es", "está", "estás", "pero"}
    palabras_en = {"the", "and", "you", "that", "was", "for", "are", "with", "his", "they", "this", "have", "from", "one", "had", "not"}

    archivos = [NADIA_DIR / "CommonEvents.json"] + sorted(NADIA_DIR.glob("Map*.json"))[:5]

    muestras_es = []
    muestras_en = []

    for fpath in archivos:
        if not fpath.exists(): continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        comandos = []
        if isinstance(data, dict) and "events" in data:
            for ev in data.get("events") or []:
                if not ev: continue
                for page in ev.get("pages", []):
                    comandos.extend(page.get("list", []))
        elif isinstance(data, list):
            for item in data:
                if not item: continue
                comandos.extend(item.get("list", []))

        for cmd in comandos:
            params = cmd.get("parameters", [])
            for p in params:
                if isinstance(p, str) and len(p.strip()) > 10:
                    # Si es script v21
                    texto = p
                    if "$gameVariables.setValue(21" in p:
                        m = re.search(r'\$gameVariables\.setValue\(21,\s*"([^"]+)"\)', p)
                        if m:
                            texto = m.group(1)
                    elif cmd.get("code") != 401:
                        continue # Solo analizar dialogos reales

                    words = set(re.findall(r'\b[a-zA-ZáéíóúñÁÉÍÓÚÑ]+\b', texto.lower()))
                    if not words: continue

                    total_textos += 1
                    coincide_es = len(words & palabras_es)
                    coincide_en = len(words & palabras_en)

                    if coincide_es > coincide_en:
                        en_espanol += 1
                        if len(muestras_es) < 5:
                            muestras_es.append(f"[{fpath.name}] {texto[:90]}")
                    elif coincide_en > coincide_es:
                        en_ingles += 1
                        if len(muestras_en) < 5:
                            muestras_en.append(f"[{fpath.name}] {texto[:90]}")

    print(f"\nTotal diálogos analizados: {total_textos}")
    print(f"Diálogos identificados en Español: {en_espanol} ({en_espanol/max(1,total_textos)*100:.1f}%)")
    print(f"Diálogos identificados en Inglés:  {en_ingles} ({en_ingles/max(1,total_textos)*100:.1f}%)")

    print("\nEjemplos en Español:")
    for m in muestras_es:
        print("  🇪🇸", m)

    print("\nEjemplos en Inglés:")
    for m in muestras_en:
        print("  🇬🇧", m)

if __name__ == "__main__":
    analizar_textos()
