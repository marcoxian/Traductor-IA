"""capturar_nadia_en.py
1. Copia la carpeta www/data recién descargada en inglés de Steam a workspace/nadia_en_data.
2. Ejecuta extraer_corpus_nadia.py para crear el dataset bilingüe y glosario.
3. Restaura automáticamente la traducción en español a Steam para que el juego quede listo para jugar.
"""

import shutil
import sys
from pathlib import Path
from extraer_corpus_nadia import procesar_corpus
from restaurar_nadia_es import restaurar

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

STEAM_DATA = Path(r"J:\SteamLibrary\steamapps\common\Treasure of Nadia\www\data")
EN_DATA = Path(r"workspace\nadia_en_data")
ES_DATA = Path(r"workspace\nadia_es_data")
OUTPUT_JSONL = Path(r"datasets\corpus_videojuegos\dataset_extra_nadia.jsonl")
OUTPUT_GLOSARIO = Path(r"glosarios\glosario_nadia.json")

def capturar_y_extraer():
    if not STEAM_DATA.exists():
        print(f"Error: {STEAM_DATA} no existe.")
        return

    # Verificar si el CommonEvents.json de Steam parece inglés
    ce_path = STEAM_DATA / "CommonEvents.json"
    if ce_path.exists():
        txt = ce_path.read_text(encoding="utf-8", errors="ignore")
        if "Ha pasado mucho desde que guardaste" in txt:
            print("AVISO: Parece que la carpeta de Steam todavía está en Español.")
            print("Por favor, haz primero en Steam: 'Verificar la integridad de los archivos del juego'.")
            return

    print("1. Copiando archivos en inglés desde Steam a workspace/nadia_en_data...")
    EN_DATA.mkdir(parents=True, exist_ok=True)
    count = 0
    for f in STEAM_DATA.glob("*.json"):
        shutil.copy2(f, EN_DATA / f.name)
        count += 1
    print(f"   -> {count} archivos en inglés guardados en {EN_DATA}.")

    print("\n2. Procesando y alineando textos en inglés con la copia en español...")
    procesar_corpus(EN_DATA, ES_DATA, OUTPUT_JSONL, OUTPUT_GLOSARIO)

    print("\n3. Restaurando automáticamente la versión en español en el juego...")
    restaurar()
    print("\n¡PROCESO COMPLETADO AL 100%! El juego vuelve a estar en español y el nuevo corpus está listo.")

if __name__ == "__main__":
    capturar_y_extraer()
