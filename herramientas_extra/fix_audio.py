"""fix_audio.py — Restauración de nombres originales de archivos de audio."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def restaurar_audio(nodo_orig, nodo_trans) -> int:
    cambios = 0
    if isinstance(nodo_orig, dict) and isinstance(nodo_trans, dict):
        # Firma de objeto de sonido de RPG Maker
        if "name" in nodo_orig and "volume" in nodo_orig and "pitch" in nodo_orig:
            if nodo_trans.get("name") != nodo_orig["name"]:
                logging.info("Restaurando audio: %s -> %s", nodo_trans.get("name"), nodo_orig["name"])
                nodo_trans["name"] = nodo_orig["name"]
                cambios += 1

        for k in nodo_orig:
            if k in nodo_trans:
                cambios += restaurar_audio(nodo_orig[k], nodo_trans[k])

    elif isinstance(nodo_orig, list) and isinstance(nodo_trans, list):
        if len(nodo_orig) == len(nodo_trans):
            for o, t in zip(nodo_orig, nodo_trans):
                cambios += restaurar_audio(o, t)
    return cambios


def main():
    parser = argparse.ArgumentParser(description="Restaura nombres de pistas de audio traducidas accidentalmente.")
    parser.add_argument("--ruta", required=True, help="Ruta a la carpeta del juego (o carpeta data)")
    args = parser.parse_args()

    ruta = Path(args.ruta)
    data_dir = ruta / "www" / "data" if (ruta / "www" / "data").exists() else (ruta / "data" if (ruta / "data").exists() else ruta)

    json_files = list(data_dir.glob("*.json"))
    total_restaurados = 0

    for json_file in json_files:
        bak_file = json_file.with_suffix(".json.bak")
        if not bak_file.exists():
            continue

        try:
            with open(bak_file, "r", encoding="utf-8-sig") as f:
                orig_data = json.load(f)
            with open(json_file, "r", encoding="utf-8-sig") as f:
                trans_data = json.load(f)

            c = restaurar_audio(orig_data, trans_data)
            if c > 0:
                with open(json_file, "w", encoding="utf-8") as f:
                    json.dump(trans_data, f, ensure_ascii=False)
                total_restaurados += c
        except Exception as e:
            logging.error("Error en %s: %s", json_file.name, e)

    logging.info("¡Restauración completada! Total de audios restaurados: %d", total_restaurados)


if __name__ == "__main__":
    main()
