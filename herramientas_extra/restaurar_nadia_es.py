"""restaurar_nadia_es.py
Restaura la traducción al español en Treasure of Nadia desde la copia de seguridad.
"""

import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SRC = Path(r"workspace\nadia_es_data")
DST = Path(r"J:\SteamLibrary\steamapps\common\Treasure of Nadia\www\data")

def restaurar():
    if not SRC.exists():
        print(f"Error: No se encontró la copia de seguridad en {SRC}")
        return

    if not DST.exists():
        print(f"Error: La carpeta de destino no existe en {DST}")
        return

    print("Restaurando archivos en español en Treasure of Nadia...")
    count = 0
    for f in SRC.glob("*.json"):
        shutil.copy2(f, DST / f.name)
        count += 1

    print(f"¡Restauración completada con éxito! Se copiaron {count} archivos JSON a {DST}.")

if __name__ == "__main__":
    restaurar()
