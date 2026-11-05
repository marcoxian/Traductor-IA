"""traducir_restos.py — Traducción selectiva de términos de System.json y plugins específicos."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from traductor import config
from traductor.ollama import OllamaTranslator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def traducir_nodo(nodo, translator: OllamaTranslator):
    if isinstance(nodo, dict):
        for k, v in nodo.items():
            if isinstance(v, str) and any(c.isalpha() for c in v):
                nodo[k] = translator.traducir_validado(v)
            elif isinstance(v, (dict, list)):
                traducir_nodo(v, translator)
    elif isinstance(nodo, list):
        for i in range(len(nodo)):
            if isinstance(nodo[i], str) and any(c.isalpha() for c in nodo[i]):
                nodo[i] = translator.traducir_validado(nodo[i])
            elif isinstance(nodo[i], (dict, list)):
                traducir_nodo(nodo[i], translator)


def main():
    parser = argparse.ArgumentParser(description="Traduce secciones específicas de System.json y plugins.")
    parser.add_argument("--ruta", required=True, help="Ruta al directorio del juego")
    parser.add_argument("--modelo", default=config.MODELO_POR_DEFECTO, help="Modelo de Ollama")
    args = parser.parse_args()

    ruta = Path(args.ruta)
    data_dir = ruta / "www" / "data" if (ruta / "www" / "data").exists() else ruta / "data"
    sys_path = data_dir / "System.json"

    if not sys_path.exists():
        logging.error("No se encontró System.json en %s", data_dir)
        return

    translator = OllamaTranslator(model_name=args.modelo)

    logging.info("Traduciendo apartado 'terms' en %s...", sys_path.name)
    with open(sys_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    if "terms" in data:
        traducir_nodo(data["terms"], translator)

    with open(sys_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    # Parchear opcionalmente plugin RecollectionMode si existe
    plugin_path = ruta / "www" / "js" / "plugins" / "RecollectionMode.js"
    if plugin_path.exists():
        logging.info("Traduciendo textos en plugin RecollectionMode.js...")
        content = plugin_path.read_text(encoding="utf-8", errors="ignore")
        reemplazos = {
            '"Watch Events"': '"Ver Eventos"',
            '"Watch Cut Scenes"': '"Ver Cinemáticas"',
            '"Return to Title"': '"Volver al Título"',
            "'Watch Events'": "'Ver Eventos'",
            "'Watch Cut Scenes'": "'Ver Cinemáticas'",
            "'Return to Title'": "'Volver al Título'",
        }
        for orig, nuevo in reemplazos.items():
            content = content.replace(orig, nuevo)
        plugin_path.write_text(content, encoding="utf-8")

    logging.info("¡Proceso de traducción de restos finalizado!")


if __name__ == "__main__":
    main()
