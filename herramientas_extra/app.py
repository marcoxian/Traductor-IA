"""app.py — Servidor Flask y monitor de portapapeles para traducción en vivo."""
from __future__ import annotations

import threading
import time
import pyperclip
import requests
from flask import Flask, jsonify
from flask_cors import CORS

import sys
from pathlib import Path

# Añadir raíz al path si se ejecuta directamente desde herramientas_extra/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from traductor import config, prompts
from traductor.ollama import OllamaTranslator

app = Flask(__name__)
CORS(app)

historial_contexto: list[str] = []
ultima_traduccion = {"original": "", "traduccion": ""}
texto_anterior = ""

perfil = config.cargar_perfil()
translator = OllamaTranslator(
    model_name=config.MODELO_POR_DEFECTO,
    endpoint=config.OLLAMA_URL,
    perfil=perfil,
    usar_historial=True,
)


def monitor_portapapeles():
    global texto_anterior, ultima_traduccion
    while True:
        try:
            texto_actual = pyperclip.paste().strip()
            if texto_actual and texto_actual != texto_anterior:
                texto_anterior = texto_actual
                texto_traducido = translator.translate(texto_actual)

                historial_contexto.append(f"EN: {texto_actual} -> ES: {texto_traducido}")
                if len(historial_contexto) > 5:
                    historial_contexto.pop(0)

                ultima_traduccion = {"original": texto_actual, "traduccion": texto_traducido}
                print(f"\n[Clipboard] Original: {texto_actual}\n[Clipboard] Traducción: {texto_traducido}")
        except Exception:
            pass
        time.sleep(1.5)


@app.route("/obtener_traduccion", methods=["GET"])
def obtener_traduccion():
    return jsonify(ultima_traduccion)


if __name__ == "__main__":
    hilo = threading.Thread(target=monitor_portapapeles, daemon=True)
    hilo.start()

    print("Monitor de portapapeles activo.")
    print("Servidor web escuchando en http://localhost:5000/obtener_traduccion")
    app.run(port=5000, debug=False, use_reloader=False)
