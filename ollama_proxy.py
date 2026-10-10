"""ollama_proxy.py — Servidor Proxy de traducción para plugins como XUnity.AutoTranslator."""
import logging
from flask import Flask, Response, request
from traductor import config
from traductor.ollama import OllamaTranslator

app = Flask(__name__)
translator = OllamaTranslator(model_name=config.MODELO_POR_DEFECTO, endpoint=config.OLLAMA_URL)

# Desactivar logs por defecto de werkzeug/flask
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)


@app.route("/translate", methods=["GET"])
def translate():
    text = request.args.get("text", "")
    if not text:
        return Response("", status=200, mimetype="text/plain")

    print(f"\n[Proxy] Recibido: {text}", flush=True)
    translated = translator.translate(text)
    print(f"[Proxy] Traducido: {translated}", flush=True)

    return Response(translated, status=200, mimetype="text/plain; charset=utf-8")


if __name__ == "__main__":
    print("=== Servidor Proxy de Traducción Iniciado ===")
    print("Escuchando en http://localhost:11435/translate")
    print("Esperando textos de XUnity.AutoTranslator...")
    app.run(host="127.0.0.1", port=11435)
