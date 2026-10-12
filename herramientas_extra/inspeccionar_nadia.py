"""inspeccionar_nadia.py — Inspecciona Treasure of Nadia para ver si incluye español y cómo está estructurado.
"""
import os
import json
import re
from pathlib import Path

NADIA_PATH = Path(r"J:\SteamLibrary\steamapps\common\Treasure of Nadia")
WWW_PATH = NADIA_PATH / "www"

def inspeccionar():
    print("=== INSPECCIÓN DE TREASURE OF NADIA ===")
    
    # 1. Buscar plugins de localización
    plugins_file = WWW_PATH / "js" / "plugins.js"
    if plugins_file.exists():
        content = plugins_file.read_text(encoding="utf-8", errors="ignore")
        names = re.findall(r'"name":"([^"]+)"', content)
        print("\n[Plugins detectados]:")
        for n in names:
            if any(k in n.lower() for k in ["local", "lang", "trans", "dk", "yep", "orange"]):
                print(f"  -> {n}")
            else:
                print(f"     {n}")
    
    # 2. Buscar archivos con nombres de idioma o csv en todo www/
    print("\n[Buscando archivos de idioma / localización]:")
    archivos_idioma = []
    for root, dirs, files in os.walk(NADIA_PATH):
        for f in files:
            fl = f.lower()
            if any(k in fl for k in ["es", "spa", "lang", "trans", "locales", "csv"]) and not fl.endswith((".dll", ".pak", ".bin", ".dat")):
                archivos_idioma.append(os.path.join(root, f))
    
    if archivos_idioma:
        for a in archivos_idioma[:30]:
            print(f"  * {a}")
    else:
        print("  (No se encontraron archivos evidentes con 'es', 'lang', 'csv')")

    # 3. Muestreo de diálogos en System.json y CommonEvents.json
    print("\n[Muestreo de textos en data/]:")
    data_dir = WWW_PATH / "data"
    if data_dir.exists():
        system_file = data_dir / "System.json"
        if system_file.exists():
            try:
                sys_data = json.loads(system_file.read_text(encoding="utf-8"))
                print(f"  Título del juego: {sys_data.get('gameTitle')}")
                terms = sys_data.get("terms", {}).get("commands", [])
                print(f"  Comandos de menú en System.json: {terms[:6]}")
            except Exception as e:
                print(f"  Error leyendo System.json: {e}")

        ce_file = data_dir / "CommonEvents.json"
        if ce_file.exists():
            try:
                ce_data = json.loads(ce_file.read_text(encoding="utf-8"))
                muestra = []
                for ce in ce_data:
                    if not ce: continue
                    for cmd in ce.get("list", []):
                        for p in cmd.get("parameters", []):
                            if isinstance(p, str) and len(p) > 20 and not p.startswith("$"):
                                muestra.append(p)
                            elif isinstance(p, str) and "$gameVariables.setValue(21" in p:
                                muestra.append(p)
                            if len(muestra) >= 8:
                                break
                    if len(muestra) >= 8:
                        break
                print("\n  Muestra de diálogos en CommonEvents.json:")
                for m in muestra[:6]:
                    print(f"    - {m[:100]}")
            except Exception as e:
                print(f"  Error leyendo CommonEvents.json: {e}")

if __name__ == "__main__":
    inspeccionar()
